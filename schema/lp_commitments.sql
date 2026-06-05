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
    coverage_tier TEXT NOT NULL DEFAULT 'candidate',
    display_enabled INTEGER NOT NULL DEFAULT 1,
    notice_tracking_enabled INTEGER NOT NULL DEFAULT 0,
    profile_status TEXT NOT NULL DEFAULT 'candidate',
    aliases TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lp_profile_fact (
    fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lp_code TEXT NOT NULL,
    section TEXT NOT NULL,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    as_of_date TEXT,
    source_name TEXT,
    source_url TEXT,
    confidence TEXT,
    notes TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    public_visible INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(lp_code, section, label, source_url),
    FOREIGN KEY (lp_code) REFERENCES lp_institution(lp_code)
);

CREATE INDEX IF NOT EXISTS idx_lp_profile_fact_lp ON lp_profile_fact(lp_code, section, sort_order);

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

CREATE TABLE IF NOT EXISTS lp_notice_gp_link (
    notice_id INTEGER NOT NULL,
    lp_code TEXT,
    source_gp_id INTEGER NOT NULL,
    gp_name TEXT NOT NULL,
    matched_alias TEXT,
    link_source TEXT NOT NULL DEFAULT 'selected_gp_names',
    confidence TEXT NOT NULL DEFAULT 'medium',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (notice_id, source_gp_id),
    FOREIGN KEY (notice_id) REFERENCES lp_commitment_notice(notice_id) ON DELETE CASCADE,
    FOREIGN KEY (lp_code) REFERENCES lp_institution(lp_code),
    FOREIGN KEY (source_gp_id) REFERENCES gp_house(gp_id)
);

CREATE INDEX IF NOT EXISTS idx_lp_notice_gp_link_lp ON lp_notice_gp_link(lp_code, source_gp_id);

CREATE TABLE IF NOT EXISTS lp_notice_news_link (
    notice_id INTEGER NOT NULL,
    news_id INTEGER NOT NULL,
    lp_code TEXT,
    link_source TEXT NOT NULL DEFAULT 'url_match',
    confidence TEXT NOT NULL DEFAULT 'high',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (notice_id, news_id),
    FOREIGN KEY (notice_id) REFERENCES lp_commitment_notice(notice_id) ON DELETE CASCADE,
    FOREIGN KEY (news_id) REFERENCES news_document(news_id),
    FOREIGN KEY (lp_code) REFERENCES lp_institution(lp_code)
);

CREATE INDEX IF NOT EXISTS idx_lp_notice_news_link_lp ON lp_notice_news_link(lp_code, news_id);

CREATE INDEX IF NOT EXISTS idx_lp_notice_lp ON lp_commitment_notice(lp_code);
CREATE INDEX IF NOT EXISTS idx_lp_notice_year ON lp_commitment_notice(notice_year);
CREATE INDEX IF NOT EXISTS idx_lp_notice_stage ON lp_commitment_notice(notice_stage);
CREATE INDEX IF NOT EXISTS idx_lp_notice_event ON lp_commitment_notice(event_type, event_date);

DROP VIEW IF EXISTS v_lp_commitment_lifecycle_compare;
DROP VIEW IF EXISTS v_lp_commitment_selected_gp_compare;
DROP VIEW IF EXISTS v_lp_commitment_notice_public;
DROP VIEW IF EXISTS v_lp_commitment_notice_enriched;

CREATE VIEW v_lp_commitment_notice_enriched AS
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

CREATE VIEW v_lp_commitment_notice_public AS
SELECT *
FROM v_lp_commitment_notice_enriched
WHERE public_visible = 1;

CREATE VIEW v_lp_commitment_selected_gp_compare AS
SELECT
    n.notice_id,
    n.lp_code,
    n.lp_name,
    n.lp_type,
    n.program_name,
    n.round_name,
    n.notice_year,
    n.event_type,
    n.event_date,
    n.announced_date,
    n.application_deadline,
    COALESCE(NULLIF(n.notice_stage, ''), n.event_type, '') AS stage,
    n.notice_stage,
    n.asset_class,
    n.strategy,
    n.program_size_krw_100mn,
    n.allocation_amount_krw_100mn,
    n.commitment_amount_krw_100mn,
    COALESCE(
        n.allocation_amount_krw_100mn,
        n.commitment_amount_krw_100mn,
        n.program_size_krw_100mn
    ) AS amount_krw_100mn,
    n.amount_type,
    n.amount_confidence,
    lgl.source_gp_id,
    COALESCE(NULLIF(gh.gp_name, ''), lgl.gp_name) AS gp_name,
    lgl.matched_alias,
    lgl.confidence AS gp_link_confidence,
    n.confidence,
    n.source_type,
    n.source_code,
    n.title AS notice_title,
    n.notice_url AS source_url,
    n.document_url,
    n.discovered_at,
    n.updated_at
FROM v_lp_commitment_notice_public n
JOIN lp_notice_gp_link lgl
    ON lgl.notice_id = n.notice_id
LEFT JOIN gp_house gh
    ON gh.gp_id = lgl.source_gp_id
WHERE COALESCE(NULLIF(lgl.gp_name, ''), NULLIF(gh.gp_name, ''), '') <> ''
  AND COALESCE(n.event_type, '') <> ''
  AND LOWER(COALESCE(n.event_type, '')) <> 'candidate'
  AND LOWER(COALESCE(n.confidence, '')) <> 'low'
  AND (
      LOWER(COALESCE(n.monitor_status, '')) NOT IN (
          'candidate',
          'review',
          'review_pending',
          'pending_review',
          'needs_review',
          'unvalidated',
          'draft'
      )
      OR (
          LOWER(COALESCE(n.source_type, '')) = 'official'
          AND LOWER(COALESCE(n.monitor_status, '')) = 'candidate'
      )
  );

CREATE VIEW v_lp_commitment_lifecycle_compare AS
WITH source_rows AS (
    SELECT
        *,
        CASE
            WHEN INSTR(title, '「') > 0 AND INSTR(title, '」') > INSTR(title, '「')
            THEN TRIM(SUBSTR(title, INSTR(title, '「') + 1, INSTR(title, '」') - INSTR(title, '「') - 1))
            WHEN INSTR(title, '『') > 0 AND INSTR(title, '』') > INSTR(title, '『')
            THEN TRIM(SUBSTR(title, INSTR(title, '『') + 1, INSTR(title, '』') - INSTR(title, '『') - 1))
            ELSE ''
        END AS title_program_name
    FROM v_lp_commitment_notice_public
),
normalized_rows AS (
    SELECT
        *,
        TRIM(
            REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
            REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                CASE
                    WHEN COALESCE(NULLIF(TRIM(program_name), ''), '') IN (
                        '국민성장펀드',
                        '모태펀드',
                        '농식품모태펀드',
                        '농림수산식품모태펀드',
                        '공급망안정화기금'
                    )
                     AND COALESCE(NULLIF(TRIM(title_program_name), ''), '') <> ''
                    THEN title_program_name
                    ELSE COALESCE(NULLIF(TRIM(program_name), ''), '')
                END,
                '(1차)', ''), '(2차)', ''), '(3차)', ''), '(4차)', ''), '(5차)', ''),
                '(6차)', ''), '(7차)', ''), '(8차)', ''), '(9차)', ''), '(10차)', ''),
                '(1호)', ''), '(2호)', ''), '(3호)', ''), '(4호)', ''), '(5호)', ''),
                '(6호)', ''), '(7호)', ''), '(8호)', ''), '(9호)', ''), '(10호)', '')
        ) AS lifecycle_program_name,
        CASE
            WHEN COALESCE(NULLIF(TRIM(round_name), ''), '') <> '' THEN TRIM(round_name)
            WHEN title_program_name LIKE '%(1차)%' THEN '1차'
            WHEN title_program_name LIKE '%(2차)%' THEN '2차'
            WHEN title_program_name LIKE '%(3차)%' THEN '3차'
            WHEN title_program_name LIKE '%(4차)%' THEN '4차'
            WHEN title_program_name LIKE '%(5차)%' THEN '5차'
            WHEN title_program_name LIKE '%(6차)%' THEN '6차'
            WHEN title_program_name LIKE '%(7차)%' THEN '7차'
            WHEN title_program_name LIKE '%(8차)%' THEN '8차'
            WHEN title_program_name LIKE '%(9차)%' THEN '9차'
            WHEN title_program_name LIKE '%(10차)%' THEN '10차'
            WHEN title_program_name LIKE '%(1호)%' THEN '1호'
            WHEN title_program_name LIKE '%(2호)%' THEN '2호'
            WHEN title_program_name LIKE '%(3호)%' THEN '3호'
            WHEN title_program_name LIKE '%(4호)%' THEN '4호'
            WHEN title_program_name LIKE '%(5호)%' THEN '5호'
            ELSE COALESCE(NULLIF(TRIM(round_name), ''), '')
        END AS lifecycle_round_name
    FROM source_rows
),
notice_rows AS (
    SELECT
        notice_id,
        lp_code,
        lp_name,
        lp_type,
        COALESCE(NULLIF(TRIM(lifecycle_program_name), ''), '') AS program_name,
        COALESCE(NULLIF(TRIM(lifecycle_round_name), ''), '') AS round_name,
        LOWER(REPLACE(REPLACE(REPLACE(COALESCE(NULLIF(TRIM(lifecycle_program_name), ''), ''), ' ', ''), '(', ''), ')', '')) AS program_key,
        LOWER(REPLACE(REPLACE(REPLACE(COALESCE(NULLIF(TRIM(lifecycle_round_name), ''), ''), ' ', ''), '(', ''), ')', '')) AS round_key,
        notice_year,
        event_type,
        event_date,
        announced_date,
        application_deadline,
        COALESCE(NULLIF(notice_stage, ''), event_type, '') AS stage,
        notice_stage,
        asset_class,
        strategy,
        program_size_krw_100mn,
        allocation_amount_krw_100mn,
        commitment_amount_krw_100mn,
        amount_type,
        amount_confidence,
        selected_gp_names,
        confidence,
        source_type,
        source_code,
        title AS notice_title,
        notice_url AS source_url,
        document_url,
        discovered_at,
        updated_at,
        COALESCE(event_date, announced_date, discovered_at, '') AS sort_date,
        CASE
            WHEN event_type IN ('new_notice', 'deadline_soon')
             AND COALESCE(application_deadline, '') <> ''
             AND date(application_deadline) >= date('now', 'localtime')
            THEN 1
            ELSE 0
        END AS is_open_notice,
        CASE
            WHEN event_type = 'final_selection' OR notice_stage = 'selection_result' THEN 1
            ELSE 0
        END AS is_final_selection,
        CASE
            WHEN event_type = 'shortlist' OR notice_stage = 'shortlist' THEN 1
            ELSE 0
        END AS is_shortlist
    FROM normalized_rows
    WHERE COALESCE(lp_code, '') <> ''
      AND COALESCE(event_type, '') <> ''
      AND LOWER(COALESCE(event_type, '')) <> 'candidate'
      AND LOWER(COALESCE(confidence, '')) <> 'low'
      AND (
          LOWER(COALESCE(monitor_status, '')) NOT IN (
              'candidate',
              'review',
              'review_pending',
              'pending_review',
              'needs_review',
              'unvalidated',
              'draft'
          )
          OR (
              LOWER(COALESCE(source_type, '')) = 'official'
              AND LOWER(COALESCE(monitor_status, '')) = 'candidate'
          )
      )
),
latest_rows AS (
    SELECT *
    FROM (
        SELECT
            nr.*,
            ROW_NUMBER() OVER (
                PARTITION BY lp_code, program_key, round_key
                ORDER BY sort_date DESC, notice_id DESC
            ) AS row_rank
        FROM notice_rows nr
    )
    WHERE row_rank = 1
),
notice_rollup AS (
    SELECT
        lp_code,
        MAX(lp_name) AS lp_name,
        MAX(lp_type) AS lp_type,
        program_key,
        round_key,
        MAX(program_name) AS program_name,
        MAX(round_name) AS round_name,
        COUNT(*) AS notice_count,
        SUM(is_open_notice) AS open_count,
        SUM(is_shortlist) AS shortlist_count,
        SUM(is_final_selection) AS final_selection_count,
        ROUND(SUM(COALESCE(allocation_amount_krw_100mn, 0)), 4) AS allocation_amount_krw_100mn_sum,
        ROUND(SUM(COALESCE(commitment_amount_krw_100mn, 0)), 4) AS commitment_amount_krw_100mn_sum,
        ROUND(SUM(COALESCE(allocation_amount_krw_100mn, commitment_amount_krw_100mn, 0)), 4) AS amount_krw_100mn_sum,
        MAX(program_size_krw_100mn) AS program_size_krw_100mn_max,
        MIN(CASE
            WHEN COALESCE(application_deadline, '') <> ''
             AND date(application_deadline) >= date('now', 'localtime')
            THEN application_deadline
            ELSE NULL
        END) AS next_application_deadline,
        MAX(NULLIF(application_deadline, '')) AS latest_application_deadline,
        MAX(sort_date) AS latest_notice_date
    FROM notice_rows
    GROUP BY lp_code, program_key, round_key
),
selected_gp_rollup AS (
    SELECT
        nr.lp_code,
        nr.program_key,
        nr.round_key,
        COUNT(DISTINCT lgl.source_gp_id) AS selected_gp_count
    FROM notice_rows nr
    JOIN lp_notice_gp_link lgl
        ON lgl.notice_id = nr.notice_id
    GROUP BY nr.lp_code, nr.program_key, nr.round_key
)
SELECT
    r.lp_code,
    r.lp_name,
    r.lp_type,
    r.program_name,
    r.round_name,
    r.program_key,
    r.round_key,
    latest.asset_class,
    latest.strategy,
    r.notice_count,
    r.open_count,
    r.shortlist_count,
    r.final_selection_count,
    COALESCE(gp.selected_gp_count, 0) AS selected_gp_count,
    r.allocation_amount_krw_100mn_sum,
    r.commitment_amount_krw_100mn_sum,
    r.amount_krw_100mn_sum,
    r.program_size_krw_100mn_max,
    latest.notice_id AS latest_notice_id,
    latest.notice_title AS latest_notice_title,
    latest.source_url AS latest_notice_url,
    latest.document_url AS latest_document_url,
    r.latest_notice_date,
    latest.event_type AS latest_event_type,
    latest.stage AS latest_stage,
    latest.confidence AS latest_confidence,
    r.next_application_deadline,
    r.latest_application_deadline,
    CASE
        WHEN r.open_count > 0 THEN 'open'
        WHEN r.final_selection_count > 0 THEN 'final_selection'
        WHEN r.shortlist_count > 0 THEN 'shortlist'
        WHEN COALESCE(r.latest_application_deadline, '') <> '' THEN 'closed'
        ELSE 'no_deadline'
    END AS deadline_status
FROM notice_rollup r
JOIN latest_rows latest
    ON latest.lp_code = r.lp_code
   AND latest.program_key = r.program_key
   AND latest.round_key = r.round_key
LEFT JOIN selected_gp_rollup gp
    ON gp.lp_code = r.lp_code
   AND gp.program_key = r.program_key
   AND gp.round_key = r.round_key;

DROP VIEW IF EXISTS v_lp_institution_stats;

CREATE VIEW v_lp_institution_stats AS
SELECT
    li.lp_code,
    li.lp_name,
    li.lp_type,
    li.default_team,
    li.focus_asset_classes,
    li.service_priority,
    li.coverage_tier,
    li.display_enabled,
    li.notice_tracking_enabled,
    li.profile_status,
    COUNT(lcn.notice_id) AS notice_count,
    SUM(COALESCE(lcn.allocation_amount_krw_100mn, 0)) AS allocation_amount_krw_100mn,
    SUM(COALESCE(lcn.commitment_amount_krw_100mn, 0)) AS commitment_amount_krw_100mn,
    MAX(COALESCE(lcn.event_date, lcn.announced_date)) AS latest_event_date,
    MAX(lcn.announced_date) AS latest_announced_date,
    MAX(lcn.discovered_at) AS latest_discovered_at
FROM lp_institution li
LEFT JOIN lp_commitment_notice lcn
    ON lcn.lp_code = li.lp_code
   AND lcn.public_visible = 1
GROUP BY li.lp_code;

DROP VIEW IF EXISTS v_lp_profile_fact_public;

CREATE VIEW v_lp_profile_fact_public AS
SELECT
    fact_id,
    lp_code,
    section,
    label,
    value,
    as_of_date,
    source_name,
    source_url,
    confidence,
    notes,
    sort_order,
    public_visible,
    updated_at
FROM lp_profile_fact
WHERE public_visible = 1;

DROP VIEW IF EXISTS v_lp_profile_summary;

CREATE VIEW v_lp_profile_summary AS
SELECT
    li.lp_code,
    li.lp_name,
    li.lp_name_en,
    li.lp_type,
    li.ownership_type,
    li.homepage_url,
    li.notice_url,
    li.default_team,
    li.focus_asset_classes,
    li.service_priority,
    li.coverage_tier,
    li.display_enabled,
    li.notice_tracking_enabled,
    li.profile_status,
    li.aliases,
    li.notes,
    COALESCE(stats.notice_count, 0) AS notice_count,
    COALESCE(stats.allocation_amount_krw_100mn, 0) AS allocation_amount_krw_100mn,
    COALESCE(stats.commitment_amount_krw_100mn, 0) AS commitment_amount_krw_100mn,
    COALESCE(stats.latest_event_date, '') AS latest_event_date,
    COALESCE(stats.latest_announced_date, '') AS latest_announced_date,
    COALESCE(facts.fact_count, 0) AS fact_count,
    COALESCE(facts.source_count, 0) AS source_count
FROM lp_institution li
LEFT JOIN v_lp_institution_stats stats
    ON stats.lp_code = li.lp_code
LEFT JOIN (
    SELECT
        lp_code,
        COUNT(*) AS fact_count,
        COUNT(DISTINCT NULLIF(source_url, '')) AS source_count
    FROM v_lp_profile_fact_public
    GROUP BY lp_code
) facts
    ON facts.lp_code = li.lp_code;

DROP VIEW IF EXISTS v_lp_profile_peer_compare;

CREATE VIEW v_lp_profile_peer_compare AS
SELECT
    lp_code,
    lp_name,
    lp_type,
    ownership_type,
    default_team,
    focus_asset_classes,
    service_priority,
    coverage_tier,
    display_enabled,
    notice_tracking_enabled,
    profile_status,
    notice_count,
    allocation_amount_krw_100mn,
    commitment_amount_krw_100mn,
    latest_event_date,
    latest_announced_date,
    fact_count,
    source_count
FROM v_lp_profile_summary;

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
  AND public_visible = 1
GROUP BY notice_year, lp_code, lp_name;
