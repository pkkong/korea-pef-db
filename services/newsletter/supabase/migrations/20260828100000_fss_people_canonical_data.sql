-- Canonical private operating data for the FSS/GP/People pipeline.
-- The public GP page snapshot remains a separate read model.

CREATE TABLE IF NOT EXISTS public.fss_canonical_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    reporting_period TEXT NOT NULL,
    as_of_date DATE NOT NULL,
    source_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK (char_length(source_sha256) = 64),
    fund_count INTEGER NOT NULL CHECK (fund_count > 0),
    primary_gp_count INTEGER NOT NULL CHECK (primary_gp_count > 0),
    commitment_amount_krw_mn NUMERIC NOT NULL CHECK (commitment_amount_krw_mn > 0),
    status TEXT NOT NULL DEFAULT 'staged'
        CHECK (status IN ('staged', 'published', 'retired')),
    generated_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (reporting_period, source_sha256)
);

CREATE TABLE IF NOT EXISTS public.fss_source_documents (
    snapshot_id TEXT NOT NULL REFERENCES public.fss_canonical_snapshots(snapshot_id) ON DELETE CASCADE,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    publisher TEXT NOT NULL,
    document_type TEXT NOT NULL,
    regime TEXT,
    period_label TEXT,
    as_of_date TEXT,
    source_url TEXT,
    local_path TEXT,
    sha256 TEXT,
    fetched_at TEXT,
    parsed_at TEXT,
    notes TEXT,
    PRIMARY KEY (snapshot_id, source_id)
);

CREATE TABLE IF NOT EXISTS public.fss_reporting_periods (
    snapshot_id TEXT NOT NULL REFERENCES public.fss_canonical_snapshots(snapshot_id) ON DELETE CASCADE,
    period_id TEXT NOT NULL,
    period_label TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    regime TEXT,
    PRIMARY KEY (snapshot_id, period_id)
);

CREATE TABLE IF NOT EXISTS public.fss_gp_houses (
    snapshot_id TEXT NOT NULL REFERENCES public.fss_canonical_snapshots(snapshot_id) ON DELETE CASCADE,
    gp_id BIGINT NOT NULL,
    gp_name TEXT NOT NULL,
    gp_name_norm TEXT NOT NULL,
    first_seen_period_id TEXT,
    last_seen_period_id TEXT,
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (snapshot_id, gp_id),
    UNIQUE (snapshot_id, gp_name_norm)
);

CREATE TABLE IF NOT EXISTS public.fss_pef_funds (
    snapshot_id TEXT NOT NULL REFERENCES public.fss_canonical_snapshots(snapshot_id) ON DELETE CASCADE,
    fund_id BIGINT NOT NULL,
    fund_name TEXT NOT NULL,
    fund_name_norm TEXT NOT NULL,
    regime_first_seen TEXT,
    fund_type TEXT,
    established_date TEXT,
    liquidation_date TEXT,
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (snapshot_id, fund_id),
    UNIQUE (snapshot_id, fund_name_norm)
);

CREATE TABLE IF NOT EXISTS public.fss_fund_gp_affiliations (
    snapshot_id TEXT NOT NULL REFERENCES public.fss_canonical_snapshots(snapshot_id) ON DELETE CASCADE,
    fund_id BIGINT NOT NULL,
    gp_id BIGINT NOT NULL,
    role TEXT NOT NULL,
    first_seen_period_id TEXT,
    last_seen_period_id TEXT,
    PRIMARY KEY (snapshot_id, fund_id, gp_id, role),
    FOREIGN KEY (snapshot_id, fund_id)
        REFERENCES public.fss_pef_funds(snapshot_id, fund_id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, gp_id)
        REFERENCES public.fss_gp_houses(snapshot_id, gp_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.fss_gp_house_aliases (
    snapshot_id TEXT NOT NULL REFERENCES public.fss_canonical_snapshots(snapshot_id) ON DELETE CASCADE,
    alias_gp_id BIGINT NOT NULL,
    canonical_gp_id BIGINT NOT NULL,
    alias_gp_name TEXT NOT NULL,
    alias_gp_name_norm TEXT NOT NULL,
    canonical_gp_name TEXT NOT NULL,
    alias_candidate_group_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    verification_decision TEXT NOT NULL,
    evidence_summary TEXT NOT NULL,
    primary_sources TEXT NOT NULL,
    merged_at TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, alias_gp_id),
    FOREIGN KEY (snapshot_id, canonical_gp_id)
        REFERENCES public.fss_gp_houses(snapshot_id, gp_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.fss_source_rows (
    snapshot_id TEXT NOT NULL REFERENCES public.fss_canonical_snapshots(snapshot_id) ON DELETE CASCADE,
    source_row_id BIGINT NOT NULL,
    source_id TEXT NOT NULL,
    sheet_name TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    raw_row_json TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, source_row_id),
    UNIQUE (snapshot_id, source_id, sheet_name, row_number),
    FOREIGN KEY (snapshot_id, source_id)
        REFERENCES public.fss_source_documents(snapshot_id, source_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.fss_fund_period_snapshots (
    snapshot_id TEXT NOT NULL REFERENCES public.fss_canonical_snapshots(snapshot_id) ON DELETE CASCADE,
    fund_period_snapshot_id BIGINT NOT NULL,
    fund_id BIGINT NOT NULL,
    period_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    gp_id BIGINT,
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
    commitment_amount_krw_mn NUMERIC,
    paid_in_amount_raw TEXT,
    paid_in_amount_krw_mn NUMERIC,
    raw_row_json TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, fund_period_snapshot_id),
    UNIQUE (snapshot_id, source_id, sheet_name, row_number),
    FOREIGN KEY (snapshot_id, fund_id)
        REFERENCES public.fss_pef_funds(snapshot_id, fund_id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, period_id)
        REFERENCES public.fss_reporting_periods(snapshot_id, period_id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, source_id)
        REFERENCES public.fss_source_documents(snapshot_id, source_id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, gp_id)
        REFERENCES public.fss_gp_houses(snapshot_id, gp_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.fss_fund_events (
    snapshot_id TEXT NOT NULL REFERENCES public.fss_canonical_snapshots(snapshot_id) ON DELETE CASCADE,
    fund_event_id BIGINT NOT NULL,
    fund_id BIGINT NOT NULL,
    gp_id BIGINT,
    event_type TEXT NOT NULL,
    event_date TEXT,
    period_id TEXT NOT NULL,
    source_id TEXT,
    confidence TEXT NOT NULL,
    basis TEXT NOT NULL,
    created_at TEXT,
    PRIMARY KEY (snapshot_id, fund_event_id),
    UNIQUE (snapshot_id, fund_id, event_type, period_id, source_id),
    FOREIGN KEY (snapshot_id, fund_id)
        REFERENCES public.fss_pef_funds(snapshot_id, fund_id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, gp_id)
        REFERENCES public.fss_gp_houses(snapshot_id, gp_id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, period_id)
        REFERENCES public.fss_reporting_periods(snapshot_id, period_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.people_persons (
    person_id BIGINT PRIMARY KEY,
    person_name_ko TEXT NOT NULL,
    person_name_en TEXT,
    person_name_norm TEXT NOT NULL,
    current_primary_org_type TEXT,
    current_primary_org_id TEXT,
    current_primary_org_name TEXT,
    current_title TEXT,
    profile_status TEXT NOT NULL,
    verification_level TEXT NOT NULL,
    primary_source_url TEXT,
    notes TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS public.people_aliases (
    alias_id BIGINT PRIMARY KEY,
    person_id BIGINT NOT NULL REFERENCES public.people_persons(person_id) ON DELETE CASCADE,
    alias_name TEXT NOT NULL,
    alias_name_norm TEXT NOT NULL,
    alias_type TEXT NOT NULL,
    source_url TEXT,
    verification_status TEXT NOT NULL,
    notes TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS public.people_roles (
    role_id BIGINT PRIMARY KEY,
    person_id BIGINT NOT NULL REFERENCES public.people_persons(person_id) ON DELETE CASCADE,
    org_type TEXT NOT NULL,
    org_id TEXT,
    org_name TEXT NOT NULL,
    title TEXT,
    team TEXT,
    role_start_date TEXT,
    role_end_date TEXT,
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    source_url TEXT,
    source_title TEXT,
    source_grade TEXT,
    verification_status TEXT NOT NULL,
    notes TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS public.people_educations (
    education_id BIGINT PRIMARY KEY,
    person_id BIGINT NOT NULL REFERENCES public.people_persons(person_id) ON DELETE CASCADE,
    school_name TEXT NOT NULL,
    school_name_en TEXT,
    degree TEXT,
    major TEXT,
    start_year INTEGER,
    graduation_year INTEGER,
    source_url TEXT,
    source_title TEXT,
    source_grade TEXT,
    verification_status TEXT NOT NULL,
    notes TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS public.people_sources (
    source_evidence_id BIGINT PRIMARY KEY,
    person_id BIGINT NOT NULL REFERENCES public.people_persons(person_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_title TEXT,
    source_url TEXT NOT NULL,
    source_grade TEXT NOT NULL,
    evidence_scope TEXT NOT NULL,
    evidence_value TEXT,
    evidence_date TEXT,
    verification_status TEXT NOT NULL,
    captured_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS public.people_news_links (
    person_id BIGINT NOT NULL REFERENCES public.people_persons(person_id) ON DELETE CASCADE,
    news_id BIGINT NOT NULL,
    matched_name TEXT,
    link_source TEXT NOT NULL,
    confidence NUMERIC,
    notes TEXT,
    created_at TEXT,
    PRIMARY KEY (person_id, news_id, link_source)
);

CREATE TABLE IF NOT EXISTS public.people_data_state (
    state_key BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (state_key),
    fss_snapshot_id TEXT REFERENCES public.fss_canonical_snapshots(snapshot_id),
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fss_canonical_snapshots_published
    ON public.fss_canonical_snapshots(status, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_fss_fund_period_snapshots_period
    ON public.fss_fund_period_snapshots(snapshot_id, period_id);
CREATE INDEX IF NOT EXISTS idx_fss_fund_period_snapshots_gp
    ON public.fss_fund_period_snapshots(snapshot_id, gp_id);
CREATE INDEX IF NOT EXISTS idx_fss_gp_house_aliases_canonical
    ON public.fss_gp_house_aliases(snapshot_id, canonical_gp_id);
CREATE INDEX IF NOT EXISTS idx_people_roles_current_gp
    ON public.people_roles(is_current, org_type, org_id);
CREATE INDEX IF NOT EXISTS idx_people_persons_name_norm
    ON public.people_persons(person_name_norm);

CREATE OR REPLACE FUNCTION public.publish_fss_canonical_snapshot(target_snapshot_id TEXT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.fss_canonical_snapshots
        WHERE snapshot_id = target_snapshot_id
    ) THEN
        RAISE EXCEPTION 'Unknown FSS canonical snapshot %', target_snapshot_id;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.fss_fund_period_snapshots WHERE snapshot_id = target_snapshot_id
    ) THEN
        RAISE EXCEPTION 'FSS canonical snapshot % has no fund period data', target_snapshot_id;
    END IF;

    UPDATE public.fss_canonical_snapshots
    SET status = 'retired'
    WHERE status = 'published'
      AND snapshot_id <> target_snapshot_id;

    UPDATE public.fss_canonical_snapshots
    SET status = 'published',
        published_at = NOW()
    WHERE snapshot_id = target_snapshot_id;
END;
$$;

CREATE OR REPLACE VIEW public.fss_current_canonical_snapshot AS
SELECT *
FROM public.fss_canonical_snapshots
WHERE status = 'published';

ALTER TABLE public.fss_canonical_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fss_source_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fss_reporting_periods ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fss_gp_houses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fss_pef_funds ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fss_fund_gp_affiliations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fss_gp_house_aliases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fss_source_rows ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fss_fund_period_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fss_fund_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.people_persons ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.people_aliases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.people_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.people_educations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.people_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.people_news_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.people_data_state ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE
    public.fss_canonical_snapshots,
    public.fss_source_documents,
    public.fss_reporting_periods,
    public.fss_gp_houses,
    public.fss_pef_funds,
    public.fss_fund_gp_affiliations,
    public.fss_gp_house_aliases,
    public.fss_source_rows,
    public.fss_fund_period_snapshots,
    public.fss_fund_events,
    public.people_persons,
    public.people_aliases,
    public.people_roles,
    public.people_educations,
    public.people_sources,
    public.people_news_links,
    public.people_data_state
FROM anon, authenticated;
REVOKE ALL ON FUNCTION public.publish_fss_canonical_snapshot(TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.publish_fss_canonical_snapshot(TEXT) TO service_role;
