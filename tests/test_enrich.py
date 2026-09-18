"""Tests for rule-based enrichment.

Several of these are regressions: the fallback's output is user-visible in the
feed, and each bug below shipped once before being caught by reading real
output rather than by reasoning about the code.
"""

from __future__ import annotations

import pytest
from pipeline import enrich
from pydantic import ValidationError


@pytest.fixture
def enricher():
    return enrich.RuleBasedEnricher()


# --- schema ---------------------------------------------------------------


def test_enrichment_defaults_are_usable():
    e = enrich.Enrichment()
    assert e.topics == [] and e.entities == [] and e.importance == 3


def test_importance_is_bounded():
    with pytest.raises(ValidationError):
        enrich.Enrichment(importance=0)
    with pytest.raises(ValidationError):
        enrich.Enrichment(importance=6)


def test_entity_rejects_unknown_sentiment():
    with pytest.raises(ValidationError):
        enrich.Entity(name="Acme", sentiment="furious")


def test_provider_is_recorded(enricher):
    """The feed must be able to say whether a model or the fallback produced this."""
    assert enricher.enrich("Title", "Body text here.").provider == "rule-based"


# --- topics ---------------------------------------------------------------


def test_topics_match_whole_words_only():
    """Regression: "app" matched inside "happen", tagging a migrant story tech."""
    text = "It happened apparently after police apprehended the suspect. " * 3
    assert "technology" not in enrich._topics(text)


def test_topics_require_more_than_one_mention():
    """Regression: a single "strike" tagged a Buffett profile as conflict."""
    assert enrich._topics("The investor mentioned a strike once in passing.") == []


def test_topics_detect_crime_not_only_warfare():
    """Regression: a school shooting matched no topic at all."""
    text = "A gunman opened fire; police said the shooting left three dead. The suspect fled."
    assert "crime" in enrich._topics(text)


def test_topics_are_capped():
    text = (
        "shares index investor stock " * 3
        + "inflation gdp recession " * 3
        + "court lawsuit judge trial " * 3
        + "oil gas pipeline opec " * 3
    )
    assert len(enrich._topics(text)) <= enrich.MAX_TOPICS


# --- summary --------------------------------------------------------------


def test_summary_strips_leading_byline():
    """Regression: every BBC summary began "- Published"."""
    body = "- Published 3 hours ago. The minister resigned on Tuesday evening. A successor was named."
    summary = enrich._summarise(body)
    assert not summary.lower().startswith("- published")
    assert "minister resigned" in summary


def test_summary_takes_two_sentences():
    body = "First sentence is long enough to count. Second one also qualifies here. Third is extra."
    assert "Third" not in enrich._summarise(body)


def test_summary_falls_back_to_title_when_body_is_thin(enricher):
    result = enricher.enrich("A headline", "")
    assert result.summary == "A headline"


# --- entities -------------------------------------------------------------


def test_entities_exclude_dates_and_demonyms(enricher):
    """Regression: "Friday", "June" and "Russian" were extracted as entities."""
    body = (
        "Russian forces moved on Friday. Russian units advanced in June. "
        "Moscow confirmed the move. Moscow said little else. "
    ) * 2
    names = {e.name for e in enricher.enrich("Report", body).entities}
    assert "Friday" not in names and "June" not in names and "Russian" not in names
    assert "Moscow" in names


def test_entities_are_frequency_ordered(enricher):
    body = "Acme Corp said so. Acme Corp repeated it. Acme Corp again. Beta Ltd spoke once."
    names = [e.name for e in enricher.enrich("Business", body).entities]
    assert names.index("Acme Corp") < names.index("Beta Ltd")


def test_organisation_suffixes_are_typed(enricher):
    body = "Acme Holdings reported results. Acme Holdings confirmed the figures today."
    entities = {e.name: e.type for e in enricher.enrich("Results", body).entities}
    assert entities.get("Acme Holdings") == "organization"


# --- tickers --------------------------------------------------------------


def test_cashtags_are_extracted(enricher):
    assert "AAPL" in enricher.enrich("Markets", "Shares of $AAPL rose today.").tickers


def test_exchange_prefixed_tickers_are_extracted(enricher):
    assert "BRK.A" in enricher.enrich("Markets", "Berkshire (NYSE: BRK.A) gained.").tickers


def test_no_tickers_when_absent(enricher):
    assert enricher.enrich("Weather", "It rained heavily across the county.").tickers == []


# --- end to end -----------------------------------------------------------


def test_enrich_returns_valid_model_on_empty_input(enricher):
    result = enricher.enrich("", "")
    assert isinstance(result, enrich.Enrichment)
    assert 1 <= result.importance <= 5


def test_enrich_is_deterministic(enricher):
    body = "The central bank raised interest rates. Inflation remains above target."
    assert enricher.enrich("Rates", body) == enricher.enrich("Rates", body)
