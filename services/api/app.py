"""Flask API serving the clustered, enriched feed.

Redis is used here as an actual cache -- a short-lived copy of a query result
that can be thrown away at any time -- which is worth contrasting with the
original tech lab, where Redis *was* the database and the whole dataset lived
under a single key.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import redis
import requests
from flask import Flask, Response, jsonify, request
from pipeline import config, db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [api] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DEFAULT_LIMIT = 30
MAX_LIMIT = 100

# Only the first page is cached: it takes the overwhelming share of traffic and
# is the one query every visitor runs. Deeper pages are rare and varied enough
# that caching them would evict more than it saves.
FEED_CACHE_KEY = "cache:feed:{}"
FEED_CACHE_TTL = 20

STREAM_POLL_SECONDS = 3


def _queue_depths() -> dict[str, Any]:
    """Queue depths from the RabbitMQ management API.

    Returns an error rather than raising: /api/stats must still answer when the
    broker is unreachable, since the rest of its numbers come from Postgres.
    """
    try:
        response = requests.get(
            f"{config.RABBITMQ_MANAGEMENT_URL}/api/queues/%2F",
            auth=(config.RABBITMQ_USER, config.RABBITMQ_PASSWORD),
            timeout=3,
        )
        response.raise_for_status()
        return {
            q["name"]: {"messages": q.get("messages", 0), "consumers": q.get("consumers", 0)}
            for q in response.json()
            if q["name"].startswith("articles")
        }
    except Exception as exc:
        return {"error": str(exc)[:120]}


def _redis() -> redis.Redis:
    return redis.Redis.from_url(config.REDIS_URL)


def _parse_limit(raw: str | None) -> int:
    try:
        return max(1, min(int(raw or DEFAULT_LIMIT), MAX_LIMIT))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


def create_app() -> Flask:
    app = Flask("newswire-api")
    rds = _redis()

    @app.get("/health")
    def health() -> Response:
        """Liveness plus a real dependency check, so compose can gate on it."""
        try:
            with db.connection() as conn:
                conn.execute("SELECT 1")
            rds.ping()
        except Exception as exc:
            return jsonify({"status": "degraded", "error": str(exc)}), 503
        return jsonify({"status": "ok"})

    @app.get("/api/feed")
    def feed() -> Response:
        limit = _parse_limit(request.args.get("limit"))
        cursor = request.args.get("cursor")

        cache_key = FEED_CACHE_KEY.format(limit) if not cursor else None
        if cache_key:
            try:
                cached = rds.get(cache_key)
                if cached:
                    return Response(cached, mimetype="application/json")
            except redis.RedisError as exc:
                # A cache is an optimisation, never a dependency: if Redis is
                # down the feed should still serve, just slower.
                log.warning("feed cache read failed: %s", exc)

        with db.connection() as conn:
            stories, next_cursor = db.fetch_feed(conn, limit=limit, cursor=cursor)

        payload = json.dumps({"stories": stories, "next_cursor": next_cursor})

        if cache_key:
            try:
                rds.set(cache_key, payload, ex=FEED_CACHE_TTL)
            except redis.RedisError as exc:
                log.warning("feed cache write failed: %s", exc)

        return Response(payload, mimetype="application/json")

    @app.get("/api/clusters/<int:cluster_id>")
    def cluster(cluster_id: int) -> Response:
        with db.connection() as conn:
            found = db.fetch_cluster(conn, cluster_id)
        if found is None:
            return jsonify({"error": "cluster not found", "cluster_id": cluster_id}), 404
        return jsonify(found)

    @app.get("/api/stats")
    def stats() -> Response:
        """Pipeline metrics, derived from recorded events rather than estimated."""
        window = request.args.get("window_minutes", type=int) or 60
        with db.connection() as conn:
            payload = db.fetch_stats(conn, window_minutes=max(1, min(window, 1440)))

        # Queue depth comes from the broker's management API, not from a
        # passive queue declare: the declare's count lags on the publishing
        # channel and reads low exactly when the queue is backing up.
        payload["queue"] = _queue_depths()
        return jsonify(payload)

    @app.get("/api/stream")
    def stream() -> Response:
        """Server-sent events: new stories as the pipeline produces them.

        SSE rather than websockets because the traffic is one-directional and
        every browser reconnects automatically on drop. Polling on the server
        side keeps the client dumb; the cost is one cheap indexed query per
        tick, against a connection the client already holds open.
        """
        with db.connection() as conn:
            start_id = db.latest_article_id(conn)

        def events():
            last_id = start_id
            # Told up front, so a reconnecting client resumes rather than
            # replaying the whole feed.
            yield f"event: hello\ndata: {json.dumps({'since_id': last_id})}\n\n"

            idle_ticks = 0
            while True:
                with db.connection() as conn:
                    fresh = db.fetch_stories_since(conn, last_id)

                for story in fresh:
                    last_id = max(last_id, story["id"])
                    yield f"event: story\ndata: {json.dumps(story)}\n\n"

                if fresh:
                    idle_ticks = 0
                else:
                    idle_ticks += 1
                    # A comment frame keeps proxies from closing an idle
                    # connection, and costs nothing to the client.
                    if idle_ticks % 5 == 0:
                        yield ": keepalive\n\n"

                time.sleep(STREAM_POLL_SECONDS)

        return Response(
            events(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # stops nginx-style proxies buffering the stream
                "Connection": "keep-alive",
            },
        )

    @app.errorhandler(Exception)
    def on_error(exc: Exception) -> Response:
        """Return JSON for every failure; the frontend only ever parses JSON."""
        code = getattr(exc, "code", 500)
        if code == 404:
            return jsonify({"error": "not found"}), 404
        log.exception("unhandled error")
        return jsonify({"error": "internal error"}), 500

    return app


app = create_app()
