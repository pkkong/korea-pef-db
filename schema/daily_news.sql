PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS news_source (
    source_code TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    locator TEXT NOT NULL,
    publisher TEXT,
    homepage_url TEXT,
    article_url_regex TEXT,
    must_contain TEXT,
    allowed_publishers TEXT,
    default_tags TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS news_run (
    run_id TEXT PRIMARY KEY,
    run_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    discovered_count INTEGER NOT NULL DEFAULT 0,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    relevant_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS news_document (
    news_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source_code TEXT NOT NULL,
    source_url TEXT NOT NULL,
    normalized_source_url TEXT NOT NULL UNIQUE,
    source_domain TEXT,
    publisher TEXT,
    title TEXT NOT NULL,
    published_at TEXT,
    discovered_at TEXT NOT NULL,
    fetched_at TEXT,
    document_type TEXT NOT NULL DEFAULT 'article',
    language_code TEXT NOT NULL DEFAULT 'ko',
    raw_html_path TEXT,
    meta_description TEXT,
    excerpt_text TEXT,
    body_text TEXT,
    content_hash TEXT,
    relevance_score REAL NOT NULL DEFAULT 0,
    relevance_label TEXT NOT NULL DEFAULT 'review',
    comment_text TEXT,
    review_status TEXT NOT NULL DEFAULT 'auto',
    is_pe_relevant INTEGER NOT NULL DEFAULT 0,
    raw_payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES news_run(run_id),
    FOREIGN KEY (source_code) REFERENCES news_source(source_code)
);

CREATE INDEX IF NOT EXISTS idx_news_document_source_code ON news_document(source_code);
CREATE INDEX IF NOT EXISTS idx_news_document_published_at ON news_document(published_at);
CREATE INDEX IF NOT EXISTS idx_news_document_relevant ON news_document(is_pe_relevant, relevance_score);

CREATE TABLE IF NOT EXISTS news_tag (
    tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id INTEGER NOT NULL,
    tag_type TEXT NOT NULL,
    tag_value TEXT NOT NULL,
    tag_source TEXT NOT NULL,
    confidence REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (news_id, tag_type, tag_value, tag_source),
    FOREIGN KEY (news_id) REFERENCES news_document(news_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_news_tag_news_id ON news_tag(news_id);
CREATE INDEX IF NOT EXISTS idx_news_tag_type_value ON news_tag(tag_type, tag_value);

CREATE TABLE IF NOT EXISTS news_entity_link (
    link_id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL,
    entity_ref TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    matched_alias TEXT,
    match_field TEXT,
    link_source TEXT NOT NULL,
    confidence REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (news_id, entity_type, entity_ref, matched_alias, match_field, link_source),
    FOREIGN KEY (news_id) REFERENCES news_document(news_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_news_entity_link_news_id ON news_entity_link(news_id);
CREATE INDEX IF NOT EXISTS idx_news_entity_link_type_ref ON news_entity_link(entity_type, entity_ref);

DROP VIEW IF EXISTS v_news_relevant;

CREATE VIEW v_news_relevant AS
SELECT
    nd.news_id,
    nd.run_id,
    nd.source_code,
    nd.source_url,
    nd.normalized_source_url,
    nd.source_domain,
    nd.publisher,
    nd.title,
    nd.published_at,
    nd.discovered_at,
    nd.document_type,
    nd.meta_description,
    nd.excerpt_text,
    nd.relevance_score,
    nd.relevance_label,
    nd.comment_text,
    nd.review_status,
    nd.is_pe_relevant,
    GROUP_CONCAT(DISTINCT CASE WHEN nt.tag_type = 'section' THEN nt.tag_value END) AS section_tags,
    GROUP_CONCAT(DISTINCT CASE WHEN nt.tag_type = 'section_override' THEN nt.tag_value END) AS section_override_tags,
    GROUP_CONCAT(DISTINCT CASE WHEN nt.tag_type = 'topic' THEN nt.tag_value END) AS topic_tags,
    GROUP_CONCAT(DISTINCT CASE WHEN nt.tag_type = 'document_type' THEN nt.tag_value END) AS document_type_tags,
    GROUP_CONCAT(DISTINCT CASE WHEN nel.entity_type = 'GP' THEN nel.entity_name END) AS gp_names
FROM news_document nd
LEFT JOIN news_tag nt
    ON nt.news_id = nd.news_id
LEFT JOIN news_entity_link nel
    ON nel.news_id = nd.news_id
GROUP BY nd.news_id;
