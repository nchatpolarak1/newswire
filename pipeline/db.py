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


# --- SimHash storage ------------------------------------------------------
# Postgres BIGINT is signed; SimHash is an unsigned 64-bit value. Round-trip
# through two's complement rather than losing the top bit.

_SIGN_BIT = 1 << 63
_MASK_64 = (1 << 64) - 1


def to_signed_64(value: int) -> int:
    value &= _MASK_64
    return value - (1 << 64) if value & _SIGN_BIT else value


def from_signed_64(value: int) -> int:
    return value & _MASK_64


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
