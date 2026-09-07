-- Staging is private. Only the final RPC mutates canonical/public data.
BEGIN;
CREATE TABLE IF NOT EXISTS public.newsletter_sync_parts (
    sync_id UUID NOT NULL,
    model TEXT NOT NULL CHECK (model IN ('canonical', 'public')),
    table_name TEXT NOT NULL,
    part_no INTEGER NOT NULL CHECK (part_no >= 0),
    rows JSONB NOT NULL CHECK (jsonb_typeof(rows) = 'array'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sync_id, table_name, part_no)
);
CREATE TABLE IF NOT EXISTS public.newsletter_sync_receipts (
    sync_id UUID PRIMARY KEY,
    model TEXT NOT NULL,
    counts JSONB NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE public.newsletter_sync_parts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.newsletter_sync_receipts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.newsletter_sync_parts, public.newsletter_sync_receipts FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.newsletter_sync_parts, public.newsletter_sync_receipts TO service_role;

-- Internal helper limited to the explicitly owned tables. Row types are taken
-- from PostgreSQL itself; a malformed value/FK aborts the caller transaction.
CREATE OR REPLACE FUNCTION public.newsletter_merge_sync_rows(target_table TEXT, incoming JSONB)
RETURNS VOID LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    keys TEXT[];
    defaults JSONB;
    columns_sql TEXT;
    updates_sql TEXT;
    keys_sql TEXT;
    mapped JSONB;
BEGIN
    defaults := jsonb_build_object('created_at', now(), 'updated_at', now());
    CASE target_table
        WHEN 'newsletter_canonical_sources' THEN
            keys := ARRAY['source_code'];
            defaults := defaults || '{"is_active":true}'::jsonb;
        WHEN 'newsletter_canonical_runs' THEN
            keys := ARRAY['run_id'];
            defaults := defaults || '{"discovered_count":0,"fetched_count":0,"inserted_count":0,"relevant_count":0}'::jsonb;
        WHEN 'newsletter_canonical_documents' THEN
            keys := ARRAY['news_id'];
            defaults := defaults || '{"document_type":"article","language_code":"ko","relevance_score":0,"relevance_label":"review","review_status":"auto","is_pe_relevant":false}'::jsonb;
        WHEN 'newsletter_issues' THEN
            keys := ARRAY['issue_date'];
            defaults := defaults || jsonb_build_object('status','published','article_count',0,'published_at',now());
        WHEN 'newsletter_articles' THEN
            keys := ARRAY['normalized_url'];
            defaults := defaults || '{"section":"Market","summary_lines":[],"gp_names":[],"lp_names":[],"search_terms":[]}'::jsonb;
        ELSE RAISE EXCEPTION 'Unsupported newsletter merge table: %', target_table;
    END CASE;
    SELECT coalesce(jsonb_agg(
        jsonb_build_object('article_id', gen_random_uuid()) || defaults || value
    ), '[]'::jsonb) INTO mapped FROM jsonb_array_elements(incoming);
    SELECT string_agg(format('%I', attname), ',' ORDER BY attnum),
           string_agg(format('%1$I = EXCLUDED.%1$I', attname), ',' ORDER BY attnum)
               FILTER (WHERE NOT attname = ANY(keys || ARRAY['article_id','created_at']))
    INTO columns_sql, updates_sql
    FROM pg_attribute
    WHERE attrelid = format('public.%I', target_table)::regclass AND attnum > 0 AND NOT attisdropped;
    SELECT string_agg(format('%I', k), ',') INTO keys_sql FROM unnest(keys) k;
    EXECUTE format(
        'INSERT INTO public.%1$I (%2$s) SELECT %2$s FROM jsonb_populate_recordset(NULL::public.%1$I, $1) ON CONFLICT (%3$s) DO UPDATE SET %4$s',
        target_table, columns_sql, keys_sql, updates_sql
    ) USING mapped;
END;
$$;
REVOKE ALL ON FUNCTION public.newsletter_merge_sync_rows(TEXT, JSONB) FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.publish_newsletter_sync(
    target_sync_id UUID, target_model TEXT, expected_counts JSONB
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    tables TEXT[];
    table_key TEXT;
    assembled JSONB := '{}'::jsonb;
    table_rows JSONB;
    receipt public.newsletter_sync_receipts%ROWTYPE;
    affected BIGINT;
BEGIN
    -- Serializes publications, including receipt retries. Readers see either
    -- the old committed data or the complete replacement, never empty tables.
    PERFORM pg_advisory_xact_lock(hashtext('newsletter-sync:' || target_model));
    SELECT * INTO receipt FROM public.newsletter_sync_receipts WHERE sync_id = target_sync_id;
    IF FOUND THEN
        IF receipt.model <> target_model OR receipt.counts <> expected_counts THEN
            RAISE EXCEPTION 'Newsletter sync receipt does not match request';
        END IF;
        RETURN receipt.counts;
    END IF;
    IF target_model = 'canonical' THEN
        tables := ARRAY['newsletter_canonical_sources','newsletter_canonical_runs','newsletter_canonical_documents','newsletter_canonical_tags','newsletter_canonical_entity_links'];
    ELSIF target_model = 'public' THEN
        tables := ARRAY['issues','articles','issue_articles','tags','entities'];
    ELSE RAISE EXCEPTION 'Unsupported newsletter sync model';
    END IF;
    IF expected_counts IS NULL OR jsonb_typeof(expected_counts) <> 'object'
       OR NOT expected_counts ?& tables
       OR (SELECT count(*) FROM jsonb_object_keys(expected_counts)) <> cardinality(tables) THEN
        RAISE EXCEPTION 'Incomplete newsletter table manifest';
    END IF;
    IF EXISTS (SELECT 1 FROM public.newsletter_sync_parts WHERE sync_id = target_sync_id
               AND (model <> target_model OR NOT table_name = ANY(tables))) THEN
        RAISE EXCEPTION 'Unexpected newsletter staging part';
    END IF;
    FOREACH table_key IN ARRAY tables LOOP
        SELECT coalesce(jsonb_agg(item.value ORDER BY p.part_no, item.ordinality), '[]'::jsonb)
        INTO table_rows
        FROM public.newsletter_sync_parts p
        CROSS JOIN LATERAL jsonb_array_elements(p.rows) WITH ORDINALITY item(value, ordinality)
        WHERE p.sync_id = target_sync_id AND p.table_name = table_key;
        IF jsonb_typeof(expected_counts->table_key) <> 'number'
           OR (expected_counts->>table_key)::integer < 0
           OR jsonb_array_length(table_rows) <> (expected_counts->>table_key)::integer
           OR EXISTS (SELECT 1 FROM jsonb_array_elements(table_rows) x WHERE jsonb_typeof(x) <> 'object') THEN
            RAISE EXCEPTION 'Incomplete or invalid staged newsletter table: %', table_key;
        END IF;
        assembled := assembled || jsonb_build_object(table_key, table_rows);
    END LOOP;

    IF target_model = 'canonical' THEN
        PERFORM public.newsletter_merge_sync_rows('newsletter_canonical_sources', assembled->'newsletter_canonical_sources');
        PERFORM public.newsletter_merge_sync_rows('newsletter_canonical_runs', assembled->'newsletter_canonical_runs');
        PERFORM public.newsletter_merge_sync_rows('newsletter_canonical_documents', assembled->'newsletter_canonical_documents');
        -- A partial input must not remove links of documents it did not load.
        IF EXISTS (
            SELECT 1 FROM (
                SELECT value FROM jsonb_array_elements(assembled->'newsletter_canonical_tags')
                UNION ALL SELECT value FROM jsonb_array_elements(assembled->'newsletter_canonical_entity_links')
            ) links
            WHERE NOT EXISTS (SELECT 1 FROM jsonb_array_elements(assembled->'newsletter_canonical_documents') d
                              WHERE d->>'news_id' = links.value->>'news_id')
        ) THEN RAISE EXCEPTION 'Newsletter links reference a document outside this sync'; END IF;
        DELETE FROM public.newsletter_canonical_tags WHERE news_id IN (
            SELECT (value->>'news_id')::bigint FROM jsonb_array_elements(assembled->'newsletter_canonical_documents')
        );
        DELETE FROM public.newsletter_canonical_entity_links WHERE news_id IN (
            SELECT (value->>'news_id')::bigint FROM jsonb_array_elements(assembled->'newsletter_canonical_documents')
        );
        INSERT INTO public.newsletter_canonical_tags
        SELECT r.* FROM jsonb_array_elements(assembled->'newsletter_canonical_tags') item
        CROSS JOIN LATERAL jsonb_populate_record(NULL::public.newsletter_canonical_tags,
            jsonb_build_object('created_at',now()) || item) r;
        INSERT INTO public.newsletter_canonical_entity_links
        SELECT r.* FROM jsonb_array_elements(assembled->'newsletter_canonical_entity_links') item
        CROSS JOIN LATERAL jsonb_populate_record(NULL::public.newsletter_canonical_entity_links,
            jsonb_build_object('created_at',now()) || item) r;
    ELSE
        IF jsonb_array_length(assembled->'issues') = 0 THEN
            RAISE EXCEPTION 'Cannot publish newsletter without issues';
        END IF;
        PERFORM public.newsletter_merge_sync_rows('newsletter_issues', assembled->'issues');
        PERFORM public.newsletter_merge_sync_rows('newsletter_articles', assembled->'articles');
        DELETE FROM public.newsletter_issue_articles WHERE issue_date IN (
            SELECT (value->>'issue_date')::date FROM jsonb_array_elements(assembled->'issues')
        );
        DELETE FROM public.newsletter_article_tags WHERE article_id IN (
            SELECT a.article_id FROM public.newsletter_articles a
            JOIN jsonb_array_elements(assembled->'articles') p ON a.normalized_url = p->>'normalized_url'
        );
        DELETE FROM public.newsletter_article_entities WHERE article_id IN (
            SELECT a.article_id FROM public.newsletter_articles a
            JOIN jsonb_array_elements(assembled->'articles') p ON a.normalized_url = p->>'normalized_url'
        );
        INSERT INTO public.newsletter_issue_articles(issue_date,article_id,rank,section_order)
        SELECT (p->>'issue_date')::date, a.article_id, (p->>'rank')::integer, (p->>'section_order')::integer
        FROM jsonb_array_elements(assembled->'issue_articles') p
        JOIN public.newsletter_articles a ON a.normalized_url = p->>'normalized_url'
        WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(assembled->'issues') i WHERE i->>'issue_date' = p->>'issue_date')
          AND EXISTS (SELECT 1 FROM jsonb_array_elements(assembled->'articles') i WHERE i->>'normalized_url' = p->>'normalized_url');
        GET DIAGNOSTICS affected = ROW_COUNT;
        IF affected <> (expected_counts->>'issue_articles')::integer THEN
            RAISE EXCEPTION 'Newsletter issue links are incomplete';
        END IF;
        INSERT INTO public.newsletter_article_tags(article_id,tag_type,tag_value,tag_source)
        SELECT a.article_id, p->>'tag_type', p->>'tag_value', p->>'tag_source'
        FROM jsonb_array_elements(assembled->'tags') p
        JOIN public.newsletter_articles a ON a.normalized_url = p->>'normalized_url'
        WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(assembled->'articles') i WHERE i->>'normalized_url' = p->>'normalized_url');
        GET DIAGNOSTICS affected = ROW_COUNT;
        IF affected <> (expected_counts->>'tags')::integer THEN RAISE EXCEPTION 'Newsletter tags are incomplete'; END IF;
        INSERT INTO public.newsletter_article_entities(article_id,entity_type,entity_name,link_source)
        SELECT a.article_id, p->>'entity_type', p->>'entity_name', p->>'link_source'
        FROM jsonb_array_elements(assembled->'entities') p
        JOIN public.newsletter_articles a ON a.normalized_url = p->>'normalized_url'
        WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(assembled->'articles') i WHERE i->>'normalized_url' = p->>'normalized_url');
        GET DIAGNOSTICS affected = ROW_COUNT;
        IF affected <> (expected_counts->>'entities')::integer THEN RAISE EXCEPTION 'Newsletter entities are incomplete'; END IF;
        IF EXISTS (
            SELECT 1 FROM public.newsletter_issues i
            JOIN jsonb_array_elements(assembled->'issues') p ON i.issue_date = (p->>'issue_date')::date
            WHERE i.article_count <> (SELECT count(*) FROM public.newsletter_issue_articles ia WHERE ia.issue_date = i.issue_date)
        ) THEN RAISE EXCEPTION 'Newsletter issue article count mismatch'; END IF;
    END IF;
    INSERT INTO public.newsletter_sync_receipts(sync_id,model,counts) VALUES (target_sync_id,target_model,expected_counts);
    DELETE FROM public.newsletter_sync_parts WHERE sync_id = target_sync_id;
    -- Orphaned uploads cannot affect production. Reclaim them on a later success.
    DELETE FROM public.newsletter_sync_parts WHERE created_at < now() - interval '7 days';
    RETURN expected_counts;
END;
$$;
REVOKE ALL ON FUNCTION public.publish_newsletter_sync(UUID, TEXT, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.publish_newsletter_sync(UUID, TEXT, JSONB) TO service_role;
COMMIT;
