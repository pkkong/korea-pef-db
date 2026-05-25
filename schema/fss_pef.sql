PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS source_document (
    source_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    publisher TEXT NOT NULL DEFAULT '금융감독원',
    document_type TEXT NOT NULL DEFAULT 'quarterly_pef_status',
    regime TEXT,
    period_label TEXT,
    as_of_date TEXT,
    source_url TEXT,
    local_path TEXT,
    sha256 TEXT,
    fetched_at TEXT,
    parsed_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS reporting_period (
    period_id TEXT PRIMARY KEY,
    period_label TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    regime TEXT
);

CREATE TABLE IF NOT EXISTS gp_house (
    gp_id INTEGER PRIMARY KEY AUTOINCREMENT,
    gp_name TEXT NOT NULL,
    gp_name_norm TEXT NOT NULL UNIQUE,
    first_seen_period_id TEXT,
    last_seen_period_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (first_seen_period_id) REFERENCES reporting_period(period_id),
    FOREIGN KEY (last_seen_period_id) REFERENCES reporting_period(period_id)
);

CREATE TABLE IF NOT EXISTS pef_fund (
    fund_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_name TEXT NOT NULL,
    fund_name_norm TEXT NOT NULL UNIQUE,
    regime_first_seen TEXT,
    fund_type TEXT,
    established_date TEXT,
    liquidation_date TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fund_gp_affiliation (
    fund_id INTEGER NOT NULL,
    gp_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT '업무집행사원',
    first_seen_period_id TEXT,
    last_seen_period_id TEXT,
    PRIMARY KEY (fund_id, gp_id, role),
    FOREIGN KEY (fund_id) REFERENCES pef_fund(fund_id),
    FOREIGN KEY (gp_id) REFERENCES gp_house(gp_id),
    FOREIGN KEY (first_seen_period_id) REFERENCES reporting_period(period_id),
    FOREIGN KEY (last_seen_period_id) REFERENCES reporting_period(period_id)
);

CREATE TABLE IF NOT EXISTS source_row (
    source_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    sheet_name TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    raw_row_json TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    UNIQUE (source_id, sheet_name, row_number),
    FOREIGN KEY (source_id) REFERENCES source_document(source_id)
);

CREATE TABLE IF NOT EXISTS fund_period_snapshot (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id INTEGER NOT NULL,
    period_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    gp_id INTEGER,
    sheet_name TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    sheet_role TEXT,
    fund_name_raw TEXT NOT NULL,
    gp_name_raw TEXT,
    fund_type_raw TEXT,
    status_raw TEXT,
    established_date_raw TEXT,
    liquidation_date_raw TEXT,
    commitment_amount_raw TEXT,
    commitment_amount_krw_mn REAL,
    paid_in_amount_raw TEXT,
    paid_in_amount_krw_mn REAL,
    raw_row_json TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    UNIQUE (source_id, sheet_name, row_number),
    FOREIGN KEY (fund_id) REFERENCES pef_fund(fund_id),
    FOREIGN KEY (period_id) REFERENCES reporting_period(period_id),
    FOREIGN KEY (source_id) REFERENCES source_document(source_id),
    FOREIGN KEY (gp_id) REFERENCES gp_house(gp_id)
);

CREATE TABLE IF NOT EXISTS fund_event (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id INTEGER NOT NULL,
    gp_id INTEGER,
    event_type TEXT NOT NULL,
    event_date TEXT,
    period_id TEXT NOT NULL,
    source_id TEXT,
    confidence TEXT NOT NULL DEFAULT 'A',
    basis TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (fund_id, event_type, period_id, source_id),
    FOREIGN KEY (fund_id) REFERENCES pef_fund(fund_id),
    FOREIGN KEY (gp_id) REFERENCES gp_house(gp_id),
    FOREIGN KEY (period_id) REFERENCES reporting_period(period_id),
    FOREIGN KEY (source_id) REFERENCES source_document(source_id)
);

CREATE INDEX IF NOT EXISTS idx_snapshot_period ON fund_period_snapshot(period_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_fund ON fund_period_snapshot(fund_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_gp ON fund_period_snapshot(gp_id);
CREATE INDEX IF NOT EXISTS idx_event_fund ON fund_event(fund_id);
CREATE INDEX IF NOT EXISTS idx_event_type_period ON fund_event(event_type, period_id);

CREATE VIEW IF NOT EXISTS v_gp_period_commitment AS
SELECT
    rp.period_label,
    rp.as_of_date,
    gh.gp_id,
    gh.gp_name,
    COUNT(DISTINCT fps.fund_id) AS fund_count,
    SUM(fps.commitment_amount_krw_mn) AS commitment_amount_krw_mn,
    SUM(fps.paid_in_amount_krw_mn) AS paid_in_amount_krw_mn
FROM fund_period_snapshot fps
JOIN reporting_period rp ON rp.period_id = fps.period_id
LEFT JOIN gp_house gh ON gh.gp_id = fps.gp_id
GROUP BY rp.period_id, gh.gp_id;

CREATE VIEW IF NOT EXISTS v_fund_timeline AS
SELECT
    pf.fund_id,
    pf.fund_name,
    gh.gp_name,
    rp.period_label,
    rp.as_of_date,
    fps.sheet_role,
    fps.fund_type_raw,
    fps.commitment_amount_krw_mn,
    fps.paid_in_amount_krw_mn,
    fps.established_date_raw,
    fps.liquidation_date_raw,
    sd.title AS source_title,
    sd.source_url
FROM fund_period_snapshot fps
JOIN pef_fund pf ON pf.fund_id = fps.fund_id
LEFT JOIN gp_house gh ON gh.gp_id = fps.gp_id
JOIN reporting_period rp ON rp.period_id = fps.period_id
JOIN source_document sd ON sd.source_id = fps.source_id;

CREATE VIEW IF NOT EXISTS v_period_summary AS
SELECT
    rp.period_label,
    rp.as_of_date,
    rp.regime,
    COUNT(DISTINCT fps.fund_id) AS fund_count,
    COUNT(DISTINCT fps.gp_id) AS primary_gp_count,
    SUM(fps.commitment_amount_krw_mn) AS commitment_amount_krw_mn,
    SUM(fps.paid_in_amount_krw_mn) AS paid_in_amount_krw_mn
FROM reporting_period rp
LEFT JOIN fund_period_snapshot fps ON fps.period_id = rp.period_id
GROUP BY rp.period_id;

CREATE VIEW IF NOT EXISTS v_fund_established_by_calendar_quarter AS
SELECT
    fe.event_date AS established_date,
    SUBSTR(fe.event_date, 1, 4) || 'Q' ||
        ((CAST(SUBSTR(fe.event_date, 6, 2) AS INTEGER) - 1) / 3 + 1) AS established_quarter,
    pf.fund_id,
    pf.fund_name,
    gh.gp_name,
    fe.confidence,
    fe.basis
FROM fund_event fe
JOIN pef_fund pf ON pf.fund_id = fe.fund_id
LEFT JOIN gp_house gh ON gh.gp_id = fe.gp_id
WHERE fe.event_type = 'established'
  AND fe.event_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]';

CREATE VIEW IF NOT EXISTS v_fund_disappeared_next_period AS
WITH ordered_periods AS (
    SELECT
        period_id,
        period_label,
        as_of_date,
        year,
        quarter,
        LEAD(period_id) OVER (ORDER BY year, quarter) AS next_period_id,
        LEAD(period_label) OVER (ORDER BY year, quarter) AS next_period_label,
        LEAD(year * 4 + quarter) OVER (ORDER BY year, quarter) AS next_period_index,
        year * 4 + quarter AS period_index
    FROM reporting_period
),
consecutive_periods AS (
    SELECT *
    FROM ordered_periods
    WHERE next_period_index = period_index + 1
)
SELECT
    cp.period_label AS last_seen_period,
    cp.next_period_label AS absent_period,
    pf.fund_id,
    pf.fund_name,
    gh.gp_name,
    fps.commitment_amount_krw_mn,
    'Absent from next consecutive imported FSS status; not a confirmed liquidation' AS basis
FROM consecutive_periods cp
JOIN fund_period_snapshot fps ON fps.period_id = cp.period_id
JOIN pef_fund pf ON pf.fund_id = fps.fund_id
LEFT JOIN gp_house gh ON gh.gp_id = fps.gp_id
WHERE NOT EXISTS (
    SELECT 1
    FROM fund_period_snapshot next_fps
    WHERE next_fps.period_id = cp.next_period_id
      AND next_fps.fund_id = fps.fund_id
);
