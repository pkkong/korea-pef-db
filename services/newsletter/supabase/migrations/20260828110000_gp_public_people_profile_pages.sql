ALTER TABLE public.gp_public_pages
    DROP CONSTRAINT IF EXISTS gp_public_pages_page_path_check;

ALTER TABLE public.gp_public_pages
    ADD CONSTRAINT gp_public_pages_page_path_check
    CHECK (
        page_path IN ('market.html', 'gps.html')
        OR page_path ~ '^gp-[0-9]+\.html$'
        OR page_path ~ '^person-[0-9]+\.html$'
    );
