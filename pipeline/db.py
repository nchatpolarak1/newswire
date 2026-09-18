"""Postgres access: connection pool, schema bootstrap, and article writes."""

from __future__ import annotations

import atexit
import hashlib
import json
import pathlib
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from pipeline import config

_SCHEMA_PATH = pathlib.Path(__file__).with_name("schema.sql")

# Opened lazily so importing this module never reaches for the network -- tests
# and the poller import it for the helpers alone.
_pool: Optional[ConnectionPool] = None

# Tracking parameters carry no meaning for identity; two URLs differing only by
# campaign tags are the same article and must hash alike.
_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref_", "spm")


def get_pool() -> ConnectionPool:
    """Process-wide connection pool, created on first use."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=8, open=True)
        # Without this the pool's worker threads outlive the interpreter and
        # every shutdown prints "couldn't stop thread ... within 5.0 seconds".
        atexit.register(close_pool)
    return _pool


def close_pool() -> None:
    """Close the pool and join its workers. Safe to call more than once."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    """A pooled connection. Commits on clean exit, rolls back on exception."""
    with get_pool().connection() as conn:
        yield conn


def init_schema() -> None:
    """Apply schema.sql. Idempotent, so every service can call it at startup."""
    with connection() as conn:
        conn.execute(_SCHEMA_PATH.read_text())


# --- Identity -------------------------------------------------------------


def normalize_url(url: str) -> str:
    """Canonical form of a URL for identity purposes.

    Lowercases the host, drops the fragment and tracking parameters, and
    removes a trailing slash, so cosmetic variants collapse to one key.
    """
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            urlencode(sorted(query)),
            "",
        )
    )


def url_hash(url: str) -> str:
    """Stable identity for an article URL."""
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


# --- Writes ---------------------------------------------------------------


def insert_article(conn: psycopg.Connection, article: dict[str, Any]) -> Optional[int]:
    """Insert one article, returning its id, or None if already stored.

    ON CONFLICT DO NOTHING is what makes redelivery harmless: a duplicate is a
    no-op rather than an error, so the consumer can ack it either way.
    """
    row = conn.execute(
        """
        INSERT INTO articles (url_hash, url, title, body, author, source, image_url, published_at)
        VALUES (%(url_hash)s, %(url)s, %(title)s, %(body)s, %(author)s, %(source)s,
                %(image_url)s, %(published_at)s)
        ON CONFLICT (url_hash) DO NOTHING
        RETURNING id
        """,
        article,
    ).fetchone()
    return row[0] if row else None


def record_event(
    conn: psycopg.Connection,
    stage: str,
    *,
    article_id: Optional[int] = None,
    latency_ms: Optional[int] = None,
    tokens_in: Optional[int] = None,
    tokens_out: Optional[int] = None,
    cache_read_tokens: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    """Append a pipeline event. These rows are the evidence behind /api/stats."""
    conn.execute(
        """
        INSERT INTO pipeline_events
            (stage, article_id, latency_ms, tokens_in, tokens_out, cache_read_tokens, detail)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (stage, article_id, latency_ms, tokens_in, tokens_out, cache_read_tokens, detail),
    )


def set_enrichment(conn: psycopg.Connection, article_id: int, enrichment: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE articles SET enrichment = %s, enriched_at = now() WHERE id = %s",
        (json.dumps(enrichment), article_id),
    )


def parse_timestamp(value: str | None) -> Optional[datetime]:
    """Parse a feed timestamp, tolerating the variants RSS puts in the wild."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# --- Clustering -----------------------------------------------------------


def create_cluster(conn: psycopg.Connection, article_id: int) -> int:
    """Start a new cluster with this article as its canonical member."""
    row = conn.execute(
        """
        INSERT INTO clusters (canonical_article_id, first_seen, last_seen)
        VALUES (%s, now(), now())
        RETURNING id
        """,
        (article_id,),
    ).fetchone()
    cluster_id = int(row[0])
    conn.execute("UPDATE articles SET cluster_id = %s WHERE id = %s", (cluster_id, article_id))
    return cluster_id


def join_cluster(conn: psycopg.Connection, article_id: int, matched_article_id: int) -> int:
    """Attach an article to the cluster of the article it matched.

    The matched article may itself be unclustered if a replica is mid-flight,
    so its cluster is created on demand. The UPDATE ... RETURNING keeps the
    member count consistent under concurrent writers by letting Postgres
    serialise the increment rather than reading then writing.
    """
    row = conn.execute("SELECT cluster_id FROM articles WHERE id = %s", (matched_article_id,)).fetchone()
    cluster_id = row[0] if row else None

    if cluster_id is None:
        cluster_id = create_cluster(conn, matched_article_id)

    conn.execute(
        """
        UPDATE clusters SET member_count = member_count + 1, last_seen = now()
        WHERE id = %s
        """,
        (cluster_id,),
    )
    conn.execute("UPDATE articles SET cluster_id = %s WHERE id = %s", (cluster_id, article_id))
    return int(cluster_id)


# --- Reads ----------------------------------------------------------------

# The feed is a list of stories, not articles: one row per cluster, represented
# by its canonical member, carrying how many outlets covered it and which.
_FEED_SELECT = """
    SELECT a.id, a.url, a.title, a.body, a.author, a.source, a.image_url,
           a.published_at, a.enrichment,
           c.id AS cluster_id, c.member_count,
           ARRAY(SELECT DISTINCT m.source FROM articles m
                 WHERE m.cluster_id = c.id AND m.source <> '' ORDER BY m.source) AS sources
    FROM clusters c
    JOIN articles a ON a.id = c.canonical_article_id
"""

# Keyset pagination rather than OFFSET: the feed grows at the head while a
# reader is paging, and OFFSET would silently skip or repeat rows as it shifts.
_FEED_ORDER = " ORDER BY a.published_at DESC NULLS LAST, a.id DESC LIMIT %(limit)s"


def _row_to_story(row: Any) -> dict[str, Any]:
    published = row["published_at"]
    return {
        "id": row["id"],
        "url": row["url"],
        "title": row["title"],
        "body": row["body"],
        "author": row["author"],
        "source": row["source"],
        "image_url": row["image_url"],
        "published_at": published.isoformat() if published else None,
        "enrichment": row["enrichment"],
        "cluster_id": row["cluster_id"],
        # Two distinct counts, because they answer different questions and a
        # cluster can hold several articles from one outlet. cluster_size is
        # how many articles; outlet_count is how many mastheads. The UI's
        # "covered by N outlets" must use the latter or it overstates reach.
        "cluster_size": row["member_count"],
        "outlet_count": len(row["sources"] or []),
        "sources": row["sources"] or [],
    }


def fetch_feed(
    conn: psycopg.Connection, limit: int = 30, cursor: Optional[str] = None
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """One page of the story feed, newest first, with the next cursor.

    The cursor encodes the last row's (published_at, id) so paging is stable
    against concurrent inserts at the head of the feed.
    """
    params: dict[str, Any] = {"limit": limit}
    sql = _FEED_SELECT

    if cursor:
        try:
            ts_part, id_part = cursor.rsplit("|", 1)
            params["cursor_ts"] = datetime.fromisoformat(ts_part)
            params["cursor_id"] = int(id_part)
            sql += " WHERE (a.published_at, a.id) < (%(cursor_ts)s, %(cursor_id)s)"
        except (ValueError, TypeError):
            pass  # an unparseable cursor returns the first page rather than erroring

    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(sql + _FEED_ORDER, params).fetchall()

    stories = [_row_to_story(r) for r in rows]
    next_cursor = None
    if len(stories) == limit and stories[-1]["published_at"]:
        next_cursor = f"{stories[-1]['published_at']}|{stories[-1]['id']}"
    return stories, next_cursor


def fetch_cluster(conn: psycopg.Connection, cluster_id: int) -> Optional[dict[str, Any]]:
    """Every article in one cluster: the same story as each outlet told it."""
    with conn.cursor(row_factory=dict_row) as cur:
        cluster = cur.execute(
            "SELECT id, member_count, first_seen, last_seen FROM clusters WHERE id = %s",
            (cluster_id,),
        ).fetchone()
        if cluster is None:
            return None

        members = cur.execute(
            """
            SELECT id, url, title, body, author, source, image_url, published_at, enrichment
            FROM articles WHERE cluster_id = %s
            ORDER BY published_at ASC NULLS LAST, id ASC
            """,
            (cluster_id,),
        ).fetchall()

    return {
        "cluster_id": cluster["id"],
        "member_count": cluster["member_count"],
        "first_seen": cluster["first_seen"].isoformat() if cluster["first_seen"] else None,
        "last_seen": cluster["last_seen"].isoformat() if cluster["last_seen"] else None,
        "articles": [
            {
                "id": m["id"],
                "url": m["url"],
                "title": m["title"],
                "body": m["body"],
                "author": m["author"],
                "source": m["source"],
                "image_url": m["image_url"],
                "published_at": m["published_at"].isoformat() if m["published_at"] else None,
                "enrichment": m["enrichment"],
            }
            for m in members
        ],
    }
