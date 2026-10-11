CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sources (
    id            TEXT PRIMARY KEY,
    owner         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    type          TEXT NOT NULL,
    category      TEXT,
    last_fetch_at TIMESTAMPTZ,
    last_status   TEXT,
    last_item_count INT
);

CREATE TABLE items (
    id            BIGSERIAL PRIMARY KEY,
    owner         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_id     TEXT NOT NULL REFERENCES sources(id),
    url           TEXT NOT NULL,
    canonical_url TEXT NOT NULL UNIQUE,
    title         TEXT,
    published_at  TIMESTAMPTZ,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    content       TEXT,                 -- raw extracted full text
    points        INT,                  -- HN only
    num_comments  INT,                  -- HN only
    hn_url        TEXT,                 -- HN thread link
    embedding     vector(1536),
    title_embedding vector(1536),
    tsv           tsvector GENERATED ALWAYS AS (
                    to_tsvector('english',
                      coalesce(title, '') || ' ' || coalesce(content, ''))
                  ) STORED,
    cluster_id    BIGINT,               -- id of the representative item
    summary       TEXT,
    starred       BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX items_tsv_idx       ON items USING gin (tsv);
CREATE INDEX items_embedding_idx ON items USING hnsw (embedding vector_cosine_ops);
CREATE INDEX items_published_idx ON items (published_at DESC);
CREATE INDEX items_source_idx    ON items (source_id);
CREATE INDEX items_cluster_idx   ON items (cluster_id);
CREATE INDEX items_owner_idx     ON items (owner);

CREATE TABLE digests (
    id         BIGSERIAL PRIMARY KEY,
    owner      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date       DATE NOT NULL,
    pdf_path   TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(owner, date)
);

CREATE TABLE digest_items (
    digest_id BIGINT NOT NULL REFERENCES digests(id) ON DELETE CASCADE,
    item_id   BIGINT NOT NULL REFERENCES items(id),
    rank      INT NOT NULL,
    PRIMARY KEY (digest_id, item_id)
);
