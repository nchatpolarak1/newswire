"""Turn a feedparser entry into the flat article dict the queue carries.

RSS is only loosely standardised, so every field here has a fallback chain.
Kept separate from the polling loop so it can be exercised without network.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any, Optional

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str) -> str:
    """Strip markup and collapse whitespace; feed summaries are often HTML."""
    if not raw:
        return ""
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", raw))).strip()


def _first_present(entry: Any, *keys: str) -> str:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def extract_body(entry: Any) -> str:
    """Longest available text for the entry.

    Feeds disagree on where the body lives, and some populate both `summary`
    and `content` with different lengths. SimHash quality depends on getting
    the most text available, so take the longest rather than the first.
    """
    candidates = [_first_present(entry, "summary", "description")]
    for block in entry.get("content") or []:
        value = block.get("value") if isinstance(block, dict) else None
        if value:
            candidates.append(value)
    return max((clean_text(c) for c in candidates), key=len, default="")


def extract_image(entry: Any) -> str:
    for key in ("media_content", "media_thumbnail"):
        for item in entry.get(key) or []:
            url = item.get("url") if isinstance(item, dict) else None
            if url:
                return url
    for link in entry.get("links") or []:
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image/"):
            return link.get("href", "")
    return ""


def extract_published(entry: Any) -> Optional[str]:
    """ISO-8601 publish time, or None when the feed omits a usable one."""
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
            except (TypeError, ValueError):
                continue
    return None


def extract_author(entry: Any) -> str:
    author = _first_present(entry, "author")
    if not author:
        detail = entry.get("author_detail") or {}
        author = detail.get("name", "") if isinstance(detail, dict) else ""
    return clean_text(author)[:200]


def to_article(entry: Any, source: str) -> Optional[dict[str, Any]]:
    """Flatten an entry, or None if it lacks the fields that make it useful.

    A title and link are required for identity; a body is required because an
    article with no text cannot be clustered or enriched.
    """
    url = _first_present(entry, "link", "id").strip()
    title = clean_text(_first_present(entry, "title"))
    body = extract_body(entry)

    if not url or not title or not body:
        return None

    return {
        "url": url,
        "title": title[:500],
        "body": body,
        "author": extract_author(entry),
        "source": source,
        "image_url": extract_image(entry),
        "published_at": extract_published(entry),
    }
