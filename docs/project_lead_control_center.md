# Project Lead Control Center

Last updated: 2026-06-15 KST

이 문서는 Project Lead가 현재 프로젝트 상태를 잃지 않기 위한 운영판이다. 새 채팅방, 서브에이전트, 별도 담당자가 작업을 시작할 때는 먼저 이 문서를 읽고, 작업이 끝나면 필요한 변경을 여기에 반영한다.

## Current Public Product

- Public site: `https://pkkong.github.io/kpef-newsletter/`
- Source repo: `pkkong/korea-pef-db`
- Public mirror repo: `pkkong/kpef-newsletter`, branch `gh-pages`
- Navigation source change verified: `998acb2 Hide Wiki from public navigation`
- Public deploy verified for navigation: `dfa868b`
- Latest public mirror deploy verified: `db45ac9` on 2026-06-15 KST
- Public bottom navigation: `브리프 / LP / GP`
- Wiki is hidden from public navigation until the user re-plans it.
- Operating model source of truth added on 2026-06-10:
  - Product/service boundaries: `docs/product_operating_model.md`
  - DB/public-view/build contract: `docs/data_operating_model.md`
- LP institution directory rule updated on 2026-06-09: direct GP selectors only. OCIO/위임형 공적기금은 `coverage_tier=ocio`, `display_enabled=0`으로 별도 pool에 두고 공개 출자기관 디렉토리와 일반 LP Notice 기본 화면에서 제외한다.
- LP public visibility rule updated on 2026-06-09: 공개 출자기관은 확인된 PE/VC/대체 출자공고·선정 이력이 있거나 사용자가 지정한 전략기관이어야 한다. KIC, 수협, 캠코는 전략기관 예외로 공개 유지한다. 그 외 이력 0건 기관은 후보 pool로 내린다.
- LP legal classification rule updated on 2026-06-09: 기관 분류는 자본시장법 시행령 제271조의14 및 제10조의 기관전용 사모집합투자기구 LP 적격 유형에 맞춘다. `legal_lp_category`와 `legal_lp_basis`는 법적 유형, `coverage_tier`와 `display_enabled`는 서비스 노출/중요도 기준이다.

## Service Ownership

- Newsletter / Brief: daily clipping, article classification, tags, search, publisher logos, archive, email-readiness. Active newsletter quality work has been moved by the user to a separate chat. This control center still owns shared product rules, source ownership boundaries, integration checks, deploy verification, and cross-service regressions.
- LP: institution directory, LP profiles, official notice monitor, notice lifecycle, selected GP links, LP logo quality.
- GP / Market: GP directory, GP profiles, market statistics, people links, GP logo quality.
- Wiki: currently not a public navigation item. Do not expand or polish Wiki unless the user explicitly reopens Wiki planning.
- Verification / Deploy: source build, static bundle, frontend checker, public URL verification, commit/push/deploy status.

## Active Assignment Board

- Current lead chat: LP Notice launch-quality improvement, LP/GP integration, build separation, public deploy readiness, and documentation discipline.
- Separate newsletter chat: newsletter classification/tag/search/logo/editorial quality. Do not duplicate newsletter edits here unless the user explicitly asks this chat to integrate or verify that work.
- Integration checkpoint for newsletter handoff: require a source diff, generated public pages, `services/newsletter/tests/test_daily_news_logic.py` result, brand icon check, and public URL smoke check before accepting newsletter changes into a deploy report.
- LP Notice current milestone: make `lp-official-notices.html`, `lp-notices.html`, and `lp-notice-*.html` work as a reliable business-level notice service, not a loose list of scraped rows. 2026-06-09 public deploy reduced public notice cards from 246 to 85 by excluding noisy candidate rows and tightening program/lifecycle grouping.
- LP directory current rule: 직접 GP/위탁운용사를 선정하는 기관만 공개 디렉토리에 표시한다. 산재보험기금·고용보험기금 등 OCIO 위임형 기금은 내부 pool로 분류하고, 별도 OCIO 서비스/탭을 기획하기 전까지 공개 기본 목록에는 섞지 않는다.
- LP classification basis: `legal_lp_category`는 자본시장법 체계상 법적 LP 유형이고, `core/policy/ocio/candidate`는 실제 공고, 선정 이력, OCIO 위임 여부, 사용자 지정 전략기관 여부를 반영한 서비스 운영 등급이다. 후보성 기관 일반정보만으로는 공개하지 않는다.
- Wiki state: hidden from public navigation. No Wiki UI/content work unless re-planned.
- Operating-system milestone: freeze service boundaries before adding more LP/GP/Brief features. New ideas go to `docs/service_quality_backlog.md` unless they have a service owner, data source, public-view contract, and verification path.

## Project Lead Execution Contract

- Start substantial work by reading this file and stating the service split.
- If a service is handed to another chat, write the handoff state here before continuing other work.
- Convert repeated user corrections into durable rules in `docs/agent_operating_briefs.md`, `docs/design_system.md`, or this file in the same work cycle.
- Do not report a service as done until source changes, build output, verification, and deploy status are separately known.
- Keep the Project Lead available for coordination. Long logo/data/backfill/QA sweeps should go to a Worker or Verifier instead of blocking this chat.

## Non-Negotiable Product Decisions

- Treat repeated user corrections as instruction-management failures.
- Public UI must look like one product, not separate apps. Benchmark quality against InnoForest-style data directories.
- Do not expose operator/internal wording: `관리자`, `자동 생성`, `source/evidence`, `AUM proxy`, `검토 대기`, `보강 필요`, `AI가 만든 듯한 설명문`.
- Use public view taxonomy:
  - news: flat article list
  - LP/GP directories: table-like row directory
  - LP/GP details: profile detail
  - LP notices: row-card notice workflow
  - Wiki: document view, but hidden for now
- Do not hand-edit generated deploy/public HTML as the source of truth. Fix source renderers, rebuild, verify, then publish.
- If the worktree is dirty, stage only files for the current task.

## Build And Deploy Commands

Compile check:

```bash
python3 -m py_compile scripts/build_service_site.py services/newsletter/src/build_newsletter_deploy.py services/newsletter/src/gp_service_pages.py services/newsletter/src/pef_wiki_pages.py scripts/check_public_frontend.py
```

Build active public site bundle:

```bash
python3 scripts/build_site_bundle.py --date YYYY-MM-DD --services newsletter,lp,gp --archive-limit 30
```

Build newsletter-only public bundle for daily GitHub Actions:

```bash
python3 scripts/build_newsletter_bundle.py --date YYYY-MM-DD --archive-limit 30
```

Build Wiki only when explicitly re-planned:

```bash
python3 scripts/build_site_bundle.py --date YYYY-MM-DD --services wiki --archive-limit 30
```

Frontend contract check:

```bash
python3 scripts/check_public_frontend.py
```

Publish to GitHub Pages:

```bash
GitHub Actions → Deploy newsletter to GitHub Pages → Run workflow
```

Remote check after deploy:

```bash
python3 scripts/check_public_frontend.py --base-url https://pkkong.github.io/kpef-newsletter/
```

## Required Verification Before Reporting Done

- Python compile check passes.
- Integrated bundle build passes.
- `scripts/check_public_frontend.py` passes.
- Public major pages show bottom nav exactly `브리프 / LP / GP`.
- If UI changed, inspect mobile 390px and desktop 1280px or provide a clear reason if not done.
- If deploy happened, verify `health.json` and at least `index.html`, `lp-notices.html`, `gps.html`, and `market.html` from the public URL after CDN cache updates.

## Cross-Chat Handoff Template

Use this when another chat or subagent takes a service:

```text
Role:
Objective:
Owned files:
Forbidden files:
Current product decisions:
Known user corrections:
Required verification:
Expected output:
Commit/deploy expectation:
```

The receiving chat must not rely on conversation memory. It should read `AGENTS.md`, `docs/agent_operating_briefs.md`, `docs/design_system.md`, `docs/service_quality_backlog.md`, and this control center first.

## Current Known Risks

- The repo worktree often contains unrelated dirty changes from prior service work. Do not reset or revert them without explicit user instruction.
- Public deployment source is the generated bundle under `services/newsletter/deploy/site/` and the `gh-pages` mirror. The legacy root `public/` directory is ignored generated output and must not be committed.
- Newsletter classification and tag quality remain active quality risks. Any classification logic change should add title-based regression tests in `services/newsletter/tests/test_daily_news_logic.py`.
- Newsletter collection is not complete until GitHub Actions public mirror push and public `health.json`/`archive.json` verification pass. Missing or weak publisher icons should create a report and backlog item, but must not block the daily public newsletter unless `NEWSLETTER_STRICT_ICON_CHECK=1` is explicitly set.
- Daily newsletter scheduling does not rely on a single GitHub cron slot. The primary target is 08:30 KST, with retry windows at 09:00, 09:30, 10:00, and 11:00 KST. Scheduled runs first check public `health.json`; if today's issue is already published with articles, the run skips collection/build/publish to avoid duplicate work.
- Daily newsletter status source is `exports/daily_news/ops_status/newsletter_ops_status_latest.md`. Check it before diagnosing newsletter incidents; it separates collection, local build, public publish, hard failures, and soft warnings.
- LP notice lifecycle and business-card grouping remain active quality risks. Do not split one LP business into multiple cards for 공고/서류심사/선정결과 unless it is truly a separate 사업. Current public gate intentionally excludes the noisy `vcs_investment_notice` candidate feed until the parser is reviewed.
- Wiki should not be shown in public navigation until the user reopens Wiki planning.

## Latest Verification Notes

- 2026-06-09 LP deploy: `python3 scripts/build_site_bundle.py --date 2026-06-09 --services lp --archive-limit 30` generated `lp_monitor_count=85` and `lp_notice_detail_page_count=85`.
- Public mirror push: `c5db810` legacy local deploy.
- Remote smoke check passed after Pages propagation: `python3 scripts/check_public_frontend.py --base-url https://pkkong.github.io/kpef-newsletter/`.
- Public `health.json` confirms `lp_monitor_count=85`; `lp-official-notices.html` no longer contains `벤처투자포털`, `벤처투자마트`, `동의하지 않은 경우`, `가치형이나 고배당형`, or the bad `2026년 국민연금기금 벤처펀드 1호` title.
- 2026-06-09 OCIO split deploy: `e90074d` legacy local deploy. Public `health.json` confirms `lp_profile_page_count=30` and `lp_monitor_count=80`; `lp-notices.html` and `lp-official-notices.html` no longer contain OCIO/위임형 기금 names such as 고용보험기금, 산재보험기금, 주택도시기금, 예금보험기금.
- 2026-06-09 LP public visibility deploy: `f75d6bb` legacy local deploy. Public mirror branch confirms `lp_profile_page_count=25`; KIC, 수협, 캠코 remain public, while 신용보증기금, 기술보증기금, 한국콘텐츠진흥원, 영화진흥위원회, 국민체육진흥공단 are hidden as candidate pool until PE/VC 출자공고·선정 이력이 확인된다.
- 2026-06-09 LP legal classification deploy: `e8d3ed2` legacy local deploy. Public mirror branch confirms `lp_profile_page_count=25` and LP detail pages now prioritize `legal_lp_category` based on 자본시장법 시행령 제271조의14 and 제10조. GitHub Pages CDN may serve the prior `14:43:32` build briefly after push; verify branch content first if public URL lags.
- 2026-06-10 operating model reset: service boundaries and data/public-view contracts are documented in `docs/product_operating_model.md` and `docs/data_operating_model.md`. Default active public build should be `newsletter,lp,gp`; Wiki remains explicit-only until replanned.
- 2026-06-11 newsletter deploy incident resolved: the legacy local scheduler generated the 2026-06-11 brief but stopped before public push because `check_newsletter_brand_icons.py --fail-on-missing` reported one missing `www.asiae.co.kr` icon. Final public mirror push `ae5d291` verified public `health.json report_date=2026-06-11 article_count=30` and archive article count 30.
- 2026-06-11 newsletter operations status added: `services/newsletter/src/newsletter_ops_status.py` writes JSON/Markdown status under `exports/daily_news/ops_status/` for diagnostics. The latest 2026-06-11 status was `ok`, public date 2026-06-11, public articles 30, icon issues 0, tag conflicts 0, soft warning `source warning_count=19`.
- 2026-06-12 NotebookLM readiness was an experiment, not an operating dependency. The local ignored `.venv/` and global Codex MCP server registration were removed during the 2026-06-13 GitHub-only reset. If NotebookLM is tested again, keep it as an optional audit/summary-assist path with an explicit `NEWSLETTER_NLM_BIN`; do not make it a hard dependency for 08:30 publication.
- 2026-06-12 newsletter AI safety hardening: AI enrichment now preserves `section_suggestion_raw` and `suggestion_status`, fills one enrichment row per review queue row, and validation fails external AI output that is partial, missing category suggestions, invalid, or has no usable public summary. Public archive validation blocks internal AI field leakage and unusable `summaryLines`. `NEWSLETTER_AI_APPLY_SECTIONS=1` can apply validated AI section suggestions to public article sections, but default remains audit-only until NotebookLM backtests pass. Local newsletter-only bundle for 2026-06-12 passes `validate_daily_news_pipeline.py`, `check_public_frontend.py`, and `newsletter_ops_status.py --no-public`.
- 2026-06-12 newsletter AI backtest added: `services/newsletter/src/backtest_newsletter_ai.py` runs AI enrichment across existing review queues and writes `exports/daily_news/ai_backtests/daily_news_ai_backtest_latest.md/.csv`. The backtest report includes provider, preflight status, NLM path/profile, Notebook ID presence, review/article counts, status counts, and conflict/invalid/missing rows. Apply-mode bug fixed: when `NEWSLETTER_AI_APPLY_SECTIONS=1`, public `subCategory` is recalculated after AI section override.
- 2026-06-12 newsletter classification golden set: `services/newsletter/data/news_classification_golden.csv` and `services/newsletter/src/evaluate_news_classification_goldens.py` now pin recurring category mistakes. Golden cases cover 국민성장펀드-vs-GP fundraising, AI-themed GP fundraise, private credit market commentary, GP stake market structure, court/governance disputes, KIC CIO LP governance, and specific company investment/funding deals. Local golden evaluation passes 12/12, and the full newsletter logic test now passes 96 checks. Recent local-rule AI backtest for 2026-06-05~2026-06-12 passes across 8 dates with 170 review rows, 170 AI articles, 0 conflicts, 0 invalid, 0 missing, 0 missing summaries. Public 3-line summaries are fixed as investment memo style, not Newneek-style explanatory copy.
- 2026-06-13 NotebookLM auth and quota status was experimental: user approved the Google passkey flow in the CLI-launched Chrome window, and a working NotebookLM notebook was created: `KPEF Newsletter AI QA` (`ef22886b-a01e-42b8-8f32-0280964477e4`) with source `KPEF Newsletter Classification Rules`. Empty notebooks cannot be queried. NotebookLM CLI wraps answers under `answer`, so `enrich_daily_news_ai.py` unwraps nested JSON. NotebookLM returned `RESOURCE_EXHAUSTED` during smoke queries, so do not use NotebookLM as a hard dependency for 08:30 publication; keep it audit/summary-assist only until quota behavior is stable and explicitly configured outside the repo.
- 2026-06-13 newsletter publish incident: legacy local collection exposed why Mac must not be an operating path. The operating reset removes local publisher and launchd paths. Primary daily generation/publish is GitHub Actions only. `.github/workflows/deploy-newsletter-pages.yml` has `schedule cron 30 23 * * *` for 08:30 KST, keeps manual `workflow_dispatch`, runs the daily pipeline across active sources, creates source audit and local-rule AI enrichment before building, validates public files, runs icon reporting without blocking on missing icons, pushes the public mirror, and verifies remote `health.json`/`archive.json`.
- 2026-06-13 re-audit: removed Windows Task Scheduler installer scripts, stopped validation from checking a local scheduled task, removed root `config/daily_news.env` fallback, moved dashboard preview/default public JSON paths from root `public/` to `services/newsletter/deploy/site/`, and made LP alias context fall back to maintained CSV when the local SQLite DB is absent.
- 2026-06-13 NotebookLM design correction: do not use NotebookLM as a stateless batch query API. If used again, create one date-specific notebook such as `KPEF Newsletter Review YYYY-MM-DD`, add classification rules and a daily article source pack as notebook sources, then ask one structured question for all articles. Cache by source pack fingerprint, cap NotebookLM to one review query per date, and keep failures out of the 08:30 publishing critical path.
- 2026-06-14 newsletter Actions hardening: a manual GitHub Actions rerun for 2026-06-14 reached the newsletter collection step but was cancelled after 10 minutes because the collection stage had no per-source progress output and an oversized candidate budget. `run_daily_news_pipeline.py` now prints source start/listing/done progress and supports `--candidate-limit-per-source`. The public workflow runs newsletter-only with `NEWSLETTER_LIMIT_PER_SOURCE=20`, `NEWSLETTER_CANDIDATE_LIMIT_PER_SOURCE=8`, and a 720-second collection timeout so daily publication does not silently hang before build/publish. The static build step skips remote brand-asset downloads in Actions via `NEWSLETTER_SKIP_BRAND_ASSET_DOWNLOADS=1`; logo completeness is a separate quality sweep, not a publication blocker.
- 2026-06-14 newsletter Actions validation fix: `validate_daily_news_pipeline.py` checks whether active Naver sources have credentials, so the static build/validation workflow step must receive `NAVER_CLIENT_ID` and `NAVER_CLIENT_SECRET` just like the collection step. Without that env, collection can succeed but validation fails before public publish.
- 2026-06-14 newsletter GitHub Actions publish verified: workflow run `27484616263` succeeded on source commit `398056a` and published public mirror commit `b7dccb9`. Public `health.json` confirms `report_date=2026-06-14`, `article_count=2`, and `archive.json` latest entry has 2 articles. The run discovered 946 candidates, fetched 265, selected 2, and icon check reported 0 issues. The low selected count is a clipping-quality follow-up, not a deploy failure.
- 2026-06-14 newsletter isolation refactor: daily GitHub Actions publication now uses `scripts/build_newsletter_bundle.py`, a newsletter-only builder that does not import LP, GP, Wiki, or the legacy `build_newsletter_deploy.py` monolith. `scripts/build_site_bundle.py` remains available for integrated builds but lazy-imports service builders only after service selection, so unselected LP/GP/Wiki import errors should not block newsletter-only builds.
- 2026-06-14 newsletter-only refactor deploy verified: source commit `966398b` passed GitHub Actions workflow run `27486984563` and published public mirror commit `ad48099`. Public `health.json` confirms `services=newsletter`, `report_date=2026-06-14`, `article_count=2`, and all LP/GP/Wiki counts are 0 for the newsletter-only bundle. Public `archive.json` latest entry is 2026-06-14 with 2 articles across 30 archive entries. Actions logs confirm the static build step calls `python3 scripts/build_newsletter_bundle.py --date "2026-06-14"` and public verification ended with `public_verify_status=ok`.
- 2026-06-14 final newsletter-only refactor verification: source commit `3203531` passed GitHub Actions workflow run `27487395440` and published public mirror commit `989c87e`. Public `health.json` confirms `built_at=2026-06-14T03:53:51+00:00`, `services=newsletter`, `report_date=2026-06-14`, `article_count=2`, and LP/GP/Wiki counts are 0. Public `archive.json` latest entry is 2026-06-14 with 2 articles across 30 archive entries. Logs confirm `scripts/build_newsletter_bundle.py` was used, `Daily news validation: OK`, icon issues 0, no `SyntaxWarning`, and public verification `public_verify_status=ok`.
- 2026-06-15 schedule delay incident: public site still showed 2026-06-14 at 11:05 KST because the scheduled GitHub Actions run for 2026-06-15 started late at 10:59 KST (`27519596935`). The run succeeded in 11m18s and published public mirror commit `0939c6e`; public `health.json` confirms `report_date=2026-06-15`, `article_count=26`, and `archive.json` latest entry has 26 articles. Workflow was hardened with retry cron windows and a public freshness guard so delayed/fallback scheduled runs skip if today's issue is already published.
- 2026-06-15 retry guard deploy verified: source commit `756105a` added 09:00, 09:30, 10:00, and 11:00 KST retry windows plus the public freshness guard. Manual workflow run `27520017415` on that commit succeeded in 11m1s and published public mirror commit `f928f81`; public `health.json` confirms `built_at=2026-06-15T02:24:34+00:00`, `report_date=2026-06-15`, `article_count=26`, `services=newsletter`, and LP/GP/Wiki counts are 0. Logs confirm `newsletter_freshness should_run=True reason=manual run`, `scripts/build_newsletter_bundle.py`, `Daily news validation: OK`, icon issues 0, and public verification `public_verify_status=ok`.
- 2026-06-15 newsletter duplicate root cause fixed: the Asia Economy article `https://www.asiae.co.kr/article/2026061211064410472` repeated across 2026-06-13, 2026-06-14, and 2026-06-15 because previous export dedupe only read local `exports/` files, while GitHub Actions starts with an empty local export directory. The daily pipeline now reads public `archive.json` as the previous-publication ledger, normalizes `view.asiae.co.kr` and `www.asiae.co.kr` article URLs to one canonical URL, and validation hard-fails if the current archive repeats a URL/title from an earlier report date. Because weekend publishing is active, Monday remains a normal 24-hour briefing window; weekend recovery belongs in a separate backfill/audit flow, not the daily publish window.
- 2026-06-15 duplicate guard deploy verified: source commit `56c1ba5` passed workflow run `27550021509` and published public mirror commit `6ff0966`. Actions generated `article_count=8`, validation reported `Daily news validation: OK`, icon issues 0, and the public site now confirms `health.json report_date=2026-06-15 article_count=8`. Public `archive.json` keeps `https://www.asiae.co.kr/article/2026061211064410472` only on 2026-06-13 and 2026-06-14; it is no longer present in the 2026-06-15 issue.
- 2026-06-15 cross-date archive dedupe verified: source commit `1ae979d` passed workflow run `27551001811`; public `health.json` confirms `report_date=2026-06-15`, `article_count=8`, and `built_at=2026-06-15T14:00:23+00:00`. Public `archive.json` now keeps `https://www.asiae.co.kr/article/2026061211064410472` only on the first publication date, 2026-06-13, and removes the duplicate from 2026-06-14 and 2026-06-15.

## Project Lead Closeout Checklist

- Was the user correction converted into a durable rule when needed?
- Were service ownership and forbidden files clear?
- Were generated artifacts produced from source rather than hand-edited?
- Were tests/build/public checks run and reported?
- Was the deploy status reported separately from source commit status?
- Are remaining risks written down instead of left in chat memory?
