"""Article enrichment: structured extraction behind a swappable interface.

Two implementations sit behind one protocol. RuleBasedEnricher needs no
credentials and no network, so the pipeline runs end to end without an API key;
ClaudeEnricher (step 14) is the real one. Whichever is active is chosen once at
startup by `get_enricher`, and the rest of the pipeline cannot tell them apart.

The rule-based output is deliberately modest -- it is a floor that keeps the
system runnable and the UI populated, not an attempt to approximate an LLM.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from pipeline import config

log = logging.getLogger(__name__)

EntityType = Literal["person", "organization", "location", "other"]
Sentiment = Literal["positive", "negative", "neutral"]


class Entity(BaseModel):
    """A named thing the article is about."""

    name: str = Field(max_length=120)
    type: EntityType = "other"
    sentiment: Sentiment = "neutral"


class Extraction(BaseModel):
    """What an enricher derives from an article.

    This is the exact schema handed to the model as a structured output, so the
    field descriptions below are prompt surface, not just documentation. It
    deliberately excludes provenance: the model is never asked for metadata it
    cannot know.
    """

    summary: str = Field(
        default="",
        max_length=600,
        description="Two sentences of plain prose describing what happened. No preamble.",
    )
    topics: list[str] = Field(
        default_factory=list,
        max_length=4,
        description="Up to four lowercase topic labels, most relevant first.",
    )
    entities: list[Entity] = Field(
        default_factory=list,
        max_length=12,
        description="People, organisations and places the article is actually about.",
    )
    tickers: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Stock tickers only where the company is confidently identifiable.",
    )
    importance: int = Field(
        default=3,
        ge=1,
        le=5,
        description="1 routine, 3 notable, 5 major news of the day.",
    )


class Enrichment(Extraction):
    """An extraction plus the provenance the pipeline records for it."""

    provider: str = Field(default="rule-based", description="Which enricher produced this.")


class Enricher(Protocol):
    """What the consumer depends on. Both implementations satisfy this."""

    name: str

    def enrich(self, title: str, body: str) -> Enrichment: ...


# --- Rule-based fallback --------------------------------------------------

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")
_PAREN_TICKER_RE = re.compile(r"\((?:NYSE|NASDAQ|LSE|AMEX):\s*([A-Z.]{1,6})\)")
_PROPER_NOUN_RE = re.compile(r"\b(?:[A-Z][a-z’'\-]{2,}(?:\s+[A-Z][a-z’'\-]{2,}){0,3})\b")

# Months, weekdays and nationality adjectives look like proper nouns but are
# not things the article is about.
_NON_ENTITIES = frozenset(
    """
January February March April May June July August September October November December
Monday Tuesday Wednesday Thursday Friday Saturday Sunday
Russian Chinese American British French German Spanish Italian Israeli Ukrainian Indian
European African Asian Australian Canadian Japanese Iranian Brazilian Mexican Dutch Swedish
""".split()
)

# Words that open sentences and would otherwise look like proper nouns.
_SENTENCE_STARTERS = frozenset(
    """
The A An This That These Those It He She They We You I But And Or If When While After Before
Since Although Though However Meanwhile Now Then There Here What Which Who Why How
Some Many Most Both Each Other Another All Any More Less Last Next First Second Third
Mr Mrs Ms Dr Sir President Prime Minister According Reuters
""".split()
)

_TOPIC_LEXICON: dict[str, tuple[str, ...]] = {
    "markets": ("stock", "shares", "index", "nasdaq", "ftse", "bond", "yield", "investor"),
    "economy": ("inflation", "gdp", "recession", "unemployment", "interest rate", "central bank"),
    "technology": ("software", "chip", "semiconductor", "startup", "platform", "app"),
    "ai": ("artificial intelligence", " ai ", "machine learning", "chatbot", "llm", "openai"),
    "politics": ("election", "parliament", "congress", "senate", "minister", "president"),
    "conflict": ("strike", "attack", "troops", "ceasefire", "missile", "war", "military"),
    "energy": ("oil", "gas", "renewable", "electricity", "solar", "pipeline", "opec"),
    "health": ("hospital", "patients", "virus", "vaccine", "disease", "doctors"),
    "climate": ("climate", "emissions", "net zero", "warming", "carbon"),
    "legal": ("court", "lawsuit", "judge", "trial", "charges", "verdict", "jury"),
    "business": ("company", "revenue", "profit", "merger", "acquisition", "takeover", "ceo"),
    "sport": ("league", "match", "goals", "tournament", "coach", "striker"),
    "crime": ("shooting", "gunman", "murder", "police", "arrested", "stabbing", "assault", "killing", "suspect"),
    "disaster": ("earthquake", "flood", "wildfire", "hurricane", "storm", "crash", "evacuated", "rescue"),
}

_NEGATIVE = (
    "dies",
    "killed",
    "crash",
    "collapse",
    "loss",
    "losses",
    "fraud",
    "scandal",
    "attack",
    "war",
    "recession",
    "plunge",
    "slump",
    "cut",
    "fell",
    "warning",
)
_POSITIVE = (
    "record",
    "surge",
    "growth",
    "profit",
    "wins",
    "won",
    "rally",
    "rescue",
    "breakthrough",
    "recovery",
    "gains",
    "rose",
    "boost",
)


# Extracted bodies often open with a byline or dateline fragment that is not a
# sentence ("- Published", "By Jane Doe", "3 hours ago").
_LEAD_BOILERPLATE_RE = re.compile(
    r"^\s*(?:[-–—]\s*)?(?:published|updated|by\s+[A-Z][\w.'’-]*(?:\s+[A-Z][\w.'’-]*)*"
    r"|\d+\s+(?:minutes?|hours?|days?)\s+ago)\b[^.!?]*[.!?]?\s*",
    re.IGNORECASE,
)


def _summarise(body: str, sentences: int = 2) -> str:
    cleaned = _LEAD_BOILERPLATE_RE.sub("", body.strip(), count=1)
    parts = [s.strip() for s in _SENTENCE_RE.split(cleaned) if len(s.strip()) > 20]
    return " ".join(parts[:sentences])[:600]


# Substring matching tagged a migrant story as "technology" because "app"
# occurs inside "happen" and "apparently". Match whole words only.
_TOPIC_PATTERNS: dict[str, re.Pattern[str]] = {
    topic: re.compile(r"\b(?:" + "|".join(re.escape(k.strip()) for k in keywords) + r")\b")
    for topic, keywords in _TOPIC_LEXICON.items()
}

# A single incidental mention is not a topic. Requiring two hits drops the
# "conflict" tag a Buffett profile earned from one use of "strike".
MIN_TOPIC_HITS = 2
MAX_TOPICS = 3


def _topics(text: str) -> list[str]:
    lowered = text.lower()
    scored = [(len(p.findall(lowered)), topic) for topic, p in _TOPIC_PATTERNS.items()]
    return [t for score, t in sorted(scored, reverse=True) if score >= MIN_TOPIC_HITS][:MAX_TOPICS]


def _tickers(text: str) -> list[str]:
    found = set(_CASHTAG_RE.findall(text)) | set(_PAREN_TICKER_RE.findall(text))
    return sorted(found)[:8]


def _sentiment(context: str) -> Sentiment:
    lowered = context.lower()
    negative = sum(lowered.count(w) for w in _NEGATIVE)
    positive = sum(lowered.count(w) for w in _POSITIVE)
    if negative > positive:
        return "negative"
    if positive > negative:
        return "positive"
    return "neutral"


def _entities(title: str, body: str) -> list[Entity]:
    """Frequent proper-noun phrases, typed only where a cheap signal exists.

    Crude by design: without a model this cannot distinguish a person from a
    company, so most entities are typed "other" rather than guessed wrongly.
    """
    text = f"{title}. {body}"
    counts: dict[str, int] = {}
    for match in _PROPER_NOUN_RE.finditer(text):
        phrase = match.group(0).strip()
        if phrase.split()[0] in _SENTENCE_STARTERS and " " not in phrase:
            continue
        if phrase in _NON_ENTITIES or len(phrase) < 3:
            continue
        counts[phrase] = counts.get(phrase, 0) + 1

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
    entities = []
    for name, _ in ranked:
        kind: EntityType = "other"
        if re.search(r"\b(Inc|Corp|Ltd|PLC|Group|Bank|Holdings|Technologies)\b", name):
            kind = "organization"
        entities.append(Entity(name=name, type=kind, sentiment=_sentiment(title)))
    return entities


def _importance(title: str, body: str, entity_count: int) -> int:
    """Rough 1-5 from length and language, since no model is available.

    Stated plainly so nobody mistakes it for a learned score: longer pieces
    with many named entities and charged language tend to be bigger stories.
    """
    score = 2
    if len(body) > 3000:
        score += 1
    if entity_count >= 6:
        score += 1
    if _sentiment(title) != "neutral":
        score += 1
    return max(1, min(5, score))


class RuleBasedEnricher:
    """Deterministic extraction with no model and no network.

    Exists so the pipeline is runnable and demonstrable without credentials.
    Its output is intentionally shallow -- entities are proper-noun frequency,
    sentiment is a word list, importance is a heuristic.
    """

    name = "rule-based"

    def enrich(self, title: str, body: str) -> Enrichment:
        text = f"{title} {body}"
        entities = _entities(title, body)
        return Enrichment(
            summary=_summarise(body) or title,
            topics=_topics(text),
            entities=entities,
            tickers=_tickers(text),
            importance=_importance(title, body, len(entities)),
            provider=self.name,
        )


# --- Claude ---------------------------------------------------------------


@dataclass(frozen=True)
class Usage:
    """Token accounting for one call, recorded so spend is measured not guessed."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class ClaudeEnricher:
    """Structured extraction via the Messages API.

    Two properties matter here beyond "it returns JSON":

    Prompt caching. The system prompt is byte-identical on every request and
    carries a cache breakpoint, so after the first call its ~1.1k tokens are
    read from cache at a fraction of the price. Nothing per-request is allowed
    ahead of it in the prefix -- that is why the article goes in the user turn
    rather than being interpolated into the system text.

    Failure separation. A rate limit or a 5xx is transient, so it propagates and
    the consumer's backoff handles it. An auth or request error would fail
    identically for every article, so rather than dead-lettering the whole feed
    it falls back to rule-based extraction and says so loudly -- and the
    provider field records which path produced the row.
    """

    name = "claude"

    # Bodies are capped before sending: extraction quality plateaus well before
    # a full long-read, and input tokens are the bulk of the cost.
    MAX_BODY_CHARS = 12_000

    def __init__(self, model: str | None = None) -> None:
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic()
        self.model = model or config.ANTHROPIC_MODEL
        self._fallback = RuleBasedEnricher()
        self.last_usage = Usage()

    def enrich(self, title: str, body: str) -> Enrichment:
        from pipeline.prompts import EXTRACTION_SYSTEM_PROMPT

        article = f"{title}\n\n{body[: self.MAX_BODY_CHARS]}".strip()
        if not article:
            return self._fallback.enrich(title, body)

        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=config.ANTHROPIC_MAX_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": EXTRACTION_SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": article}],
                output_config={"effort": "low"},
                output_format=Extraction,
            )
        except (self._anthropic.RateLimitError, self._anthropic.APIConnectionError):
            raise  # transient: let the consumer's backoff retry it
        except self._anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise  # transient
            log.error(
                "enrichment request rejected (HTTP %s); falling back to rule-based: %s",
                exc.status_code,
                exc.message,
            )
            return self._fallback.enrich(title, body)

        usage = response.usage
        self.last_usage = Usage(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )

        extraction = response.parsed_output
        if extraction is None:
            log.warning("model returned no parsed output; falling back to rule-based")
            return self._fallback.enrich(title, body)

        return Enrichment(**extraction.model_dump(), provider=self.name)


def get_enricher() -> Enricher:
    """Pick an implementation once, at startup.

    The log line names the choice either way, so rule-based output is never
    mistaken for model output. Construction failure is not fatal: a bad key
    should degrade the feed, not stop it ingesting.
    """
    if not config.has_anthropic_credentials():
        log.warning(
            "no Anthropic credentials; using rule-based enrichment (set ANTHROPIC_API_KEY for model extraction)"
        )
        return RuleBasedEnricher()

    try:
        enricher = ClaudeEnricher()
    except Exception:
        log.exception("could not start Claude enrichment; falling back to rule-based")
        return RuleBasedEnricher()

    log.info("using Claude enrichment (model %s)", enricher.model)
    return enricher
