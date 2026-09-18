"""Consume raw articles, persist them, and record pipeline timings."""

from __future__ import annotations

import logging
import signal
import sys
import time
from typing import Any

from pipeline import config, db, fulltext

from services.enricher.consumer import PermanentError, consume

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [enricher] %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("pika").setLevel(logging.WARNING)

log = logging.getLogger(__name__)

REQUIRED_FIELDS = ("url", "title", "body")

_running = True


def _stop(signum: int, _frame: Any) -> None:
    global _running
    log.info("received signal %s, stopping after current message", signum)
    _running = False


def handle_article(payload: dict[str, Any]) -> None:
    """Persist one article.

    Safe to run twice on the same payload: the insert is a no-op when the
    url_hash is already stored, which is what lets the broker redeliver freely.
    """
    missing = [f for f in REQUIRED_FIELDS if not payload.get(f)]
    if missing:
        raise PermanentError(f"missing required fields: {', '.join(missing)}")

    started = time.monotonic()

    # Feeds mostly carry a one-sentence teaser. Clustering and entity
    # extraction both need real prose, so pull the body from the page; a
    # blocked or unreachable site degrades to the teaser rather than failing.
    body = payload["body"]
    body_source = "teaser"
    if config.FULLTEXT_ENABLED:
        result = fulltext.fetch_body(payload["url"], payload["body"])
        body, body_source = result.body, result.source

    record = {
        "url_hash": db.url_hash(payload["url"]),
        "url": payload["url"],
        "title": payload["title"],
        "body": body,
        "author": payload.get("author") or "",
        "source": payload.get("source") or "",
        "image_url": payload.get("image_url") or "",
        "published_at": db.parse_timestamp(payload.get("published_at")),
    }

    with db.connection() as conn:
        article_id = db.insert_article(conn, record)

        if article_id is None:
            # Already stored. Recorded so the duplicate rate is visible in
            # /api/stats rather than being silently invisible.
            db.record_event(conn, "duplicate", detail=record["source"])
            log.debug("duplicate: %s", record["title"][:60])
            return

        db.record_event(
            conn,
            "ingest",
            article_id=article_id,
            latency_ms=int((time.monotonic() - started) * 1000),
            detail=f"{record['source']}:{body_source}",
        )

    log.info(
        "stored [%s] %s (%s, %d ch)",
        record["source"],
        record["title"][:60],
        body_source,
        len(body),
    )


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    db.init_schema()
    log.info("schema ready")

    try:
        consume(handle_article, lambda: _running)
    except KeyboardInterrupt:
        pass
    finally:
        db.close_pool()

    log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
