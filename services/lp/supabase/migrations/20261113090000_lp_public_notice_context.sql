-- LP -> GP public contract (docs/data_operating_model.md).
-- Exposes only the reviewed public context the LP publisher stores under
-- program_state.data.public_notice_context: official selection results with
-- LP page links. No candidates, press-reported results or review state.
BEGIN;
CREATE OR REPLACE FUNCTION public.lp_public_notice_context()
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, lp_program_private
AS $$
  SELECT s.data -> 'public_notice_context'
  FROM lp_program_private.program_state s
  WHERE s.id = 1 AND jsonb_typeof(s.data -> 'public_notice_context') = 'object';
$$;
REVOKE ALL ON FUNCTION public.lp_public_notice_context() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.lp_public_notice_context() TO anon, authenticated, service_role;
COMMIT;
