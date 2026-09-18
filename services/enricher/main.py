"""Consume raw articles, persist them, and record pipeline timings."""

from __future__ import annotations

import logging
import signal
import sys
import time
from typing import Any

import redis
from pipeline import clustering, config, db, enrich, fulltext

from services.enricher.consumer import PermanentError, consume

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [enricher] %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("pika").setLevel(logging.WARNING)
# The Anthropic SDK and its HTTP client narrate every request at INFO, which
# buries the pipeline's own lines one-for-one with each enrichment.
for _noisy in ("httpx", "httpcore", "anthropic"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

log = logging.getLogger(__name__)

REQUIRED_FIELDS = ("url", "title", "body")

_running = True
_redis_client: redis.Redis | None = None
_enricher_impl: enrich.Enricher | None = None


def _enricher() -> enrich.Enricher:
    """The process-wide enricher, chosen once on first use."""
    global _enricher_impl
    if _enricher_impl is None:
        _enricher_impl = enrich.get_enricher()
    return _enricher_impl


def _redis() -> redis.Redis:
    """Lazily opened Redis connection, reused for the life of the process."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(config.REDIS_URL)
    return _redis_client


def _stop(signum: int, _frame: Any) -> None:
    global _running
    log.info("received signal %s, stopping after current message", signum)
    _running = False


def _enrich_article(article_id: int, title: str, body: str) -> None:
    """Extract structured metadata and record what the call cost.

    Deliberately opens its own connection *after* the model call rather than
    running inside the insert transaction: an extraction round trip takes
    seconds, and holding a pooled connection open across it would starve the
    pool once several replicas are running at prefetch 8.

    Enrichment failures do not fail the message either. The article is already
    stored and clustered, so losing extraction is a degraded row rather than a
    lost one, and raising here would send a perfectly good article round the
    retry loop and eventually to the DLQ.
    """
    started = time.monotonic()
    try:
        result = _enricher().enrich(title, body)
    except Exception as exc:
        log.warning("enrichment failed for article %d: %s", article_id, exc)
        with db.connection() as conn:
            db.record_event(conn, "enrich_failed", article_id=article_id, detail=str(exc)[:200])
        return

    usage = getattr(_enricher(), "last_usage", None)
    with db.connection() as conn:
        db.set_enrichment(conn, article_id, result.model_dump())
        db.record_event(
            conn,
            "enrich",
            article_id=article_id,
            latency_ms=int((time.monotonic() - started) * 1000),
            tokens_in=getattr(usage, "input_tokens", 0),
            tokens_out=getattr(usage, "output_tokens", 0),
            cache_read_tokens=getattr(usage, "cache_read_tokens", 0),
            detail=result.provider,
        )


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

        # Clustering runs inside the same transaction as the insert, so an
        # article is never visible without a cluster, and a crash between the
        # two leaves nothing half-written for the redelivery to trip over.
        clustered = time.monotonic()
        assignment = clustering.assign(_redis(), article_id, record["title"], body)

        if assignment.matched_article_id is not None:
            cluster_id = db.join_cluster(conn, article_id, assignment.matched_article_id)
            db.record_event(
                conn,
                "cluster_join",
                article_id=article_id,
                latency_ms=int((time.monotonic() - clustered) * 1000),
                detail=f"{cluster_id}:{assignment.score:.3f}:{assignment.candidates_examined}",
            )
        else:
            cluster_id = db.create_cluster(conn, article_id)
            db.record_event(
                conn,
                "cluster_new",
                article_id=article_id,
                latency_ms=int((time.monotonic() - clustered) * 1000),
                detail=f"{cluster_id}:{assignment.candidates_examined}",
            )

    # Only the article that opens a cluster is enriched. Every later member is
    # the same story from another outlet, so extracting again would pay the
    # model repeatedly for one result -- clustering first is what makes the
    # spend proportional to stories rather than to articles. Runs after the
    # transaction closes, not inside it.
    if assignment.matched_article_id is None:
        _enrich_article(article_id, record["title"], body)

    if assignment.matched_article_id is not None:
        log.info(
            "clustered [%s] %s -> cluster %d (cos %.2f, %d candidates)",
            record["source"],
            record["title"][:50],
            cluster_id,
            assignment.score,
            assignment.candidates_examined,
        )
    else:
        log.info(
            "stored [%s] %s (%s, %d ch, %d candidates)",
            record["source"],
            record["title"][:50],
            body_source,
            len(body),
            assignment.candidates_examined,
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
