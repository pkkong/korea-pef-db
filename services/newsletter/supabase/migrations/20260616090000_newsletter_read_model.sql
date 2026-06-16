CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION public.newsletter_set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS public.newsletter_sources (
    source_code TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    locator TEXT NOT NULL,
    publisher TEXT,
    homepage_url TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.newsletter_runs (
    run_id TEXT PRIMARY KEY,
    run_date DATE NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'published', 'failed', 'skipped')),
    discovered_count INTEGER NOT NULL DEFAULT 0,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    relevant_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.newsletter_articles (
    article_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    normalized_url TEXT NOT NULL UNIQUE,
    source_url TEXT NOT NULL,
    source_domain TEXT,
    publisher TEXT,
    title TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    summary_text TEXT,
    summary_lines TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    section TEXT NOT NULL DEFAULT 'Market',
    sub_category TEXT,
    raw_section TEXT,
    source_icon_url TEXT,
    source_icon_style TEXT,
    tag_version TEXT,
    gp_names TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    lp_names TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    search_terms TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_newsletter_articles_section
    ON public.newsletter_articles(section);

CREATE INDEX IF NOT EXISTS idx_newsletter_articles_published_at
    ON public.newsletter_articles(published_at);

CREATE TABLE IF NOT EXISTS public.newsletter_article_tags (
    article_id UUID NOT NULL REFERENCES public.newsletter_articles(article_id) ON DELETE CASCADE,
    tag_type TEXT NOT NULL,
    tag_value TEXT NOT NULL,
    tag_source TEXT NOT NULL DEFAULT 'archive',
    confidence NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (article_id, tag_type, tag_value, tag_source)
);

CREATE TABLE IF NOT EXISTS public.newsletter_article_entities (
    article_id UUID NOT NULL REFERENCES public.newsletter_articles(article_id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('GP', 'LP', 'Person', 'Company', 'Topic')),
    entity_name TEXT NOT NULL,
    entity_ref TEXT,
    link_source TEXT NOT NULL DEFAULT 'archive',
    confidence NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (article_id, entity_type, entity_name, link_source)
);

CREATE TABLE IF NOT EXISTS public.newsletter_issues (
    issue_date DATE PRIMARY KEY,
    visible_date TEXT,
    basis TEXT,
    status TEXT NOT NULL DEFAULT 'published'
        CHECK (status IN ('draft', 'published', 'archived')),
    article_count INTEGER NOT NULL DEFAULT 0,
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_run_id TEXT REFERENCES public.newsletter_runs(run_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.newsletter_issue_articles (
    issue_date DATE NOT NULL REFERENCES public.newsletter_issues(issue_date) ON DELETE CASCADE,
    article_id UUID NOT NULL REFERENCES public.newsletter_articles(article_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL DEFAULT 0,
    section_order INTEGER NOT NULL DEFAULT 999,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (issue_date, article_id)
);

CREATE INDEX IF NOT EXISTS idx_newsletter_issue_articles_issue_rank
    ON public.newsletter_issue_articles(issue_date DESC, rank ASC);

DROP TRIGGER IF EXISTS set_newsletter_sources_updated_at ON public.newsletter_sources;
CREATE TRIGGER set_newsletter_sources_updated_at
BEFORE UPDATE ON public.newsletter_sources
FOR EACH ROW EXECUTE FUNCTION public.newsletter_set_updated_at();

DROP TRIGGER IF EXISTS set_newsletter_runs_updated_at ON public.newsletter_runs;
CREATE TRIGGER set_newsletter_runs_updated_at
BEFORE UPDATE ON public.newsletter_runs
FOR EACH ROW EXECUTE FUNCTION public.newsletter_set_updated_at();

DROP TRIGGER IF EXISTS set_newsletter_articles_updated_at ON public.newsletter_articles;
CREATE TRIGGER set_newsletter_articles_updated_at
BEFORE UPDATE ON public.newsletter_articles
FOR EACH ROW EXECUTE FUNCTION public.newsletter_set_updated_at();

DROP TRIGGER IF EXISTS set_newsletter_issues_updated_at ON public.newsletter_issues;
CREATE TRIGGER set_newsletter_issues_updated_at
BEFORE UPDATE ON public.newsletter_issues
FOR EACH ROW EXECUTE FUNCTION public.newsletter_set_updated_at();

DROP TRIGGER IF EXISTS set_newsletter_issue_articles_updated_at ON public.newsletter_issue_articles;
CREATE TRIGGER set_newsletter_issue_articles_updated_at
BEFORE UPDATE ON public.newsletter_issue_articles
FOR EACH ROW EXECUTE FUNCTION public.newsletter_set_updated_at();

ALTER TABLE public.newsletter_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.newsletter_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.newsletter_articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.newsletter_article_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.newsletter_article_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.newsletter_issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.newsletter_issue_articles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public can read active newsletter sources" ON public.newsletter_sources;
CREATE POLICY "Public can read active newsletter sources"
ON public.newsletter_sources
FOR SELECT
USING (is_active = TRUE);

DROP POLICY IF EXISTS "Public can read published newsletter issues" ON public.newsletter_issues;
CREATE POLICY "Public can read published newsletter issues"
ON public.newsletter_issues
FOR SELECT
USING (status = 'published');

DROP POLICY IF EXISTS "Public can read published newsletter issue articles" ON public.newsletter_issue_articles;
CREATE POLICY "Public can read published newsletter issue articles"
ON public.newsletter_issue_articles
FOR SELECT
USING (
    EXISTS (
        SELECT 1
        FROM public.newsletter_issues issue
        WHERE issue.issue_date = newsletter_issue_articles.issue_date
          AND issue.status = 'published'
    )
);

DROP POLICY IF EXISTS "Public can read articles in published newsletter issues" ON public.newsletter_articles;
CREATE POLICY "Public can read articles in published newsletter issues"
ON public.newsletter_articles
FOR SELECT
USING (
    EXISTS (
        SELECT 1
        FROM public.newsletter_issue_articles issue_article
        JOIN public.newsletter_issues issue
          ON issue.issue_date = issue_article.issue_date
        WHERE issue_article.article_id = newsletter_articles.article_id
          AND issue.status = 'published'
    )
);

DROP POLICY IF EXISTS "Public can read tags in published newsletter issues" ON public.newsletter_article_tags;
CREATE POLICY "Public can read tags in published newsletter issues"
ON public.newsletter_article_tags
FOR SELECT
USING (
    EXISTS (
        SELECT 1
        FROM public.newsletter_issue_articles issue_article
        JOIN public.newsletter_issues issue
          ON issue.issue_date = issue_article.issue_date
        WHERE issue_article.article_id = newsletter_article_tags.article_id
          AND issue.status = 'published'
    )
);

DROP POLICY IF EXISTS "Public can read entities in published newsletter issues" ON public.newsletter_article_entities;
CREATE POLICY "Public can read entities in published newsletter issues"
ON public.newsletter_article_entities
FOR SELECT
USING (
    EXISTS (
        SELECT 1
        FROM public.newsletter_issue_articles issue_article
        JOIN public.newsletter_issues issue
          ON issue.issue_date = issue_article.issue_date
        WHERE issue_article.article_id = newsletter_article_entities.article_id
          AND issue.status = 'published'
    )
);

CREATE OR REPLACE VIEW public.newsletter_public_issue_articles
WITH (security_invoker = true)
AS
SELECT
    issue.issue_date,
    COALESCE(issue.visible_date, issue.issue_date::TEXT) AS visible_date,
    issue.basis,
    issue.status AS issue_status,
    issue.article_count,
    issue.published_at,
    issue_article.rank,
    issue_article.section_order,
    article.article_id,
    article.normalized_url,
    article.source_url,
    article.source_domain,
    article.publisher,
    article.title,
    article.published_at AS article_published_at,
    article.summary_text,
    article.summary_lines,
    article.section,
    article.sub_category,
    article.raw_section,
    article.source_icon_url,
    article.source_icon_style,
    article.tag_version,
    article.gp_names,
    article.lp_names,
    article.search_terms
FROM public.newsletter_issue_articles issue_article
JOIN public.newsletter_issues issue
  ON issue.issue_date = issue_article.issue_date
JOIN public.newsletter_articles article
  ON article.article_id = issue_article.article_id
WHERE issue.status = 'published';

GRANT USAGE ON SCHEMA public TO anon, authenticated;
GRANT SELECT ON public.newsletter_sources TO anon, authenticated;
GRANT SELECT ON public.newsletter_articles TO anon, authenticated;
GRANT SELECT ON public.newsletter_article_tags TO anon, authenticated;
GRANT SELECT ON public.newsletter_article_entities TO anon, authenticated;
GRANT SELECT ON public.newsletter_issues TO anon, authenticated;
GRANT SELECT ON public.newsletter_issue_articles TO anon, authenticated;
GRANT SELECT ON public.newsletter_public_issue_articles TO anon, authenticated;
