BEGIN;
-- Supabase safeupdate requires an explicit predicate, including inside RPCs.
-- The primary key is NOT NULL, so this preserves the validated full replacement.
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

    DELETE FROM public.people_persons WHERE person_id IS NOT NULL;
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
