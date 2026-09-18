"""Poll RSS feeds and publish new articles to RabbitMQ.

Two dedup layers exist in this system and they do different jobs. This service
owns the first: an exact-URL seen-set in Redis, which stops a story being
republished on every cycle simply because it is still in the feed. The second
layer -- SimHash clustering in the enricher -- catches the same story told by
different outlets, which URL identity cannot see.
"""

from __future__ import annotations

import logging
import pathlib
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import feedparser
import redis
import yaml
from pipeline import config, db, queue

from services.poller.extract import to_article

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [poller] %(message)s",
    datefmt="%H:%M:%S",
)
# pika narrates every frame at INFO, which buries our own lines in container
# logs. feedparser's chardet probing is similarly chatty.
logging.getLogger("pika").setLevel(logging.WARNING)
logging.getLogger("charset_normalizer").setLevel(logging.WARNING)

log = logging.getLogger(__name__)

FEEDS_PATH = pathlib.Path(__file__).with_name("feeds.yaml")

# A seen URL expires after a week: long enough that a story cycling through a
# feed is never republished, short enough that Redis does not grow without end.
SEEN_TTL_SECONDS = 7 * 24 * 3600
SEEN_KEY = "seen:url:{}"

_running = True


def _stop(signum: int, _frame: Any) -> None:
    global _running
    log.info("received signal %s, finishing current cycle", signum)
    _running = False


def load_feeds() -> list[dict[str, str]]:
    feeds = yaml.safe_load(FEEDS_PATH.read_text())["feeds"]
    log.info("loaded %d feeds", len(feeds))
    return feeds


def fetch_feed(feed: dict[str, str]) -> tuple[str, list[dict[str, Any]]]:
    """Fetch and flatten one feed. Never raises -- one bad feed must not stop a cycle."""
    name, url = feed["name"], feed["url"]
    try:
        parsed = feedparser.parse(url)
    except Exception as exc:
        log.warning("%s: fetch failed: %s", name, exc)
        return name, []

    if parsed.bozo and not parsed.entries:
        log.warning("%s: unparseable (%s)", name, getattr(parsed, "bozo_exception", "unknown"))
        return name, []

    articles = [a for a in (to_article(e, name) for e in parsed.entries) if a]
    skipped = len(parsed.entries) - len(articles)
    if skipped:
        log.debug("%s: skipped %d entries missing title/link/body", name, skipped)
    return name, articles


def poll_once(rds: redis.Redis) -> tuple[int, int]:
    """One pass over every feed. Returns (seen, published)."""
    feeds = load_feeds()
    started = time.monotonic()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch_feed, feeds))

    total = published = 0
    with queue.channel() as ch:
        for name, articles in results:
            for article in articles:
                total += 1
                key = SEEN_KEY.format(db.url_hash(article["url"]))
                # SET NX is atomic, so two poller replicas cannot both claim the
                # same URL. Whoever sets the key owns publishing it.
                if not rds.set(key, 1, nx=True, ex=SEEN_TTL_SECONDS):
                    continue
                queue.publish(ch, f"article.raw.{name}", article)
                published += 1

    elapsed = time.monotonic() - started
    log.info(
        "cycle complete: %d entries, %d new, %d already seen (%.1fs)",
        total,
        published,
        total - published,
        elapsed,
    )
    return total, published


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    rds = redis.Redis.from_url(config.REDIS_URL)
    log.info("polling every %ds", config.POLL_INTERVAL_SECONDS)

    while _running:
        try:
            poll_once(rds)
        except Exception:
            log.exception("cycle failed; retrying next interval")

        # Sleep in short slices so SIGTERM is honoured promptly rather than
        # after a full interval -- otherwise `docker compose down` waits.
        for _ in range(config.POLL_INTERVAL_SECONDS):
            if not _running:
                break
            time.sleep(1)

    log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
