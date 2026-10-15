# 프로젝트 리드 현재 상태판

최종 수정: 2026-09-08 KST

이 문서는 Project Lead가 현재 프로젝트 상태를 잃지 않기 위한 운영판이다. 새 채팅방, 서브에이전트, 별도 담당자가 작업을 시작할 때는 먼저 이 문서를 읽고, 작업이 끝나면 필요한 변경을 여기에 반영한다.

사용자가 이번 구조 정리 결과를 확인할 때는 먼저 `docs/refactor_closeout_2026-06-21.md`를 읽는다.

## 현재 공개 제품

- 뉴스레터 공식 앱: `https://kpef-newsletter.vercel.app`
- GitHub Pages 백업 미러: `https://pkkong.github.io/kpef-newsletter/`
- 원본 저장소: `pkkong/korea-pef-db`
- 공개 미러 저장소: `pkkong/kpef-newsletter`, branch `gh-pages`
- 공개 하단 메뉴: `브리프 / LP / GP`
- Wiki는 사용자가 다시 기획하기 전까지 공개 메뉴에서 숨긴다.
- 인프라 우선순위: Vercel은 유일한 공식 공개 runtime, Supabase는 canonical/public read model DB, GitHub은 코드·원천·workflow와 backup mirror다. GitHub Pages URL은 검증·장애 복구 목적이며 기본 서비스 URL이 아니다.
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
- Vercel/Supabase 운영 경로는 다음과 같이 고정한다. `services/newsletter/web/`는 Vercel Flask 앱이다. Supabase는 뉴스 source/run/document/tag/entity의 비공개 canonical collection과 Vercel용 public read model을 모두 가진다. `services/newsletter/src/sync_newsletter_canonical_supabase.py`는 GitHub Actions에서만 쓸 임시 SQLite adapter를 Supabase로부터 복원하고 다시 반영한다. `sync_newsletter_supabase.py`는 검증된 archive를 public read model로 옮기는 별도 동기화 코드다. 개발자 컴퓨터의 SQLite는 기준 DB가 아니다.
- 2026-09-03에 newsletter canonical collection migration을 Supabase에 적용했다. `Sync newsletter Supabase read model` run `33763459735`가 기존 public archive를 최초 이관해 canonical document 506개, run 30개, tag 1,012개를 기록했고, 후속 run `33763668752`가 source registry 71개를 반영했다. 두 run 모두 Vercel `report_date=2026-09-03`, 기사 23개를 확인했다. `Apply newsletter Supabase migration`은 같은 폴더의 GP-owned migration을 다시 적용하지 않는다.
- 2026-09-04 뉴스레터 수집 장애를 복구했다. 초기 build 두 건은 수집 자체는 성공했지만, raw HTML을 Supabase Storage에 올릴 때 `text/html; charset=utf-8`가 bucket의 정확한 MIME allow-list와 달라 `415 invalid_mime_type`로 중단됐다. commit `31d670c`에서 전송 MIME을 `text/html`로 바로잡고 회귀 검사를 추가했다. 재실행 `33829142583`은 322건 발견, 103건 원문 수집, 50건 신규 적재, 19건 브리프 선별, canonical document 556개와 raw HTML 66개 업로드까지 성공했다. 이어 `33829360418`이 Pages archive 19건을 Supabase public read model(30 issue, 497 article)에 반영하고 Vercel `report_date=2026-09-04`, 기사 19건을 검증했다.
- 뉴스 원문 HTML은 장기 보관 대상이 아니다. `newsletter-raw`는 30일 오류 분석 캐시이며, 매일 canonical sync 뒤 만료 원문 파일과 `raw_html_path`만 soft-cleanup한다. 삭제 실패는 경고로 남기고 당일 뉴스 발행은 계속한다.
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

- 2026-09-06 검토 후 수정, 2026-09-07 인계: `docs/project_fixes_2026-09-06.md`에 수정 결과와 운영 반영 순서를 기록했다. 뉴스·People 갱신 실패 시 기존 자료 보존, 수정된 FSS 자료의 새 버전 발행, 원문 정리 실패의 경고 처리, LP 사업명/회차 병합, GP 페이지별 캐시 만료, 장애 응답, 브리프 GP 메뉴를 소스에서 수정했다. 자동 검사 241개(누락·실패 0개), PostgreSQL 장애 검사 14개, 실제 로컬 FSS 60,269행 및 People 877행의 임시 DB 발행을 통과했다. 통합 빌드와 frontend/architecture/Flask smoke도 통과했다. 로컬 LP 입력은 없어 채워진 LP 전체 화면은 미검증이다.
- 2026-09-07 운영 배포: 사용자가 배포를 명시 지시했다. 소스 `02f218b`(안전성), `4c61278`(LP SQLite 호환), `82c3015`(Deal 분류 검사 일치), `7a1896c`(Supabase People 교체 조건)를 main에 반영했다. 뉴스 migration `34073780498`, GP migration `34073781843` 및 후속 `34111886362`, Vercel 앱 배포 `34111607800` 성공. GP 발행 `34111961285`는 FSS 60,269행·People 관련 956행을 안전하게 반영하고 공개 페이지 186개를 발행해 Vercel까지 검증했다. canonical ID는 `fss-core-2025q4-ec864d1a2f16-267ab6e750b26a69f8988d02`, public ID는 `fss-2025q4-ec864d1a2f16-91fd1930ab37`이다. 최종 CI `34111887301` 성공(243개 발견, 전체 실데이터 fixture 없는 5개 명시 skip); 로컬은 243개 전부 통과, SQL 실패 검사 14개 통과.
- 배포 중 확인한 추가 결함: Supabase safeupdate가 WHERE 없는 People DELETE를 거부해 첫 GP run `34111610359`는 rollback됐다. 보호 설정을 해제하지 않고 후속 migration `20260907110000_gp_people_safeupdate_predicate.sql`로 명시적 조건을 추가했다. GP migration workflow는 9월 6일 안전성 migration과 이 후속 보정만 적용하며 과거 profile 제약을 재실행하지 않는다. GP 발행과 migration은 `gp-publish`로 직렬 실행한다.
- 뉴스 새 경로 검증: 자동 mirror `34084940305`와 sync `34085134733` 성공. 최종 코드의 수동 재발행 `34111915257`와 sync `34112268116`도 성공했다. 실제 브라우저에서 9월 7일 브리프, 9월 5일 날짜 이동, 공식 GP 메뉴, 390px 모바일 Brief/GP와 console error 없음을 확인했다.
- 최종 완료 확인(2026-09-08 21:20 KST): `524fb69`는 정정된 같은 날짜의 Supabase 기사보다 예전 백업의 많은 기사 수를 우선하던 문제를 수정했다. Vercel 최종 배포 `34112456563` 성공, CI `34112456549`는 244개 발견·실패 0·fixture 없는 5개 명시 skip, SQL 실패 검사 14개 통과다. 공개 Vercel과 Pages 모두 9월 8일자 19건, 30일 archive이며 Vercel은 `status=ok`, `data_source=supabase`, `stale=false`다. 브리프와 GP 배포는 완료, LP 화면은 아래 원본 복원 조건 때문에 보류다.
- LP 화면 배포 보류: 전체 검수 monitor/DB가 없고 공개 legacy JSON은 현재 83개 카드의 대표 원문 중 5개가 누락됐다. 원본 복원 전까지 기존 LP HTML/상세 URL/기관 프로필을 유지한다. `--monitor`가 목록에도 동일하게 전달되도록 LP builder 계약을 정리한 뒤 재발행한다. 상세 근거는 `docs/project_fixes_2026-09-06.md`에 있다.
- LP Vercel 이전은 별도 잔여 과제다. 검토 당시 Vercel LP route는 없고 Pages가 실제 연결 경로였으므로, 이번 수정은 GP 메뉴만 `/gps.html`로 전환하고 LP 링크를 유지한다. 기존 검토 근거는 `docs/project_review_2026-09-06.md`에 보존했다.

- 이 채팅방의 현재 책임: LP Notice 출시 품질, LP/GP 통합, 빌드 분리, 공개 배포 준비성, 문서 운영 기준을 관리한다.
- 별도 뉴스레터 채팅방의 현재 책임: 뉴스레터 분류, 태그, 검색, 로고, 편집 품질을 관리한다. 사용자가 이 채팅방에 통합·검증을 명시하지 않는 한 같은 뉴스레터 수정을 중복으로 하지 않는다.
- 뉴스레터 작업을 넘겨받을 때 필요한 확인: source diff, 생성된 공개 페이지, `services/newsletter/tests/test_daily_news_logic.py` 결과, 브랜드 아이콘 검사, 공개 URL smoke check가 있어야 배포 보고에 포함한다.
- LP Notice 현재 목표: `lp-official-notices.html`, `lp-notices.html`, `lp-notice-*.html`을 긁어온 row 목록이 아니라 사업 단위 공고 서비스로 만든다. 2026-06-09 공개 배포에서는 noisy candidate row를 제외하고 program/lifecycle grouping을 강화해 공개 공고 카드를 246개에서 85개로 줄였다.
- LP DB/runtime 전환: LP의 최종 경로는 `Supabase canonical LP data → published LP public read model → Vercel`이다. 현재 local SQLite collector와 static export는 이관 대상 build helper다. LP는 GitHub Pages나 local export를 공식 운영 DB·기본 서비스로 취급하지 않는다.
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

전체 자동 검사와 DB 교체 실패 검사:

```bash
python3 scripts/run_regression_tests.py
npm ci --prefix scripts/tests/sql --ignore-scripts
npm test --prefix scripts/tests/sql
python3 scripts/check_architecture_contracts.py
```

전체 FSS fixture가 없는 신규 checkout에서는 기존 실데이터 검사 5개가 명시적으로 skip된다. 로컬 최종 검사는 fixture가 있어 241개 모두 실행했다. 테스트가 0개인 파일이나 실행 실패는 성공으로 처리하지 않는다.

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

이 workflow는 먼저 Supabase canonical collection을 임시 SQLite adapter로 복원하고, 수집·분류·검수 결과와 raw HTML을 다시 Supabase에 기록한다. 이후 GitHub Pages 백업 미러만 publish/verify한다. 성공한 뒤에는 `Sync newsletter Supabase read model`이 별도로 실행되어 검증된 mirror archive를 public read model로 복사하고 Vercel 공식 앱을 검증한다. `Deploy newsletter Vercel app`은 앱 코드 배포만 담당한다.

GP 금감원 통계 발행 workflow 실행:

```bash
GitHub Actions → Deploy GP FSS market → Run workflow
```

이 workflow는 GitHub에 versioned 된 FSS raw source를 검증한 뒤 SQLite build 사본을 재생성하고, 승인된 GP alias merge, 최신 분기/집계/순위 readiness 검증, canonical GP profile evidence 적용·대사를 거쳐 GP static backup과 Supabase public snapshot을 함께 갱신한다. 금감원 원본 수집은 새 분기 자료가 확인됐을 때만 별도로 실행해 Excel과 registry를 commit하는 작업이며, 이 배포 workflow에 포함하지 않는다. Evidence CSV의 숫자 `source_gp_id`는 rebuild마다 달라질 수 있으므로 표준명 정규화 기준으로만 연결한다. Alias·profile evidence 문제는 warning으로 기록하고 후속 정리 대상으로 둔다. 이 품질 경고만으로 통계 snapshot 배포를 막지 않는다. People 반영 뒤에는 Top 50 People coverage CSV를 Actions artifact로 30일간 남긴다. 이 worklist는 리서치 우선순위용이며 배포를 막지 않는다. Vercel 공식 앱은 `/market.html`, `/gps.html`, source-backed GP의 `/gp-<id>.html`, 공개 가능한 People의 `/person-<id>.html`에서 published Supabase snapshot을 읽어 공개한다. GP profile은 금감원 확인 펀드의 전체 이력을 함께 표시한다. 뉴스레터 archive와 LP 산출물은 건드리지 않는다. FSS-only GP는 디렉터리 행으로만 공개하며 근거 없는 기존 상세 프로필은 같이 제거한다.

뉴스레터 Supabase migration 적용:

```bash
GitHub Actions → Apply newsletter Supabase migration → Run workflow
```

이 workflow는 `services/newsletter/supabase/migrations/*.sql` 중 newsletter-owned migration만 순서대로 적용한다. GP-owned migration은 별도 GP 발행 경로에서 관리하며 이 workflow가 다시 실행하지 않는다. Supabase external watchdog이 `skipped_missing_token`으로 기록되면 Supabase Vault에 `newsletter_github_actions_dispatch_token`이 없는 상태다.

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
- KOFIA 목록 응답은 간헐적으로 `IncompleteRead`로 끊길 수 있다. LP collector는 전송 중단·타임아웃 계열을 3회까지 짧게 재시도하며, 2026-08-30 1건 readiness run에서 두 번의 끊김 뒤 세 번째 응답으로 정상 수집했다. 이 채널의 자동 발견 row는 계속 candidate로만 유지한다.
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
- 2026-08-30 LP collector 독립화 및 공개 계약 정리: LP 단독 SQLite build가 `news_document`·`gp_house` 외래키를 요구해 자동 정리 단계에서 실패하던 결함을 제거했고, 기존 DB도 실행 시 local link table로 변환한다. `--limit-per-source=1` readiness run은 24초에 공식 후보 14건과 검수 이벤트 9건을 수집했다. 후보는 공개하지 않고 lifecycle을 거친 validated 공식 선정 결과 2개만 `lp-notices.json`에 남겼다. 이 context를 임시 GP build에 반영한 결과는 2개 공고, 11개 GP 정확 연결이다. KOFIA channel은 두 번의 `IncompleteRead` 뒤 세 번째 bounded retry로 정상 수집했으며, 이 진단 데이터는 아직 공개 배포하지 않았다.

## 프로젝트 리드 종료 체크리스트

- 사용자 지적이 반복될 성격이면 지속 규칙으로 바꿨는가?
- 서비스 책임과 금지 파일 범위가 명확했는가?
- generated artifact를 손으로 고치지 않고 source에서 다시 만들었는가?
- test/build/public check를 실행했고 결과를 보고했는가?
- 배포 상태를 source 수정·커밋 상태와 분리해서 보고했는가?
- 남은 risk를 채팅 기억에만 두지 않고 문서에 남겼는가?

## LP 공고 자동 수집 현재 기준 (2026-10-07)

- 현재 사용자 우선순위는 GP 연결보다 출자공고의 누락 없는 코드 수집·조건 추출·사업별 단계 묶기다. 개별 공고 ID를 사람이 골라 등록하는 방식으로 신규 사업을 확장하지 않는다.
- 최신 운영/검증 기록은 `services/lp/docs/priority_institutions_automation.md`가 관리한다. 10월 6일 수집 실행37470359891은 공개15사업 및 공식 후보10건/6묶음을 검증했다. 10월 7일 변경은 우정 공동투자·수은 임상3상 신규 사업의 공통 조건 추출과 산업은행에 있는 공동사업 원공고의 자동 보완 수집이다. 운영 게시 완료 여부는 해당 문서의 후속 실행 기록을 확인한다.
- 공식 원문 범위 미확인·VC 전용·PE/PD 투자관리 위탁·혼합형을 PE 전용 신규 게시로 추정하지 않는다. 공동사업은 해당 기관 출자 예정액과 전체 출자액을 분리하고 기관별 승인 완료를 가정하지 않는다.
- 검증: LP workflow suite(91개), `python3 scripts/check_architecture_contracts.py`, 실제 공고 기반17사업 생성과320/390/1000px 검증. 신규 조건 추출 소스 `services/lp/src/lp_notice_terms.py`, 공식 공동사업 원공고 탐색 `services/lp/src/collect_kdb_related.py`. generated export·DB·배포 번들은 커밋하지 않는다.

## LP 공동사업 정리 후속 (2026-10-08)

- 신규2개 사업 자동 게시 완료: 실행37628376137·37629905224 모두 전체 성공, 공개17사업. 교직원 수집 재시도 보완d38ae0a도 운영 경로에 적용됐다.
- 혼합형 공동사업은 현재 공개 PE 목록과 구분해 검토 화면에 둔다. `lp_joint_terms.py`가 공식 표에서 분야 합계·선정 수·결성목표·주목적·일정을 읽고 총계와 대조한다. 글로벌 스케일업 중형2,574억원을 펀드당 또는 은행당 금액으로 나누지 않고, 주목적50/30/30%를 합산 정규화하지 않는다. FAQ는 별도 자료이며 모집 필수값 대체 소스가 아니다.
- 검사97개·구조 계약 통과 후 운영 실행37725759888이 전체 성공했다. 공개 실행6274b8c20dd8a7eb5239319f. 외부 검토 화면의 공동사업 금액·일정·주목적과320/390px 가로 넘침·스크립트 오류 없음을 확인했다. 공개17개 사업과 GP 연결은 유지했다. 상세 기록은 `services/lp/docs/priority_institutions_automation.md`를 참조한다.

## 뉴스레터 저장 시간 초과 보정 (2026-10-08)

사용자 요청: 오늘 뉴스 수집 실패를 확인하고 재발 원인을 개선한다. run37705855977·37719973410은 기사 수집/브리프 생성 후 Supabase HTTP500/57014 저장 시간 초과로 게시 전에 중단됐다. 당시 Vercel/Pages 최신 날짜는10월7일이다. 전체 복원 기사1,521건·태그3,614건을 매번 다시 저장하던 경로를 복원 시 비교값을 기록해 신규/변경 기사만 저장하도록 수정했다. 태그/기관 연결만 바뀌거나 삭제되어도 owning article와 전체 연결을 함께 저장한다. 새 migration은 연결 검사에서 문서본문 대신ID집합을 사용한다. 기존 query도 planner가 hash join으로 최적화할 수 있으므로 시간초과의 SQL위치를 로그만으로 확정하지 않는다. 작업단계·입력건수·저장시간 로그를 추가했다.

로컬 검증: newsletter/web190개·PostgreSQL20개 통과. 기사2,000건/태그6,000건 full commit·원자성·응답분실 재시도·보류행 보존·migration재적용 검증. 신규/변경없는 복원자료는0건 전송, 과거5,001기사 중1기사 변경은1건 전송. 운영순서와 검사명령은 services/newsletter/docs/vercel_supabase.md 참조. 운영 적용과 오늘 발행 확인은 아래에 실제 결과를 남긴다.

운영 적용 확인: 소스 `d92c7f7`, CI `37728148371` 성공(352개 발견, 실패 0, fixture 없는 5개 명시 skip; SQL 20개 통과), DB migration `37728153109` 성공. 오늘자 Build mirror `37728265754`와 자동 Supabase sync `37728672671` 모두 성공. 과거 1,521개 전체 기사 대신 신규/변경 78개 기사·217개 태그·1개 run·71개 source를 저장했고 저장 단계는 3.649초에 완료됐다. 원문 HTML 71개 업로드·만료 94개 정리, 정리 실패 0. Vercel과 Pages 모두 `report_date=2026-10-08`, 기사 18개. 두 공개 archive의 기사 URL·제목·분류·순서를 비교해 일치 확인. Vercel source는 Supabase다. 앱 UI 변경이나 별도 Vercel 앱 배포는 필요 없으며 정기 수집은 수정된 main 코드를 사용한다.


## LP 공식 첨부 자동 추출 (2026-10-08)

- 사용자 승인: 한국성장금융부터 HWP/HWPX 본문 판독·모집 조건 추출·공식 목록 대비 수집 누락 검사를 코드로 연결한다. 신규 공고 ID·금액을 수동으로 골라 추가하지 않는다. GP 프로필 연결은 후순위다.
- 구현·한계·운영 경로는 `docs/lp_attachment_automation.md` 참조. HWP5 전체 본문·단순 HWPX·텍스트 PDF를 읽고 모집문과 제출서식을 구분한다. 알려진 항목·표 형식에서만 총액·선정 수·펀드당 금액·주목적·일정을 추출하고 총계와 검산한다. ZIP 묶음·OCR·복잡한 HWPX 표 및 미지원 항목 배치는 보류한다. 읽기 성공과 조건 추출 성공을 구분한다.
- 실제 목록 3페이지에서32건 발견·추적 포함37건 수집, 발견 후 누락0건. 첨부26개 중 본문19개(한글8·PDF11), 보조ZIP6개, 크기 제한 실패1개. IBK 일반매칭350억원·10개사·소형5×20억원·중형5×50억원·10월8일16시 마감·11월 심사 예정이 원문에서 자동 추출됐다. 자율 제안이 함께 적힌30%는 확정 의무비율로 표시하지 않는다.
- 로컬383개 회귀 검사·구조 계약 통과. 기존17사업 유지·반복 실행 재검증·수정/취소 보류·단계별 제목 연결·다른 금액/ID의 공통 추출 검사. 공개17상세와 목록320/390/1280px54조건 가로 넘침0. 운영 적용은 아래의 실제 실행 기록으로 구분한다.


운영 적용 확인: 소스93e4a14·검사환경 보완57bcea9. CI37731327828 전체 성공(383개 발견, 실패0, 원본 fixture 없는5개 명시 skip; PostgreSQL20개 통과). 실제 수집37731397319의3개 job 모두 성공, LP 수집·게시 계약128개 통과. 성장금융37건·첨부26개/본문19개·누락0건·조건 추출1건·추출 보류10건이며 우정7·교직원1·수은14건의 수집 오류0. 공개 실행f0c4f1ea7b12a24b4a758fcc·17사업 전수 Vercel 실행 일치 확인. IBK 일반매칭은11월 예정 일정과 펀드당20/50억원이 공개 화면에 반영됐다. 전체 형식 자동 추출 완료로 보고하지 않는다. 초기 CI는 PDF 테스트 라이브러리 누락으로 실패해 설치를 보완했고, 초기 수집 실행37731259559는 공개 전 취소했다. 평일09:20/15:20 정기 수집이 수정된 main을 사용한다.


<!-- LP release audit 2026-10-12 -->
## LP 정식 출시 준비 상태 확인 (2026-10-12)

사용자가 다음 작업과 정식 서비스 연결 시점을 질문했다. 새 출시 범위나 일정에 대한 승인은 아직 없다. 최근 수집 5회 성공. 오늘 실행38211276411은 성장금융38건·우정7건·교직원1건·수은14건을 수집하고 공개17사업을 유지했다. 공개 실행530fd37fe54903a27212c43d를 Vercel 목록·IBK 상세에서 확인했다. 성장금융 조건 공통 추출1건·추출 보류10건이며, 오늘 IBK 접수 현황도 수집했으나 기존 사업 자동 연결은 보류됐다. 뉴스레터 LP 메뉴는 여전히 Pages의lp-notices.html로 연결되고 신규LP는/samples/lp/ 및noindex 상태다. 수집 성공을 새 사업·새 단계 자동 반영이나 정식 메뉴 통합 완료로 보고하지 않는다.

다음 출시 과제 제안: 성장금융·우정·교직원·수은4기관 범위에서 새 사업/후속 단계 연결과 보류 처리를 마무리하고, 공식 LP 경로·공통 메뉴를 전환한 뒤 누락·장애복구·모바일을 검증한다. 전체 기관·과거 공고·GP 프로필 연결 완료는 첫 출시 전제와 구분한다.


<!-- LP scope expansion 2026-10-13 -->
## LP 출시 범위 확대와 공통 자동 수집 (2026-10-13)

사용자는 위의 4기관 출시 제안을 거절하고 PEF 블라인드 공식 공개모집 기관 전체를 빠르게 스크리닝하도록 지시했다. 4기관은 기존 수집 연결 상태이며 출시 범위의 상한이 아니다. GP 연결은 미루고 공고 수집에 집중한다. 우선 33기관·기금을 검토해 16기관의 PE 블라인드 모집 근거를 확인했고 국민연금·산업/기업은행·새마을금고 등 8기관은 우선 추가 확인 대상으로 유지한다. 근거 미확인을 공고 없음으로 단정하지 않는다.

범위·근거·실행 절차는 `docs/lp_contest_collection_scope.md`와 `data/lp_blind_contest_scope.json`을 따른다. KVCA·KOFIA 3개 게시판 공통 수집을 기존 정기 실행에 추가한다. 개별 공고 ID를 수동 등록하지 않고 목록에서 발견·기관 연결·범위 판정을 코드로 수행한다. 본문과 첨부 보존/검토 연결이며 금액·일정·새 공개 사업의 자동 승인과 구분한다. 로컬 실제 90목록→11기관25본문·17검토 후보·첨부 보류6, 회귀404개와 구조 계약 통과. 운영 반영은 해당 문서의 실행 기록을 확인한다. 공식 LP 메뉴 전환·새 후보 모집조건/단계 자동 연결은 아직 남아 있다.


LP 범위 확대 운영 반영: 소스9f0aa6a·저장 보완3e60f17, CI38393627395 성공(407개 발견·실패0·fixture 없는5개 skip, SQL20개 통과). 최초 실행38392502981은 PDF U+0000 문자로 DB 저장 실패하여 기존 공개본이 유지됐고, 문자 경계 보존 정리와 재현 검사로 보완했다. 후속38393786090은4개 job 모두 성공, 공통11기관25본문·17첨부본문·판독 보류6건, 기존 공개17사업/ID 전부 유지. 공개 실행1a3fd2330bb86406f0444396이 Vercel 목록·검토 및17상세와 일치. 목록/검토320·390·1280px 가로넘침·스크립트 오류0 및 신규기관/협회등록일 구분 확인. 수정된 main이 기존 평일09:20/15:20 정기 실행을 사용하며 수정 후 예약 실적은 아직 없다. 공식LP메뉴 전환·16기관 전부 모집조건/후속단계 자동 게시 완료는 아니다. 상세 근거와 남은 범위는 docs/lp_contest_collection_scope.md 참조.


## LP 원공고 추적·모집정보 자동 정리 운영 반영 (2026-10-14)

사용자의 계속 진행 지시로 협회 공고 안에 발견된 기관 원문을 자동 추적하고 금액·선정 수·펀드별액·주목적·예정 일정을 공통 코드로 정리했다. 기관/도메인/제목/연도/차수/단계 재검증, 일반·재공고 분리, PE·VC 합계/PE배분/표 합계 검산, 월·주차·월간 범위 원문 정밀도 보존 및 예정/완료 구분을 적용했다. 공고ID를 수동으로 골라 넣지 않는다.

소스109a3ef·CI38514076754 성공(427개 발견·실패0·fixture없는5개 skip, SQL20개 통과). 실제 수집38514223236의4개 작업 모두 성공, 공통25본문/11기관·기관 원공고1건(군인공제회7월31일)·모집정보4건 저장. 과기공 PE2700억/7곳, 군인 PE2000억내외/8곳·200~300억내외, 중기중앙회 PE·VC합계3000억이내/10곳·100~800억자율제안, 전문건설300억/1곳. 새 정보는 검토 화면에 반영하며 기존 공개17사업을 유지했다. 공개실행30d3fe1c438842b6089f1312. 외부320/390/1280px 일정/개요표8개·PEVC구분·원공고일자·예정 월간범위·가로넘침/스크립트오류0 확인. 기관 원문링크 없는14건·동적첨부목록1건·협회첨부 판독7건은 보류했다. 새공개사업/GP연결/정식메뉴 전환 완료가 아니다. 다음은 미연결 기관의 공식 게시판 발견 경로와 추가 모집문/첨부 형식 보완. 상세 근거와 실행기록은 docs/lp_contest_collection_scope.md 참조.

## LP 공식 게시판 원공고 자동 연결 확장 (2026-10-14)

과기공·중기중앙회·캠코·공무원연금 실제 목록/검색 경로를 연결하고 과기공 용역게시판/공무원연금 결과표 오지정을 수정했다. 관측된 목록 링크·JavaScript 인자를 파싱하고 기관/사업 제목/연도/차수/단계를 재검증하며 공고ID를 지정하지 않는다. 성장금융 기존 수집 원문을 재사용하고 신규 원문 본문 지문 검증/기존 raw 지문 호환/반복 저장 중복 방지를 적용했다. 동일 예정 월 표현 차이도 조건 누락으로 처리하지 않는다.

로컬4게시판41목록→신규 원문3건+기존 성장금융4건+군인1건=8건 연결, 대상15건 중7건 미연결. 공통25본문·모집정보4건 유지, 회귀437개/실패0·구조계약·320/390/1280px 넘침/스크립트오류0. 공무원연금 현재 해외공고와 캠코 대출형 범위 미확인은 국내PE 사업으로 추정하지 않는다. 운영 적용은 docs/lp_contest_collection_scope.md의 후속 실행 기록 확인. 정식 LP 메뉴·16기관 전부 최근 공고/조건/단계 자동 게시 완료가 아니다.

## LP 공식 게시판 확장 운영 확인 (2026-10-15)

소스99694cd·원문 표시 보완2c476eb. CI38684716879 성공(438개 발견/실패0/fixture없는5skip, SQL20개). 수동38565109885·정기38683732775·최종38684780853 모두4작업 성공. 공통25본문/11기관·기관 원문8건·모집정보4건·공개17사업 유지, 대상15건 중 미연결7. 공식4게시판41목록→신규 원문3건+성장금융 재사용4건+군인1건. 캠코 대출형과 공무원연금 해외공고는 국내PE 사업으로 추정하지 않는다.

공개 실행bd6c293793cbfc1df2f20b98. 검토 화면의 기관 원문8링크 모두 노출. 최초에는 모집정보가 있는3건만 보이던 문제를 수정했고, 원문 표시는 조건 추출/그룹 첫 자료와 독립시켜 테스트로 고정했다. 외부320/390/1280px 목록/검토6화면 최신 실행/17사업/8표/가로넘침·스크립트오류0. 서버17상세 실행 일치. DB 발행 반영이며 별도 앱 배포 없음. 수집 확장 정기 실행 확인, 표시 보완은 최종 수동 실행 확인. 정식 LP 메뉴·새 공개 사업 자동 승격·GP 연결은 미완료.

다음 작업: 성장금융4건은 최근38본문에 모집 원문이 없으므로 공식 검색폼(search_colume=Title/search_text CP949)으로 사업명→연도/차수/모집단계 검증→상세 수집. 선정 결과를 모집 원문에 연결하지 않는다. 고용/산재보험기금2건은 고용노동부 자산운용 공통 게시판 정적 상세 수집. 전문건설은 자체 동적 목록 요청 확인부터. 목록 후보 발견을 상세/첨부/PE판정 완료로 보고하지 않는다. 상세 근거·실행·QA는 docs/lp_contest_collection_scope.md 참조.
