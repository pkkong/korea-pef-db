# Project Lead Control Center

Last updated: 2026-06-08 KST

이 문서는 Project Lead가 현재 프로젝트 상태를 잃지 않기 위한 운영판이다. 새 채팅방, 서브에이전트, 별도 담당자가 작업을 시작할 때는 먼저 이 문서를 읽고, 작업이 끝나면 필요한 변경을 여기에 반영한다.

## Current Public Product

- Public site: `https://pkkong.github.io/kpef-newsletter/`
- Source repo: `pkkong/korea-pef-db`
- Public mirror repo: `pkkong/kpef-newsletter`, branch `gh-pages`
- Navigation source change verified: `998acb2 Hide Wiki from public navigation`
- Public deploy verified for navigation: `dfa868b`
- Public bottom navigation: `브리프 / LP / GP`
- Wiki is hidden from public navigation until the user re-plans it.

## Service Ownership

- Newsletter / Brief: daily clipping, article classification, tags, search, publisher logos, archive, email-readiness. The user has moved active newsletter quality work to a separate chat; this project must still keep shared rules and integration checks current here.
- LP: institution directory, LP profiles, official notice monitor, notice lifecycle, selected GP links, LP logo quality.
- GP / Market: GP directory, GP profiles, market statistics, people links, GP logo quality.
- Wiki: currently not a public navigation item. Do not expand or polish Wiki unless the user explicitly reopens Wiki planning.
- Verification / Deploy: source build, static bundle, frontend checker, public URL verification, commit/push/deploy status.

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

Build integrated site bundle:

```bash
python3 scripts/build_site_bundle.py --date YYYY-MM-DD --services newsletter,lp,gp,wiki --archive-limit 30
```

Frontend contract check:

```bash
python3 scripts/check_public_frontend.py
```

Publish to GitHub Pages:

```bash
services/newsletter/scripts/publish_newsletter_pages_local.sh --date YYYY-MM-DD --skip-generate
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
- If deploy happened, verify `health.json` and at least `index.html`, `lp-notices.html`, `gps.html`, `db.html` from the public URL after CDN cache updates.

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
- `public/` may contain generated or stale static files. Public deployment source is the generated bundle under `services/newsletter/deploy/site/` and the `gh-pages` mirror.
- Newsletter classification and tag quality remain active quality risks. Any classification logic change should add title-based regression tests in `services/newsletter/tests/test_daily_news_logic.py`.
- LP notice lifecycle and business-card grouping remain active quality risks. Do not split one LP business into multiple cards for 공고/서류심사/선정결과 unless it is truly a separate 사업.
- Wiki should not be shown in public navigation until the user reopens Wiki planning.

## Project Lead Closeout Checklist

- Was the user correction converted into a durable rule when needed?
- Were service ownership and forbidden files clear?
- Were generated artifacts produced from source rather than hand-edited?
- Were tests/build/public checks run and reported?
- Was the deploy status reported separately from source commit status?
- Are remaining risks written down instead of left in chat memory?
