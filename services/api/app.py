"""Flask API serving the clustered, enriched feed.

Redis is used here as an actual cache -- a short-lived copy of a query result
that can be thrown away at any time -- which is worth contrasting with the
original tech lab, where Redis *was* the database and the whole dataset lived
under a single key.
"""

from __future__ import annotations

import json
import logging

import redis
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
