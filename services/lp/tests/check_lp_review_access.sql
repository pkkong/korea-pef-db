-- Read-only permission checks; no auth users or review decisions are created.
DO $$
BEGIN
 IF has_function_privilege('anon','public.lp_review_queue()','EXECUTE') OR
    has_function_privilege('anon','public.lp_review_decide(text,text,text,jsonb,jsonb)','EXECUTE') THEN
   RAISE EXCEPTION 'Anonymous access to review RPC';
 END IF;
 BEGIN
   PERFORM public.lp_review_queue();
   RAISE EXCEPTION 'Unauthenticated queue unexpectedly succeeded';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
 BEGIN
   PERFORM public.lp_review_decide('invalid','invalid','hold',NULL,'[]'::jsonb);
   RAISE EXCEPTION 'Unauthenticated decision unexpectedly succeeded';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $$;
