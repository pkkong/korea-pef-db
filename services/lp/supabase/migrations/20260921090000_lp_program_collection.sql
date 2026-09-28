-- LP program evidence is private; only validated rendered pages are readable.
BEGIN;
CREATE SCHEMA IF NOT EXISTS lp_program_private;
REVOKE ALL ON SCHEMA lp_program_private FROM PUBLIC, anon, authenticated;
CREATE TABLE IF NOT EXISTS lp_program_private.collection_runs (
  run_id text PRIMARY KEY,
  collected_at timestamptz NOT NULL DEFAULT now(),
  institution text NOT NULL,
  report jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS lp_program_private.documents (
  source_url text NOT NULL,
  content_hash text NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now(),
  document jsonb NOT NULL,
  PRIMARY KEY(source_url, content_hash)
);
CREATE TABLE IF NOT EXISTS lp_program_private.program_state (
  id integer PRIMARY KEY CHECK(id=1),
  updated_at timestamptz NOT NULL DEFAULT now(),
  data jsonb NOT NULL,
  pages jsonb NOT NULL,
  run_id text NOT NULL REFERENCES lp_program_private.collection_runs(run_id)
);
CREATE OR REPLACE FUNCTION public.lp_program_page(page_name text)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, lp_program_private
AS $$
  SELECT jsonb_build_object('page_html', s.pages ->> page_name, 'run_id', s.run_id)
  FROM lp_program_private.program_state s
  WHERE s.id=1 AND page_name ~ '^[a-zA-Z0-9_-]+\.html$' AND s.pages ? page_name;
$$;
REVOKE ALL ON FUNCTION public.lp_program_page(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.lp_program_page(text) TO anon, authenticated, service_role;
COMMIT;
