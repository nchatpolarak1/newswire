"""Fetch an article's real body text from its URL.

RSS feeds mostly carry a headline plus a one-sentence teaser -- around 110
characters across most of our sources. SimHash needs actual prose to tell
"same story, different outlet" from "different story", and entity extraction
needs more than one sentence, so the body is fetched from the page itself.

The teaser is always kept as a fallback: a paywall, a bot block or a timeout
is a normal outcome here, not an error worth failing the message over.
"""

from __future__ import annotations

import logging
import urllib.robotparser
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

import requests
import trafilatura

from pipeline import config

log = logging.getLogger(__name__)

# Identify the crawler honestly rather than impersonating a browser.
USER_AGENT = "NewswireBot/0.1 (+https://github.com/nchatpolarak1/newswire) python-requests"

# Anything under this is a nav stub or a cookie wall, not an article body.
MIN_BODY_CHARS = 400


@lru_cache(maxsize=256)
def _robots_for(origin: str) -> urllib.robotparser.RobotFileParser | None:
    """Parse a host's robots.txt once and reuse it.

    On any failure this returns None and the caller proceeds: an unreachable
    robots.txt is not the same as a disallow.
    """
    parser = urllib.robotparser.RobotFileParser()
    try:
        response = requests.get(f"{origin}/robots.txt", timeout=8, headers={"User-Agent": USER_AGENT})
        if response.status_code != 200:
            return None
        parser.parse(response.text.splitlines())
        return parser
    except requests.RequestException:
        return None


def allowed_by_robots(url: str) -> bool:
    """Whether robots.txt permits us to fetch this URL."""
    parts = urlsplit(url)
    origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    parser = _robots_for(origin)
    if parser is None:
        return True
    return parser.can_fetch(USER_AGENT, url)


@dataclass(frozen=True)
class FetchResult:
    body: str
    source: str  # "fulltext" | "teaser"
    fetched_chars: int


def fetch_body(url: str, teaser: str, timeout: int | None = None) -> FetchResult:
    """Best-effort full text, falling back to the teaser.

    Never raises: every failure path yields the teaser, so a blocked site
    degrades the article rather than dead-lettering it.
    """
    timeout = timeout or config.FULLTEXT_TIMEOUT_SECONDS

    if not allowed_by_robots(url):
        log.debug("robots.txt disallows %s", url)
        return FetchResult(teaser, "teaser", 0)

    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        if status in (401, 403, 429):
            log.debug("%s refuses automated access (HTTP %s)", urlsplit(url).netloc, status)
        else:
            log.debug("fulltext fetch failed for %s: %s", url, exc)
        return FetchResult(teaser, "teaser", 0)
    except requests.RequestException as exc:
        log.debug("fulltext fetch failed for %s: %s", url, exc)
        return FetchResult(teaser, "teaser", 0)

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower():
        return FetchResult(teaser, "teaser", 0)

    extracted = trafilatura.extract(
        response.text,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )

    if not extracted or len(extracted) < MIN_BODY_CHARS:
        return FetchResult(teaser, "teaser", len(extracted or ""))

    # Keep the teaser when extraction somehow yielded less than the feed gave us.
    if len(extracted) <= len(teaser):
        return FetchResult(teaser, "teaser", len(extracted))

    return FetchResult(extracted, "fulltext", len(extracted))
