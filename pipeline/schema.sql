-- Newswire schema. Applied idempotently at service startup by pipeline.db.init_schema.

CREATE TABLE IF NOT EXISTS clusters (
    id                   BIGSERIAL PRIMARY KEY,
    canonical_article_id BIGINT,
    member_count         INT         NOT NULL DEFAULT 1,
    first_seen           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS articles (
    id           BIGSERIAL PRIMARY KEY,
    -- SHA-256 of the normalized URL. The uniqueness that makes the consumer
    -- safe to replay under at-least-once delivery.
    url_hash     TEXT        NOT NULL UNIQUE,
    url          TEXT        NOT NULL,
    title        TEXT        NOT NULL,
    body         TEXT        NOT NULL DEFAULT '',
    author       TEXT        NOT NULL DEFAULT '',
    source       TEXT        NOT NULL DEFAULT '',
    image_url    TEXT        NOT NULL DEFAULT '',
    published_at TIMESTAMPTZ,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Stored signed: Postgres BIGINT has no unsigned variant, so the 64-bit
    -- SimHash is mapped through a signed round-trip in pipeline.db.
    simhash      BIGINT,
    cluster_id   BIGINT REFERENCES clusters(id) ON DELETE SET NULL,
    enrichment   JSONB,
    enriched_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS articles_published_at_idx ON articles (published_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS articles_cluster_id_idx   ON articles (cluster_id);
CREATE INDEX IF NOT EXISTS articles_unenriched_idx   ON articles (id) WHERE enrichment IS NULL;

-- Evidence for the throughput, latency, dedup and spend numbers. Written on
-- every stage transition; queried by /api/stats.
CREATE TABLE IF NOT EXISTS pipeline_events (
    id                BIGSERIAL PRIMARY KEY,
    stage             TEXT        NOT NULL,
    article_id        BIGINT,
    latency_ms        INT,
    tokens_in         INT,
    tokens_out        INT,
    cache_read_tokens INT,
    detail            TEXT,
    ts                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pipeline_events_ts_idx    ON pipeline_events (ts DESC);
CREATE INDEX IF NOT EXISTS pipeline_events_stage_idx ON pipeline_events (stage, ts DESC);

-- clusters.canonical_article_id references articles, which is declared after
-- clusters; add the constraint separately so ordering does not matter.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'clusters_canonical_article_fk'
    ) THEN
        ALTER TABLE clusters
            ADD CONSTRAINT clusters_canonical_article_fk
            FOREIGN KEY (canonical_article_id) REFERENCES articles(id) ON DELETE SET NULL;
    END IF;
END $$;
