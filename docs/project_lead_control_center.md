# 프로젝트 리드 현재 상태판

최종 수정: 2026-06-21 KST

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
- 매일 뉴스레터 schedule은 GitHub cron 한 번에 의존하지 않는다. 기본 mirror build는 08:37 KST이고, 09:17, 09:47, 10:17, 11:17 KST retry window가 있다. Scheduled mirror run은 GitHub Pages mirror freshness만 보고, 오늘자 mirror가 이미 기사와 함께 publish되어 있으면 수집/build/publish를 건너뛴다. watchdog은 08:52 KST부터 확인해 mirror가 stale이면 mirror build를 dispatch하고, mirror는 fresh인데 Vercel/Supabase만 stale이면 Supabase-only sync를 dispatch한다.
- 매일 뉴스레터 상태 source는 `exports/daily_news/ops_status/newsletter_ops_status_latest.md`다. 뉴스레터 장애를 진단하기 전에 먼저 이 파일을 확인한다. 이 파일은 collection, local build, public publish, hard failure, soft warning을 분리한다.
- LP/GP/Wiki import drift와 newsletter workflow role drift는 이제 자동 회귀 risk다. `scripts/check_architecture_contracts.py`가 실패하면 제품 작업을 추가하기 전에 경계 위반부터 고친다.
- LP notice lifecycle과 business-card grouping은 계속 active risk다. 진짜 별도 사업이 아닌 한 한 LP 사업을 공고/서류심사/선정결과 카드로 쪼개지 않는다. 현재 public gate는 parser review 전까지 noisy한 `vcs_investment_notice` candidate feed를 의도적으로 제외한다.
- 사용자가 Wiki 기획을 다시 열기 전까지 Wiki는 공개 내비게이션에 보여주지 않는다.

## 현재 검증 기록

- 오래된 incident/deploy 검증 로그는 `docs/project_history_archive.md`로 옮겼다.
- 2026-06-21 구조 정리의 사용자용 완료 보고서는 `docs/refactor_closeout_2026-06-21.md`에 있다.
- 2026-06-21 구조 정리 로컬 검증 통과: Python compile, `services/newsletter/tests/test_daily_news_logic.py` 113개 검사, `services/newsletter/tests/test_public_status.py`, `services/newsletter/web/tests/test_newsletter_data.py`, `services/lp/tests/test_lp_notice_dedupe.py`, `services/lp/tests/test_lp_notice_gp_link.py`, `scripts/check_architecture_contracts.py`, `scripts/check_public_frontend.py`, `services/newsletter/scripts/check_github_actions_readiness.py --skip-secrets`, `services/newsletter/scripts/check_vercel_supabase_readiness.py`.
- 2026-06-21 source build 통과: `scripts/build_newsletter_bundle.py --date 2026-06-21 --archive-limit 30`, `scripts/build_site_bundle.py --date 2026-06-21 --services newsletter,lp,gp --archive-limit 30`, `sync_newsletter_supabase.py --payload-out /tmp/newsletter_supabase_payload.json` dry-run.
- 2026-06-21 UX smoke 통과: Chrome 390px와 1280px에서 `index.html`, `lp-notices.html`, `gps.html`, `market.html`을 확인했다. console error 없음, 하단 메뉴 `브리프 / LP / GP`, Wiki/internal wording 숨김, horizontal overflow 0px. 스크린샷은 `/tmp/kpef-*-mobile390.png`, `/tmp/kpef-*-desktop1280.png`에 있다.
- 2026-06-21 production deploy 완료: commit `82e9737`을 `main`에 push했고, Vercel 앱 배포 run `27906187275`, GitHub Pages 미러 build/publish/verify run `27906187286`, Supabase read model sync와 Vercel 공식 앱 검증 run `27906477785`가 모두 성공했다. 공개 Pages `health.json`과 Vercel `health.json?refresh=1`은 `report_date=2026-06-21`, `article_count=2`, `status=ok`로 확인했다.

## 프로젝트 리드 종료 체크리스트

- 사용자 지적이 반복될 성격이면 지속 규칙으로 바꿨는가?
- 서비스 책임과 금지 파일 범위가 명확했는가?
- generated artifact를 손으로 고치지 않고 source에서 다시 만들었는가?
- test/build/public check를 실행했고 결과를 보고했는가?
- 배포 상태를 source 수정·커밋 상태와 분리해서 보고했는가?
- 남은 risk를 채팅 기억에만 두지 않고 문서에 남겼는가?
