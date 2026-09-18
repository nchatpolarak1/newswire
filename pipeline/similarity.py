"""TF-IDF document similarity for story clustering.

Pure functions, no I/O: this is the one part of the pipeline whose correctness
can be pinned down by unit tests alone. Step 12 builds the Redis inverted index
and cluster assignment on top of it.

Why TF-IDF and not SimHash: SimHash finds near-duplicate *text* -- the same
document with small edits. Two outlets covering one event share vocabulary but
almost no three-word sequences, so on real data SimHash scored them as far
apart as unrelated articles. TF-IDF weights the rare shared terms -- the proper
nouns and numbers that actually identify a story -- which is the signal here.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, Mapping

Vector = dict[str, float]

# Terms shorter than this are almost always function words that survive the
# stop list ("us", "eu" are the notable losses; acceptable at this corpus size).
MIN_TERM_LENGTH = 3

# Terms appearing in more than this fraction of the corpus carry no signal --
# they are site boilerplate ("subscribe", "newsletter") or news filler.
MAX_DOCUMENT_FREQUENCY = 0.4

# A term seen in only one document cannot link two articles, and including
# hapaxes inflates vector norms with noise.
MIN_DOCUMENT_FREQUENCY = 2

# How many of an article's heaviest terms get posted to the inverted index.
# Enough that a shared story is reachable from at least one posting; small
# enough that common-ish terms do not turn candidate lookup into a full scan.
INDEX_TERM_COUNT = 24

STOPWORDS = frozenset(
    """
a an and are as at be been being but by for from had has have he her his how i if in is it its
me my no not of on or our she so than that the their them then there these they this those to
too up us was we were what when where which who whom why will with you your
about after again against all also any because before below between both can could did do does
doing down during each few further here into just more most now once only other out over own
same should some such through under until very
said says say according told reported reports report new news latest update updated
first second third one two three like get got make made take taken see seen
mr mrs ms dr sir
""".split()
)

_WORD_RE = re.compile(r"[a-z][a-z'’-]*[a-z]|[a-z]")


def tokenize(text: str) -> list[str]:
    """Content terms: lowercase words, stopwords and very short terms removed."""
    return [w for w in _WORD_RE.findall(text.lower()) if len(w) >= MIN_TERM_LENGTH and w not in STOPWORDS]


def term_frequencies(text: str) -> Counter[str]:
    return Counter(tokenize(text))


def tfidf_vector(
    tf: Mapping[str, int],
    document_frequency: Mapping[str, int],
    corpus_size: int,
    *,
    min_df: int = MIN_DOCUMENT_FREQUENCY,
    max_df_ratio: float = MAX_DOCUMENT_FREQUENCY,
) -> Vector:
    """L2-normalised TF-IDF vector.

    Sublinear term frequency (1 + log tf) keeps a word repeated twenty times
    from dominating a long article. Normalising to unit length makes cosine a
    plain dot product and removes document length from the comparison, so a
    5000-word feature and a 200-word brief on the same story still match.
    """
    if corpus_size <= 0:
        return {}

    max_df = max(corpus_size * max_df_ratio, min_df)
    vector: Vector = {}
    for term, count in tf.items():
        df = document_frequency.get(term, 0)
        if df < min_df or df > max_df:
            continue
        vector[term] = (1.0 + math.log(count)) * math.log(corpus_size / df)

    norm = math.sqrt(sum(w * w for w in vector.values()))
    if norm == 0.0:
        return {}
    return {term: weight / norm for term, weight in vector.items()}


def cosine(a: Vector, b: Vector) -> float:
    """Cosine similarity of two L2-normalised vectors, in [0, 1].

    Iterates the smaller vector, so comparing a brief against a long article
    costs the length of the brief rather than of the article.
    """
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(weight * b.get(term, 0.0) for term, weight in a.items())


def top_terms(vector: Vector, count: int = INDEX_TERM_COUNT) -> list[str]:
    """The heaviest terms, which are what get posted to the inverted index.

    Ties break on the term itself so two replicas indexing the same article
    always choose the same postings.
    """
    return [t for t, _ in sorted(vector.items(), key=lambda kv: (-kv[1], kv[0]))[:count]]


def best_match(vector: Vector, candidates: Iterable[tuple[int, Vector]], threshold: float) -> tuple[int, float] | None:
    """Highest-scoring candidate at or above `threshold`, as (id, score).

    Ties resolve to the lowest id so cluster assignment stays deterministic
    when several enricher replicas process related articles concurrently.
    """
    best: tuple[int, float] | None = None
    for article_id, other in candidates:
        score = cosine(vector, other)
        if score < threshold:
            continue
        if best is None or score > best[1] or (score == best[1] and article_id < best[0]):
            best = (article_id, score)
    return best


def text_for_similarity(title: str, body: str) -> str:
    """The text a vector is built from.

    The title is included once rather than weighted up: outlets rewrite
    headlines for the same story far more than they rewrite the substance.
    """
    return f"{title} {body}".strip()
