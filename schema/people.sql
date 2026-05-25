PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS person (
    person_id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_name_ko TEXT NOT NULL,
    person_name_en TEXT,
    person_name_norm TEXT NOT NULL,
    current_primary_org_type TEXT,
    current_primary_org_id TEXT,
    current_primary_org_name TEXT,
    current_title TEXT,
    profile_status TEXT NOT NULL DEFAULT 'draft',
    verification_level TEXT NOT NULL DEFAULT 'unknown',
    primary_source_url TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_person_name_norm ON person(person_name_norm);
CREATE INDEX IF NOT EXISTS idx_person_current_org ON person(current_primary_org_type, current_primary_org_id);

CREATE TABLE IF NOT EXISTS person_alias (
    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    alias_name TEXT NOT NULL,
    alias_name_norm TEXT NOT NULL,
    alias_type TEXT NOT NULL DEFAULT 'name_variant',
    source_url TEXT,
    verification_status TEXT NOT NULL DEFAULT 'source_derived',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (person_id, alias_name_norm, alias_type),
    FOREIGN KEY (person_id) REFERENCES person(person_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_person_alias_norm ON person_alias(alias_name_norm);

CREATE TABLE IF NOT EXISTS person_role (
    role_id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    org_type TEXT NOT NULL,
    org_id TEXT,
    org_name TEXT NOT NULL,
    title TEXT,
    team TEXT,
    role_start_date TEXT,
    role_end_date TEXT,
    is_current INTEGER NOT NULL DEFAULT 0,
    source_url TEXT,
    source_title TEXT,
    source_grade TEXT,
    verification_status TEXT NOT NULL DEFAULT 'source_derived',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (person_id) REFERENCES person(person_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_person_role_person ON person_role(person_id);
CREATE INDEX IF NOT EXISTS idx_person_role_org ON person_role(org_type, org_id);
CREATE INDEX IF NOT EXISTS idx_person_role_current ON person_role(is_current, org_type, org_id);

CREATE TABLE IF NOT EXISTS person_education (
    education_id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    school_name TEXT NOT NULL,
    school_name_en TEXT,
    degree TEXT,
    major TEXT,
    start_year INTEGER,
    graduation_year INTEGER,
    source_url TEXT,
    source_title TEXT,
    source_grade TEXT,
    verification_status TEXT NOT NULL DEFAULT 'source_derived',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (person_id) REFERENCES person(person_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_person_education_person ON person_education(person_id);
CREATE INDEX IF NOT EXISTS idx_person_education_school ON person_education(school_name);

CREATE TABLE IF NOT EXISTS person_source (
    source_evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    source_title TEXT,
    source_url TEXT NOT NULL,
    source_grade TEXT NOT NULL DEFAULT 'supporting',
    evidence_scope TEXT NOT NULL,
    evidence_value TEXT,
    evidence_date TEXT,
    verification_status TEXT NOT NULL DEFAULT 'source_derived',
    captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    FOREIGN KEY (person_id) REFERENCES person(person_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_person_source_person ON person_source(person_id);
CREATE INDEX IF NOT EXISTS idx_person_source_scope ON person_source(evidence_scope);
CREATE INDEX IF NOT EXISTS idx_person_source_url ON person_source(source_url);

CREATE TABLE IF NOT EXISTS person_news_link (
    person_id INTEGER NOT NULL,
    news_id INTEGER NOT NULL,
    matched_name TEXT,
    link_source TEXT NOT NULL DEFAULT 'manual',
    confidence REAL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (person_id, news_id, link_source),
    FOREIGN KEY (person_id) REFERENCES person(person_id) ON DELETE CASCADE,
    FOREIGN KEY (news_id) REFERENCES news_document(news_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_person_news_link_news ON person_news_link(news_id);

CREATE VIEW IF NOT EXISTS v_person_current_gp AS
SELECT
    p.person_id,
    p.person_name_ko,
    p.person_name_en,
    p.current_title,
    pr.title AS role_title,
    pr.team,
    pr.org_id AS gp_id,
    pr.org_name AS gp_name,
    p.profile_status,
    p.verification_level,
    p.primary_source_url
FROM person p
JOIN person_role pr
    ON pr.person_id = p.person_id
   AND pr.org_type = 'GP'
   AND pr.is_current = 1;

CREATE VIEW IF NOT EXISTS v_person_profile_summary AS
SELECT
    p.person_id,
    p.person_name_ko,
    p.person_name_en,
    p.current_primary_org_type,
    p.current_primary_org_id,
    p.current_primary_org_name,
    p.current_title,
    p.profile_status,
    p.verification_level,
    COUNT(DISTINCT pr.role_id) AS role_count,
    COUNT(DISTINCT pe.education_id) AS education_count,
    COUNT(DISTINCT ps.source_evidence_id) AS source_count
FROM person p
LEFT JOIN person_role pr
    ON pr.person_id = p.person_id
LEFT JOIN person_education pe
    ON pe.person_id = p.person_id
LEFT JOIN person_source ps
    ON ps.person_id = p.person_id
GROUP BY p.person_id;
