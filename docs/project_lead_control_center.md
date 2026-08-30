# 프로젝트 리드 현재 상태판

최종 수정: 2026-08-28 KST

이 문서는 Project Lead가 현재 프로젝트 상태를 잃지 않기 위한 운영판이다. 새 채팅방, 서브에이전트, 별도 담당자가 작업을 시작할 때는 먼저 이 문서를 읽고, 작업이 끝나면 필요한 변경을 여기에 반영한다.

사용자가 이번 구조 정리 결과를 확인할 때는 먼저 `docs/refactor_closeout_2026-06-21.md`를 읽는다.

## 현재 공개 제품

- 뉴스레터 공식 앱: `https://kpef-newsletter.vercel.app`
- GitHub Pages 백업 미러: `https://pkkong.github.io/kpef-newsletter/`
- 원본 저장소: `pkkong/korea-pef-db`
- 공개 미러 저장소: `pkkong/kpef-newsletter`, branch `gh-pages`
- 공개 하단 메뉴: `브리프 / LP / GP`
- Wiki는 사용자가 다시 기획하기 전까지 공개 메뉴에서 숨긴다.
- 2026-06-17 기준 최신 GitHub Pages 미러 검증: GitHub Actions run `27692675935`가 source `40d6e5b`에서 성공했다. 공개 `health.json`은 `report_date=2026-06-17`, `article_count=17`, `services=newsletter`였다.
- 2026-06-17 기준 최신 Vercel 앱 검증: GitHub Actions run `27694685414`가 source `dbb2a9e`에서 성공했다. Vercel `health.json?refresh=1`은 `report_date=2026-06-17`, `article_count=17`, `issue_count=30`, `data_source=supabase`였다.
- 2026-06-17에 뉴스레터 UI 원본을 단일화했다. `services/newsletter/web/newsletter_ui.py`가 Vercel 앱과 GitHub Pages 미러가 함께 쓰는 HTML/CSS/JS 원본이다. Vercel 전용 Jinja template이나 `web/static/service.css`를 다시 만들면 회귀다.
- 2026-06-18에 뉴스레터 legacy deploy 파일을 정리했다. 큰 monolith였던 `services/newsletter/src/build_newsletter_deploy.py`는 LP 호환용 `services/lp/src/lp_legacy_service_pages.py`로 옮겼고, 뉴스레터 경로에는 `scripts/build_newsletter_bundle.py`로 위임하는 얇은 wrapper만 남긴다.
- 2026-06-21에 구조 계약 검사를 추가했다. `scripts/check_architecture_contracts.py`는 LP/GP/Wiki import 경계, newsletter-only/Vercel import 격리, workflow 역할 분리, generated output tracking 금지를 검사한다.
- 2026-06-21에 뉴스레터 workflow 상태 판단을 `services/newsletter/src/newsletter_public_status.py`로 모았다. workflow YAML에는 긴 inline Python을 넣지 않고 이 CLI를 호출한다.
- 2026-07-28에 뉴스레터 자동 발행을 안정 운영 모드로 전환했다. `Build newsletter mirror`의 routine schedule은 `NEWSLETTER_SOURCE_PROFILE=stable`을 사용해 핵심 Google/Naver 쿼리와 수동 클리핑만 수집한다. 전체 67개 소스는 수동 `source_profile=all` 실행으로만 돌린다. 수집은 collection soft deadline을 지나 충분한 원문을 확보하면 남은 느린 소스를 건너뛰고 발행을 계속해야 한다.
- 2026-08-07에 GitHub Actions/Pages 장애로 primary schedule과 GitHub 내부 watchdog이 모두 누락되는 리스크를 확인했다. 외부 복구 장치로 Supabase Cron migration `20260807093000_newsletter_external_watchdog_cron.sql`을 추가했다. Supabase Cron은 09:05, 09:35, 10:05, 10:35 KST에 GitHub `Newsletter publish watchdog` workflow를 깨운다. 이 기능은 GitHub Actions secret `NEWSLETTER_WATCHDOG_DISPATCH_TOKEN`을 `Apply newsletter Supabase migration` workflow가 Supabase Vault secret `newsletter_github_actions_dispatch_token`으로 저장해야 실제 dispatch가 된다.
- 2026-08-12에 09:05 KST external watchdog이 GitHub API TLS 검증 오류로 실패 메일을 보냈지만, 09:09 KST mirror build와 09:12 KST Supabase sync가 성공해 공개 뉴스레터는 정상 발행됐다. `Newsletter publish watchdog`은 GitHub API 조회/dispatch를 retry하고, 일시 API 오류는 실패 메일 대신 뒤의 watchdog 창에 맡기도록 soft-fail해야 한다.
- 2026-08-07에 Vercel production 앱이 404를 반환하는 회귀를 수정했다. 원인은 `services/newsletter/web/vercel.json`의 catch-all rewrite가 모든 요청을 `/index.py`로 넘긴 것이었다. Vercel Flask 앱은 `framework=flask` 설정만 유지하고, 전체 요청을 `/index.py`로 rewrite하면 안 된다. `services/newsletter/scripts/check_vercel_supabase_readiness.py`와 `services/newsletter/web/tests/test_newsletter_data.py`가 이 회귀를 검사한다.
- 2026-06-21부터 LP, GP, Wiki는 공통 유틸을 `services/shared/src/`에서 가져와야 한다. `services.newsletter.src.*` 직접 import는 금지한다.
- Vercel archive 계약은 유지한다. Vercel은 날짜 이동용 `newsletter_issues`와 기사 row용 `newsletter_public_issue_articles`를 함께 읽어야 하고, 빈 issue와 `section_order=0`을 보존해야 한다.
- Vercel/Supabase 운영 경로는 다음과 같이 고정한다. `services/newsletter/web/`는 Vercel Flask 앱, `services/newsletter/supabase/`는 public read model schema, `services/newsletter/src/sync_newsletter_supabase.py`는 검증된 archive를 Supabase로 옮기는 동기화 코드다.
- 운영 기준 문서:
  - 제품/서비스 책임선: `docs/product_operating_model.md`
  - DB/public-view/build 계약: `docs/data_operating_model.md`
  - 코드로 강제되는 구조 계약: `docs/architecture_contracts.md`
- 2026-06-09에 LP 기관 디렉토리 기준을 직접 GP/위탁운용사 선정 기관으로 고정했다. OCIO/위임형 공적기금은 `coverage_tier=ocio`, `display_enabled=0`으로 별도 pool에 두고 공개 출자기관 디렉토리와 일반 LP Notice 기본 화면에서 제외한다.
- 2026-06-09에 LP 공개 노출 기준을 정했다. 공개 출자기관은 확인된 PE/VC/대체 출자공고·선정 이력이 있거나 사용자가 지정한 전략기관이어야 한다. KIC, 수협, 캠코는 전략기관 예외로 공개 유지한다. 그 외 이력 0건 기관은 후보 pool로 내린다.
- 2026-06-09에 LP 법적 분류 기준을 정했다. 기관 분류는 자본시장법 시행령 제271조의14 및 제10조의 기관전용 사모집합투자기구 LP 적격 유형에 맞춘다. `legal_lp_category`와 `legal_lp_basis`는 법적 유형, `coverage_tier`와 `display_enabled`는 서비스 노출/중요도 기준이다.

## 서비스 책임

- 뉴스레터 / 브리프: 매일 뉴스 클리핑, 기사 분류, 태그, 검색, 언론사 로고, archive, email-readiness를 담당한다. 뉴스레터 품질 작업은 사용자가 별도 채팅방으로 넘긴 상태다. 이 상태판은 공통 제품 규칙, source 경계, 통합 검증, 배포 검증, cross-service 회귀만 관리한다.
- LP: 출자기관 디렉토리, LP 프로필, 공식 공고 모니터, 공고 lifecycle, 선정 GP 연결, LP 로고 품질을 담당한다.
- GP / Market: GP 디렉토리, GP 프로필, 시장 통계, People/news 연결, GP 로고 품질을 담당한다.
- Wiki: 현재 공개 메뉴가 아니다. 사용자가 Wiki 기획을 다시 열기 전까지 확장하거나 polish하지 않는다.
- 검증 / 배포: source build, static bundle, frontend checker, 공개 URL 검증, commit/push/deploy 상태를 담당한다.

## 현재 작업판

- 이 채팅방의 현재 책임: LP Notice 출시 품질, LP/GP 통합, 빌드 분리, 공개 배포 준비성, 문서 운영 기준을 관리한다.
- 별도 뉴스레터 채팅방의 현재 책임: 뉴스레터 분류, 태그, 검색, 로고, 편집 품질을 관리한다. 사용자가 이 채팅방에 통합·검증을 명시하지 않는 한 같은 뉴스레터 수정을 중복으로 하지 않는다.
- 뉴스레터 작업을 넘겨받을 때 필요한 확인: source diff, 생성된 공개 페이지, `services/newsletter/tests/test_daily_news_logic.py` 결과, 브랜드 아이콘 검사, 공개 URL smoke check가 있어야 배포 보고에 포함한다.
- LP Notice 현재 목표: `lp-official-notices.html`, `lp-notices.html`, `lp-notice-*.html`을 긁어온 row 목록이 아니라 사업 단위 공고 서비스로 만든다. 2026-06-09 공개 배포에서는 noisy candidate row를 제외하고 program/lifecycle grouping을 강화해 공개 공고 카드를 246개에서 85개로 줄였다.
- LP directory current rule: 직접 GP/위탁운용사를 선정하는 기관만 공개 디렉토리에 표시한다. 산재보험기금·고용보험기금 등 OCIO 위임형 기금은 내부 pool로 분류하고, 별도 OCIO 서비스/탭을 기획하기 전까지 공개 기본 목록에는 섞지 않는다.
- LP classification basis: `legal_lp_category`는 자본시장법 체계상 법적 LP 유형이고, `core/policy/ocio/candidate`는 실제 공고, 선정 이력, OCIO 위임 여부, 사용자 지정 전략기관 여부를 반영한 서비스 운영 등급이다. 후보성 기관 일반정보만으로는 공개하지 않는다.
- GP/FSS 통계 기준: 최신 공식 원천은 `2025Q4` (`2025-12-31` 기준, 2026-07-02 금감원 게시)다. 현재 검증 수치는 펀드 1,195개, 대표 운용 GP 397개, 출자약정액 167.5조원, 상위 10개 GP 비중 42.84%다. Market의 GP는 펀드별 대표 운용사 기준이며, FSS에서 관측된 전체/공동 운용사 수와 섞지 않는다.
- GP/FSS 공개 계약: `scripts/check_fss_statistics_ready.py`는 최신 raw 파일, DB SHA-256, 최신 reporting period, non-zero market summary, complete primary-GP ranking을 확인하고 400일 이상 지난 기준일을 실패 처리한다. GP를 포함한 `build_site_bundle.py`는 이 검사를 통과해야 한다. `sync_gp_public_read_model.py`는 준비성 검사와 page contract를 통과한 public HTML을 Supabase versioned snapshot으로 발행한다. Snapshot ID에는 원본 SHA와 모든 public page content SHA를 함께 넣어 변환 로직이나 공개 결과가 바뀌면 같은 분기라도 새 snapshot을 만든다. Vercel은 published snapshot만 읽는다. FSS 명칭만 확인된 GP는 디렉터리 행으로만 공개하며, source-backed profile facts가 없는 상세 페이지를 만들지 않는다.
- Wiki 상태: 공개 내비게이션에서 숨긴다. 사용자가 다시 기획하기 전까지 Wiki UI나 본문 작업을 하지 않는다.
- 운영 체계 목표: LP/GP/Brief 기능을 더 넣기 전에 서비스 경계를 먼저 고정한다. 새 아이디어는 담당 서비스, 데이터 소스, 공개 view 계약, 검증 경로가 정해지기 전까지 `docs/service_quality_backlog.md`에 보관한다.

## 프로젝트 리드 실행 계약

- 큰 작업은 이 파일을 먼저 읽고, 어떤 서비스가 이번 작업 범위인지 짧게 밝힌 뒤 시작한다.
- 서비스 담당명은 실제 하위에이전트 수가 아니라 책임 영역이다. `Newsletter / Brief`, `LP`, `GP`, `Wiki`, `Verification / Deploy`가 있다고 해서 하위에이전트 5명이 실행 중이라는 뜻이 아니다.
- 실행 중인 역할은 작게 유지한다. 지침 정리, 단일 서비스 진단, 결합도 높은 리팩터링은 Project Lead가 직접 처리한다. 독립적인 세 번째 작업 축이 분명할 때가 아니면 Worker 1명과 Verifier 1명을 넘기지 않는다.
- 사용자가 하위에이전트가 너무 많거나 전담인지 묻는 경우, 먼저 실제 실행 역할을 줄이고 전체 서비스 소유권 목록이 아니라 현재 켜진 역할만 보고한다.
- 어떤 서비스가 다른 채팅방으로 넘어가면 다른 일을 계속하기 전에 이 파일에 handoff 상태를 기록한다.
- 사용자가 같은 지적을 반복하면 같은 작업 주기 안에서 `docs/agent_operating_briefs.md`, `docs/design_system.md`, 또는 이 파일의 지속 규칙으로 바꾼다.
- source 변경, build output, 검증 결과, 배포 상태가 각각 확인되기 전에는 완료로 보고하지 않는다.
- Project Lead는 조율할 수 있어야 한다. 긴 로고 보강, 데이터 백필, QA sweep은 이 채팅방을 막지 않도록 Worker 또는 Verifier에게 넘긴다.

## 반드시 지킬 제품 결정

- 반복되는 사용자 지적은 단순 실수가 아니라 지시 관리 실패로 본다.
- 공개 UI는 서비스별 앱 모음이 아니라 하나의 제품처럼 보여야 한다. 품질 기준은 혁신의숲 같은 데이터 디렉토리 서비스다.
- Do not expose operator/internal wording: `관리자`, `자동 생성`, `source/evidence`, `AUM proxy`, `검토 대기`, `보강 필요`, `AI가 만든 듯한 설명문`.
- 공개 화면 유형은 아래처럼 고정한다.
  - 뉴스: 평평한 기사 리스트
  - LP/GP 목록: 표에 가까운 row 디렉토리
  - LP/GP 상세: 프로필 상세
  - LP 공고: row-card 공고 workflow
  - Wiki: 문서형 화면, 단 현재는 숨김
- 생성된 deploy/public HTML을 source of truth처럼 직접 고치지 않는다. source renderer를 고치고, 다시 빌드하고, 검증한 뒤 publish한다.
- worktree가 dirty이면 현재 작업에 속한 파일만 stage한다.

## 빌드와 배포 명령

Python 문법 검사:

```bash
python3 -m py_compile scripts/build_newsletter_bundle.py scripts/build_site_bundle.py scripts/check_public_frontend.py scripts/check_architecture_contracts.py services/newsletter/web/app.py services/newsletter/web/index.py services/newsletter/web/newsletter_data.py services/newsletter/web/newsletter_ui.py services/newsletter/src/newsletter_renderer.py services/newsletter/src/sync_newsletter_supabase.py services/newsletter/src/newsletter_public_status.py services/newsletter/scripts/check_github_actions_readiness.py services/newsletter/scripts/check_vercel_supabase_readiness.py services/lp/src/build_lp_service_pages.py services/lp/src/lp_legacy_service_pages.py services/gp/src/build_gp_service_pages.py services/gp/src/gp_service_pages.py services/shared/src/brand_assets.py
```

현재 공개 서비스 통합 빌드:

```bash
python3 scripts/build_site_bundle.py --date YYYY-MM-DD --services newsletter,lp,gp --archive-limit 30
```

금감원 GP 통계 준비성 검사:

```bash
python3 scripts/check_fss_raw_sources.py --db db/private_equity.db
python3 scripts/check_fss_statistics_ready.py --db db/private_equity.db --expected-latest-period 2025Q4
```

GP 순위 검증 데이터팩 생성:

```bash
python3 scripts/build_gp_ranking_datapack.py --period 2025Q4 --raw-history all --excel-compatible --soffice /path/to/soffice
```

이 명령은 `exports/gp_ranking_datapack_2025YE.xlsx`를 생성한다. 이 파일은 public deploy가 아니라 감사/검토용 ignored artifact다. 최종 순위는 웹 GP DB와 동일한 고유 펀드 누적 총약정액 기준이며, 실제 NAV/AUM이 아니라는 한계를 함께 표시한다. 모바일 전달 사본은 반드시 Office-compatible normalization과 Microsoft Excel 열기 검증을 거친다.

매일 GitHub Actions용 뉴스레터 단독 빌드:

```bash
python3 scripts/build_newsletter_bundle.py --date YYYY-MM-DD --archive-limit 30
```

뉴스레터 Supabase payload 생성:

```bash
python3 services/newsletter/src/sync_newsletter_supabase.py --archive services/newsletter/deploy/site/archive.json --issue-limit 30
```

뉴스레터 Vercel 앱 코드 배포:

```bash
GitHub Actions → Deploy newsletter Vercel app → Run workflow
```

Wiki를 명시적으로 다시 기획했을 때만 빌드:

```bash
python3 scripts/build_site_bundle.py --date YYYY-MM-DD --services wiki --archive-limit 30
```

공개 frontend 계약 검사:

```bash
python3 scripts/check_public_frontend.py --services newsletter
python3 scripts/check_public_frontend.py
```

구조 계약 검사:

```bash
python3 scripts/check_architecture_contracts.py
```

뉴스레터 백업 미러 발행 workflow 실행:

```bash
GitHub Actions → Build newsletter mirror → Run workflow
```

이 workflow는 뉴스레터 데이터를 수집하고 GitHub Pages 백업 미러만 publish/verify한다. 성공한 뒤에는 `Sync newsletter Supabase read model`이 별도로 실행되어 검증된 mirror archive를 Supabase에 복사하고 Vercel 공식 앱을 검증한다. `Deploy newsletter Vercel app`은 앱 코드 배포만 담당한다.

GP 금감원 통계 발행 workflow 실행:

```bash
GitHub Actions → Deploy GP FSS market → Run workflow
```

이 workflow는 GitHub에 versioned 된 FSS raw source를 검증한 뒤 SQLite build 사본을 재생성하고, 승인된 GP alias merge, 최신 분기/집계/순위 readiness 검증, canonical GP profile evidence 적용·대사를 거쳐 GP static backup과 Supabase public snapshot을 함께 갱신한다. 금감원 원본 수집은 새 분기 자료가 확인됐을 때만 별도로 실행해 Excel과 registry를 commit하는 작업이며, 이 배포 workflow에 포함하지 않는다. Evidence CSV의 숫자 `source_gp_id`는 rebuild마다 달라질 수 있으므로 표준명 정규화 기준으로만 연결한다. Alias·profile evidence 문제는 warning으로 기록하고 후속 정리 대상으로 둔다. 이 품질 경고만으로 통계 snapshot 배포를 막지 않는다. People 반영 뒤에는 Top 50 People coverage CSV를 Actions artifact로 30일간 남긴다. 이 worklist는 리서치 우선순위용이며 배포를 막지 않는다. Vercel 공식 앱은 `/market.html`, `/gps.html`, source-backed GP의 `/gp-<id>.html`, 공개 가능한 People의 `/person-<id>.html`에서 published Supabase snapshot을 읽어 공개한다. GP profile은 금감원 확인 펀드의 전체 이력을 함께 표시한다. 뉴스레터 archive와 LP 산출물은 건드리지 않는다. FSS-only GP는 디렉터리 행으로만 공개하며 근거 없는 기존 상세 프로필은 같이 제거한다.

뉴스레터 Supabase migration 적용:

```bash
GitHub Actions → Apply newsletter Supabase migration → Run workflow
```

이 workflow는 `services/newsletter/supabase/migrations/*.sql`을 순서대로 적용한다. Supabase external watchdog이 `skipped_missing_token`으로 기록되면 Supabase Vault에 `newsletter_github_actions_dispatch_token`이 없는 상태다.

배포 후 공개 URL 확인:

```bash
python3 scripts/check_public_frontend.py --base-url https://pkkong.github.io/kpef-newsletter/
curl -fsS "https://kpef-newsletter.vercel.app/health.json?refresh=1"
```

## 완료 보고 전 필수 검증

- Python 문법 검사가 통과해야 한다.
- `scripts/check_architecture_contracts.py`가 통과해야 한다.
- 관련 source build가 통과해야 한다. Brief만 바뀌면 newsletter-only build, 여러 서비스가 바뀌면 integrated bundle을 확인한다.
- `scripts/check_public_frontend.py`가 통과해야 한다.
- 주요 공개 페이지의 하단 메뉴가 정확히 `브리프 / LP / GP`만 보여야 한다.
- UI가 바뀌었으면 모바일 390px와 데스크톱 1280px를 확인한다. 못 했으면 이유를 완료 보고에 명확히 쓴다.
- Brief/Vercel이 바뀌었으면 Vercel과 Pages의 `report_date`, `article_count`, archive issue count, issue 순서, 기사 row 순서, CSS, JS가 같아야 한다.
- 배포했다면 CDN cache 반영 뒤 공개 URL에서 `health.json`, `index.html`, `lp-notices.html`, `gps.html`, `market.html`을 확인한다.

## 다른 채팅방 인계 양식

다른 채팅방이나 서브에이전트가 서비스를 맡을 때는 아래 양식을 쓴다.

```text
역할:
목표:
담당 파일:
금지 파일:
현재 제품 결정:
이미 반영된 사용자 지적:
필수 검증:
기대 산출물:
커밋/배포 기대치:
```

받는 채팅방은 대화 기억에 의존하면 안 된다. 먼저 `AGENTS.md`, `docs/agent_operating_briefs.md`, `docs/design_system.md`, `docs/service_quality_backlog.md`, 이 control center를 읽어야 한다.

## 현재 알려진 리스크

- 이 repo의 worktree에는 이전 서비스 작업의 unrelated dirty changes가 자주 남아 있다. 사용자가 명시하지 않으면 reset/revert하지 않는다.
- 정적 미러 배포 source는 `services/newsletter/deploy/site/`의 생성 번들과 `gh-pages` 미러다. 공식 Brief 앱 상태는 검증된 mirror archive를 Supabase public read model로 동기화한 뒤 Vercel이 읽는 상태다. legacy root `public/` 디렉토리는 ignored generated output이며 커밋하면 안 된다.
- 뉴스레터 분류와 태그 품질은 계속 active risk다. 분류 로직을 바꾸면 `services/newsletter/tests/test_daily_news_logic.py`에 제목 기반 회귀 테스트를 추가한다.
- 뉴스레터 수집 완료는 GitHub Actions public mirror push와 공개 `health.json`/`archive.json` 검증 뒤에만 인정한다. 공식 앱 완료는 별도 Supabase sync workflow와 Vercel `health.json?refresh=1` 검증이 필요하다. 언론사 아이콘 누락이나 약한 아이콘은 report와 backlog를 남기되, `NEWSLETTER_STRICT_ICON_CHECK=1`을 명시하지 않는 한 당일 공개 뉴스레터를 막지 않는다.
- 매일 뉴스레터의 GitHub 내부 schedule은 메일 폭탄을 막기 위해 자동 mirror build 08:37 KST 1회와 GitHub 내부 watchdog 09:22 KST 1회만 둔다. Scheduled mirror run은 GitHub Pages mirror freshness만 보고, 오늘자 mirror가 이미 기사와 함께 publish되어 있으면 수집/build/publish를 건너뛴다. watchdog은 mirror가 stale이면 mirror build를 dispatch하고, mirror는 fresh인데 Vercel/Supabase만 stale이면 Supabase-only sync를 dispatch한다. 최근 6시간 안에 mirror build가 이미 실패했으면 watchdog은 같은 실패 workflow를 다시 dispatch하지 않는다. GitHub Actions 자체 장애로 이 두 schedule이 누락되는 경우에는 Supabase external watchdog이 GitHub `Newsletter publish watchdog`을 외부에서 깨운다.
- 매일 자동 발행은 `stable` source profile을 사용한다. publisher/watch/category safety net과 전체 67개 소스 크롤링은 누락 기사 조사, 백필, source audit 목적의 수동 `source_profile=all` 실행으로 분리한다. 자동 발행이 다시 `all`을 기본값으로 쓰면 운영 안정성 회귀다.
- 매일 뉴스레터 상태 source는 `exports/daily_news/ops_status/newsletter_ops_status_latest.md`다. 뉴스레터 장애를 진단하기 전에 먼저 이 파일을 확인한다. 이 파일은 collection, local build, public publish, hard failure, soft warning을 분리한다.
- LP/GP/Wiki import drift와 newsletter workflow role drift는 이제 자동 회귀 risk다. `scripts/check_architecture_contracts.py`가 실패하면 제품 작업을 추가하기 전에 경계 위반부터 고친다.
- FSS raw registry에는 2015Q4와 2016Q1 legacy `.xls` 원천도 보존한다. 현재 표준 라이브러리 parser는 `.xlsx`만 적재하므로 이 두 파일은 raw health check에서는 SHA로 보존 확인하지만 normalized DB에는 넣지 않는다. 2025Q4 공개 통계 준비성은 최신 `.xlsx` 원천과 DB/순위 일치로 별도 보장한다.
- LP notice lifecycle과 business-card grouping은 계속 active risk다. 진짜 별도 사업이 아닌 한 한 LP 사업을 공고/서류심사/선정결과 카드로 쪼개지 않는다. 현재 public gate는 parser review 전까지 noisy한 `vcs_investment_notice` candidate feed를 의도적으로 제외한다.
- LP 공식 채널 수집 진단에서 KOFIA 목록 응답이 간헐적으로 `IncompleteRead`로 끊겼다. 이 채널은 자동 후보로 공개하지 않으며, 다음 수집 개선은 retry/response validation을 추가한 뒤 1건 readiness 진단으로 확인한다.
- 사용자가 Wiki 기획을 다시 열기 전까지 Wiki는 공개 내비게이션에 보여주지 않는다.

## 현재 검증 기록

- 오래된 incident/deploy 검증 로그는 `docs/project_history_archive.md`로 옮겼다.
- 2026-06-21 구조 정리의 사용자용 완료 보고서는 `docs/refactor_closeout_2026-06-21.md`에 있다.
- 2026-06-21 구조 정리 로컬 검증 통과: Python compile, `services/newsletter/tests/test_daily_news_logic.py` 113개 검사, `services/newsletter/tests/test_public_status.py`, `services/newsletter/web/tests/test_newsletter_data.py`, `services/lp/tests/test_lp_notice_dedupe.py`, `services/lp/tests/test_lp_notice_gp_link.py`, `scripts/check_architecture_contracts.py`, `scripts/check_public_frontend.py`, `services/newsletter/scripts/check_github_actions_readiness.py --skip-secrets`, `services/newsletter/scripts/check_vercel_supabase_readiness.py`.
- 2026-06-21 source build 통과: `scripts/build_newsletter_bundle.py --date 2026-06-21 --archive-limit 30`, `scripts/build_site_bundle.py --date 2026-06-21 --services newsletter,lp,gp --archive-limit 30`, `sync_newsletter_supabase.py --payload-out /tmp/newsletter_supabase_payload.json` dry-run.
- 2026-06-21 UX smoke 통과: Chrome 390px와 1280px에서 `index.html`, `lp-notices.html`, `gps.html`, `market.html`을 확인했다. console error 없음, 하단 메뉴 `브리프 / LP / GP`, Wiki/internal wording 숨김, horizontal overflow 0px. 스크린샷은 `/tmp/kpef-*-mobile390.png`, `/tmp/kpef-*-desktop1280.png`에 있다.
- 2026-06-21 production deploy 완료: commit `82e9737`을 `main`에 push했고, Vercel 앱 배포 run `27906187275`, GitHub Pages 미러 build/publish/verify run `27906187286`, Supabase read model sync와 Vercel 공식 앱 검증 run `27906477785`가 모두 성공했다. 공개 Pages `health.json`과 Vercel `health.json?refresh=1`은 `report_date=2026-06-21`, `article_count=2`, `status=ok`로 확인했다.
- 2026-08-21 FSS 통계 갱신 검증: 공식 `2025Q4` source를 registry/raw에 추가하고 SQLite를 재생성했다. raw health는 34/34 파일 확인, 32개 `.xlsx` DB SHA 일치(legacy `.xls` 2개는 미적재 경고), FSS readiness는 `2025Q4`, 1,195 펀드, 대표 GP 397개, ranking 397개로 통과했다. 별도 GP bundle에서 `market.html`/`gps.html` 계약 검사와 Chrome 390px/1440px smoke를 통과했다. GitHub Pages `gh-pages` commit `0f7e03d`로 검증된 정적 GP source를 갱신하고 FSS-only GP 120개 상세 페이지를 제거했다. Vercel production deploy run `32486898154`는 `/market.html`과 `/gps.html`의 200 응답, source header, 2025Q4 본문을 확인했다. 이후 발행은 전용 source gate를 통과해야 한다.
- 2026-08-25 GP Vercel direct read model 전환 완료: Supabase migration run `32845250938`, Vercel 앱 deploy run `32845667639`, GP FSS publish run `32845812052`가 모두 성공했다. 당시 GP workflow는 source/readiness, GP static backup, Supabase versioned snapshot 발행, GitHub Pages backup, Vercel 검증을 모두 통과했다. 이후 FSS raw source는 GitHub versioned input으로 전환했다. 공개 `/market.html`과 `/gps.html`은 `X-GP-Data-Source: supabase-public-snapshot`, `X-GP-Reporting-Period: 2025Q4`, snapshot `fss-2025q4-ec864d1a2f16`을 반환한다. GitHub Pages는 GP의 backup mirror일 뿐 Vercel GP 화면의 runtime source가 아니다.
- 2026-08-26 GP 순위 검증 데이터팩 기준 수정: Excel은 웹 GP DB와 별도 집계를 하지 않는다. `FSS raw → normalized fund/GP analytics → gp_profile → 누적 순위`가 하나의 기준이다. 최종 표는 2025Q4 단일 시점 순위가 아니라, 2016Q2~2025Q4 정규화 FSS의 `fund × 업무집행사원 GP` 관계별로 펀드 최대 공시 총약정액을 전액 반영한 누적 순위다. 공동 GP는 각 GP에 중복 반영하므로 합계는 경제적 펀드 전체 총약정액보다 클 수 있다. 모바일 공개 배포 사본은 `services/newsletter/web/downloads/gp_ranking_datapack_2025YE.xlsx`에 versioned asset으로 두고 Vercel `/downloads/gp-ranking-datapack-2025ye.xlsx`에서 attachment로 제공한다. 갱신 때는 data-pack build, Office normalization, Microsoft Excel 열기, SHA/ZIP 검증, delivery copy 교체, Vercel deploy와 공개 URL download 검증을 모두 통과해야 한다.
- 2026-08-27 GP profile evidence binding 보강: 금감원 재수집 때 `source_gp_id`가 변하는데도 숫자 ID로 `data/gp_profile_evidence.csv`를 적용하던 결함을 수정했다. 이제 evidence는 `standard_gp_name → gp_name_norm` 기준으로 한 GP에만 연결하며, 이름 중복은 배포 차단이다. GP FSS workflow는 rebuild 뒤 evidence 770행을 재적용하고 source/profile 대사를 통과해야 한다. 최신 2025Q4 사본 검증에서 59개 GP에 근거가 적용됐고, 55개에는 공식 홈페이지가 확인됐다.
- 2026-08-28 MBK profile People 첫 공개: MBK 공식 팀 페이지 출처의 현재 인물 13명을 `주요 인물` section에만 표시한다. 이름·직함·근무지만 공개하고, 전체 People tab은 coverage 기준이 충족될 때까지 숨긴다. FSS rebuild 뒤 `scripts/import_people_csv.py`를 실행하도록 GP FSS workflow에 넣어 People table이 사라지는 회귀를 막는다.
- 2026-08-28 FSS/People 운영 DB 전환 완료: migration run `33174218647`로 FSS 정규화 데이터와 People 운영 데이터를 담을 Supabase private canonical tables를 생성했고, run `33175077955`가 versioned 2015Q4~2025Q4 FSS Excel 34개로 2025Q4 canonical snapshot `fss-core-2025q4-ec864d1a2f16`을 최초 발행했다. 이 snapshot은 FSS 행 60,269개와 People 행 877개를 보관한다. SQLite↔Supabase sync/restore 도구와 FSS 재수집 없는 `Publish GP and People from Supabase` workflow도 추가했다. 원본 Excel과 registry는 GitHub repository의 `data/raw/fss_pef/`에 versioned source로 보관하며, `Deploy GP FSS market`은 금감원 사이트에서 다시 받지 않고 이 원본만으로 build한다. 새 분기 자료가 생길 때만 새 파일과 registry를 commit한 뒤 실행한다.
- 2026-08-28 People-only publish 검증: run `33179651922`가 published canonical FSS snapshot을 임시 SQLite로 복원(FSS 행 60,269개), People CSV 141명을 재적재하고, canonical People 877행과 GP public page 61개를 다시 발행했다. `supabase_fss_canonical_sync`는 `fss_rows=0`, `status=people_synced`로 끝났으며 FSS fetch/ingest 명령은 실행하지 않았다. Vercel은 2025Q4 Supabase GP snapshot을 정상 응답했다.
- 2026-08-29 GP public UI 통일: commit `a8fea82`에서 MBK 한 곳에만 적용됐던 profile layout을 source-backed GP 59개 전체로 확장했다. GP directory는 현재 결과 수와 `기준일/집계 기준/정렬기준` 세 control만 노출하고, Market은 `시장 개요`로 용어를 통일했다. `Publish GP and People from Supabase` run `33256165062`는 현재 canonical `2025Q4`를 복원해 FSS 재수집 없이 public snapshot, backup, Vercel 검증을 모두 통과했다. Vercel 일반 GP profile은 `X-GP-Data-Source: supabase-public-snapshot`, snapshot `fss-2025q4-ec864d1a2f16-eb8c7155f7f1`을 반환한다.
- 2026-08-28 People 상세 profile 확장: 공식 현재 역할이 확인된 대표·파트너·임원급을 `person-<id>.html`로 공개한다. GP의 `주요 인물`에서 해당 이름을 상세로 연결하고, 상세에는 현재 역할, 공식 프로필에 기재된 경력·학력, 공식 출처만 표시한다. 현재 2025Q4 People 데이터에서는 114개 상세 페이지가 생성된다. 전체 People 탭은 계속 숨긴다.
- 2026-08-29 People 공식 출처 보강: 아이엠엠크레딧앤솔루션 9명과 글랜우드크레딧 2명을 공식 팀 페이지 근거로 추가했다. `Publish GP and People from Supabase` run `33257090060`은 FSS 재수집 없이 People만 canonical Supabase와 public snapshot에 반영했고, 125개 People 상세 페이지를 생성했다. Top 50에서 People 작업이 시작된 GP는 27개에서 29개가 됐다. 두 GP workflow는 이후 매 실행 때 coverage worklist를 30일 artifact로 남기며, 이 리포트는 배포 차단 조건이 아니다. Vercel 모바일 390px에서 People 목록과 개별 profile을 확인해 가로 overflow 없이 직함·소속·경력·학력·공식 출처가 표시되는 것을 확인했다.
- 2026-08-29 GP 공개 뉴스 연결: `Publish GP and People from Supabase` run `33257755605`가 published newsletter archive 30일치 502건을 read-only로 반영해 65개 GP에 172개 관련 뉴스 링크를 붙였다. GP별로 긴 별칭이 짧은 별칭을 포함할 때 짧은 match를 제외해 글랜우드크레딧 기사가 글랜우드프라이빗에쿼티에 같이 붙지 않게 했다. Vercel 모바일 MBK profile에서 관련 정보 6건, 가로 overflow 0, 콘솔 error 0을 확인했다. LP 선정 연결은 다음 정상 LP monitor build가 public `lp-notices.json`을 만들면 같은 GP publish 경로에서 자동 반영된다. monitor input이 없는 build는 기존 context를 빈 파일로 교체하지 않는다.
- 2026-08-30 LP collector 독립화 및 공개 계약 정리: LP 단독 SQLite build가 `news_document`·`gp_house` 외래키를 요구해 자동 정리 단계에서 실패하던 결함을 제거했고, 기존 DB도 실행 시 local link table로 변환한다. `--limit-per-source=1` readiness run은 21초에 공식 후보 13건과 검수 이벤트 9건을 수집했다. 후보는 공개하지 않고 lifecycle을 거친 validated 공식 선정 결과 2개만 `lp-notices.json`에 남겼다. 이 context를 임시 GP build에 반영한 결과는 2개 공고, 11개 GP 정확 연결이다. KOFIA channel의 `IncompleteRead`는 별도 retry 개선 대상이며, 이 진단 데이터는 아직 공개 배포하지 않았다.

## 프로젝트 리드 종료 체크리스트

- 사용자 지적이 반복될 성격이면 지속 규칙으로 바꿨는가?
- 서비스 책임과 금지 파일 범위가 명확했는가?
- generated artifact를 손으로 고치지 않고 source에서 다시 만들었는가?
- test/build/public check를 실행했고 결과를 보고했는가?
- 배포 상태를 source 수정·커밋 상태와 분리해서 보고했는가?
- 남은 risk를 채팅 기억에만 두지 않고 문서에 남겼는가?
