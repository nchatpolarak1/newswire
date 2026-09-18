"""Tests for TF-IDF similarity.

These pin the properties clustering depends on. The corpus fixture is small and
explicit so a failure points at a behaviour rather than at a statistic.
"""

from __future__ import annotations

import math
from collections import Counter

import pytest
from pipeline import similarity as sim

# Four short documents: two about one event, two unrelated. Small enough to
# reason about by hand, varied enough that IDF does real work.
BUFFETT_A = "Warren Buffett steps down as chairman of Berkshire Hathaway after six decades"
BUFFETT_B = "Berkshire Hathaway chairman Warren Buffett announces he will step down"
SHARK = "Swimmer dies after being bitten by a shark off a popular Perth beach on Saturday"
FOOTBALL = "Manchester United beat Arsenal three one at Old Trafford with two late goals"

CORPUS = [BUFFETT_A, BUFFETT_B, SHARK, FOOTBALL]


@pytest.fixture
def corpus():
    """(document_frequency, corpus_size, vectors) for the fixture corpus."""
    tfs = [sim.term_frequencies(d) for d in CORPUS]
    df: Counter[str] = Counter()
    for tf in tfs:
        df.update(tf.keys())
    vectors = [sim.tfidf_vector(tf, df, len(CORPUS)) for tf in tfs]
    return df, len(CORPUS), vectors


# --- tokenizing -----------------------------------------------------------


def test_tokenize_lowercases_and_drops_punctuation():
    assert sim.tokenize("Berkshire, Hathaway! Inc.") == ["berkshire", "hathaway", "inc"]


def test_tokenize_removes_stopwords_and_short_terms():
    tokens = sim.tokenize("the chairman of a company is in it")
    assert tokens == ["chairman", "company"]


def test_tokenize_keeps_internal_apostrophes():
    assert "company's" in sim.tokenize("the company's results")


def test_tokenize_empty_text():
    assert sim.tokenize("") == []


# --- vectors --------------------------------------------------------------


def test_vector_is_unit_length(corpus):
    """Non-empty vectors are L2-normalised.

    A vector can legitimately be empty -- see the no-shared-vocabulary tests
    below -- so the assertion is conditional rather than universal.
    """
    _, _, vectors = corpus
    non_empty = [v for v in vectors if v]
    assert non_empty, "fixture should produce at least one usable vector"
    for vector in non_empty:
        assert math.isclose(math.sqrt(sum(w * w for w in vector.values())), 1.0, rel_tol=1e-9)


def test_article_with_no_shared_vocabulary_yields_empty_vector(corpus):
    """An article sharing no term with the corpus cannot be clustered.

    Every term in the shark and football documents is unique to it, so min_df
    drops all of them. The empty vector scores 0.0 against everything, which
    makes the article start its own cluster -- the correct outcome, since there
    is no evidence linking it to anything.
    """
    _, _, vectors = corpus
    assert vectors[2] == {}
    assert vectors[3] == {}
    assert sim.cosine(vectors[0], vectors[2]) == 0.0


def test_cold_start_clusters_nothing():
    """With too few documents every term is a hapax, so nothing clusters yet.

    Not a defect, but it means the first articles after a fresh boot each start
    their own cluster and the dedup rate climbs as the corpus grows. Worth
    knowing before reading the rate off a two-minute run.
    """
    docs = ["Warren Buffett steps down from Berkshire Hathaway"]
    tfs = [sim.term_frequencies(d) for d in docs]
    df: Counter[str] = Counter()
    for tf in tfs:
        df.update(tf.keys())
    assert sim.tfidf_vector(tfs[0], df, len(docs)) == {}


def test_rare_terms_outweigh_common_ones(corpus):
    """A term in one document must weigh more than one spread across the corpus."""
    df, n, vectors = corpus
    vector = vectors[0]
    # "berkshire" appears in 2 of 4 docs; "decades" only in this one -- but
    # min_df drops singletons, so compare against the other shared term instead.
    assert df["berkshire"] == 2
    assert vector["berkshire"] > 0


def test_terms_below_min_df_are_dropped(corpus):
    """A term unique to one document cannot link two articles, so it is excluded."""
    df, n, vectors = corpus
    assert df["trafford"] == 1
    assert "trafford" not in vectors[3]


def test_terms_above_max_df_are_dropped():
    """A term in every document is boilerplate and carries no signal."""
    docs = [f"newsletter subscribe {w}" for w in ("alpha beta", "gamma delta", "epsilon zeta")]
    tfs = [sim.term_frequencies(d) for d in docs]
    df: Counter[str] = Counter()
    for tf in tfs:
        df.update(tf.keys())
    vector = sim.tfidf_vector(tfs[0], df, len(docs))
    assert "newsletter" not in vector
    assert "subscribe" not in vector


def test_empty_corpus_yields_empty_vector():
    assert sim.tfidf_vector(Counter({"a": 1}), {"a": 1}, 0) == {}


def test_sublinear_term_frequency():
    """Twenty repeats must not weigh twenty times one repeat."""
    df = {"berkshire": 2, "hathaway": 2}
    once = sim.tfidf_vector(Counter({"berkshire": 1, "hathaway": 1}), df, 10)
    many = sim.tfidf_vector(Counter({"berkshire": 20, "hathaway": 1}), df, 10)
    # Both are normalised, so compare the ratio within each vector.
    assert many["berkshire"] / many["hathaway"] < 20
    assert many["berkshire"] / many["hathaway"] > once["berkshire"] / once["hathaway"]


# --- cosine ---------------------------------------------------------------


def test_identical_text_scores_one(corpus):
    df, n, _ = corpus
    vector = sim.tfidf_vector(sim.term_frequencies(BUFFETT_A), df, n)
    assert math.isclose(sim.cosine(vector, vector), 1.0, rel_tol=1e-9)


def test_same_story_scores_above_unrelated(corpus):
    """The property the whole design rests on."""
    _, _, vectors = corpus
    same_story = sim.cosine(vectors[0], vectors[1])
    unrelated = sim.cosine(vectors[0], vectors[3])
    assert same_story > unrelated
    assert same_story > 0.3
    assert unrelated == 0.0


def test_cosine_is_symmetric(corpus):
    _, _, vectors = corpus
    assert sim.cosine(vectors[0], vectors[1]) == sim.cosine(vectors[1], vectors[0])


def test_cosine_stays_in_unit_range(corpus):
    _, _, vectors = corpus
    for a in vectors:
        for b in vectors:
            assert 0.0 <= sim.cosine(a, b) <= 1.0 + 1e-9


def test_cosine_with_empty_vector(corpus):
    _, _, vectors = corpus
    assert sim.cosine(vectors[0], {}) == 0.0
    assert sim.cosine({}, {}) == 0.0


def test_length_does_not_dominate(corpus):
    """A short brief and a long article on one story must still match.

    41% of ingested articles are teaser-only, so this is load-bearing rather
    than theoretical.
    """
    df, n, _ = corpus
    brief = sim.tfidf_vector(sim.term_frequencies("Warren Buffett Berkshire Hathaway"), df, n)
    full = sim.tfidf_vector(sim.term_frequencies(BUFFETT_A + " " + BUFFETT_A), df, n)
    assert sim.cosine(brief, full) > 0.5


# --- indexing and matching ------------------------------------------------


def test_top_terms_returns_heaviest_first():
    vector = {"low": 0.1, "high": 0.9, "mid": 0.5}
    assert sim.top_terms(vector, 2) == ["high", "mid"]


def test_top_terms_breaks_ties_deterministically():
    """Replicas must choose the same postings for the same article."""
    vector = {"beta": 0.5, "alpha": 0.5, "gamma": 0.5}
    assert sim.top_terms(vector, 2) == ["alpha", "beta"]


def test_top_terms_caps_at_count():
    vector = {f"t{i}": i / 100 for i in range(50)}
    assert len(sim.top_terms(vector, 24)) == 24


def test_best_match_picks_highest_scorer(corpus):
    _, _, vectors = corpus
    candidates = [(2, vectors[2]), (1, vectors[1]), (3, vectors[3])]
    match = sim.best_match(vectors[0], candidates, threshold=0.1)
    assert match is not None and match[0] == 1


def test_best_match_respects_threshold(corpus):
    _, _, vectors = corpus
    assert sim.best_match(vectors[0], [(3, vectors[3])], threshold=0.35) is None


def test_best_match_with_no_candidates(corpus):
    _, _, vectors = corpus
    assert sim.best_match(vectors[0], [], threshold=0.35) is None


def test_best_match_ties_resolve_to_lowest_id(corpus):
    """Deterministic assignment when replicas race on related articles."""
    _, _, vectors = corpus
    match = sim.best_match(vectors[0], [(9, vectors[1]), (4, vectors[1])], threshold=0.1)
    assert match is not None and match[0] == 4


def test_text_for_similarity_joins_title_and_body():
    assert sim.text_for_similarity("Title", "Body") == "Title Body"
    assert sim.text_for_similarity("Title", "") == "Title"
