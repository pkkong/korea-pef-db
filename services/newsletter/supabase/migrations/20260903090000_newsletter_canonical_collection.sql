-- Newsletter collection data is private operational data. The public
-- newsletter_* read model remains a separately published projection.

CREATE TABLE IF NOT EXISTS public.newsletter_canonical_sources (
    source_code TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    locator TEXT NOT NULL,
    publisher TEXT,
    homepage_url TEXT,
    article_url_regex TEXT,
    must_contain TEXT,
    allowed_publishers TEXT,
    default_tags TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.newsletter_canonical_runs (
    run_id TEXT PRIMARY KEY,
    run_date DATE NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    discovered_count INTEGER NOT NULL DEFAULT 0,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    relevant_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS public.newsletter_canonical_documents (
    news_id BIGINT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES public.newsletter_canonical_runs(run_id),
    source_code TEXT NOT NULL REFERENCES public.newsletter_canonical_sources(source_code),
    source_url TEXT NOT NULL,
    normalized_source_url TEXT NOT NULL UNIQUE,
    source_domain TEXT,
    publisher TEXT,
    title TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    discovered_at TEXT NOT NULL,
    fetched_at TIMESTAMPTZ,
    document_type TEXT NOT NULL DEFAULT 'article',
    language_code TEXT NOT NULL DEFAULT 'ko',
    raw_html_path TEXT,
    meta_description TEXT,
    excerpt_text TEXT,
    body_text TEXT,
    content_hash TEXT,
    relevance_score NUMERIC NOT NULL DEFAULT 0,
    relevance_label TEXT NOT NULL DEFAULT 'review',
    comment_text TEXT,
    review_status TEXT NOT NULL DEFAULT 'auto',
    is_pe_relevant BOOLEAN NOT NULL DEFAULT FALSE,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_newsletter_canonical_documents_source_code
    ON public.newsletter_canonical_documents(source_code);
CREATE INDEX IF NOT EXISTS idx_newsletter_canonical_documents_published_at
    ON public.newsletter_canonical_documents(published_at);
CREATE INDEX IF NOT EXISTS idx_newsletter_canonical_documents_relevant
    ON public.newsletter_canonical_documents(is_pe_relevant, relevance_score);

CREATE TABLE IF NOT EXISTS public.newsletter_canonical_tags (
    tag_id BIGINT PRIMARY KEY,
    news_id BIGINT NOT NULL REFERENCES public.newsletter_canonical_documents(news_id) ON DELETE CASCADE,
    tag_type TEXT NOT NULL,
    tag_value TEXT NOT NULL,
    tag_source TEXT NOT NULL,
    confidence NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (news_id, tag_type, tag_value, tag_source)
);

CREATE INDEX IF NOT EXISTS idx_newsletter_canonical_tags_news_id
    ON public.newsletter_canonical_tags(news_id);
CREATE INDEX IF NOT EXISTS idx_newsletter_canonical_tags_type_value
    ON public.newsletter_canonical_tags(tag_type, tag_value);

CREATE TABLE IF NOT EXISTS public.newsletter_canonical_entity_links (
    link_id BIGINT PRIMARY KEY,
    news_id BIGINT NOT NULL REFERENCES public.newsletter_canonical_documents(news_id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_ref TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    matched_alias TEXT,
    match_field TEXT,
    link_source TEXT NOT NULL,
    confidence NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (news_id, entity_type, entity_ref, matched_alias, match_field, link_source)
);

CREATE INDEX IF NOT EXISTS idx_newsletter_canonical_entity_links_news_id
    ON public.newsletter_canonical_entity_links(news_id);
CREATE INDEX IF NOT EXISTS idx_newsletter_canonical_entity_links_type_ref
    ON public.newsletter_canonical_entity_links(entity_type, entity_ref);

DROP TRIGGER IF EXISTS set_newsletter_canonical_sources_updated_at ON public.newsletter_canonical_sources;
CREATE TRIGGER set_newsletter_canonical_sources_updated_at
BEFORE UPDATE ON public.newsletter_canonical_sources
FOR EACH ROW EXECUTE FUNCTION public.newsletter_set_updated_at();

DROP TRIGGER IF EXISTS set_newsletter_canonical_documents_updated_at ON public.newsletter_canonical_documents;
CREATE TRIGGER set_newsletter_canonical_documents_updated_at
BEFORE UPDATE ON public.newsletter_canonical_documents
FOR EACH ROW EXECUTE FUNCTION public.newsletter_set_updated_at();

ALTER TABLE public.newsletter_canonical_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.newsletter_canonical_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.newsletter_canonical_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.newsletter_canonical_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.newsletter_canonical_entity_links ENABLE ROW LEVEL SECURITY;

-- The service role bypasses RLS. Do not add anonymous or authenticated
-- policies: raw bodies, review state, and source credentials are not public.

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'newsletter-raw',
    'newsletter-raw',
    FALSE,
    10485760,
    ARRAY['text/html', 'application/xhtml+xml']
)
ON CONFLICT (id) DO UPDATE
SET
    public = EXCLUDED.public,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;
