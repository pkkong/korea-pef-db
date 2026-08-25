CREATE TABLE IF NOT EXISTS public.gp_public_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    reporting_period TEXT NOT NULL,
    as_of_date DATE NOT NULL,
    source_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK (char_length(source_sha256) = 64),
    fund_count INTEGER NOT NULL CHECK (fund_count > 0),
    primary_gp_count INTEGER NOT NULL CHECK (primary_gp_count > 0),
    commitment_amount_krw_mn NUMERIC NOT NULL CHECK (commitment_amount_krw_mn > 0),
    status TEXT NOT NULL DEFAULT 'staged'
        CHECK (status IN ('staged', 'published', 'retired')),
    generated_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (reporting_period, source_sha256)
);

CREATE TABLE IF NOT EXISTS public.gp_public_pages (
    snapshot_id TEXT NOT NULL REFERENCES public.gp_public_snapshots(snapshot_id) ON DELETE CASCADE,
    page_path TEXT NOT NULL CHECK (page_path IN ('market.html', 'gps.html')),
    page_html TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (char_length(content_sha256) = 64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (snapshot_id, page_path)
);

CREATE INDEX IF NOT EXISTS idx_gp_public_snapshots_published
    ON public.gp_public_snapshots(status, published_at DESC);

DROP TRIGGER IF EXISTS set_gp_public_snapshots_updated_at ON public.gp_public_snapshots;
CREATE TRIGGER set_gp_public_snapshots_updated_at
BEFORE UPDATE ON public.gp_public_snapshots
FOR EACH ROW EXECUTE FUNCTION public.newsletter_set_updated_at();

DROP TRIGGER IF EXISTS set_gp_public_pages_updated_at ON public.gp_public_pages;
CREATE TRIGGER set_gp_public_pages_updated_at
BEFORE UPDATE ON public.gp_public_pages
FOR EACH ROW EXECUTE FUNCTION public.newsletter_set_updated_at();

CREATE OR REPLACE FUNCTION public.publish_gp_public_snapshot(target_snapshot_id TEXT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    page_count INTEGER;
BEGIN
    SELECT count(*)
    INTO page_count
    FROM public.gp_public_pages
    WHERE snapshot_id = target_snapshot_id
      AND page_path IN ('market.html', 'gps.html');

    IF page_count <> 2 THEN
        RAISE EXCEPTION 'GP snapshot % must include market.html and gps.html before publication', target_snapshot_id;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.gp_public_snapshots
        WHERE snapshot_id = target_snapshot_id
    ) THEN
        RAISE EXCEPTION 'Unknown GP snapshot %', target_snapshot_id;
    END IF;

    UPDATE public.gp_public_snapshots
    SET status = 'retired'
    WHERE status = 'published'
      AND snapshot_id <> target_snapshot_id;

    UPDATE public.gp_public_snapshots
    SET status = 'published',
        published_at = NOW()
    WHERE snapshot_id = target_snapshot_id;
END;
$$;

ALTER TABLE public.gp_public_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gp_public_pages ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public can read published GP snapshots" ON public.gp_public_snapshots;
CREATE POLICY "Public can read published GP snapshots"
ON public.gp_public_snapshots
FOR SELECT
USING (status = 'published');

DROP POLICY IF EXISTS "Public can read pages from published GP snapshots" ON public.gp_public_pages;
CREATE POLICY "Public can read pages from published GP snapshots"
ON public.gp_public_pages
FOR SELECT
USING (
    EXISTS (
        SELECT 1
        FROM public.gp_public_snapshots snapshot
        WHERE snapshot.snapshot_id = gp_public_pages.snapshot_id
          AND snapshot.status = 'published'
    )
);

GRANT SELECT ON public.gp_public_snapshots TO anon, authenticated;
GRANT SELECT ON public.gp_public_pages TO anon, authenticated;
REVOKE ALL ON FUNCTION public.publish_gp_public_snapshot(TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.publish_gp_public_snapshot(TEXT) TO service_role;
