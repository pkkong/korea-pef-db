BEGIN;
-- GP-owned migration. Apply after 20260828100000_fss_people_canonical_data.sql
-- and before deploying the corresponding canonical sync client.
ALTER TABLE public.fss_canonical_snapshots
    ADD COLUMN IF NOT EXISTS content_hash TEXT,
    ADD COLUMN IF NOT EXISTS table_manifest JSONB,
    ADD COLUMN IF NOT EXISTS source_manifest JSONB;
-- A raw workbook can have multiple corrected parser/alias interpretations.
ALTER TABLE public.fss_canonical_snapshots
    DROP CONSTRAINT IF EXISTS fss_canonical_snapshots_reporting_period_source_sha256_key;

CREATE OR REPLACE FUNCTION public.fss_canonical_row_digest(row_data JSONB)
RETURNS TEXT LANGUAGE sql IMMUTABLE
SET search_path = pg_catalog, public
AS $$
    SELECT md5(COALESCE(string_agg(key || ':' ||
        CASE WHEN value = 'null'::jsonb THEN '-1:' ELSE
            octet_length(scalar_value)::text || ':' || scalar_value END,
        ',' ORDER BY key COLLATE "C"), ''))
    FROM (
        SELECT key, value,
            CASE WHEN jsonb_typeof(value) = 'number' THEN trim_scale((value #>> '{}')::numeric)::text
                 ELSE value #>> '{}' END AS scalar_value
        FROM jsonb_each(row_data - ARRAY['snapshot_id', 'created_at', 'updated_at', 'fetched_at', 'parsed_at', 'merged_at'])
    ) fields;
$$;
REVOKE ALL ON FUNCTION public.fss_canonical_row_digest(JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fss_canonical_row_digest(JSONB) TO service_role;

CREATE OR REPLACE FUNCTION public.guard_fss_canonical_rows()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE row_snapshot_id TEXT;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        row_snapshot_id := OLD.snapshot_id;
        PERFORM 1 FROM public.fss_canonical_snapshots
        WHERE snapshot_id = row_snapshot_id AND status = 'staged' FOR SHARE;
        IF NOT FOUND THEN RAISE EXCEPTION 'FSS snapshot % is immutable', row_snapshot_id; END IF;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        row_snapshot_id := NEW.snapshot_id;
        PERFORM 1 FROM public.fss_canonical_snapshots
        WHERE snapshot_id = row_snapshot_id AND status = 'staged' FOR SHARE;
        IF NOT FOUND THEN RAISE EXCEPTION 'FSS snapshot % is immutable', row_snapshot_id; END IF;
        RETURN NEW;
    END IF;
    RETURN OLD;
END;
$$;
REVOKE ALL ON FUNCTION public.guard_fss_canonical_rows() FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.guard_fss_canonical_header()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF OLD.status IN ('published', 'retired') THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Published FSS snapshot history cannot be deleted';
        END IF;
        IF (to_jsonb(OLD) - ARRAY['status', 'published_at', 'updated_at'])
             IS DISTINCT FROM (to_jsonb(NEW) - ARRAY['status', 'published_at', 'updated_at'])
           OR NEW.status = 'staged' THEN
            RAISE EXCEPTION 'Published FSS snapshot metadata is immutable';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.guard_fss_canonical_header() FROM PUBLIC, anon, authenticated;
DROP TRIGGER IF EXISTS guard_fss_canonical_header ON public.fss_canonical_snapshots;
CREATE TRIGGER guard_fss_canonical_header BEFORE UPDATE OR DELETE ON public.fss_canonical_snapshots
FOR EACH ROW EXECUTE FUNCTION public.guard_fss_canonical_header();

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'fss_source_documents', 'fss_reporting_periods', 'fss_gp_houses', 'fss_pef_funds',
        'fss_fund_gp_affiliations', 'fss_gp_house_aliases', 'fss_source_rows',
        'fss_fund_period_snapshots', 'fss_fund_events'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS guard_fss_canonical_rows ON public.%I', table_name);
        EXECUTE format('CREATE TRIGGER guard_fss_canonical_rows BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.guard_fss_canonical_rows()', table_name);
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.publish_fss_canonical_snapshot(target_snapshot_id TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    target public.fss_canonical_snapshots;
    table_name TEXT;
    expected JSONB;
    actual_count BIGINT;
    actual_hash TEXT;
    table_names TEXT[] := ARRAY[
        'fss_source_documents', 'fss_reporting_periods', 'fss_gp_houses', 'fss_pef_funds',
        'fss_fund_gp_affiliations', 'fss_gp_house_aliases', 'fss_source_rows',
        'fss_fund_period_snapshots', 'fss_fund_events'
    ];
BEGIN
    -- Shared with People replacement; serializes publish against stale People runs.
    PERFORM pg_advisory_xact_lock(731640923);
    SELECT * INTO target FROM public.fss_canonical_snapshots
    WHERE snapshot_id = target_snapshot_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Unknown FSS canonical snapshot %', target_snapshot_id; END IF;
    -- An acknowledged/uncertain successful request can be retried without writes.
    IF target.status = 'published' THEN RETURN; END IF;
    IF target.status <> 'staged' THEN RAISE EXCEPTION 'Cannot republish a retired FSS snapshot'; END IF;
    IF target.content_hash IS NULL OR target.content_hash !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(target.table_manifest) IS DISTINCT FROM 'object'
       OR jsonb_typeof(target.source_manifest) IS DISTINCT FROM 'object'
       OR (SELECT count(*) FROM jsonb_object_keys(target.table_manifest)) <> cardinality(table_names) THEN
        RAISE EXCEPTION 'FSS snapshot has no complete content manifest';
    END IF;
    FOREACH table_name IN ARRAY table_names LOOP
        expected := target.table_manifest -> table_name;
        IF expected IS NULL OR expected ->> 'row_count' IS NULL OR expected ->> 'content_md5' IS NULL THEN
            RAISE EXCEPTION 'FSS manifest is missing %', table_name;
        END IF;
        EXECUTE format(
            'SELECT count(*), md5(COALESCE(string_agg(public.fss_canonical_row_digest(to_jsonb(t)), '''' ORDER BY public.fss_canonical_row_digest(to_jsonb(t))), '''')) FROM public.%I t WHERE snapshot_id = $1',
            table_name
        ) INTO actual_count, actual_hash USING target_snapshot_id;
        IF actual_count <> (expected ->> 'row_count')::bigint OR actual_hash <> expected ->> 'content_md5' THEN
            RAISE EXCEPTION 'FSS manifest mismatch in % (expected %, found % rows)', table_name, expected ->> 'row_count', actual_count;
        END IF;
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM public.fss_fund_period_snapshots WHERE snapshot_id = target_snapshot_id)
       OR NOT EXISTS (SELECT 1 FROM public.fss_source_documents WHERE snapshot_id = target_snapshot_id AND source_id = target.source_id AND sha256 = target.source_sha256) THEN
        RAISE EXCEPTION 'FSS snapshot is missing its verified source or fund period data';
    END IF;
    UPDATE public.fss_canonical_snapshots SET status = 'retired'
    WHERE status = 'published' AND snapshot_id <> target_snapshot_id;
    UPDATE public.fss_canonical_snapshots SET status = 'published', published_at = now()
    WHERE snapshot_id = target_snapshot_id;
END;
$$;
REVOKE ALL ON FUNCTION public.publish_fss_canonical_snapshot(TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.publish_fss_canonical_snapshot(TEXT) TO service_role;

CREATE OR REPLACE FUNCTION public.replace_people_canonical(
    people_tables JSONB, people_state JSONB, publish_snapshot_id TEXT DEFAULT NULL
)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    table_name TEXT;
    table_names TEXT[] := ARRAY['people_persons', 'people_aliases', 'people_roles', 'people_educations', 'people_sources', 'people_news_links'];
    target_fss_id TEXT := people_state ->> 'fss_snapshot_id';
BEGIN
    PERFORM pg_advisory_xact_lock(731640923);
    IF jsonb_typeof(people_tables) IS DISTINCT FROM 'object'
       OR jsonb_typeof(people_state) IS DISTINCT FROM 'object'
       OR people_state -> 'state_key' IS DISTINCT FROM 'true'::jsonb
       OR NULLIF(people_state ->> 'source_hash', '') IS NULL
       OR target_fss_id IS NULL
       OR (SELECT count(*) FROM jsonb_object_keys(people_tables)) <> cardinality(table_names) THEN
        RAISE EXCEPTION 'Invalid People replacement/state';
    END IF;
    -- A bounded single request permits transaction rollback of every child insert.
    IF octet_length(people_tables::text) > 10000000 THEN RAISE EXCEPTION 'People replacement exceeds atomic RPC size limit'; END IF;
    FOREACH table_name IN ARRAY table_names LOOP
        IF jsonb_typeof(people_tables -> table_name) IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'People replacement is missing %', table_name;
        END IF;
    END LOOP;
    IF publish_snapshot_id IS NOT NULL AND publish_snapshot_id <> target_fss_id THEN
        RAISE EXCEPTION 'People state does not reference the FSS publication target';
    END IF;
    IF publish_snapshot_id IS NULL AND NOT EXISTS (
        SELECT 1 FROM public.fss_canonical_snapshots WHERE snapshot_id = target_fss_id AND status = 'published'
    ) THEN RAISE EXCEPTION 'People replacement must reference the current published FSS snapshot'; END IF;

    DELETE FROM public.people_persons;
    -- Complete typed records preserve the original schema's NOT NULL and FK
    -- checks. Any malformed late table rolls back the deletion and earlier rows.
    FOREACH table_name IN ARRAY table_names LOOP
        EXECUTE format('INSERT INTO public.%I SELECT * FROM jsonb_populate_recordset(NULL::public.%I, $1)', table_name, table_name)
        USING people_tables -> table_name;
    END LOOP;
    INSERT INTO public.people_data_state (state_key, fss_snapshot_id, synced_at, source_hash)
    VALUES (TRUE, target_fss_id, COALESCE((people_state ->> 'synced_at')::timestamptz, now()), people_state ->> 'source_hash')
    ON CONFLICT (state_key) DO UPDATE SET fss_snapshot_id = EXCLUDED.fss_snapshot_id,
        synced_at = EXCLUDED.synced_at, source_hash = EXCLUDED.source_hash;
    IF publish_snapshot_id IS NOT NULL THEN
        PERFORM public.publish_fss_canonical_snapshot(publish_snapshot_id);
    END IF;
END;
$$;
REVOKE ALL ON FUNCTION public.replace_people_canonical(JSONB, JSONB, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.replace_people_canonical(JSONB, JSONB, TEXT) TO service_role;

COMMIT;
