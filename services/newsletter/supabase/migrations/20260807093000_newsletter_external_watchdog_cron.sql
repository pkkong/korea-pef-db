CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE SCHEMA IF NOT EXISTS vault;
CREATE EXTENSION IF NOT EXISTS pg_net WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS supabase_vault WITH SCHEMA vault;

CREATE SCHEMA IF NOT EXISTS newsletter_ops;

CREATE TABLE IF NOT EXISTS newsletter_ops.newsletter_external_watchdog_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_date DATE NOT NULL,
    dispatch_reason TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('queued', 'skipped_missing_token', 'failed_to_queue')),
    request_id BIGINT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE newsletter_ops.newsletter_external_watchdog_runs ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION newsletter_ops.newsletter_report_date_kst(now_at TIMESTAMPTZ DEFAULT NOW())
RETURNS DATE
LANGUAGE sql
STABLE
AS $$
    SELECT timezone('Asia/Seoul', now_at)::DATE;
$$;

CREATE OR REPLACE FUNCTION newsletter_ops.dispatch_newsletter_watchdog(
    dispatch_reason TEXT DEFAULT 'supabase_cron',
    requested_report_date DATE DEFAULT NULL
)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = newsletter_ops, public, extensions, net, vault
AS $$
DECLARE
    github_token TEXT;
    resolved_report_date DATE;
    github_request_id BIGINT;
BEGIN
    resolved_report_date := COALESCE(requested_report_date, newsletter_ops.newsletter_report_date_kst());

    SELECT decrypted_secret
      INTO github_token
      FROM vault.decrypted_secrets
     WHERE name = 'newsletter_github_actions_dispatch_token'
     LIMIT 1;

    IF github_token IS NULL OR btrim(github_token) = '' THEN
        INSERT INTO newsletter_ops.newsletter_external_watchdog_runs (
            report_date,
            dispatch_reason,
            status,
            error_message
        )
        VALUES (
            resolved_report_date,
            dispatch_reason,
            'skipped_missing_token',
            'Missing Supabase Vault secret: newsletter_github_actions_dispatch_token'
        );
        RETURN NULL;
    END IF;

    SELECT net.http_post(
        url := 'https://api.github.com/repos/pkkong/korea-pef-db/actions/workflows/newsletter-watchdog.yml/dispatches',
        headers := jsonb_build_object(
            'Authorization', 'Bearer ' || github_token,
            'Accept', 'application/vnd.github+json',
            'X-GitHub-Api-Version', '2022-11-28',
            'Content-Type', 'application/json',
            'User-Agent', 'kpef-newsletter-supabase-watchdog'
        ),
        body := jsonb_build_object(
            'ref', 'main',
            'inputs', jsonb_build_object(
                'report_date', resolved_report_date::TEXT,
                'dry_run', 'false'
            )
        )
    )
    INTO github_request_id;

    INSERT INTO newsletter_ops.newsletter_external_watchdog_runs (
        report_date,
        dispatch_reason,
        status,
        request_id
    )
    VALUES (
        resolved_report_date,
        dispatch_reason,
        'queued',
        github_request_id
    );

    RETURN github_request_id;
EXCEPTION
    WHEN OTHERS THEN
        INSERT INTO newsletter_ops.newsletter_external_watchdog_runs (
            report_date,
            dispatch_reason,
            status,
            error_message
        )
        VALUES (
            COALESCE(resolved_report_date, newsletter_ops.newsletter_report_date_kst()),
            COALESCE(dispatch_reason, 'supabase_cron'),
            'failed_to_queue',
            SQLERRM
        );
        RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION newsletter_ops.newsletter_report_date_kst(TIMESTAMPTZ) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION newsletter_ops.dispatch_newsletter_watchdog(TEXT, DATE) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON newsletter_ops.newsletter_external_watchdog_runs FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE VIEW newsletter_ops.newsletter_external_watchdog_recent_requests
AS
SELECT
    run.run_id,
    run.report_date,
    run.dispatch_reason,
    run.status,
    run.request_id,
    run.error_message,
    run.created_at,
    response.status_code,
    response.error_msg,
    response.timed_out,
    response.created AS response_created_at
FROM newsletter_ops.newsletter_external_watchdog_runs run
LEFT JOIN net._http_response response
  ON response.id = run.request_id;

REVOKE ALL ON newsletter_ops.newsletter_external_watchdog_recent_requests FROM PUBLIC, anon, authenticated;

DO $$
DECLARE
    existing_job RECORD;
BEGIN
    FOR existing_job IN
        SELECT jobid
          FROM cron.job
         WHERE jobname IN (
            'newsletter-external-watchdog-0905-kst',
            'newsletter-external-watchdog-0935-kst',
            'newsletter-external-watchdog-1005-kst',
            'newsletter-external-watchdog-1035-kst'
         )
    LOOP
        PERFORM cron.unschedule(existing_job.jobid);
    END LOOP;
END;
$$;

SELECT cron.schedule(
    'newsletter-external-watchdog-0905-kst',
    '5 0 * * *',
    $$SELECT newsletter_ops.dispatch_newsletter_watchdog('supabase_cron_0905_kst');$$
);

SELECT cron.schedule(
    'newsletter-external-watchdog-0935-kst',
    '35 0 * * *',
    $$SELECT newsletter_ops.dispatch_newsletter_watchdog('supabase_cron_0935_kst');$$
);

SELECT cron.schedule(
    'newsletter-external-watchdog-1005-kst',
    '5 1 * * *',
    $$SELECT newsletter_ops.dispatch_newsletter_watchdog('supabase_cron_1005_kst');$$
);

SELECT cron.schedule(
    'newsletter-external-watchdog-1035-kst',
    '35 1 * * *',
    $$SELECT newsletter_ops.dispatch_newsletter_watchdog('supabase_cron_1035_kst');$$
);
