-- A new public page artifact must create a new snapshot even when the FSS
-- source file and reporting period are unchanged. The old uniqueness rule
-- silently retained stale page content after a transformation change.
ALTER TABLE public.gp_public_snapshots
    DROP CONSTRAINT IF EXISTS gp_public_snapshots_reporting_period_source_sha256_key;
