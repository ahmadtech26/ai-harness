-- db.SCHEMA as on recall-plan 649559a (git show 649559a:services/legal-search/src/legal_search/db.py), the schema the
-- image before verification and provenance runs. tests/test_ingest.py builds a database of that image with it, to
-- check what the current schema step does to one. A record of that image: never edit it.

CREATE TABLE IF NOT EXISTS laws (
  slug TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  number INT,
  year INT,
  gazette_issue INT,
  gazette_date DATE,
  gazette_url TEXT,
  amendment_law INT,
  amendment_year INT,
  amendment_gazette_issue INT,
  amendment_gazette_date DATE,
  amendment_url TEXT,
  note TEXT,
  approved BOOLEAN NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS articles (
  id BIGSERIAL PRIMARY KEY,
  law_slug TEXT NOT NULL,
  law_title TEXT NOT NULL,
  number INT NOT NULL,
  suffix TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL,
  text TEXT NOT NULL,
  norm TEXT NOT NULL,
  tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', norm)) STORED,
  source TEXT NOT NULL DEFAULT '',
  shard TEXT NOT NULL DEFAULT '',
  verified_at DATE,
  UNIQUE (law_slug, number, suffix)
);
CREATE INDEX IF NOT EXISTS articles_tsv ON articles USING GIN (tsv);
-- The keyword engine's heading field (recall plan Task 3.4): index-only, never served. heading_origin says where it
-- came from: 'site', headings.extract over the text as published; '' never derived.
ALTER TABLE articles ADD COLUMN IF NOT EXISTS heading TEXT NOT NULL DEFAULT '';
ALTER TABLE articles ADD COLUMN IF NOT EXISTS heading_origin TEXT NOT NULL DEFAULT '';
-- The keyword engine's corpus version (keyword_engine): every write to articles bumps it, and an index built from
-- another (created, version) pair is rebuilt. created tells a recreated table from the old one, whose counter it restarts.
CREATE TABLE IF NOT EXISTS index_state (
  id SMALLINT PRIMARY KEY CHECK (id = 1),
  version BIGINT NOT NULL,
  created TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO index_state (id, version) VALUES (1, 0) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS memorandum_notes (
  note_no INT PRIMARY KEY,
  text TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS memorandum_links (
  article_number INT NOT NULL,
  note_no INT NOT NULL REFERENCES memorandum_notes (note_no) ON DELETE CASCADE,
  PRIMARY KEY (article_number, note_no)
);
CREATE TABLE IF NOT EXISTS retrieval_log (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  message_id TEXT,
  conversation_id TEXT,
  tool TEXT NOT NULL,
  query TEXT,
  article_ids BIGINT[] NOT NULL DEFAULT '{}',
  note_ids BIGINT[] NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS note_ids BIGINT[] NOT NULL DEFAULT '{}';
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS requested_law TEXT;
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS requested_number INT;
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS requested_suffix TEXT;
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS outcome TEXT NOT NULL DEFAULT 'served'
  CHECK (outcome IN ('served', 'capped', 'throttled', 'suspended'));
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS candidate_ids BIGINT[] NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS retrieval_log_user_time ON retrieval_log (user_id, created_at);
CREATE INDEX IF NOT EXISTS retrieval_log_message ON retrieval_log (message_id);
-- Telemetry and simulation read a window by time alone (R3 n=14); without it each request scans the whole log.
CREATE INDEX IF NOT EXISTS retrieval_log_created ON retrieval_log (created_at);
CREATE TABLE IF NOT EXISTS guard_settings (
  id INT PRIMARY KEY CHECK (id = 1),
  settings JSONB NOT NULL,
  updated_by TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS guard_settings_history (
  id BIGSERIAL PRIMARY KEY,
  changed_by TEXT NOT NULL,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  reason TEXT NOT NULL,
  previous JSONB,
  settings JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS sweep_flags (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  level TEXT NOT NULL CHECK (level IN ('suspected', 'proven')),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'cleared')),
  opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  opened_log_id BIGINT NOT NULL,
  escalated_at TIMESTAMPTZ,
  escalated_log_id BIGINT,
  evidence JSONB NOT NULL,
  cleared_at TIMESTAMPTZ,
  cleared_by TEXT,
  clear_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS sweep_flags_one_open ON sweep_flags (user_id) WHERE status = 'open';
CREATE TABLE IF NOT EXISTS guard_watermarks (
  user_id TEXT PRIMARY KEY,
  since TIMESTAMPTZ NOT NULL,
  since_log_id BIGINT NOT NULL
);
