"""Central configuration, read from the environment with local-dev defaults.

Every service imports from here rather than calling os.getenv directly, so the
full set of knobs is visible in one place and docker-compose only has to inject
the handful that differ from the defaults.
"""

import os

# --- Datastores -----------------------------------------------------------
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "newswire")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "newswire")
POSTGRES_DB = os.getenv("POSTGRES_DB", "newswire")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}",
)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_URL = os.getenv("REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}/0")

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "newswire")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "newswire")
RABBITMQ_URL = os.getenv(
    "RABBITMQ_URL",
    f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASSWORD}@{RABBITMQ_HOST}:{RABBITMQ_PORT}/",
)
# The management HTTP API backs the queue-depth metric on /api/stats.
RABBITMQ_MANAGEMENT_URL = os.getenv("RABBITMQ_MANAGEMENT_URL", f"http://{RABBITMQ_HOST}:15672")

# --- Queue topology -------------------------------------------------------
EXCHANGE = "news"
DLX_EXCHANGE = "news.dlx"
RAW_QUEUE = "articles.raw"
DEAD_QUEUE = "articles.dead"
RAW_ROUTING_PATTERN = "article.raw.#"

# --- Consumer tuning ------------------------------------------------------
# Bounded prefetch is what makes `--scale enricher=N` actually distribute work;
# without it one consumer buffers the whole queue and the others idle.
PREFETCH_COUNT = int(os.getenv("PREFETCH_COUNT", "8"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# --- Pipeline behaviour ---------------------------------------------------
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "600"))

# Cosine score at or above which two articles are treated as the same story.
# Chosen from the measured distribution over 393 real articles, not guessed:
# >=0.50 is near-verbatim, 0.40-0.50 reads as clean same-story pairs, and
# 0.30-0.40 still holds up (Buffett across four outlets, the Nigerian custody
# deaths, the new cat species) with the first topical false positives appearing
# near the bottom. 0.35 balances precision against recall; re-measure if the
# feed set changes.
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.35"))

# Heaviest terms per article posted to the Redis inverted index.
INDEX_TERM_COUNT = int(os.getenv("INDEX_TERM_COUNT", "24"))

# --- Enrichment -----------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Sonnet rather than Opus: chosen for this workload, where extraction is
# schema-bound and the cost difference matters across thousands of articles.
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

# Extraction output is bounded by the Enrichment schema, so a large ceiling
# would only risk a runaway response.
ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "2000"))


def has_anthropic_credentials() -> bool:
    """Whether LLM enrichment is available.

    The SDK also resolves credentials from an `ant auth login` profile on disk,
    so an unset key does not prove there are none -- but constructing a client
    is the only reliable check and that belongs at call time, not import time.
    When this returns False the enricher falls back to RuleBasedEnricher and the
    pipeline still runs end to end.
    """
    return bool(ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_AUTH_TOKEN"))


# --- Full-text fetching ---
FULLTEXT_TIMEOUT_SECONDS = int(os.getenv("FULLTEXT_TIMEOUT_SECONDS", "12"))
FULLTEXT_ENABLED = os.getenv("FULLTEXT_ENABLED", "1") != "0"
