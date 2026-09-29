BEGIN;
CREATE TABLE IF NOT EXISTS lp_program_private.reviewers(email text PRIMARY KEY);
CREATE TABLE IF NOT EXISTS lp_program_private.review_decisions(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 created_at timestamptz NOT NULL DEFAULT now(),
 actor uuid NOT NULL,
 run_id text NOT NULL REFERENCES lp_program_private.collection_runs(run_id),
 source_id text NOT NULL,
 action text NOT NULL CHECK(action IN ('approve','hold','exclude')),
 program jsonb,
 evidence jsonb NOT NULL
);
CREATE OR REPLACE FUNCTION lp_program_private.require_reviewer() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM auth.users u JOIN lp_program_private.reviewers r ON lower(u.email)=lower(r.email)
 WHERE u.id=auth.uid() AND u.email_confirmed_at IS NOT NULL) THEN
 RAISE EXCEPTION 'Reviewer access required' USING ERRCODE='42501';
 END IF;
END $$;
REVOKE ALL ON FUNCTION lp_program_private.require_reviewer() FROM PUBLIC;
CREATE OR REPLACE FUNCTION public.lp_review_queue() RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE result jsonb;
BEGIN
 PERFORM lp_program_private.require_reviewer();
 SELECT jsonb_build_object('run_id',s.run_id,'programs',s.data->'programs','report',r.report,'review_outcomes',s.data->'review_outcomes',
 'decisions',COALESCE((SELECT jsonb_agg(to_jsonb(d) ORDER BY d.id DESC) FROM
 (SELECT DISTINCT ON(source_id) source_id,id,action,created_at FROM lp_program_private.review_decisions ORDER BY source_id,id DESC) d),'[]'::jsonb))
 INTO result FROM lp_program_private.program_state s JOIN lp_program_private.collection_runs r ON r.run_id=s.run_id WHERE s.id=1;
 RETURN result;
END $$;
CREATE OR REPLACE FUNCTION public.lp_review_decide(p_run_id text,p_source_id text,p_action text,p_program jsonb,p_source_ids jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE current_run text; evidence jsonb; expected integer; decision_id bigint;
BEGIN
 PERFORM lp_program_private.require_reviewer();
 PERFORM pg_advisory_xact_lock(728160921);
 SELECT run_id INTO current_run FROM lp_program_private.program_state WHERE id=1;
 IF current_run IS DISTINCT FROM p_run_id THEN RAISE EXCEPTION 'Collection changed; reload before reviewing' USING ERRCODE='40001'; END IF;
 IF p_action NOT IN ('approve','hold','exclude') OR jsonb_typeof(p_source_ids) IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'Invalid decision'; END IF;
 SELECT count(DISTINCT value) INTO expected FROM jsonb_array_elements_text(p_source_ids);
 IF expected=0 OR expected>30 OR NOT p_source_ids ? p_source_id THEN RAISE EXCEPTION 'Invalid evidence selection'; END IF;
 SELECT jsonb_agg(n) INTO evidence FROM lp_program_private.collection_runs r,
 jsonb_array_elements(r.report->'notices') n WHERE r.run_id=p_run_id AND p_source_ids ? (n->>'source_id');
 IF jsonb_array_length(evidence) IS DISTINCT FROM expected THEN RAISE EXCEPTION 'Evidence missing'; END IF;
 IF p_action='approve' AND (jsonb_typeof(p_program) IS DISTINCT FROM 'object' OR p_program->>'institution_id' IS DISTINCT FROM 'kgrowth') THEN RAISE EXCEPTION 'Invalid program'; END IF;
 INSERT INTO lp_program_private.review_decisions(actor,run_id,source_id,action,program,evidence)
 VALUES(auth.uid(),p_run_id,p_source_id,p_action,CASE WHEN p_action='approve' THEN p_program END,evidence) RETURNING id INTO decision_id;
 RETURN jsonb_build_object('id',decision_id,'action',p_action);
END $$;
REVOKE ALL ON FUNCTION public.lp_review_queue() FROM PUBLIC,anon;
REVOKE ALL ON FUNCTION public.lp_review_decide(text,text,text,jsonb,jsonb) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.lp_review_queue() TO authenticated;
GRANT EXECUTE ON FUNCTION public.lp_review_decide(text,text,text,jsonb,jsonb) TO authenticated;
COMMIT;
