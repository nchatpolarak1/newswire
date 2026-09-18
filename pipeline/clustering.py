"""Cluster assignment backed by a Redis inverted index.

The shape is index -> candidates -> verify. Rather than comparing a new article
against every stored one, each article's heaviest terms are posted to Redis
sets; a new article's candidates are the union of the postings for *its*
heaviest terms, and exact cosine is computed only against those. That keeps
comparison proportional to how many articles share rare vocabulary rather than
to corpus size.

IDF is maintained incrementally: a Redis hash of document frequencies plus a
document counter, both updated as articles arrive, so weights reflect the live
corpus instead of a snapshot.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

import redis

from pipeline import config
from pipeline import similarity as sim

log = logging.getLogger(__name__)

DF_KEY = "tfidf:df"  # hash term -> document frequency
DOC_COUNT_KEY = "tfidf:n"  # total documents seen
POSTING_KEY = "tfidf:inv:{}"  # set of article ids per indexed term
VECTOR_KEY = "tfidf:vec:{}"  # json vector per article id

# Vectors and postings expire so Redis does not grow without bound on a long
# run. A week is far longer than any story stays live.
TTL_SECONDS = 7 * 24 * 3600

# A term posted by more articles than this is too common to be a useful
# candidate source, and unioning its postings would approach a full scan.
MAX_POSTING_FANOUT = 400


@dataclass(frozen=True)
class Assignment:
    cluster_id: Optional[int]
    matched_article_id: Optional[int]
    score: float
    candidates_examined: int

    @property
    def is_new_cluster(self) -> bool:
        return self.matched_article_id is None


def register_document(rds: redis.Redis, term_count: dict[str, int]) -> int:
    """Fold one document into the corpus statistics, returning the new size.

    Document frequency counts distinct terms, not occurrences, so a term
    repeated within an article still contributes one.
    """
    pipe = rds.pipeline()
    for term in term_count:
        pipe.hincrby(DF_KEY, term, 1)
    pipe.incr(DOC_COUNT_KEY)
    return int(pipe.execute()[-1])


def document_frequencies(rds: redis.Redis, terms: list[str]) -> dict[str, int]:
    """Document frequencies for the terms of one article, in a single round trip."""
    if not terms:
        return {}
    values = rds.hmget(DF_KEY, terms)
    return {t: int(v) for t, v in zip(terms, values) if v is not None}


def candidate_ids(rds: redis.Redis, terms: list[str]) -> set[int]:
    """Article ids sharing at least one of these terms.

    Postings for very common terms are skipped: they would contribute most of
    the corpus while adding little discriminating power, turning candidate
    lookup into the scan the index exists to avoid.
    """
    if not terms:
        return set()

    sizes = rds.pipeline()
    for term in terms:
        sizes.scard(POSTING_KEY.format(term))
    usable = [term for term, size in zip(terms, sizes.execute()) if 0 < size <= MAX_POSTING_FANOUT]
    if not usable:
        return set()

    members = rds.pipeline()
    for term in usable:
        members.smembers(POSTING_KEY.format(term))
    ids: set[int] = set()
    for group in members.execute():
        ids.update(int(m) for m in group)
    return ids


def load_vectors(rds: redis.Redis, ids: set[int]) -> list[tuple[int, sim.Vector]]:
    """Stored vectors for candidate articles, skipping any that have expired."""
    if not ids:
        return []
    ordered = sorted(ids)
    pipe = rds.pipeline()
    for article_id in ordered:
        pipe.get(VECTOR_KEY.format(article_id))
    return [(article_id, json.loads(raw)) for article_id, raw in zip(ordered, pipe.execute()) if raw]


def index_document(rds: redis.Redis, article_id: int, vector: sim.Vector, terms: list[str]) -> None:
    """Store an article's vector and post it to its heaviest terms."""
    pipe = rds.pipeline()
    pipe.set(VECTOR_KEY.format(article_id), json.dumps(vector), ex=TTL_SECONDS)
    for term in terms:
        key = POSTING_KEY.format(term)
        pipe.sadd(key, article_id)
        pipe.expire(key, TTL_SECONDS)
    pipe.execute()


def assign(rds: redis.Redis, article_id: int, title: str, body: str) -> Assignment:
    """Place an article: join the nearest existing story, or start a new one.

    Registering the document before scoring means its own terms are included in
    the corpus statistics. That is deliberate -- it keeps df consistent with the
    vectors already indexed, and the article cannot match itself because it is
    not yet posted to the index.
    """
    term_count = sim.term_frequencies(sim.text_for_similarity(title, body))
    if not term_count:
        return Assignment(None, None, 0.0, 0)

    corpus_size = register_document(rds, term_count)
    df = document_frequencies(rds, list(term_count))
    vector = sim.tfidf_vector(term_count, df, corpus_size)

    if not vector:
        # Nothing shared with the corpus yet -- common on a cold start.
        return Assignment(None, None, 0.0, 0)

    terms = sim.top_terms(vector, config.INDEX_TERM_COUNT)
    candidates = load_vectors(rds, candidate_ids(rds, terms))
    match = sim.best_match(vector, candidates, config.SIMILARITY_THRESHOLD)

    index_document(rds, article_id, vector, terms)

    if match is None:
        return Assignment(None, None, 0.0, len(candidates))
    matched_id, score = match
    return Assignment(None, matched_id, score, len(candidates))
