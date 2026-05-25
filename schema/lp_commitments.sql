PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS lp_institution (
    lp_code TEXT PRIMARY KEY,
    lp_name TEXT NOT NULL,
    lp_name_en TEXT,
    lp_type TEXT,
    ownership_type TEXT,
    homepage_url TEXT,
    notice_url TEXT,
    default_team TEXT,
    focus_asset_classes TEXT,
    service_priority INTEGER NOT NULL DEFAULT 0,
    aliases TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lp_commitment_source (
    source_code TEXT PRIMARY KEY,
    lp_code TEXT,
    source_name TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    locator TEXT NOT NULL,
    homepage_url TEXT,
    article_url_regex TEXT,
    must_contain TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lp_code) REFERENCES lp_institution(lp_code)
);

CREATE TABLE IF NOT EXISTS lp_commitment_notice (
    notice_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lp_code TEXT,
    source_code TEXT,
    source_type TEXT NOT NULL DEFAULT 'official',
    notice_url TEXT NOT NULL,
    normalized_notice_url TEXT NOT NULL UNIQUE,
    document_url TEXT,
    attachment_names TEXT,
    attachment_urls TEXT,
    title TEXT NOT NULL,
    event_type TEXT,
    event_date TEXT,
    program_name TEXT,
    round_name TEXT,
    announced_date TEXT,
    notice_year INTEGER,
    application_deadline TEXT,
    notice_stage TEXT,
    asset_class TEXT,
    strategy TEXT,
    program_size_krw_100mn REAL,
    allocation_amount_krw_100mn REAL,
    amount_type TEXT,
    amount_confidence TEXT,
    commitment_amount_krw_100mn REAL,
    selected_gp_names TEXT,
    contact_team TEXT,
    confidence TEXT,
    confidence_note TEXT,
    public_visible INTEGER NOT NULL DEFAULT 1,
    monitor_status TEXT NOT NULL DEFAULT 'candidate',
    raw_excerpt TEXT,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lp_code) REFERENCES lp_institution(lp_code),
    FOREIGN KEY (source_code) REFERENCES lp_commitment_source(source_code)
);

CREATE INDEX IF NOT EXISTS idx_lp_notice_lp ON lp_commitment_notice(lp_code);
CREATE INDEX IF NOT EXISTS idx_lp_notice_year ON lp_commitment_notice(notice_year);
CREATE INDEX IF NOT EXISTS idx_lp_notice_stage ON lp_commitment_notice(notice_stage);
CREATE INDEX IF NOT EXISTS idx_lp_notice_event ON lp_commitment_notice(event_type, event_date);

DROP VIEW IF EXISTS v_lp_commitment_notice_public;

CREATE VIEW v_lp_commitment_notice_public AS
SELECT
    lcn.notice_id,
    lcn.lp_code,
    COALESCE(li.lp_name, '') AS lp_name,
    COALESCE(li.lp_type, '') AS lp_type,
    COALESCE(li.default_team, lcn.contact_team, '') AS default_team,
    lcn.source_code,
    lcn.source_type,
    lcn.title,
    lcn.notice_url,
    lcn.document_url,
    lcn.attachment_names,
    lcn.attachment_urls,
    lcn.event_type,
    lcn.event_date,
    lcn.program_name,
    lcn.round_name,
    lcn.announced_date,
    lcn.notice_year,
    lcn.application_deadline,
    lcn.notice_stage,
    lcn.asset_class,
    lcn.strategy,
    lcn.program_size_krw_100mn,
    lcn.allocation_amount_krw_100mn,
    lcn.amount_type,
    lcn.amount_confidence,
    lcn.commitment_amount_krw_100mn,
    lcn.selected_gp_names,
    lcn.contact_team,
    lcn.confidence,
    lcn.confidence_note,
    lcn.public_visible,
    lcn.monitor_status,
    lcn.raw_excerpt,
    lcn.discovered_at,
    lcn.updated_at
FROM lp_commitment_notice lcn
LEFT JOIN lp_institution li
    ON li.lp_code = lcn.lp_code;

DROP VIEW IF EXISTS v_lp_institution_stats;

CREATE VIEW v_lp_institution_stats AS
SELECT
    li.lp_code,
    li.lp_name,
    li.lp_type,
    li.default_team,
    li.focus_asset_classes,
    li.service_priority,
    COUNT(lcn.notice_id) AS notice_count,
    SUM(COALESCE(lcn.allocation_amount_krw_100mn, 0)) AS allocation_amount_krw_100mn,
    SUM(COALESCE(lcn.commitment_amount_krw_100mn, 0)) AS commitment_amount_krw_100mn,
    MAX(COALESCE(lcn.event_date, lcn.announced_date)) AS latest_event_date,
    MAX(lcn.announced_date) AS latest_announced_date,
    MAX(lcn.discovered_at) AS latest_discovered_at
FROM lp_institution li
LEFT JOIN lp_commitment_notice lcn
    ON lcn.lp_code = li.lp_code
GROUP BY li.lp_code;

DROP VIEW IF EXISTS v_lp_commitment_yearly_stats;

CREATE VIEW v_lp_commitment_yearly_stats AS
SELECT
    notice_year,
    lp_code,
    lp_name,
    COUNT(notice_id) AS notice_count,
    SUM(COALESCE(allocation_amount_krw_100mn, 0)) AS allocation_amount_krw_100mn,
    SUM(COALESCE(commitment_amount_krw_100mn, 0)) AS commitment_amount_krw_100mn
FROM v_lp_commitment_notice_public
WHERE notice_year IS NOT NULL
GROUP BY notice_year, lp_code, lp_name;
