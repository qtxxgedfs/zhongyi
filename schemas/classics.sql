PRAGMA foreign_keys = ON;

CREATE TABLE schema_info (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    page_title TEXT NOT NULL,
    page_url TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    license_json TEXT NOT NULL,
    textual_status TEXT NOT NULL,
    aggregate_raw_sha256 BLOB NOT NULL,
    processed_traditional_sha256 BLOB NOT NULL,
    processed_simplified_sha256 BLOB NOT NULL,
    citable_simplified_sha256 BLOB NOT NULL,
    passage_count INTEGER NOT NULL,
    citable_passage_count INTEGER NOT NULL,
    quarantined_passage_count INTEGER NOT NULL
) STRICT;

CREATE TABLE works (
    id TEXT PRIMARY KEY,
    canon TEXT NOT NULL CHECK (canon IN ('huangdi', 'zhongjing', 'nanjing', 'wenbing')),
    layer TEXT NOT NULL CHECK (layer IN ('core', 'commentary', 'lineage')),
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    relationship_json TEXT NOT NULL,
    edition_label TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL UNIQUE REFERENCES sources(id)
) STRICT;

CREATE TABLE work_targets (
    work_id TEXT NOT NULL REFERENCES works(id),
    target_work TEXT NOT NULL CHECK (target_work IN (
        'suwen', 'lingshu', 'shanghanlun', 'jingui', 'nanjing', 'wenbingtiaobian'
    )),
    PRIMARY KEY (work_id, target_work)
) STRICT;

CREATE TABLE source_pages (
    id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    title_source TEXT NOT NULL,
    title_simplified TEXT NOT NULL,
    revision_id INTEGER NOT NULL,
    raw_sha256 BLOB NOT NULL,
    UNIQUE (source_id, title_source, revision_id)
) STRICT;

CREATE TABLE locations (
    id INTEGER PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(id),
    volume TEXT NOT NULL DEFAULT '',
    section TEXT NOT NULL DEFAULT '',
    subsection TEXT NOT NULL DEFAULT '',
    speaker TEXT NOT NULL DEFAULT '',
    speaker_type TEXT NOT NULL DEFAULT '',
    UNIQUE (work_id, volume, section, subsection, speaker, speaker_type)
) STRICT;

-- Only clean, citable passages enter this runtime table. Repeated source-page and
-- location metadata is normalized into compact tables to keep the Skill small.
CREATE TABLE passages (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(id),
    sequence INTEGER NOT NULL,
    location_id INTEGER NOT NULL REFERENCES locations(id),
    source_page_id INTEGER NOT NULL REFERENCES source_pages(id),
    text_simplified TEXT NOT NULL,
    content_sha256 BLOB NOT NULL,
    UNIQUE (work_id, sequence)
) STRICT;

CREATE INDEX passages_source_page ON passages(source_page_id);
CREATE INDEX passages_location ON passages(location_id);

CREATE TABLE aliases (
    id INTEGER PRIMARY KEY,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    canonical TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('work', 'canon', 'author', 'term')),
    work_id TEXT REFERENCES works(id),
    target_work TEXT,
    canon TEXT,
    UNIQUE (alias, canonical, kind, work_id, target_work, canon)
) STRICT;

CREATE INDEX aliases_normalized ON aliases(normalized_alias, kind);

-- Tokens are pre-generated overlapping Chinese bigrams. The FTS table is
-- contentless: display text lives only once in passages.
CREATE VIRTUAL TABLE passage_fts USING fts5(
    title_tokens,
    body_tokens,
    content = '',
    tokenize = 'unicode61 remove_diacritics 0'
);
