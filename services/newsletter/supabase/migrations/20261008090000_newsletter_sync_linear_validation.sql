-- Keep newsletter publication atomic while validating document membership
-- without repeatedly decoding the full document set for each tag or link.
BEGIN;
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
        -- Parse document IDs once and keep only the typed ID in the membership
        -- relation. Hashing full article JSON retains unnecessary body/raw data
        -- as history grows; the materialized IDs keep this validation compact.
        IF EXISTS (
            WITH document_ids AS MATERIALIZED (
                SELECT d.news_id
                FROM jsonb_to_recordset(assembled->'newsletter_canonical_documents') AS d(news_id BIGINT)
            ), link_ids AS (
                SELECT t.news_id
                FROM jsonb_to_recordset(assembled->'newsletter_canonical_tags') AS t(news_id BIGINT)
                UNION ALL
                SELECT e.news_id
                FROM jsonb_to_recordset(assembled->'newsletter_canonical_entity_links') AS e(news_id BIGINT)
            )
            SELECT 1
            FROM link_ids links
            LEFT JOIN document_ids documents USING (news_id)
            WHERE documents.news_id IS NULL
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
