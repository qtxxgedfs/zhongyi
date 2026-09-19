PRAGMA foreign_keys = ON;

CREATE TABLE cache_info (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

CREATE TABLE source_registry (
    id TEXT PRIMARY KEY,
    organization TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN (
        'official-health-agency', 'regulator', 'guideline-body', 'systematic-review-platform',
        'bibliographic-database', 'professional-society'
    )),
    priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 6),
    domains_json TEXT NOT NULL,
    allowed_uses_json TEXT NOT NULL,
    notes_zh TEXT NOT NULL DEFAULT ''
) STRICT;

CREATE TABLE topics (
    id TEXT PRIMARY KEY,
    title_zh TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN (
        'classical-concept', 'intervention', 'herbal-safety', 'symptom', 'condition', 'emergency', 'population'
    )),
    default_level TEXT NOT NULL CHECK (default_level IN ('M1', 'M2', 'M3')),
    refresh_days INTEGER NOT NULL CHECK (refresh_days BETWEEN 1 AND 1095),
    search_terms_zh_json TEXT NOT NULL,
    search_terms_en_json TEXT NOT NULL
) STRICT;

CREATE TABLE topic_aliases (
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    topic_id TEXT NOT NULL REFERENCES topics(id),
    PRIMARY KEY (alias, topic_id)
) STRICT;

CREATE INDEX topic_aliases_normalized ON topic_aliases(normalized_alias);

-- Each record is a Chinese evidence summary tied to one fully reviewed source page.
-- Full copyrighted pages are not stored in the Skill.
CREATE TABLE evidence_records (
    id TEXT PRIMARY KEY,
    summary_zh TEXT NOT NULL,
    conclusion_direction TEXT NOT NULL CHECK (conclusion_direction IN (
        'supports', 'mixed', 'negative', 'uncertain', 'safety-warning', 'emergency-action', 'not-applicable'
    )),
    directness TEXT NOT NULL CHECK (directness IN ('direct', 'indirect', 'not-directly-comparable')),
    evidence_type TEXT NOT NULL CHECK (evidence_type IN (
        'official-guidance', 'regulatory-information', 'clinical-guideline', 'systematic-review',
        'meta-analysis', 'randomized-trial', 'observational-study', 'mechanistic-study', 'official-evidence-summary'
    )),
    confidence TEXT NOT NULL CHECK (confidence IN ('higher', 'moderate', 'limited', 'very-limited', 'no-direct-clinical-evidence')),
    limitations_zh TEXT NOT NULL,
    population_zh TEXT NOT NULL DEFAULT '',
    intervention_zh TEXT NOT NULL DEFAULT '',
    outcomes_zh TEXT NOT NULL DEFAULT '',
    source_registry_id TEXT NOT NULL REFERENCES source_registry(id),
    source_title TEXT NOT NULL,
    source_organization TEXT NOT NULL,
    publication_date TEXT NOT NULL,
    url TEXT NOT NULL,
    doi TEXT NOT NULL DEFAULT '',
    pmid TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    source_content_sha256 BLOB NOT NULL,
    verification_method TEXT NOT NULL CHECK (verification_method IN ('manual-full-page-review', 'official-api-and-page-review')),
    status TEXT NOT NULL CHECK (status IN ('verified', 'superseded', 'retracted')),
    CHECK (url LIKE 'https://%')
) STRICT;

CREATE TABLE evidence_record_topics (
    record_id TEXT NOT NULL REFERENCES evidence_records(id),
    topic_id TEXT NOT NULL REFERENCES topics(id),
    relevance REAL NOT NULL CHECK (relevance BETWEEN 0 AND 1),
    PRIMARY KEY (record_id, topic_id)
) STRICT;

CREATE INDEX evidence_records_validity ON evidence_records(status, expires_at);
CREATE INDEX evidence_record_topics_topic ON evidence_record_topics(topic_id, relevance DESC);
