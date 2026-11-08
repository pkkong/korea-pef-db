# 프로젝트 리드 현재 상태판

기관별 LP 구축 현황은 [LP 공고 수집 구축 현황](lp_collection_status.md)을 우선한다. 일반 현황 질문은 이 표로 답하고, 작업 완료 시 해당 행을 갱신한다. 아래 날짜별 기록은 이력이며 최신 구축 상태와 혼동하지 않는다.

최종 수정: 2026-11-02 KST

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

## LP 성장금융 검색·두 기금 원문 연결 구현 (2026-10-15)

다음6건 원문 탐색을 코드로 구현했다. 성장금융 기존 원문을 먼저 재사용하고 미연결 사업명만 CP949 공식 제목검색(최대8검색/첫페이지)→관측 링크→연도/차수/분야/모집 단계 재검증한다. 고용노동부 공통 목록은 캐시하고 기금명으로 고용/산재를 분리한다. 기관·공고ID/금액을 수동으로 골라 넣지 않는다. 공식 검색 proof는 발행기에서 다시 검사하고 원문 링크 노출은 조건 추출과 독립이다.

로컬 검색4회→성장금융 원문4/첨부4 판독+기금 원문2=원문8→14건, 대상15중1건(전문건설 자체 원문) 미연결. 모집정보4건/기존 공개사업 유지, 고용보험 HWPX 병합셀은 보류하며 unknown PE판정 유지. 검색이 수집 뒤에 실행되므로 발행시간으로 관측시각을 검증하고 수집시간은 별도 보존. 첨부 재판독 실패시 같은본문·같은지문은 이전 전체검증본 재사용, 변경/미확인은 이전본보존+hold. 새proof에 이전 텍스트를 섞지 않는다. 목록/상세 장애만 실행 실패로 구분한다. 독립 감사59개·전체454개 회귀 실패0/구조계약·모바일검사 통과. 소유 소스 discover_growth_originals.py/discover_lp_original_boards.py/collect_lp_original_notices.py/lp_shared_notice_catalog.py/publish_lp_programs.py 및 config/workflow. 운영 반영은 docs/lp_contest_collection_scope.md 후속 기록 확인. 정식메뉴/새공개사업/GP연결 미완료.

## LP 원문15번째 연결 최종 구현

성장금융/두 기금 확장은a4970a1·CI38717754178 성공(454개발견/실패0/5skip, SQL20개), 수동38717840965/정기38729369836 모두4작업 성공·공통26본문/원문14/모집정보4/공개17사업 유지·서버17상세 실행일치까지 확인했다.

마지막 전문건설은 공식 목록/상세API의 관측ntCode·원게시일/연도/단계/제목·본문 국내PE블라인드 확인을 코드로 수행한다. 6월/9월 유사공고는같은날짜여야연결하며 closed=1은보류, 새ID수동등록/제목변조/일반유사도완화없음. 원문JSON+지문/첨부경로를발행기재검증. 로컬 원문1/HWP3525자 추가→이번대상15건 원문연결완료/미연결0, 조건정리4/기존사업유지. 공동출자자 일반문구를 공동사업으로오인하던조건추출회귀수정. 독립27개·전체465개 실패0/구조계약/모바일검사통과. TLS검증우회없음, 번들Python CA문제와시스템Python실제검증은구분하며Ubuntu운영확인은후속기록참조. 소유discover_kfinco_originals.py/collect_lp_original_notices.py/lp_shared_notice_terms.py/config/workflow와테스트, 금지GP/뉴스레터/미관련dirty파일. 공식LP메뉴/새공개사업자동승격은남아있으며원문연결을정식출시완료로보고하지않는다. 실행/QA와다음작업은docs/lp_contest_collection_scope.md 참조.

## LP 전문건설 인증서 검증 환경 보완

d25fbe3/CI38848635676은465개발견·실패0/5skip/SQL20 통과했으나 운영38848738850은 전문건설 Ubuntu 인증서체인 확인 실패로 source outage에서 실패했다. 원문14/모집정보4/공개17사업은보존발행됐으며15건운영성공은아니다.

전문건설만macOS작업으로분리해truststore0.10.5의OS인증서검증을명시사용한다. SSLContext를HTTPSHandler에전달하며CERT_REQUIRED/호스트검증강제·전역SSL주입없음·TLS끄기/HTTP전환/임의인증서추가없음. 실패하던로컬번들Python도동일방식원문1/HWP1판독성공. 전체466개실패0/구조계약통과. 공통→전문건설macOS→산출물병합→성장금융재사용/검색→발행의5job, 미수신/실제접속장애는기존본보존+실패보고. 최종운영검증은docs/lp_contest_collection_scope.md 후속기록참조. 원문15/15를전국전수/새사업자동승격/정식메뉴완료로보고하지않는다.

## LP 재개 지점: GitHub 계정 실행 차단

829fbfc/CI38849847040 성공(466개발견·실패0·5skip, SQL20). 로컬 기존 실패환경에서 native TLS로 전문건설 원문1/HWP1 판독 성공. 운영38849900731은 GitHub 결제/사용한도 문제로 collect-kfinco/collect job이 코드 시작 전 차단돼15건 운영 반영은 미완료다. 계정 결제/예산 변경은 하지 않았다. 현재 실제 공개 e64fb1c05043a7c9410a1dbc·원문14/모집정보4/17사업, 외부320/390/1280px 6화면 넘침/스크립트오류0·8표·원공고일/PEVC/예정표기 확인. 로컬15와 운영14를 혼동하지 않는다.

사용자가 GitHub Billing & plans를 복구한 뒤 최신 main의 Collect LP programs를 전체 새 실행해야 한다. 38849900731 공통 산출물은 kbiz/geps/moel의 응답시간초과7건이 있어 실패job만 재실행해 재사용하지 않는다. 새수집/source outage→macOS --system-trust 실제검증→15원문/4모집정보/기존17사업/최신Vercel run/모바일까지 확인. 기관 응답지연 반복시 bounded retry/호스트별경로 보완, 장애은폐/추정승인 금지. 예산 임의증가/추가실행 반복 없음. 코드·검증·차단근거/남은작업은 docs/lp_contest_collection_scope.md 참조. 이 문서 변경은 코드가 같고 CI가 이미 통과해 중복 CI를 실행하지 않는다.


## GitHub 무료 실행 경로 복구 (2026-10-16)

사용자는 결제 설정 안내만 넘기지 말고 저장소 공개 전환 등 실행 가능한 해결책을 처리하도록 지시했다. `pkkong/korea-pef-db`를 공개로 전환했다. 현재/과거1,761개 blob의 알려진 인증키·개인키·비밀번호 패턴과1,569개 과거 텍스트 버전의 인증정보 리터럴을 제한 검사했고 실제 인증정보는 발견되지 않았다. 실제.env/DB/log 커밋 이력도 발견되지 않았다. KEXIM PEM은 공개인증서이며, 인물CSV는 출처가 있는 업무 약력이다. 보존126개 Actions 산출물은 LP 수집 JSON이며 일반 workflow의 secrets 출력/PR발행 경로는 추가하지 않았다. 제한된 패턴 검사는 모든 과거 로그의 비밀정보 부재를 보증하지 않는다.

GitHub 공식 문서상 공개 저장소의 standard GitHub-hosted 실행은 무료다. 결제수단·예산·요금제는 변경하지 않았다. 실제 복구 실행38857689603에서 기존에 코드 시작 전 차단됐던Ubuntu/macOS job이 시작됐고 우정 수집도 완료됐다. 위의 사용자 Billing 복구 대기 지침보다 이 실행 경로 복구가 우선한다. 기존 평일09:20/15:20 예약은 active다. 정식LP메뉴/전국전수/자동승인 완료와 구분한다. 수집·발행 완료 결과는 아래 후속 검증으로 기록한다.

운영 원칙은 AGENTS.md의 Automation Cost and Execution Failures에 반영했다. 불명확한 provider 오류를 추가결제 필요로 단정하지 않고, 반복 dispatch·예산증액 대신 사용 근거와 무료 대안을 확인한다. 표준 runner 외 유료 옵션·인증정보 공개·신뢰하지 않는PR의 secret 발행을 추가하지 않는다.


공개 전환 후 수동38857689603과 정기38894936059는 모든 job이 시작됐고 발행/Vercel17상세 검증까지 완료했다. 후자는 원문15/모집정보4/공개17사업·공통27본문을 유지했으며 공개실행8000d029aebdf64b95fa9886이다. 다만 두 실행 모두 KOFIA의 다른 목록/상세 요청이 curl25초 timeout28로 끝나 마지막 source-outage 검사에서 실패했다. 이를 전체자동화성공으로 보고하지 않는다. 결제차단은 해소됐고 남은 오류는 기관접속지연이다. 외부15원문링크와320/390/1280px 목록/검토6화면의 가로넘침/스크립트오류0·8표·17사업을 확인했다.

협회 HTTP 수집에 timeout/연결실패/일시적HTTP오류만 최대3시도,1/2초 backoff를 추가했다. 전체수집은 추가시도4회를 공유해 다수접속장애시 재시도가 계속늘어나지 않게 했다. 인증서/404/호스트/크기 오류는 재시도하지 않고, curl 실패의부분응답은버린다. 소진된오류는기존hold/실패보고로남긴다. 재시도 보완은 아래 후속 운영 실행으로 완료 여부를 구분한다.


## LP 수집 실행 복구 완료 확인 (2026-10-18)

최종 소스 e191b24(협회 재시도 c275f3e, 공통 수집 macOS 경로 ea55b1d). 마지막 실제 실행39025057650은5개 job 모두 성공했고, 공통9목록페이지 전부정상/27본문·원문15·모집정보4·공개17사업을 발행했다. 목록·상세·기관 게시판·성장금융검색·전문건설의 접속장애0건, 전문건설공식원문1/HWP1(3,525자) 실제 판독 성공. 공개실행662f4b794117b2e787adf5ed와17상세일치를서버에서검증했고, 외부원문15링크·320/390/1280px목록/검토6화면의넘침/스크립트오류0·8표를다시확인했다. 공통27본문/원문15는이번추적범위이며전국전수/조건완전자동해석/정식메뉴완료를뜻하지않는다.

재시도만 적용한39024301569는네트워크경로상KOFIA2/KAMCO2접속시간초과를남겨최종실패했지만기존15원문/17사업은보존발행했다. 공통수집을macOS로옮긴중간39024782156은발행전중단했다. if:always후속job이기본취소후에도시작돼발행단계가pending이고공식자료읽기중임을재확인한뒤force-cancel했다. 동시발행은없었다. 향후cancel시발행단계를확인하고쓰기중인job을무조건중단하지않는다.

KOFIA의기본curl요청은동일URL에서20초/0byte timeout이났으나HTTP/1.0·Mozilla UA·Connection:close를함께지정한요청은완전HTML52,079byte를받았다. 어느한옵션이단독원인인지단정하지않고, urllib부분응답오류뒤curl보완요청도브라우저형헤더·명시적연결종료를사용하도록맞췄다. TLS검증/공식호스트/용량제한·부분응답폐기는유지한다. 수정후실제서버의모든접속오류0건과발행성공을확인했다.

검증은로컬471개실패0,최종CI39025057418성공(471개발견·실패0·fixture없는5skip, PostgreSQL20개). 저장소PUBLIC,정기workflow active와평일09:20/15:20예약은유지한다. 추가결제/예산/요금제변경없음. 수정후실제성공은수동실행이며다음평일예약실적은아직없다. 정식LP메뉴전환/새사업자동승격/나머지기관확장은별도남은과제다. 계정복구대기또는운영14원문이라고쓴위기록보다이절을우선한다.


## LP 첫 출시 범위·일정 제안 (2026-10-18, 사용자 확정 전)

사용자는 뉴스레터 대비 LP 출시 지연을 지적하고 다음 작업과 공개 시점을 요청했다. 현재 수집 복구 이후 메뉴 연결·새 공고 공개 경로를 우선하는 출시 집중을 제안한다. 실서비스 브리프의 LP 메뉴는 아직 Pages의 lp-notices.html로 연결됨을 실제 HTML에서 확인했다. Vercel 신규 공고 서비스는 /samples/lp/·noindex다. 현재 공개17사업, 공통 수집자료11기관27본문, 연결된 기관 원문15건은 각각 다른 지표다. 27본문에는 VC/해외/미확인 자료가 있어 전부 PE 공개공고로 세지 않는다. 16기관 조사 범위는 유지한다.

제안하는 첫 출시 기준: (1) 공식 국내 PE 모집이 확인된 공고의 기관/제목/게시일/확인된마감/원문을 자동으로 목록에 반영하고, 모집 금액/선정 수/펀드당액/주목적/일정은 근거 확인된 항목만 추가한다. 첨부의 모든 조건 해석을 공고 노출의 일괄 전제로 삼지 않으며 범위 불명확/혼합/정정취소/중복·동일사업 불확실 자료를 임의 승인하지 않는다. 이 기준 변경은 아직 제안이며 게시 게이트를 낮추는 코드 변경은 하지 않았다. (2) 공식 Vercel LP 주소와 브리프/GP의 공통 LP 메뉴를 연결하고 과거 상세 링크를 보존한다. (3) 마감·정정/취소·새공고중복·모바일·장애시기존자료보존과 수정 후 정기수집을 최종 검증한다.

출시 작업에 집중할 경우 2~3일의 작업 분량, 10월20~21일 첫 공개를 계획 목표로 제안한다. 이는 확정 납기나 16기관의 모든 최근/과거 공고·자동조건해석 완료 약속이 아니다. 실제 수집 공고가 있는 기관의 확인된 PE 공고부터 공개하며 기관별 미연결 범위는 운영 문서에서 별도 관리한다. GP 연결/로그인/과거 전수복원은 첫 출시 선행조건에서 제외한다. 사용자 요청 전까지 이 제안을 승인된 일정이나 범위로 바꾸지 않는다.


## 서비스 독립 실행 전환 — 현재 작업

사용자 확정: 뉴스레터·LP·GP는 독립 서비스로 운영하고 사용자 메뉴/링크로만 연결한다. 메인은 뉴스레터·공통 순수자산·배포 전환, LP/GP Worker는 각 web 앱, Verifier는 분리 실행 검사와 구조 가드를 담당했다. 서비스별 app 패키지만 복사한 임시 폴더에서 다른 서비스 import/네트워크를 막아도 루트·health·CSS/JS가 동작하는 검사 통과. 로컬 전체489개 실패0, 구조검사 통과.

각 서비스 소스 services/{newsletter,lp,gp}/web 및 별도 배포 workflow를 준비했다. 공통 CSS/JS/icon은 services/shared/web/service_assets.py 단일원본에서 각 앱에 포함한다. 뉴스레터의 LP/GP adapter·eager import·빌드/검증 의존은 제거하고 옛 주소는 외부 redirect만 한다. 기존 버전관리 GP XLSX를 GP web/downloads로 같은 바이트 이동했다. LP17사업·원문15/GP snapshot·뉴스 아카이브 DB는 이번 전환에서 수정하지 않는다.

배포 목표: 기존 kpef-newsletter + 별도 kpef-lp/kpef-gp Vercel 프로젝트. 각 배포는 자기 앱 파일과 공통 자산만 업로드하고 다른 서비스의 코드/검사를 요구하지 않는다. 기존 프로젝트의 Git 자동배포 여부와 root/framework를 read-only workflow로 먼저 확인한다. 실제 전환은 후속 배포 기록 전까지 미완료다. Supabase 물리서버는 공유 상태이며 서비스별 독립 public read 설정을 지원한다. DB서버/플랫폼 공통장애까지 없어졌다고 보고하지 않는다.


## 독립 서비스 운영 전환 완료

별도 Vercel 프로젝트 LP `https://kpef-lp.vercel.app`와 GP `https://kpef-gp.vercel.app`를 생성·배포했다. 소스 ea2a2b4, 배포39180815345/39180817060 성공. 뉴스레터는 ccc1ea9/배포39181128037 성공으로 LP·GP import/실행/빌드 의존을 제거했다. 옛 LP/GP 상세·시장·인물·엑셀9경로는 query를 보존하는307로 독립 앱에 연결한다. 메뉴도 각 공식 서비스 주소를 사용한다. Git 자동배포를 끄고 서비스별 workflow로 자기 앱만 배포하며 각 health의 release SHA까지 대조한다.

검증: 로컬490개 실패0, CI39181111322는490개 발견·실패0·로컬fixture없는5skip 및 PostgreSQL20개 통과. 다른 두 서비스 코드/네트워크가 없는 패키지의 자기 루트·health·assets 실행을3서비스 모두 검사했다. LP/GP 외부18화면(목록/상세/검토 또는 시장×320/390/1280px)의 넘침·스크립트오류·뉴스레터 CSS/JS 요청0. LP17사업/17상세·기관원문15·공개실행662f4b794117b2e787adf5ed, GP snapshot fss-2025q4-ec864d1a2f16-91fd1930ab37 유지. GP397개 목록 및 기존 XLSX2587467bytes SHA 동일. 뉴스레터30호/최신15기사 아카이브 JSON과 순서가 전환 전후 완전히 같다. 뉴스레터3화면320/390/1280px 넘침/스크립트오류/타서비스 요청0, 과거기사·검색도 후속 점검했다. 검증 산출물은/tmp에만 보관했다.

초기 LP/GP bootstrap 배포39180729017/39180731367은 아직 커밋되지 않은 공통 검사 파일을 실행하려다 배포 전 실패했다. 자기 앱의 분리 실행 검사만 쓰도록 고쳐 위 최종2실행 성공을 확인했다. 실패신호를 숨기거나 자료발행을 다시 실행하지 않았다. 이번 작업은 앱 코드와 배포 분리이며 Supabase DB 내용·수집 예약·발행 게이트를 바꾸지 않았다. LP noindex 유지, 새사업 자동승격·16기관 수집완성·정식출시 완료와 구분한다. 다음 LP 제품 작업은 기존 출시범위의 확인된 신규공고 노출/정정·마감 처리다. 공유 Supabase 서버/Vercel 계정 장애는 여전히 공통위험이다.


## LP 기본 공고 자동 공개 운영 반영 (2026-10-19)

사용자가 승인한 다음 목표는 공식 PE 모집의 기본 공고 자동 공개, 정정·취소·마감/후속 단계 반영이며 GP 프로필 연결은 미룬다. Worker는 협회 HTTP200 불완전 HTML 복구, Verifier는 단계 분류/원천 조사·검사, 메인은 기본 공개·일정·발행 통합을 맡았다. 공고 ID를 골라 넣거나 신규 GP 명단을 작성하지 않았다. 기관별 현재 상태는 docs/lp_collection_status.md를 우선한다.

소스8c454aa에서 기관 원문/검증된 PE 트랙으로 기본 공고를 공개하도록 연결했다. 금액·주목적·GP가 없다고 공고를 숨기지 않으며 모호한 범위·차수는 보류한다. 과기공 PE2700억/7개사내외, 군인 PE2000억내외/8개사내외, 전문건설 PE300억/1개사 사업3건을 자동 추가해 기존17→20사업. 우정 국내PE의10/12 1차심사 결과를 GP 추정 없이 연결했다. 기존17ID/주소 모두 유지.

실제 수동39253406656은5job성공·공개fdce06b4497c9aba151bda12. 외부 화면 검사에서 월 단위 예정 심사가 같은 달 접수 마감보다 앞에 놓이던 정렬/완료된 단계의 옛 예정 표시를 발견해72e8b1b로 고쳤다. 68cda73은 일반적인 운용 목적을 주목적 투자로 재표시하지 않게 했다. 최종 수동39254941732도5job성공, 같은20사업/ID를 중복 없이 유지하고 공개c7c719a6dec70bc85d1ba74f 및20상세 응답 일치를 확인했다. 금투협 포함협회9페이지·원공고/첨부 접속장애0, 보존27본문/11기관·원문15·모집정보4 유지. 자료 갱신과 전체기관 구축 완료는 구분한다.

최종CI39254827993 성공(526개발견/실패0/로컬fixture없는5skip, SQL20), 구조검사통과. 공개15화면320/390/1280px의 가로넘침·스크립트오류·뉴스레터CSS/JS요청0, 기존URL과 신규기관원문 연결을 확인했다. 예약09:20/15:20은 유지하며 최종코드의 수동실행 성공과 이후예약실적은 구분한다. 이번반영은 LP DB HTML발행이고 별도앱배포/뉴스레터/GP변경없음. 소스외/tmp검증산출물은커밋하지않았다. 다음은 미연결기관 공식수집 및 모호한후속차수/혼합트랙 보완이다.


## LP 4기관 직접 수집 연결 — 2026-10-20

- Source `b3ce6a7`: 지방행정공제회·경찰공제회·사학연금·신협중앙회의 관측 목록→상세/첨부 수집, 출처 재검증, 기본 공고 공개를 LP 전용 경로에 추가했다. `68625bf`는 단일 트랙 펀드당 출자액/한도를 기존 모집 개요에 표시한다. 기관별 설정은 `data/lp_institution_board_channels.json`, 보존 자료는 `institution_notices`다. 신규 코드는 Newsletter/GP 빌드나 배포를 요구하지 않는다.
- 수집 정책: 실행 연도 포함 최근 4개 연도, 설정된 검색/페이지, 기관별 상세 최대30건. 고정 공고ID 선정·VC/해외/공동투자 합계의 PE 오표시·GP 추정 금지. POBA는 동일 세션 쿠키로 공식 첨부 수신. 경찰공제회 현재 공공 경로는 `www.pmaa.or.kr`이며 예전 조사본의 `policefund.or.kr` 호스트와 구분한다.
- 마지막 예약 실행39261750198은 자료20개 발행/검증 후 금투협 안내게시판의 `HTML encoding not recognized`를 보고하며 실패했다. 엄격한 판독은 유지하고 불완전 멀티바이트 응답을 기존 제한 재시도/HTTP1.0 전체 복구 경로로 보냈다. 잘못된 응답을 성공으로 처리하거나 알림/예약을 끄지 않았다.
- 로컬 검증: 실제14본문·5개PE공개 재생, 첨부/목록/날짜 변조·중복·실패 시 보존·PEVC 분리·마감 시각 충돌 검사. 전체569검사 실패0, 구조 검사 통과. Source CI39370057972 성공. 로컬 결과와 운영 발행 결과는 아래 최종 검증 기록에서 구분한다.

- 재실행 `39370234728`은 25개 사업 발행과 모든 상세 검사 후 KFINCO API의 일시 DNS 오류 1건을 최종 장애 보고로 남겼다. 새 4기관의 14본문·첨부 10건은 무보류였다. Source `aa30098`은 KFINCO 목록·본문·첨부 전송에만 URL당 최대 3시도, 실행 전체 추가 4시도, 1/2초 대기를 적용한다. 인증서·호스트·404·본문 검증은 재시도하지 않고 영구 실패는 기존 보류를 유지한다. 최종 운영 복구 결과는 아래에 기록한다.
- 외부 화면 검증 Source `68625bf` / 공개 `6e53ed1f052852e5c4b752a9`: 25개 상세 주소와 320/390/1280px의 21개 화면에서 가로 넘침·JS 오류·뉴스레터 원격 자산 의존이 없었다. 기존 20개 주소를 유지했다. 신협 500억/300억원은 펀드당 한도이며, 경찰공제회 PE 1,200억원·3개사·펀드당 400억원, 행정공제회 Buyout·Growth 2,000억원 이내·4개사, 사학연금의 2023년 금액·선정 수·기한을 확인했다.

- Source `54a3d1d`: KFINCO 정상화 뒤 공무원연금에서 같은 DNS 오류가 발견되어 `lp_transport_errors.py`로 실제 resolver 예외 분류를 공통화했다. 기관 원문은 DNS에만 최대3시도, 협회/신규 기관은 기존 예산 내에서 같은 분류를 사용한다. KFINCO는 공통 단일 수신 함수를 가져와 재시도 중첩을 방지한다. 해당 집중 검사73개 및 구조 검사 통과. 재실행 `39371364680`의 공무원연금 오류와 최종 검증 실행 `39371835704`를 구분한다.

- 최종 운영 검증: [39372462106](https://github.com/pkkong/korea-pef-db/actions/runs/39372462106), Source `ac0387d`, 6개 작업 모두 성공. 공개 `90272c64a8693210830544a5`의 25개 사업이 첫 발행과 같은 ID로 유지됐고 모든 상세와 마지막 장애 보고를 통과했다. 4기관14본문/첨부10건/PE5사업, 발행 출처 오류0이다. 최종 CI39372462381는584개 검사 중 실패0·오류0·fixture5skip, PostgreSQL20개 및 구조 검사 통과. 운영 반영 방식은 LP DB 발행이며 Newsletter/GP 배포·DB 변경 없음. 이후 일상 현황 답변은 `docs/lp_collection_status.md`를 따른다.


## LP 추가 3기관 수집 및 운영 차단 확인 — 2026-10-20

Source a5ebdbe: 새마을금고 MG공지, 산업은행 JSON 검색/상세, 기업은행 검색/상세의 관측 기반 어댑터와 공통 출처 재검증을 연결했다. KFCC Worker와 정책은행 Worker가 각각 순수 파서를 작성했고 Lead가 설정·범위·PE 판독·통합을 맡았다. 로컬55본문/첨부56건에서 새마을금고2025 PE4400억원·10개사를 VC600억원과 분리했다. 산업은행은 올해38건(50상세 한도), 기업은행12건이며 혼합·공동사업을 공개하지 않는다. 공고ID 허용목록, GP 추정, TLS 완화는 없다.

운영39439295391은 은행50본문/첨부52건을 포함한 기관64본문을 저장하고 공개760b534aea4e220d5b568508의 기존25주소를 보존했다. 기관 출처 검증오류0. 25상세/모바일 포함 외부6화면에서 누락·넘침·JS오류0이다. 새마을금고는 GitHub 목록2요청이 HTTP400으로 차단되어 공개 추가0이며 최종 장애 보고 실패를 유지했다. macOS39440254245/Linux39440491869 진단의 일반·브라우저헤더·세션·curl 모두 Request Blocked를 재현했다. 운영 수집 완료 기관으로 분류하지 않는다. 전문건설은 전용 native TLS 경로의 이번 운영 성공과 이전 예약 HTTP400 원인 미확인을 구분한다.

CI39439261862:619검사 실패0/오류0, 로컬 원본 fixture없는5skip, PostgreSQL20개 및 구조검사 통과. 새마을금고 상세는 로컬320/390/1280px에서 금액범위와 일정 표시를 확인했으며 운영 공개가 아니다. 앱 배포나 Newsletter/GP DB 갱신은 없었다. c7c1164/b18a639는 비밀 없는 수동 HTTP 진단 workflow다.

현재 상태는 docs/lp_collection_status.md, 첫 공개 완료 기준은 docs/lp_first_release_checklist.md. 17근거확인 기관=직접운영8+부분연결8+KFCC차단1, 별도미확인7(은행2곳은 원문만 운영 수집). 다음은 KFCC 공식 대체 경로/실행 환경과 예약 오류 추적·실제 예약 성공이며, 추가기관·GP·과거전수복원을 끝없이 출시 선행조건으로 늘리지 않는다. 로컬 완성/수동 운영 발행/실제 예약 성공/정식 공개 완료를 구분한다.


## LP 새마을금고 운영 차단 해소·발견 대조 — 2026-10-21

- 역할: Worker는 벤치마킹 공개 구조 조사·독립 대조 모듈·KFCC 전용 전송기, Verifier는 경계와 검사, Lead는 공식 전송 연결·배포·실제 발행·외부 검증을 맡았다. 완료된 Worker를 상시 담당자로 남기지 않는다.
- 벤치마킹 근거: 공개 pe-vc-lp.com은 자동 감지 API, 자체 PDF, 별도 구조화/핀 자료를 함께 제공한다. 핀 56건만 코드에서 수동 관리로 명시된다. 전체 133개 구조화 자료의 수작업 비율·내부 크롤러 주기·실행 위치는 미확인이다. 브라우저 30초 갱신은 서버 수집 주기가 아니다. 195개 감지 자료에는 VC·해외·주식도 섞여 우리 PE 사업 수와 비교하지 않는다.
- Source `3d79002`/`fc318c1`: 공식 보관 문서의 기관·제목·원문을 읽기 전용으로 대조한다. 별도 실행 `39535351474`와 실제 수집의 비교 단계에서 성공했다. 195건 중 기보유 56건, 원문 확인 후보 13건, 범위 외 23건, VC 명시 2건, 기관 미연결 101건이다. 후보 수를 확정 누락 PE 사업으로 읽지 않는다. 외부 금액·마감·결과로 사업을 승인하지 않는다.
- 지역 측정 `39535351502`: 서울 `icn1`에서 KFCC 목록 200/64,017bytes. 전문건설은 Node 인증서 체인 실패로 기존 경로를 유지했다. 임시 프로젝트는 제거했다. KFCC만 고정 공식 경로·기계 인증·20초·3MiB·리다이렉트 금지·기본 TLS·응답 SHA256을 적용해 별도 `services/lp/collector`로 배포했다.
- 전송기 배포 `39536359018`/Source `8e032ec` 성공. health의 지역/release, 공식 목록 3행, 무인증 401을 확인했다. DB 키나 다른 서비스 코드를 포함하지 않는다. 전문건설을 옮기거나 TLS 검증을 완화하지 않았다.
- 운영 `39536759687`/Source `8e032ec`: KFCC 5본문·첨부 4건·지역 수신 11회·해당 보류 0. 현재 66본문 수신과 이전 신협 3본문 보존으로 운영 문서 69건, 출처 검증 오류 0이다. 공개 실행 `f2f791d798917ce11b7d22e9`의 26사업/26상세와 기존 25주소 보존을 확인했다.
- 새 사업 `kfcc-2025-cdf0424918597361`: 2025년 PE 4,400억원/10개사, VC 600억원 제외, 펀드당 500~700억원/300~500억원, 마감 2025-05-14 14시와 주 단위 일정을 보존했다. 외부 320/390/1280px 9화면에서 넘침·JS 오류·Newsletter 원격 자산 의존 0. 검증 자료는 `/tmp/lp-kfcc-live-*`에만 둔다. LP DB 발행이며 Newsletter/GP 앱·DB·배포는 변경하지 않았다.
- **같은 운영의 최종 결과는 실패**다. 신협 목록 2요청이 제한 재시도 후 macOS DNS `Errno8`로 실패했고 기존 자료는 보존했다. 같은 시각 로컬 주소 조회/HTTPS 200은 해결 완료 증거가 아니다. 이번 협회/공무원연금/전문건설의 정상 수집과 이전 예약 장애의 원인 해결을 구분한다.
- 다음 작업: 신협 실행 경로 진단과 실제 예약 성공 확인. 09:20/15:20 예약 및 실패 알림을 유지한다. 수정 이후 예약 성공은 미확인이다. 새 기관·GP·로그인·과거 전수를 출시 선행조건으로 늘리지 않는다.
- 검증: Source `8e032ec`의 CI `39536302246`은 646검사 중 실패 0·오류 0·원본 fixture 없는 5skip, SQL 20개 및 구조 검사 통과. Node 전송기 16검사 통과. 기관별 현황과 끝내는 기준은 `docs/lp_collection_status.md`와 `docs/lp_first_release_checklist.md`를 따른다. KFCC를 직접 운영으로 전환해 목표 17기관=직접 9+부분 8, 추가 확인 7기관을 유지한다. 다른 사용자 수정과 생성물은 이번 커밋에서 제외한다.


## LP 공통 DNS 복구·동일 출처 시험 순차 실행 — 2026-10-21

- 사용자 다음 작업은 신협 DNS 오류 대응과 실제 수집 확인이다. Lead는 진단/수집 통합을, 재사용한 Verifier는 DNS·전송 경계·Python3.12 검사를 읽기 전용으로 점검했다. 파일 소유 충돌이나 다른 서비스 작업은 없었다.
- `cabcaaf`: 신협 typed DNS 오류 후 기존 두 번째 직접 시도를 native IPv4로 바꿨다. `d8a3493`: 산업은행에서도 같은 DNS 오류가 관측돼 직접 기관 Session에 공통 IPv4 HTTPS 연결을 추가했다. 같은 CookieJar·OfficialRedirect와 hostname/SNI/TLS context·12MiB·20초를 유지한다. CU native 경로는 검증된 별도 경로로 남긴다. KFCC 기존 지역 전송이 결합될 수 있어 직접 시도2회라고 설명한다.
- `f740c2d`: 실제 공식 사이트를 호출하는 시험과 운영 수집에 같은 `lp-program-collection` 동시 실행 제한을 적용했다. 지역 오류에서 비밀이나 원문 응답 대신 허용된 실패 분류만 남긴다. Vercel source worker의 배포는 기존8e032ec를 유지하며 다른 앱을 배포하지 않았다.
- DNS 진단39538352277(mac)/39538354721(linux)은 CU 모든 방식70,830bytes·동일해시. KDB 로컬 기존/IPv4도108,454bytes·50행·동일해시였다. IPv6 원인이나 과거 resolver 오류 원인으로 단정하지 않는다. Ubuntu 전체39539271911은 다른6기관 정상, KDB TLS EOF 다수로 실패해 macOS 운영 경로를 유지했다.
- 오류 주입 검증39538729812는 CU3본문/첨부2건/native7회 성공. 공통 주입39540076779는 다른6기관64본문 성공이나 KFCC502로 전체 실패. 단독39540604127은 KFCC5본문/첨부4건/지역11회 성공이다. 주입 시험은 DB를 수정하지 않았으며 실제 오류를 재현했거나 단일 전체 실행이 성공했다고 표현하지 않는다.
- 실패한 운영39538727449(Source cabcaaf)는 CU 정상·KDB DNS3건 실패,26사업 공개9287c167bc3df157d7c7eff9. 운영39540079421(Source d8a3493)는 KDB 포함6기관 정상·KFCC502 실패,26사업 공개98ecd9acb76e70774d417de0. 문서69건과 기존26주소를 유지했다. 동시 시험이 KFCC502 원인이라는 증거는 없으며 가설로만 남긴다.
- 최종 운영39541070805(Source f740c2d): 이번69본문/첨부66건, 직접7기관 목록·본문 접속 오류0, KFCC지역11회·CU/native와공통DNSIPv4실행0. 산업은행 ZIP1건은 기존 추출 한도 보류. 최종6job 모두성공·출처검증오류0·공개b3f32c8c93be9b605f2339d4/26사업. 외부26상세와320/390/1280px12화면의 기존URL누락/넘침/JS오류/타서비스원격자산의존0. 신협 소형300억원·중형500억원 펀드당한도/2025년/공식원문/일정우선 표시도대조했다.
- CI39540576622:659검사 실패0/오류0/원본fixture5skip·SQL20·구조검사 통과. Verifier의Python3.12 전송25검사 통과. 최종 판단 전후 현황은 docs/lp_collection_status.md, 첫 공개 완료 기준은 docs/lp_first_release_checklist.md를 따른다.
- 다음은 수정 후 실제 예약 수집의 성공 확인과 중간 오류 재발 관찰이다. 예약09:20/15:20과 알림을 유지하고, GP·로그인·과거 전수·새 기관을 새로운 출시 선행조건으로 늘리지 않는다. 생성 자료는/tmp에만 두고 이번 소스/문서 외 사용자 수정은 커밋하지 않는다.

## LP 공식365일 대조와 검색 보완 — 2026-10-22

현재 기준은 `docs/lp_collection_status.md`와 `docs/lp_first_release_checklist.md`다. 목표17기관(직접9·부분8)과 추가 확인7기관은 유지한다. Source2a9ab98은 우정의 기본6개월을365일 공식 검색으로 바꾸고 공고번호 역산을 제거했다. 실제3페이지29행·대상8본문 수집을 확인했다. 사학은 제목+100개 보기500을 재현하고 제목 조건을 유지한10개 보기로 변경했다. 단독39757288009에서4본문·첨부1건·보류0을 검증했다.

공식365일 대조39757334051은 사학 정상 조회 후 신협 DNS/nativecurl exit6으로 실패했다. 24대상 중10측정·미측정14(미연결13+신협1), 미보관 제목105개=미확인73·범위 외31·VC1이다. 전체시장 수집률을 계산하지 않고 미측정을0으로 바꾸지 않는다. 기업은행 반복 페이지도 남긴다. 모든 공식 목록 응답은7일 artifact이며 DB 읽기 전용·운영 수집과 같은 대기열에서 처리한다.

예약39596498662·39725799934는 각6작업 성공했다. 이후 수동39754788986은26사업 발행·26상세 검증·69문서 보존 후 사학500으로 실패했다. source2a9ab98의 전체 실행39757590691은 아래 후속 기록을 따른다. 로컬685검사·구조 검사·CI39757268895 성공. Newsletter/GP/화면 소스는 변경하지 않았다.

후속39757590691은69문서 정상 수집·26사업 발행 후 과거 사학100개 기록4건의 설정 불일치 검증 오류로 실패했다. Source def2ce7은 과거100개 보기 검증 경로만 보존하며 신규 수집은10개를 유지한다. 실제 이전/새69개 합치기에서69개 유지·검증오류0, 전체686검사·구조 검사·독립검토 통과. 최종 전체 실행 결과는 아래 기록을 따른다.

최종 source def2ce7/39759525879: 새69문서 수집, 공개ac06ebdf86730aa1eab881c0의26사업·주소 유지·상세 검증 성공·출처검증오류0. 다만 전문건설공제조합 공식 목록 API HTTP400으로 최종장애보고 실패다. 다음 우선순위는 해당400 진단과 신협DNS 재발 관찰이며 전체 수집 완료로 표시하지 않는다. Source CI39759487120/686검사 통과. 상세 근거는 최신 LP status/checklist를 따른다.

## LP 전문건설공제조합 수집 복구 — 2026-10-23

- 담당 범위는 LP 수집/전송기다. Newsletter/GP·공개 화면·로그인·GP 연결은 변경하지 않는다. 이전 로컬 화면 수정은 이번 소스 커밋에 포함하지 않았다.
- Source `f4f0dca`: 운영 macOS의 특정 HTTP400만 인증된 서울 전송기로1회 보완한다. 공식 API·관측된 상세NT코드·첨부 경로를 코드로 제한하고 기존 원문 근거 판독을 유지한다. 서버 누락 중간 인증서1장은 Sectigo 공식 배포본 지문 고정·원래 Node루트 유지·partial-chain 금지·호스트명 검증으로 처리한다.
- [전송기39953102438](https://github.com/pkkong/korea-pef-db/actions/runs/39953102438)에서 실제서울 실행·release 일치·전문건설3행·새마을금고3행을 검증했다. 전체 운영 [39953198641](https://github.com/pkkong/korea-pef-db/actions/runs/39953198641)은6작업·발행·26상세·최종 장애 보고까지 성공했다. 공개실행 c8cc8460b48e4afa176ae040의26사업·기존주소·69직접 문서를 유지하고 출처 검증 오류0을 확인했다. 전문건설 원문1건/HWP1건/보류0이다. 임시 진단39900053732는API200·TLS authorized를 확인했고 임시 프로젝트를 삭제했다.
- 최신 예약39948898031은 전문건설HTTP400과 신협DNS 재발을 기록하며실패했다. 이후 수동 복구로 이 실패를 지우지 않는다. 예약 성공 여부와 기관별 범위는 `docs/lp_collection_status.md`를 우선한다.
- 검증: Python691검사·Node25검사·구조 계약 검사 통과. 명령 `node --test services/lp/collector/tests/*.test.js`, `scripts/run_regression_tests.py`, `scripts/check_architecture_contracts.py`. 배포 workflow도 Node전체 검사를 실행한다. 모든 실제 공식 호출은 같은 수집 대기열을 사용한다.

- 다음은 신협DNS 재발 대응·수정 이후 예약 확인이다. 이번 신협3본문/첨부2건은 정상 수집했지만 과거DNS 원인은 미확인이다. 산업은행 ZIP1건 추출 한도 보류와 부분 연결8기관·추가 확인7기관은 남긴다. 최신 세부 근거는 status/checklist를 따른다.

## LP 신협 DNS 복구 보완 — 2026-10-23

- Source `65b63d4`: 첫 DNS 오류와 두 번째 native curl exit6이 이어질 때만 서울 전송을 한 번 사용한다. 일반 HTTP·TLS·내용 오류로 확대하지 않는다. 공식 경로, 지역, 해시, 3MiB, 기존 판독 검증을 유지한다. Newsletter·GP·화면·DB 구조는 변경하지 않았다.
- 배포39957331933에서 CU/KFCC/KFINCO 공식 목록을 각각 3행 검증했다. Source `0fbde97`의 오류 주입39957487910은 실제 서울 7요청으로 3본문·PDF 텍스트 2건·출처 검증·보류0을 확인했다. 이 시험은 DB 쓰기가 없고 실제 DNS 발생이나 예약 성공과 구분한다. 임시 진단39956931281 프로젝트는 삭제했다.
- Python698·Node29 검사와 구조 계약, CI39957478244를 통과했다. 일반 운영39957583501은 신협3본문/첨부2건, 공개26사업/기존26주소, 보관69문서, 출처오류0을 확인했다. 공개 실행은 `43ad76d6acf410d0c64b3dc2`이며 외부26상세 검증도 통과했다.
- 전체 실행은 산업은행3목록의 DNS Err8로 실패했다. 이번 새 직접본문31건과 이전 산업은행38건을 구분한다. 산업은행의 두 번째 요청도 Python getaddrinfo(AF_INET)를 쓰므로 조회 경로는 같다. 다음은 DNS 조회 부분의 별도 경로를 검증하되 기존 HTTPS/SNI/TLS·쿠키·리디렉션을 보존하는 범위다. 신협 curl을 그대로 확대하지 않는다. 고정 IP·임의 CA·무조건 재시도는 금지한다. 이후 예약은 미확인이며 최신 세부 현황은 `docs/lp_collection_status.md`를 따른다.

## LP 산업은행 주소 조회 및 벤치마크 식별 — 2026-10-24

- Source ad3dea5는 KDB 두 번째 IPv4 DNS 오류에만 별도 HTTPS DNS를 사용하고 기존 원서버 HTTPS/SNI/TLS·쿠키·리디렉션을 보존한다. DNS5초/16KiB·공인주소·질문/CNAME 검증·재시도0을 적용한다. 다른 기관과 원서버 IP를 임의로 확대/고정하지 않는다.
- 실제 시험40061487286은 두 Python DNS 조회만 실패시킨 뒤 실제38본문·첨부44건·출처검증38건·텍스트44건을 확보했다. 대체조회86회이며 기존 ZIP 크기 한도1건만 보류다. DB 쓰기 없는 시험이며 자연발생 DNS 복구와 구분한다. CI40061484513·710검사·구조 계약을 통과했다.
- Source7ea36c4는 벤치마크의 CSV 기관 식별과 수집 정책을 분리한다. 대상 밖 기관을 식별해도 공개나 already_known으로 처리하지 않는다. 교차 범위 동명이름·제목 차용을 거절한다. 미분류100건의 오프라인 재분류에서53건을 식별했고47건은 미확인이다. 통합715검사 통과. 수정 후 전체40061956429는6작업·자료발행·외부26상세·최종장애보고까지 성공했다. 공개 실행a38db28a13c7638a8733f293의26사업·기존26주소·출처오류0을 확인했고 직접본문69건 모두 새로 받았다. KDB38본문/첨부44건은 이번 기본 경로에서 정상이며 대체DNS횟수0이다. 이전 DNS 원인 해소나 이후 예약 성공을 뜻하지 않는다. 실제 대조195건은 보관57·대상밖기관식별53·미분류47이며 식별 개선을 신규수집으로 세지 않는다.
- 작업 기준은 docs/lp_collection_status.md, docs/lp_collection_delivery_plan.md다. 사용자에게 최근1년 국내PE 기준 추가5~7작업일을 추정으로 설명했다. VC 전체·모든 과거·GP·로그인은 포함하지 않는다. 다음 실자료 묶음은 대조 후보12건 중 성장금융9건의 날짜 기준 탐색/공식 검색 보강이다. 총회연금1건의 지속 발견과 수출입/과기공 각1건의 공식 범위 판단을 별도로 다룬다. 감지시각을 공식 게시일로 쓰거나 이12건을 누락PE12사업으로 확정하지 않는다.
- 로컬 /tmp 테스트 패키지가 정리돼 Flask·olefile이 빠진 첫 전체 실행은 환경 오류로 실패했다. 프로젝트 요구 패키지를 /tmp/lp-kdb-test-deps-20261024에 다시 설치한 뒤 전체715검사를 통과했다. 소스에서 검사를 우회하지 않았다. GitHub CI는 별도 설치 환경의 결과를 따른다.

## LP 성장금융 최근1년 탐색 운영 반영 — 2026-10-24

- Source0fcf19b는 성장금융 공식 게시일365일/최대20페이지 탐색을 구현했다. 고정 공지 제외한 일반공고의 오래된 경계를 관측해야 완료이며 반복·한도·불완전 날짜를 완료로 처리하지 않는다. 공식 목록 파서는 감사와 수집이 공유하고 기존 tracked/승인 자료를 계속 확인한다. 새 공고ID를 골라 넣지 않았다.
- 발행 없는 실제40102265477은13페이지·114본문·첨부100개를 확보했다. Source29e3070을 정기 운영에 연결한 전체40102899629도6작업·DB발행·26상세·최종장애보고까지 성공했다. 공개 실행5d40ded750f018f38af5b0e7의26사업·이전26주소·직접69본문·출처오류0을 확인했다. 앱 배포나 Newsletter/GP/화면/DB구조 수정은 없다.
- 성장금융38→114본문으로76문서를 추가했고 기존 누락0이다. 추가76문서는 모집18·후속/FAQ40·제출서식18이며 모두PE사업으로 세지 않는다. 벤치마크 성장금융36문서는 전부 공식 보관, 전체195표본 보관57→66이다. 새 공개PE사업은0이며 기존26개를 유지했다. 수정 이후 예약 성공은 아직 미확인이다.
- 첨부 미판독26개를 다음 작업으로 잡기 전에 유형을 확인했다. 서식24·기업 안내1·이미 별도 HWP를 읽은 모집 ZIP1이어서 일괄 ZIP 판독은 우선순위에서 제외했다. 관련 규칙을 agent_operating_briefs에 기록했다. 다음은 총회연금의 지속 발견 및 나머지2후보의 공식 범위 판단이다. 총회연금 결과는 같은 게시물이 기존 공개 사업에 연결되어 있으므로 대조 후보를 확정 누락PE로 부르지 않는다.
- 로컬731검사·구조 계약·CI40102855032·PostgreSQL20검사 통과. 기관 범위와 일정 기준은 docs/lp_collection_status.md 및 docs/lp_collection_delivery_plan.md를 따른다. 최초10월24일5~7작업일 추정을 매 대화 초기화하지 않는다. 별도 검토 담당은 한도 오류로 작업하지 못해 Lead가 구현·전체 검증·운영 확인을 통합했다. 다른 사용자 수정과 생성 자료는 커밋하지 않는다.

## LP 총회연금재단 자동 수집 및 새 모집 공개 — 2026-10-25

- Source67726e3는 PCK 공식 제목검색·목록/본문/첨부 재판독을 연결하고 WordprocessingML 본문을 제한적으로 읽는다.3검색목록·6본문·공고문3개(엑셀3개 제외)를 실제40105083040에서 검증했다. 고정 공고ID는 없다. 원서버 HTTPS/쿠키/게시판·파일명/12MiB·공고문 ZIP 한도와 원문 재판독을 유지한다.
- 새10월22일 모집과7월 모집의 제목이 같아도 게시물별로 분리한다. 자산군별 별도 제출이 확인된 PE 블라인드 트랙을 기본 공개하며 전체500억원/1,000억원을 PE 배정액으로 쓰지 않는다. 마감10월29일17시·1차11월6일·2차/최종11월10일(예정)을 원문에서 추출했다. GP·목적·선정 수를 새로 추정하지 않는다. 원공고 연결이 불명확한2025결과2개는 보류한다.
- Source207a81b 운영40106111235는 수집 도중 로컬 전체 페이지 사전검사에서 기존 GP→최종선정 이벤트 명칭 호환 문제가 확인돼 발행 전에 취소했다. always job이 일반 취소로 끝나지 않아 force-cancel을 사용했다. 공통 단계 보정의 타기관 일정 회귀1건도 검사에서 검출해 PCK 범위에 한정했다. 기존 이름/주소/선정GP와 전체 lp_program_service.validate 계약을 함께 검사하도록 보완했다.
- 최종 Sourceee93774/전체40106801596은6작업·발행·외부27상세·최종장애보고까지 성공했다. 공개cab48f6936f5ef89ae02d51a의27사업·이전26주소·기존 PCK GP 유지·신규10월 모집1건을 외부에서 확인했다. 직접75본문·PCK6본문/첨부3개·출처오류0이며 기존 산업은행 ZIP1건의 추출 한도만 보류다. 벤치마크195문서 보관66→67, PCK 결과 후보도 공식 보관으로 확인됐다.
- 18대상=직접10·부분8, 추가확인6기관이다. PCK는 기존 확인 대상의 공식 근거가 확보되어 이동했다. 로컬750검사·구조 계약·CI40106792083·원문→전체 페이지 생성 계약 통과. LP 데이터 발행이며 앱·Newsletter·GP·화면·DB구조는 변경하지 않았다. 평일09:20/15:20에 포함했으나 수정 후 예약 성공은 미확인이다.
- PCK 검증 workflow는 중복된 임시 조사 코드를 제거하고 실제 수집/바이트 재판독/기존 GP원문 연결 검증/전체 페이지 생성까지 DB 쓰기 없이 수행하도록 정리했다. 다음은 남은2개 대조 후보의 공식 범위 판단과 부분 연결 기관의 실제 누락 대조다. 최신 현황과 최초10월24일5~7작업일 추정 기준은 status/delivery plan을 따른다. 원래 사용자 변경과 생성 자료는 이번 커밋에서 제외한다.

## LP 공식 후보 범위 판독·기업은행 대조 보완 — 2026-10-25

- Lead는 공식 원문 역탐색·범위 판독과 통합을, 재사용한 automation_check는 IBK 마지막 쪽 파서와 독립 경계 검토를 맡았다. 검토 완료 후 상시 담당자로 남기지 않는다. Newsletter/GP/공개 화면/DB 구조는 변경하지 않았다.
- Sourceb4c87aa/최종40148373846: 공식43페이지·24대상 중12측정/12대조 미연결·접속/판독 오류0. 기업은행1·2쪽이 정상 마지막 경계다. 기존 반복은 초과 요청 오류였으며 수집 GET·과거 검증 경로를 유지했다. 앞선40147970192의 교직원 홈페이지 응답 실패와 원인 미확인은 보존한다.
- 공식 목록의 관측 링크와 제목/날짜 대조로 남은 벤치마크2건(수출입 사업타당성 지원·과기공 일본 상장주식) 및 산업은행2건(성과평가 용역 입찰)을 판독했다.4출처 검증·범위 외4·보류0이다. 고정 공고ID·제3자PDF·감지일 게시일 대체가 없다. 제목/본문 PE 혼합은 보류한다. 수출입 첨부 없는 본문 경계를 보완하되 기존 지문을 보존했다.
- 검증: scripts/run_regression_tests.py 765검사/0실패/0오류/0skip, scripts/check_architecture_contracts.py 통과, CI40148364423 성공. 읽기 전용 대조로 새 공개0. 외부 health=ok/run cab48f6936f5ef89ae02d51a·27사업 링크 유지 확인. 앱 배포나 DB 발행은 없었다. 수정 후 예약 성공은 별도 확인 전이다.
- 다음은 과기공의 독립 게시판 수집 보강과 군인/중기중앙회 누락·빈도 비교다. 상세는 status/delivery plan을 따른다.18대상=직접10·부분8/추가6 및 최초10월24일5~7작업일 추정을 유지한다. 생성 자료는/tmp에만 두고 원래 사용자 변경은 이번 커밋에서 제외한다.

## LP 과기공 독립 게시판 수집 — 2026-10-25

- Lead가 수집 연결·범위/페이지/첨부 검증·운영 통합을 맡았다. 재사용 검토 담당은 저장 원문 구조를 조사하고 파서 초안을 작성한 뒤 실행 한도로 중단돼 Lead가 완성·검증했다. 별도 상시 담당자는 남기지 않는다.
- Sourced94bb16: 공지사항 자체 제목검색·365일 경계·공식 본문/첨부 바이트 재판독. 실제40180513148은5목록·4본문·첨부5건·보류0, 기존27사업·과기공 금액/일정/주소/GP 보존 및 전체 페이지 생성 통과. 전체40180619766의 기관 수집79본문 중 과기공4본문/첨부5건 정상이다. 최종6작업·DB발행·외부27상세·최종장애보고까지 성공했으며 공개6dbc48006718ec1a30e1ebdb의27기존주소·과기공 금액/마감/예정일정/원문·출처오류0을 외부 확인했다. 신규공개0이며 최신status를 따른다.
- 직접11·부분7/추가6으로 운영 목록과 현황을 갱신한다. 범위/관련 문서 보관을 신규PE사업 수와 구분하고 SEMA 입찰 게시판·전체 과거까지 전수 확인으로 확장하지 않는다.773검사·구조 계약·CI40180504926 통과. Newsletter/GP/앱/DB구조 변경은 없다. 생성 자료와 사용자 변경은 커밋에서 제외한다.
- 다음은 군인공제회 자체 신규 발견, 이후 중기중앙회 PE/VC 분리다. 평일09:20/15:20의 이후 예약 성공은 미확인이고 최초10월24일5~7작업일 추정을 유지한다. 재현 명령은 scripts/run_regression_tests.py, scripts/check_architecture_contracts.py, verify-pck-board.yml의 institution=sema다. 실제 공식 호출은 같은lp-program-collection 대기열을 사용한다.

## LP 남은7기관 자체 수집·예약 발행 복구 — 2026-10-26

- Lead는 기관 수집/발행 통합·실제 Actions·최종 공개 검증을 맡았다. 재사용 Worker들이 KBIZ/MOEL/GEPS/KAMCO/KFINCO 순수 어댑터를 분담했고, 마지막 Verifier는 문서 묶음 저장을 읽기 전용 검토한 뒤 GEPS/PCK 좁은 진단을 구현했다. 완료된 담당자는 상시 역할로 남기지 않는다. 다른 서비스나 사용자 기존 변경을 수정하지 않았다.
- Source04dac6e/ca56636은 남은7기관 자체 목록·365일 경계·본문/첨부 재판독과 HWPX 병합/중첩 표 제한 판독을 연결했다. 군인 작은 결과목록 마지막 쪽을 검증한다. Source2dcc810은 전문건설6월/9월 동명 모집 분리·7월1일15시 날짜 경계·공식 후속 링크를 검증하고, 중기중앙회 기본 PE 모집을 공통 배정 없이 공개한다. 고용부 국내 범위 미확인 사업은 추정 공개하지 않는다.
- 실제 예약40271866093은 기관86본문/신규6기관13본문·첨부13건과 성장금융115문서를 확보했으나 발행 job15분 제한으로 취소됐다. GEPS DNS4·PCK 목록4·KOFIA 부분수신1 오류도 남겼다. 기존27사업 보존을 확인했다. 수집 job 성공이 출처 오류0이나 전체 예약 성공을 뜻하지 않는다.
- Source2dcc810/복구40286460473은 같은 저장소·main·신뢰된 workflow·최근48시간의 공식 보관자료를 재검증했다. 기존27주소·선정GP·핵심 조건을 유지하고 중기중앙회/전문건설6월2개를 자동 추가해29사업을 발행했다. 문서287개 저장 처리22.77초·공개 상태15.66초,92기관문서·출처검증오류0이다. 외부29상세가 공개dd1f993b832bf6a0b92fdb31/Supabase와 일치했다. 원출처 오류9건을 보고해 복구 workflow 전체는실패다. 예약 성공으로 치환하지 않는다.
- Source240ce88/좁은 진단40286657349은 GEPS1/PCK2목록200·정상 파싱, GEPS 시스템/IPv4 주소조회 정상을 확인했다. 간헐 오류 원인은 미확정이다. 전체 재수집40287016348은6작업·95기관본문/첨부89건(신규7기관16/15)·29사업 발행/기존주소·출처검증오류0·외부29상세·최종장애보고까지 성공했다. 공개da160fb7d0a1031103b676ec이다. 문서290개 저장 처리24.48초·공개 상태36.74초를 확인했으며, 수정 후 실제 예약 성공은 별도 확인 전이다. 발행 작업은 문서 묶음 저장과25분 한도를 유지한다.
- 신규2상세·군인·목록320/390px에서 가로 넘침/JS오류/다른 서비스 원격 자산 의존0을 확인했다. 로컬814검사·구조 계약·CI40286445074, 진단3검사·CI40286646640(817검사/원본fixture5skip) 통과. 전체 연결 상태 보고의 오래된 일부 연결 가정도 별도fixture로 고쳐 최신 로컬818검사/실패·오류·skip0을 확인했다. LP DB 자료 발행이며 앱·Newsletter·GP·DB구조 배포는 없다. 반복 명령은 scripts/run_regression_tests.py, scripts/check_architecture_contracts.py, recover-lp-publication.yml(collection_run), inspect-lp-remaining-boards.yml(profile=geps_pck_recovery)다.
- 현재 기준은 docs/lp_collection_status.md, lp_first_release_checklist.md, lp_collection_delivery_plan.md다. 목표18기관 자체 설정 연결, 실제 보관·발행18, 추가확인6기관을 구분한다. 최근1년 전체시장 동등 확보나 첫 공개 전체 완료를 아직 주장하지 않는다. 원래 사용자 수정·DB·원문·runtime 출력은 이번 소스 커밋에서 제외한다.

## LP 공식72목록 대조·글로벌 범위 보완 — 2026-10-26

- Source61c082b/40287655873은 최근365일 공식72목록·20기관 측정(18대상+은행2)/미측정4·출처오류0으로 완료했다. 마지막 확인4기관은 국민연금·농협·수협·건설근로자다. 측정 검색어/기간 밖까지 전수 확보를 주장하지 않는다.
- 초기 미보관 제목45개 중 ‘글로벌’만으로 제외된5문서를 발견해 Source857c64d로 모호한 글로벌 사업을 범위 미확인으로 보존하도록 수정했다. 현재 국내 PE 블라인드 근거만 기존 판정에 사용하며 과거 실적 각주·공통 PE/VC 배정·3은행 합계4,500억원을 PE 값으로 쓰지 않는다. 로컬819검사/실패·오류·skip0·구조 검사·CI40289890661 성공.
- 읽기전용 재판독40289938026은 최근 공식목록 artifact의 출처를 확인하고 현재 코드로 재분류했다.72목록 재요청 없이 후보8원문을 검증해 범위외3/미확인5·출처오류0이다. 미확인5는 정책은행 글로벌 스케일업 공동사업의 모집2/FAQ/지원현황/서류심사다. 아직 확정 대상이나 공개 사업으로 추가하지 않는다. 기존29사업/주소·공개실행da160fb7d0a1031103b676ec를 유지하며 DB·다른 서비스 변경은 없다.
- Source624e776/IBK 읽기전용40290187882는16본문·첨부10건·보류0·기존29사업/주소/GP·전체 페이지 생성 보존을 확인했다. 글로벌4문서/공고PDF·FAQ2개를 추가 판독했지만 대형/중형만 구분하고 PE/벤처/신기술기구를 공통 허용하므로 독립 PE 트랙 확인 전 새 공개0이다. DB 쓰기는 없으며 운영DB12/8과 시험16/10을 구분한다. 다음 정기 수집부터 글로벌 발견 범위가 넓어진다. CI40290182249 성공. 현재18대상 자동수집·29사업 운영 발행은 완료했지만 수정 후 실제 예약 성공은 미확인이다. 추가6기관·GP·로그인·모든 과거를 새 출시 선행조건으로 늘리지 않는다.

## LP 공개 설정·실행 경로 마무리 — 2026-10-26

- Lead가 LP 수집·발행·공개 설정·배포를 통합했다. Verifier는 초기 예약active/public/main을 확인했고 후속 검토는 실행 한도로 실패해 Lead가 경계 검증·전체검사·운영 확인을 마쳤다. 후속 수정은 긴급하게 결합된 수집→발행 복구여서 추가 담당을 늘리지 않았다. 사용자 기존 수정·다른 서비스·DB구조는 변경하지 않았다.
- Source2840e0c/[앱 배포40325664585](https://github.com/pkkong/korea-pef-db/actions/runs/40325664585) 성공. 공개 페이지index/follow·robots, 검토/오류/상태noindex·검토no-store/no-referrer/frame-deny를 실제 검증했다. 최신 공개는29사업/실행142a6253e7b95123de1de722/healthok/Supabase/stalefalse다. 검색 허용과 검색엔진 수록 완료는 구분한다.
- Source2124a8a는 교직원을 별도macOS job으로 옮기고 같은 실행2시간 이내 artifact를 publisher가 원문 재판독한다. 자체 수집 기관의 협회경유 중복조회는 위임하되 오류를 삭제하지 않는다. 실제 예약40329496602에서도 교직원1본문/PDF1개·보류0이었다. 산업41/47·기업16/10은 실제 보관했고 공동4,500억원을 PE 배정액으로 쓰지 않았다.
- Source95f199a는 실패 최대2기관·각1회 재수집·첫오류/커버리지/시각 보존을 구현했다. 실제 예약40329496602(event=schedule)는 수집 후 공개 데이터 저장 단계의25분 제한으로 취소됐다. 중복 수동복구40328941875/40330278197는 요청 전 취소했다. 예정시각보다 늦은 이벤트 생성 원인은 미확정이며 결제 문제로 단정하지 않는다.
- Source41e48c9는 총회연금 실제 표 변경을 구/신 구조 검증으로 수용하고 캠코의 공식 점검 주소404를 구분했다. 직렬화·DB 잠금20초/쿼리120초/유휴300초 제한과LP전용연결 태그를 추가했다. 진단은 읽기전용pg_stat의대기유형/시간/차단pid/단계만 수집하며 SQL본문·자료·비밀값을 내보내지 않는다. 진단40339516969는 검증 중ClientRead/차단0을 관측했으며 과거 지연의 단일 원인을 확정하지 않는다.
- [복구40338458112](https://github.com/pkkong/korea-pef-db/actions/runs/40338458112)는 실제Intel Mac에서 총회6본문/첨부3건·새 기관100본문/첨부93건을 확보했다. 캠코 이전2본문/첨부1건 보존 후102기관문서·29사업·기존주소/GP·출처검증오류0·외부29상세를 확인했다.297문서 저장26.43초·직렬화0.59초(63,635,428+1,316,731bytes)·공개상태34.07초다. 최종장애보고는 캠코 공식/error/system_work.html→404 한 건으로실패다. KDB ZIP1개 추출한도는 별도 보류다. 로컬832검사/실패·오류·skip0·구조계약·CI40338115342 성공.
- 공개 앱·검색 설정·검증된 자료의 운영 반영은 완료다. 수정 후 실제 예약 전체 성공·캠코 점검 종료 후 자동 수집은 미확인이다. main/active 평일09:20/15:20·실패알림을 유지한다. 예약 이벤트 대기를 새 공개 설정 선행조건으로 다시 늘리거나 수동 성공을 예약 성공으로 바꾸지 않는다. 추가6기관·GP·로그인·모든과거도 새 출시 조건으로 늘리지 않는다. 다음 실행 근거와 기관 현황은lp_collection_status.md/checklist/delivery_plan을 따른다.

## LP 캠코 수집 회복·공개 DB 접근 장애 — 2026-10-27

- Lead는 수집 실행·DB 진단·발행 수정을, 재사용 Verifier는 공개29상세·장애 재현·동시성 검토·같은 시각 뉴스레터 실패의 읽기 전용 확인을 맡았다. 다른 서비스 수정/재실행·관리 설정 변경은 없다. 사용자 기존 변경과 생성 자료는 커밋에서 제외한다.
- 진단40423123285 성공: 캠코200/10행·총회20/5행. 전체40423159311(Sourcee55042c)은6수집작업 성공·102본문/첨부94건·접속 오류0·재시도0·캠코2/1·총회6/3이다. 기존KDB ZIP1건 한도 보류. 발행00:09:55UTC 잠금·00:11:06 검증70.89초 이후 원문 저장 완료 없이 멈췄고 공개503이 재현돼 cancel/force-cancel했다. 최종cancelled·이번 발행 없음이다. 기관별artifact는 보존됐지만 발행 작업의 성장금융artifact는 없어 완전한 복구 입력으로 가정하지 않는다.
- 일반 진단40424998741은ECHECKOUTTIMEOUT15초, session진단40425647847은 DB 연결timeout이었다. 마지막00:21:17UTC 공개health503/10.28초. 뉴스레터 동기화40424915542도00:16:49 Supabase POST 읽기timeout. 공유 인프라 장애와 일치하지만 LP 원인이나 코드 결합은 입증되지 않았다. 재시작·DB 연결 종료·요금 변경·다른 서비스 수정은 없다.
- Source17887e2는 prepare_publication에서 짧은 REPEATABLE READ READ ONLY 기준/버전 읽기 후 연결을 닫고 원문을 검증한다. publish_prepared는 READ COMMITTED·같은 advisory lock 획득 후 별도 revision 쿼리로 run_id/updated_at/전체 검토 결정을 확인하며 변경 시 쓰기 전에 실패한다. 실제 저장은 여전히 같은 트랜잭션이다. 로컬835검사/실패·오류·skip0·구조 계약·CI40425522128 성공. Sourcea5d9b16/CI40425634378은 설정된 Supabase 풀러6543에 한해 읽기 전용session5432 진단을 허용했다. 운영 접속 설정은 바꾸지 않았다.
- 공개 앱release2840e0c·마지막 정상 자료142a6253e7b95123de1de722/29사업이나 현재 DB 조회503이다. 관리 API 토큰과 관리 브라우저 세션이 없어 Supabase 관리 로그인을 요청했다. 다음은 로그인 후 DB 상태 확인·복구→health/29상세→새 코드 발행→실제 예약 확인이다. 예약09:20/15:20과 실패 신호는 유지한다. 관리 로그인 답변 대기이며 장애 미해결을 완료라고 보고하지 않는다. 세부 근거는lp_collection_status/checklist/delivery_plan을 따른다.

## 관리 로그인·실제 예약 회복 확인 — 2026-10-27 18:15 KST

- 사용자2FA 등록 후 정상 GitHub 로그인으로 Supabase 관리 접속을 완료했다. 만료된 OAuth 요청은 새로 시작했고, Mac 잠금 중에도 연결된 Chrome 브라우저의 정상 웹 경로로 접속했다. 암호/토큰은 문서·소스에 저장하지 않았다. 새 인증수단 등록·계정 생성·보안 약화·암호 저장은 하지 않았다.
- Lead는 관리 화면의 프로젝트/용량 확인과 운영 증거 통합을, 재사용 Verifier는 최신 실제 예약/CI·외부29상세·검색/검토 경계를 읽기 전용 검증했다. 다른 서비스 코드·실행·DB는 변경하지 않았고 사용자 기존 변경과 생성 자료는 커밋 제외다.
- 실제예약40454401111(event=schedule, Sourcec1d709c)은2026-10-27 14:16:43 KST 생성·14:32:25 종료로7작업 모두 성공했다.102기관본문/첨부94건·성장금융115본문·캠코2/1·총회6/3·접속 오류0·출처검증오류0·29사업 발행/전체상세·최종 장애 보고 통과. 기존KDB ZIP1건 추출 한도 보류. 공개실행14d718c41b35ce67f8c0cbba다. 설정된09:20/15:20 정시 생성으로 치환하지 않는다.
- Source17887e2의 연결 반환 경로는 원문 검증87.13초(연결 닫힘)·잠금0.12초·297문서 저장20.41초·직렬화0.37초·공개 상태34.50초로 실제 운영을 통과했다. 기존835로컬검사·구조 계약·CI40425522128/40425634378 통과. 앱release2840e0c는 그대로이며 새 앱 배포 없이 자료가 갱신됐다.
- 18:15:32 KST 외부29상세 전부200/Supabase/새실행/진행일정,healthok/stalefalse. 첫화면index/follow·검토두주소noindex/no-store/no-referrer/frame-deny도 통과했다. 관리 프로젝트는Healthy(CPU2%/RAM50%/연결4/60)로 확인돼 강제 재시작·연결 종료·설정 변경을 하지 않았다. 회복이 수동 DB 조치 때문이라고 설명하지 않는다. 오전503/연결timeout 실패 이력은 위 기록에 보존한다.
- 읽기 전용 용량 점검에서 프로젝트1,009.02MB/무료0.5GB 초과를 확인했다. lp_program_private.collection_runs730.59MB(72.41%),documents36.36MB,program_state32.92MB다. 다음 우선순위는 원문 증거를 보존하면서 실행별 반복 보관을 줄이는 구조의 설계·검증이다. 자료 삭제·이전·유료 전환은 하지 않았다. 관측된 한도 경고를 오전 장애의 단일 원인이나 결제 필요로 단정하지 않는다.
- 첫 공개 기능·자료·실제 정기 실행 검증은 완료다. 전체시장 확보율/벤치마크 동등 확보·영구 무중단을 주장하지 않는다. 추가6기관·GP·로그인·모든과거는 별도다. 최신 기관/운영 근거는lp_collection_status.md/checklist/delivery_plan을 따른다. 현재 관리 브라우저 탭은 로그인된 용량 보고서로 유지했다.

## LP 이력 보관 운영 반영 — 2026-10-29

현재 공개는 `fd111cf4f9a1a79848b5e95f`/29사업이며 앱은2840e0c다. 최종 보관40794080828과 공간 회수40795575999에서94이력·91개 비공개 보관·최신3개 전체 보고서를 유지했고,91보관본 전부를 다시 복원 검증했다. 프로젝트DB 1,145.3MB→484.6MB, LP 이력 테이블 766.9MB→106.0MB, Storage 280.9MB다. 실제DB복원40624431866·공개/검토 지문 보존·외부29상세/목록도 통과했다. 물리 재작성은LP 실행 이력 테이블만 수행했다. 유료 전환·연결 종료·다른 서비스 데이터/앱 배포는 없다.

최종 소스85475f6: 일반 본문은256KiB까지 압축 목록에 유지해 작은HTML 파일별 요청을 줄이고, attachment_bytes의 검증된 PDF/OLE/ZIP은8KiB부터 중복 보관을 줄인다. 기존8KiB/256KiB 보관본은 재작성 없이 복원한다. 인스턴스당64MiB 검증 청크 캐시, private bucket/RLS/공개키 차단 검사, 최신3+현재 보호, 잠금을 잡은 후 행 버전 확인를 유지한다. 최종 대상47검사·구조 계약과 CI40796957235(882검사/실패0·fixture없는5skip)를 통과했다.

보관은 수집/복구 완료 뒤 별도 workflow_run으로 분리했다. 동일repo/main/예약·수동 이벤트만 허용하고 항상main 코드를 실행한다. 자동 대기열은lp-report-retention, 수동은lp-program-collection이며 자동 일반VACUUM은5초로 발행20초 잠금 대기보다 먼저 끝난다. 새 보관 후보가 없어도 실행 이력과 단일 공개상태 행의 일반VACUUM을 수행해 실패한 발행의 빈 공간도 재사용한다. 실제 분리된 자동 이벤트 완료는 다음 정기 작업 뒤 확인한다. 기존 정기40694398568의 자료 발행 성공·KFINCO 보류·보관 도중25분 취소는 각각 구분한다. 다음은 새 정기 수집/분리 보관 관찰이며 기관·GP·로그인을 추가 출시 조건으로 늘리지 않는다. 자세한 현황과 명령은 lp_collection_status/lp_report_storage_operations를 따른다.

## LP 자동 정리·빈 공식 공고 복구 — 2026-10-29

40826691771은 선행6수집 성공 후 성장금융913의 상세 파싱에서 중단돼 발행하지 않았다. 첫 자동 정리40827539507도 QueryCanceled로 실패했다. c543e08은 일반 정리에서 발행 advisory 잠금을 없애고 VACUUM(ANALYZE, TRUNCATE FALSE), 쿼리180초/경합5초로 바꿨다. 수동40879872004와 실제 workflow_run40882105378/40887228378/40981312228에서 완료를 확인했다. FULL만 기존 발행 잠금·크기 제한·공개 상태 불변 검사를 유지한다. e7e0840은 동시 발행이 있을 때 정리 후 실제 상태로 외부 검증하도록 했다.

공식 진단40880218235는913의 HTTP200/9,581bytes/완성된 빈 공고 양식을 확인했다. 목록대조40880588822는365일114행과913 미포함을 확인했으나 삭제·비공개 원인으로 단정하지 않는다. 1d17d37은 모든 필수칸과 첨부가 빈 완성된 공식 양식만 official_detail_empty로 보류하고 다른 공고 수집을 계속한다. 과거 원문은 tracked에 보존하고 새 추출에서 제외한다. 잘린 HTML·부분 누락·접근 제한은 여전히 오류이며 고정ID 제외 규칙은 없다. 로컬892검사·CI40881170614 통과 후 전체40881170521은 수집/검증을 통과했지만 큰 상태 저장 중25분 제한으로 취소됐다. 아래10/30 복구와 구분한다.

## LP 제한 공고·상태 압축·안전 전송 — 2026-10-30

**10:03 KST 운영 검증 완료.** c7aef97의 발행 복구40982170768과 후속 자동 보관40983019866이 모두 성공했다. 공개 실행299ef2169c4e9998ce82ca51의29사업·70페이지, 기관102본문·성장금융115본문·문서298개 저장을 확인했다. 새 공개 사업은0이며 기존 주소를 유지한다. 외부 health=ok/stale=false/Supabase, 목록·상세29/29의200/동일 실행/진행 일정, review 두 별칭의 noindex/no-store/no-referrer/DENY를 검증했다. 앱release2840e0c는 그대로이며 LP 자료 발행이다. Newsletter/GP/화면/DB구조를 변경하거나 배포하지 않았다.

94992d2에서 shell-python 진단의 PYTHONPATH를 수정했고40979957482에서 전문건설공제조합 목록4행의 closed=[0,0,1,0]을 확인했다. 3b45099는 int1만 owner_closed로 건별 보류하고 공개3행은 계속 처리한다. 제한행의 상세/첨부는 요청하지 않으며 목록 보관본에도 ID/flag만 남긴다. 잘못된 플래그와 정상 공개자료의 오류는 실패 신호를 유지한다. 이번 복구에서 해당 범위2본문·첨부4건을 재수집했다. 기존2사업은 유지하며 신규사업으로 세지 않는다.

e33e710/8c17d17은 누적 증거6항목만 gzip/base64와 지문으로 보존하고 baseline에서 완전히 복원한다. programs/review_outcomes는 SQL에서 읽는 형태를 유지한다. 지난 회차에만 있는 증거도 유지하고 첫 SQL 쓰기 전에 압축 복원본과 준비 자료를 대조한다. c7aef97은 documents.executemany/pipeline을 없애고25행/UTF8 1MiB 기준의 단일 jsonb_to_recordset 문장으로 전송한다. 큰 한 문서는 단독 전송하며 원문·이력·전체 트랜잭션을 유지한다. 실제 운영에서 상태 전송28,880,076bytes/저장17.18초·298문서 저장36.79초로 완료했다. 로컬905검사(실패·오류·skip0), 실제PostgreSQL17 23검사·CI40982170547 통과. SQL검사는 생산 함수가 만든SQL/파라미터를 직접 실행하며 뒤쪽 실패 시 앞 문서와 공개 상태 rollback을 검증한다.

자동 보관은1건을 새로 옮기고95이력·92개 비공개 보관·최신3개 전체 보관·남은 대상0개를 확인했다. 10:01:54 KST DB419,327,123bytes·이력 테이블142,073,856bytes·Storage288,376,538bytes다. 공개70페이지/검토 지문은 보관 전후 동일하다. 임의 삭제·유료 전환·한도 증액·다른 서비스 조치는 없다. 강한 추가 공간 회수는 필요하지 않아 실행하지 않았다.

이번은10/29 수집40881170521의48시간 이내 자료를 재판독하고 실패한 전문건설 경로만 재요청한 수동 복구다. 앞선 복구40980551856은 executemany 전송의 SSL bad length로 실패했고, 자동40981312228에서 기존 공개/94행/91보관 유지로 rollback을 확인했다. 수정 후 실제 예약 수집 성공은 아직 미확인이다. 원문 접속·목록·본문의 남은 실패0이며 산업은행ZIP 추출 한도1건·성장금융 빈 양식·전문건설 비공개1건은 보류로 보존한다. 기존 평일09:20/15:20 예약과 실패 알림을 유지하고 다음 실제 예약 결과로 갱신한다.18대상/추가확인6 범위와 출시 판단은 status/checklist/delivery_plan을 따른다. 새입력·원문·비밀값/DB/로그/생성물과 기존 사용자 변경은 커밋하지 않는다.

Lead는 운영 복구·통합·문서와 커밋을, 재사용 Worker는 상태 압축/문서 전송의 제한된 구현을, 재사용 Verifier는 KFINCO 원인 확인·PostgreSQL 검사·마지막 외부 페이지 검증을 맡았다. 모두 이번 범위 종료 후 상시 작업자로 남기지 않는다.

## LP 캠코 신규 공고 검색 누락 수정 — 2026-10-30

사용자가10월26일 캠코 신규 출자 공고 누락을 지적했다. 공식 공고 ‘캠코 소규모 구조조정 펀드 운용사 선정계획 공고’와 첨부 HWP를 확인했다. 이전 검색어 주력산업/PEF/블라인드/출자가 제목에 없어서 빠졌으며, 당일 예약41011675140은 성공했지만 캠코는 기존 PD2본문만 포함했다. 작업 성공을 발견 완료로 해석한 한계다.

7a26d74는 운용사/펀드의 일반 제목 검색을 추가했다. 최근365일·최대10페이지·본문60건 한도와 원목록/본문/첨부 재판독을 유지하며 같은 공고를 중복 수집하지 않는다. 로컬 실제 수집은13목록·4본문·첨부3개·보류0이며 신규PE1/나머지PF·PD3건 분리를 확인했다. 공식 HWP의 현재 블라인드 방식·기관전용 투자기구·외국기업 투자제한을 함께 확인해야 공개한다. 고정 공고ID/금액/일정을 입력하지 않는다.

별도 labelled 파서는 공사출자300억원·1개사·최소결성500억원·11월16일15시 마감·12월 최종선정예정을 근거와 함께 추출한다. 주목적은 구조개선기업60%이상·사후적구조조정 중소기업 재기지원30%이상 의무 문장만 표시한다. 첨부 근거는 보존하되 예정 일정의 공개 연결은 모집 원문을 사용해 최종 _refresh에서 사라지지 않게 했다. 실제 검증된 수집본→사업1개→공개 페이지 생성까지 통과했다. 로컬911검사/실패·오류·skip0, 구조 계약, CI41021912415 성공이다.

전체41021928138은30사업 생성 후 보고서 저장에서 실패했고 아래0e08cfc 복구로 운영 발행을 완료했다. 신규 kamco-2026-d219c7aa6bfeb9d9·기존29주소·목록/상세 조건을 확인했다. 후속 자동보관은 아래 최신 기록을 따른다. Worker는 공식 조사와 신규 파서2파일, Lead는 검색 설정/공개 통합/운영 실행/기록, Verifier는 읽기검토/CI/공개 검증을 맡았다. 다른 서비스나 기존 사용자 변경은 건드리지 않는다.

## LP 큰 보고서 전송 복구 — 2026-10-30

41021928138은 새캠코 포함30사업 생성 검증을 통과한 뒤 `collection_runs.report` INSERT에서120초 QueryCanceled로 실패했다. 수집은 자체 게시판104기관본문/캠코4본문·첨부3건을 확보했고 다시 수집할 필요가 없다. 같은 자료의 macOS 복구41023828149도 검증30/잠금0.13초 뒤25분 제한으로 취소됐다. 같은 날 Ubuntu 예약41011675140은 정상 발행했으므로 OS를 원인으로 단정하거나 환경만 전환하지 않는다. 자동정리41023716697은96이력·93보관·기존공개29/검토불변·DB449,817,747bytes/Storage294,702,590bytes를 확인했다.

0e08cfc는 기본JSON88.3MB의 단일 파라미터를 compact UTF8 70.9MB로 직렬화하고1MiB 이하 UTF8 경계 보존 조각으로 전송한다. 임시 테이블의 seq순 합치기 후 동일한 전체 report JSONB로 저장하며 최신3/현재 보고서·직접 SQL검토 계약을 유지한다. 원래 발행 잠금/버전 대조·120초 쿼리 제한·전체 트랜잭션은 유지하고 report/문서/공개 상태의 부분 commit과 재시도는 없다. 임시 테이블은 commit/rollback 때 제거된다. 로그에는 바이트/조각 수/단계 시간만 남긴다.

로컬914검사/실패·오류·skip0, 실제PostgreSQL26검사(생산SQL 직접 실행)의 한글/emoji·0/false/null·리터럴 이스케이프·후속 실패 전체 원복·임시 테이블 제거·anon report 차단을 통과했다. Lead는 publisher/단위검사, 재사용 Verifier는 SQL검사 파일1개만 수정했다. 복구41057202680이0e08cfc에서 원 수집41021928138의48시간 이내 자료를 재사용해 성공했다. 보고서70,920,731bytes/68조각 전송11.43초·최종 보고서 저장15.02초,301문서 저장 처리37.64초(보고서 포함)·공개상태16.98초다. 공개8c6894d4a79ceaae58de8f36의30사업/72페이지·신규캠코 조건/12월예정/공식원문·기존29주소·healthok/stalefalse/Supabase를21:46 KST 외부에서 검증했다. 발행 전 기존선정GP 보존 검사도 통과했다. 후속 자동보관41057863803도 성공했다.21:48:50 KST 기준97이력·94비공개 보관·최신3전체·남은대상0, DB451,570,835bytes/이력테이블142,983,168bytes/Storage300,873,413bytes, 공개72페이지·검토 지문 보존이다. 유료 전환·한도 증액·원문 삭제·다른 서비스 변경은 없으며 추가 강한 공간 회수도 하지 않았다. 새 코드의 실제 예약 성공은 아직 미확인이고 다음 정기09:20/15:20과 실패 신호는 유지한다.

## LP 독립 누락 점검·검색 보완 — 2026-11-02

- 대상18기관/추가확인6기관의 기존 범위를 유지하며 운영 검색어와 다른 공식 목록·일반 운용사/펀드/출자 검색으로 대조한다. Source57be8f2/b8f4796은 독립 감사, 기관별 공정한 요청 순서, 일부 오류 시 정상 자료 보존,20건 초과 후보 명시 대기, 교직원공제회 일반 검색 및 실제365일/수은 전년도 게시 공고 발견을 추가했다. 후보 대기의 자동 다음 묶음 처리는 아직 없다.
- 10/31 감사41189506391은101목록/19기관을 측정했지만 POBA점검4·KFCC2·KTCU1 오류로 실패했다. 미보관 관련제목50은 범위외40/미확인10이며 PE50사업 누락으로 해석하지 않는다. 본문11건 확인만으로 새 국내PE블라인드 누락을 확정하지 않았다. 오류 수·부분 측정 범위와 미연결4곳을 보존한다.
- Source90ff3f5는 KTCU화면2쪽/정적hidden1을 구분해 실제 페이지 검증, KFCC실제 마지막 페이지 확인으로 overrun방지, 빈검색 제외 및 POBA점검 응답의 명시적 오류를 추가했다. 실제 저장1·2쪽 재생과 잘못된 페이지/검색 거절을 확인했다.
- Sourceab0f4d6는 IBK의 제목에 펀드/선정 없는 ‘출자사업 공고/서류심사 결과’를 자동 발견·원문 수집하도록 출자검색/정책은행 후보 규칙을 보완했다. 고정 공고ID를 등록하지 않고 기존 PE근거/혼합분리/보류를 유지한다. 국내PE블라인드 여부는 첨부 검증 전 추정하지 않는다.
- 최신 로컬936검사/실패·오류·skip0, 구조 계약과 CI41388032262 통과. Sourcefe81ddb는 제목 속 날짜와 공식 게시일 칸을 구분해 KTCU실제6쪽 판독을 수정했다. Source36567ce는 매주 일요일10:00 KST독립목록감사를 설정했고 첫 실제예약 성공은 미관측이다. Worker는 KFCC/POBA 파서, Verifier는 저장응답/후보 읽기검증, Lead는 KTCU·IBK 통합/운영실행/기록을 담당했다. 추가 Verifier후속조사는 사용량 제한으로 끝나 Lead가 인계했다. 비밀/생성물/다른 서비스/기존 사용자 변경은 sourcecommit에 포함하지 않는다.
- 운영 확인: 11/2 전체 수집·발행41387589563(Sourceab0f4d6)이 성공했다. 공개32eecf33815cc82a84b85808의30사업/72페이지와 이전30주소를 보존했고 기관 출처검증오류0·외부30상세 검증·health=ok/stale=false/Supabase를 확인했다. 직접109본문/첨부102건·IBK모집/서류/최종3문서를 확보했으며 새PE사업 공개는0이다. 목록/본문 오류0과 첨부4건·비공개1건 보류를 구분한다. 자동보관41389911498도99이력/96비공개보관/최신3전체/남은대상0·공개72페이지와검토불변으로 성공했다.

- 후속 독립감사41388039811은 KTCU1~8쪽/20기관을 측정했지만 신협의 직접DNS실패 뒤 대체경로가 새로운 검색어3개를 거절해 실패했다. Sourceb586d5a는 신협 공식1020게시판의 이미관측한 운용사/펀드/출자와 빈검색1쪽만 Python/서울 경로의 동일 allow-list에 추가했다. 임의검색·다른게시판·빈검색2쪽은 계속거절한다.937검사/Node30검사·구조계약·CI41390670043 통과. 배포41390679108은서울에서실제 운용사2행/펀드4행/출자0행/최신1쪽51행과기존CU/KFCC/KFINCO목록을 검증했다. 새로운 전체대조41390799484 결과는 상태문서 최신기록을 따른다.

- 최종 독립 목록 대조: [최종대조41390799484](https://github.com/pkkong/korea-pef-db/actions/runs/41390799484)/Sourceb586d5a 성공. 공식107목록·20기관(대상18+은행2)·목록오류0·조회한도도달0, 미연결4곳과 전문건설 공개API의 독립검색 제한을 유지했다. 미보관 관련제목47은 제목상범위외40/VC1/미확인6으로, PE47사업 누락이 아니다. 후보8항목 중 공식본문7항목을 검증했고 새마을금고 회원이벤트1항목은 본문 판독불가로 보류했다. 제목상 명시PE블라인드 미보관0을 전체시장 누락0으로 바꾸지 않는다.

## LP 첨부·미연결 기관 후속 — 2026-11-03

**최종17:25 KST:** 41601686300/d31eb68 성공·공개b565e201bf71ed7853a7db29/30사업72페이지·기존주소/GP·외부30상세·health/접근경계 보존·직접검증오류0·목록/본문/발견 오류0. 자체124본문/첨부128개·성장금융115·수은16·KOFIA17 3쪽30행을 확인했다. 수집 연결22/미연결농협·수협2, 새PE사업0·별도첨부/비공개3보류다. 실제예약과 후속자동보관은 상태문서를 따른다.

- Lead는 LP 수집·원문 재검증·복구·운영 기록을 통합했다. 재사용 Verifier/Worker는 OCR/CWMA 읽기 검토와 KEXIM DNS/연결초기화 보완의6개→2개 파일만 맡았다. 다른 서비스·화면·DB구조·기존 사용자 변경은 제외한다.
- Sourceffbd153/7e4049c/2145cc4는 국민연금·건설근로자 자체 수집/목록 대조, 제한된 스캔 판독v2, ZZ/KD 과거경계 지원을 연결했다. Source16b2d54는 양식 다운로드/공개 근거 제외를, b519946/9ed2a61은 제한된 실패기관/협회 복구와 KEXIM DNS·연결초기화 재시도를 구현했다. 개별 공고ID·금액을 등록하지 않는다.
- 현재 실적: 전체41592822493은124기관본문·국민연금8/첨부12·건설근로자3/첨부5를 보관하고30사업/72페이지를 발행했지만 NPS 과거목록·수은 DNS·협회잘림 오류로 최종실패다. 국민연금 수정 후 복구41595223116은3쪽/365일경계·8/12·직접검증오류0·30기존주소/GP·외부30상세를 통과하고 공개379fbb5d2ea04bc4b9746506을 발행했다. 남은 수은 연결초기화/협회 curl18 때문에 전체는실패이며 숨기지 않는다.
- 최신 로컬1007검사/실패·오류·skip0·구조 계약·CI41601630525 통과. KOFIA 전송 비교41600945251 후 Worker2파일/29검사를 통합한d31eb68의 최종복구41601686300은 성공했다. 이전 실패는 아래와 상태문서에 보존한다. 운영 스케줄09:20/15:20·일요일10:00감사·실패 신호를 유지한다. 11/3 예약41593309277과 진단41593089429은 공유대기열의 한개 pending 교체로 실행전취소됐으며 예약 성공으로 쓰지 않는다. 마지막 실제예약 전체성공41399937023/19e5127은11/2다.
- 농협은 공식 공지/입찰의 검색POST, 수협은 일반공고 메뉴까지 확인했다. 진단41595307584는15응답/보류0이며 관련없는 본문을 메뉴로 고르던 artclView 경로는9ed2a61에서 제외했다. 두 기관 자체 자동수집은 아직 미연결이다. KDB ZIP한도·캠코 보호HWP·전문건설 비공개는 별도보류다. 원문 접근제한을 우회하지 않는다.
- 재현: scripts/run_regression_tests.py, scripts/check_architecture_contracts.py, recover-lp-publication.yml(collection_run,retry_failed_institutions=true), inspect-lp-remaining-boards.yml(profile=pending_contracts|pending_institutions). 실제 원출처 요청은 공유 Actions 대기열에서만 수행한다. 최신 상세 결과는 [수집 현황](lp_collection_status.md)을 따른다.

## LP 농협·수협 후속 연결 — 2026-11-03

- Sourceb650199/09cb54b는 농협 공지·입찰 두 게시판과 수협 일반공고의 자동 검색·페이지 경계·본문·첨부/원문 재판독을 구현했다. 기본 매일 발행 설정은 비활성화하고 주간 읽기 전용 목록 점검에만 추가했다. 실제41644570867은 농협11목록/2본문/첨부1개·수협5목록/1본문·보류0으로 성공했다. 진단41637074089의21응답과 GET/POST 상세 일치도 확인했다. 전체24기관 대조41780854226은11/4 124목록·24측정/미연결0·오류0·조회한도0으로 성공했다. 원문후보9항목 중8확인/회원이벤트1본문판독보류이며 후보예산초과0이다. 실제 예약 성공과 구분한다.
- 농협 NPL 모집은 공식 첨부의 중앙회 직접출자 없음/회원조합 개별계약을 함께 확인해 중앙회 LP사업에서 제외했다. 은행·증권 계열사 발행을 공통푸터로 중앙회에 귀속하지 않는다. 미스터리쇼핑 용역/재해복구 전산입찰은 제목과 공식 본문을 함께 검증해야 제외하며, 관련없는 첨부를 내려받지 않는다. 제목의 펀드/출자 단어만으로 PE를 공개하거나 고정 공고ID/금액을 입력하지 않는다. 향후 혼합 투자유형의 비출자 조항은 해당 트랙에만 적용해야 한다.
- 첫 검증41642014368은 일반 용역ZIP의 지원하지 않는 형식 때문에 실패했다. Source09cb54b에서 본문상 확인된 비투자 용역만 파일 수집에서 제외한 뒤41644570867에서 실제 회복했다. 오류를 숨기거나 ZIP 판독 한도를 완화하지 않았다. 로컬1034검사/실패·오류·skip0·구조 계약·CI41644569767 통과다.
- Lead는 수협/공통수집/주간감사·실행/통합·운영기록을, 재사용Worker는 농협 어댑터2파일과 마지막 읽기 검증을 맡았다. 역할별 작업은 통합 완료 후 종료했다. 다른 서비스/화면/DB구조·기존 사용자 변경과 생성자료는 커밋하지 않는다.
- 기존 공개 운영의 마지막 정상 기준은41601686300/d31eb68·공개b565e201bf71ed7853a7db29/30사업72페이지·매일22기관/기금 수집연결이다. 이번은 읽기 전용 탐색 확장이므로 공개자료 발행이나 Vercel 앱 배포가 아니다. 최신 실행·공개·기관 현황은lp_collection_status.md를 따른다.
- DB 마지막 관측은11/3의533,802,131bytes/104이력·101비공개보관/최신3전체/미보관대상0이다. 공간회수41635927387은 전체아카이브 검증 한도1로 쓰기 전에 거절됐다. 올바른 한도150의41636389765는 전체보관본 검증이 새공고 확인을 막아 취소 완료했다. 공간회수 완료로 보고하지 않는다. 공개자료/원문 삭제·요금제/한도 변경은 없다. 추가 DB 쓰기가 필요할 때 실제 용량과 자료 증가량을 확인하고 공간 조치 필요성을 판단한다.
- 운영 순서 교훈: 전체보관본QA 같은 긴 수동점검을 공식출처 계약 확인보다 먼저 공유수집대기열에 넣지 않는다. 출처응답을 먼저 확보하고 로컬 구현/검증과 병행한다. 실제 공식출처 요청은 계속Actions 공유lp-program-collection에서만 수행한다.

## LP 후보 자동 이어처리 — 2026-11-04

- Source47a238f: audit_lp_candidate_batches.py가공통후보목록을20건씩전부처리하며단일실행캐시/세션/응답예산20MiB·원정보/중복단서연결·묶음별원자저장을유지한다. 기존한묶음resolve의20건한도는그대로다. 공식사이트HTTP는기존Actions공유lp-program-collection에서만수행한다.
- 재개는같은입력지문+각영수증지문검증뒤현재파서로다시판정하며완료/PE표시는신뢰하지않는다. 기존workflow의같은repo/main/완료/48시간검사를거쳐저장목록/보고서를쓴다. artifact가존재하는중단회차의재개입력은구현했고자동실패회차재디스패치를구현한것으로설명하지않는다. 통신/근거무결성/응답예산실패·미처리후보는workflow실패신호를유지한다. 범위미확인은보류다.
- Lead는공통수집context·묶음제어·Actions통합/운영기록을,재사용Verifier는새test_audit_lp_candidate_batches.py의독립6검사를담당했다. Lead가실패격리·원자파일저장2검사를더했다. 로컬1042검사/실패·오류·skip0·구조계약·workflow YAML/bash문법·CI41787448108통과다. 실제이전9후보저장응답의2묶음재생/8원문확인/보류1·재개신규HTTP0도확인했다.
- 오늘실제예약41787255295는06:41:55UTC생성/22ef81c·자료발행성공후협회목록오류로전체실패다.15:20설정의정시실행으로바꾸지않는다. 읽기전용2묶음검증41787464249와재개41789671811은성공했다. 운영수집을취소하거나정기예약/실패신호를끄지않는다.실제완료결과는lp_collection_status.md를따른다.
- 재현: python3 -m unittest services.lp.tests.test_audit_lp_candidate_batches services.lp.tests.test_audit_lp_candidate_sources; scripts/run_regression_tests.py; scripts/check_architecture_contracts.py; audit-lp-official-inventory.yml(inventory_run,candidate_batch_size=5|20). 코드/검사와운영실행·공개발행을구분한다. LP읽기전용점검변경이며다른서비스/화면/DB구조·기존사용자변경/생성물은커밋제외다.

- 실제2묶음41787464249와재개41789671811은9후보/8원문확인/회원이벤트1본문보류·미처리0·추가응답2381661→0bytes·source_errors0으로성공했다. 오늘예약41787255295는7794b53a5c7dcbbbaffbf785/30사업발행·전체상세/검증오류0이나KOFIA17두목록curl18때문에전체실패다. 본실행로그에서KOFIA212목록2회+본문2회가공유추가4회를모두소진함을확인했다. 새전송방식/한도증액은하지않았고기존실패스트림복구41789785499는성공했다. KOFIA17의1~3쪽각10행/목록본문오류0·공개36fb30904ef29491435f7360/30사업72페이지·외부30상세/health/접근경계를확인했다. 수동회복을예약성공으로바꾸지않으며재발방지는다음항목이다. 최신외부30상세/health/접근경계는정상이다.
- 자동보관41789460643은105이력/102비공개보관/최신3전체/미보관대상0·공개/검토불변으로성공했다.16:04:50KST DB534350995bytes/Storage363973646bytes다. 후속복구이전관측이며공간재작성/유료전환/한도변경은없다.

## 협회 응답 잘림·재시도 편중 보완 — 2026-11-04

- Lead는공통수집의예약예산/시도메타데이터·범위제한전송복구·워크플로통합/운영확인을,재사용Worker/Verifier는전송진단2파일/7검사와최종읽기리뷰를맡았다. 다른서비스/DB/화면·사용자기존변경/원문생성물은제외한다.
- Source23fbb91은총추가4회중채널별목록1회예약/미사용반환을추가했다. 앞선본문에서모든기회를쓰는문제를막되요청당최대3회·전체4회와실패신호는유지한다. 전송시도별원문없는메타데이터와복구전송이력을보존한다.
- 실제진단41843582215은7요청: KOFIA17첫identity HTTP1.1은curl18/HTML불완전32090bytes, 압축첫쪽은curl0/10행. 관측된2·3쪽에서HTTP1.1 chunked와HTTP1.0 nonchunked는각52434/52147bytes·동일SHA/10행이었다. Sourcee84d05d는KOFIA17목록의typed잘림에만HTTPSHTTP1.0재시도와성공후당일실행내재사용을추가했다. TLS/HTTP/시간초과·다른채널에는확대하지않는다.
- 로컬1051검사/실패·오류·skip0·구조계약·YAML/bash문법·CI41844143010통과다. 검토담당은읽기42검사/차단오류없음을보고했다. 실제전체협회수집41844220489는association_collection프로필에서3게시판/9목록/29본문·목록본문오류0·추가재시도1/4회로성공했다. DB쓰기/발행없이목록·본문오류와예산4회상한을검증한다. 원문/헤더생성물은/tmp에만두고커밋하지않는다.
- 재현: python3 -m unittest services.lp.tests.test_collect_shared_lp_notices services.lp.tests.test_retry_lp_failed_sources scripts.tests.test_inspect_lp_kofia_transfer; scripts/run_regression_tests.py; scripts/check_architecture_contracts.py; inspect-lp-remaining-boards.yml(profile=kofia_transfer|association_collection). 새예약의실제전체성공과읽기검증을구분하며최신공개/기관/예약은lp_collection_status.md를따른다.
- 제어실패검사41845222898/b9b0379도성공했다. 첫요청에테스트short-read1회를주입한뒤실제KOFIA17의1~3쪽각10행을대체전송으로수집했다.4events/추가1회·보류0이며실제자연발생장애로기록하지않는다.일반실수집에서는대체전송사용0·첨부7판독보류였고구분보존한다. CI41845222155도성공했다. 현재공개30사업/health는36fb30904ef29491435f7360/2840e0c로정상이며DB쓰기/발행/앱변경은없다. 다음실제예약성공은미관측이므로41787255295의예약실패/후속수동복구와구분한다.

## 제출양식 오분류·누락예약 보조 — 2026-11-05

- Lead는기존v1/v2바이트재생분리·수집통합/실행/상태기록과감시큐/이벤트/시작전실패/독립성검증을,재사용Worker는양식정책/검사2파일과감시3신규파일을맡았다. 기존사용자문서/LP화면·다른서비스/DB/원문생성물은범위밖이다.
- fe5f29f는재공고명이붙은제출한글/엑셀양식을다운로드·PE범위/금액/마감근거에서제외하며v1/v2영수증은그대로재생한다. v2는is_submission_form_v2에원래정책을동결했다. 원본124기관본문에새로영향받는것은KDB양식2개뿐이다. 전체로컬1065/실패·오류·skip0·구조계약·YAML/bash·CI41949011160성공이다.
- 실제41945877217/fe5f29f는KDB3목록/44본문/53첨부/해당보류0·기존30사업/주소/GP·전체페이지생성을통과했다. 11/4게시글로벌스케일업선정결과1건도자동발견했으나PE범위미확인으로공개/GP연결하지않았다. 이번은DB쓰기/자료발행/앱배포가없고운영시점과읽기검증을구분한다. KAMCO부실채권프로젝트펀드DRM과협회첨부는대체PDF/원기관PE원문이확보돼이번표본에미확보핵심PE를추가발견하지못했다.
- 아침예약은11/5 10:31KST까지생성미관측/workflowactive다. 0c1162e/1a40dd2/15a572f에독립LP경량감시를등록했다. 평일매시05분에90분유예가지난수집창만판정하고기존main실행/활성LP작업/이전시작전실패/비활성설정/API실패를존중한다. 최근100실행+필요시이전실패job의시작근거를읽으며최대13GET/1POST·응답4MiB/30초한도다. 형제서비스/관리Pages메타데이터는LP상태판정에서제외하고공유출처목록누락을검사한다.
- 실제41947886679/0c1162e는10:20:57KST dry-run/no_due_window로성공했으며새수집은요청하지않았다. 실제보조자동발동/새코드전체정기성공은미관측이다. 기본수동은dry-runtrue,자동schedule은false이고정확collect-kgrowth-programs.yml@main만dispatch한다. 최상위contentsread·신뢰된mainjob만actionswrite이며PR/다른ref/저장소는제외한다. 기본GITHUB_TOKEN의workflow_dispatch허용은[GitHub공식안내](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)를확인했다. PAT/다른계정/요금/한도변경은없다. GitHub자체예약장애와API-dispatch경쟁구간의완전격리를주장하지않는다.
- 재현: scripts/run_regression_tests.py; scripts/check_architecture_contracts.py; python3 -m unittest services.lp.tests.test_lp_attachment_policy services.lp.tests.test_collect_lp_institution_boards scripts.tests.test_lp_collection_watchdog; verify-pck-board.yml(institution=kdb); lp-collection-watchdog.yml(dry_run=true기본). 최신기관별관측/보조발동/공개자료는lp_collection_status.md만기준으로보고한다. 현재public36fb30904ef29491435f7360/30사업72페이지·healthok/stalefalse·앱2840e0c다.

## 현재 채팅 LP 자동 재개 예약 — 2026-11-06

- 사용자 요청으로 앱 heartbeat `lp-db`를 현재 채팅 `01a0723f-e8d9-7de0-9e85-18cb46f006a3`에 ACTIVE/60분으로 연결했다. 독립 작업/새 채팅은 생성하지 않았다. 최초 앱 실행예정은11/6 09:50 KST이며 첫 실제 발동은 확인 전이다.
- 재개 진입점은 [LP 체크포인트](lp_resume_checkpoint.md)다. 소스31530df의 검증 완료와 KOFIA 서울 경로3파일의 미검증 초안, 운영/미완료/검사/사용자 변경 경계를 기록했다. 사용량 제한은 다음 예약에서 재평가하며 완료로 처리하지 않는다.
- 이 예약은 실제 작업용이다. 완료 또는 필수 사용자 판단 때 보고하며, 합의된 구축·출시 조건을 실제 검증한 뒤 예약을 중지한다. 로컬 앱/컴퓨터/프로젝트가 이용 가능해야 한다.

## KOFIA 서울 복구 운영 검증 — 2026-11-06

- 소스60ce265·Python1092/Node34/구조/문법·CI42134148595/별도검토56검사를 통과했다. 재사용Worker는JS범위/Node검사, Lead는Python/예산/워크플로/배포·운영통합을 맡았다. 기존 사용자 변경은 제외했다.
- 수집전용서버42134157051·제어된복구42134295629·전체수동수집/발행42134436375가 모두 성공했다. 직접126본문/128첨부·성장금융115·출처22/22·협회원문오류0·공개227640c6cf239e14a401412a/30사업72페이지·외부30상세/health/접근경계를 확인했다. 실제전체에서는서울사용0/HTTP1.0복구1회였고 제어검사는주입2회뒤실제서울3목록으로검증했다.
- 기관별 운영 숫자는artifact의lp-collection-health.json/md다. 현재공개16기관30사업이며 공무원연금0공개를 반영해 수기점수의17기관공개확인을 정정했다. 원문수집/사업공개/자동성공을 혼동하지 않는다. 최신소스무인6회·주간예약·후속보관 확인은 [재개 체크포인트](lp_resume_checkpoint.md)를 따른다. 사용자LP앱버전2840e0c/다른서비스는 변경하지 않았다.

## LP 첫 재개 예약·보관 확인 — 2026-11-06 09:50

- lp-db가현재채팅에서실제발동했다. 활성LP작업/새정기회차없음·09:20창90분유예전이므로중복수집/배포없이후속보관42136933530성공을검증했다.109이력/106비공개보관/최신3전체/미보관0·공개72페이지와검토지문보존이다.
- 예약지시는이미완료된서울초안작업을빼고남은자동6회/주간감사/오류대응으로갱신했다. 같은id/채팅/60분/ACTIVE유지다. 최신공개227640c6cf239e14a401412a는유지됐고추가발행은없다. 조용한정상점검은사용자알림없이문서에남긴다.

## LP 1·2번 사전점검·캠코 제목 보완 — 2026-11-06

- Lead는현재주간감사42161864383을실행했고Worker는KAMCO파서/검사2파일을맡았다.124목록/24기관은정상이나신규공고의새글표시가제목에붙어본문대조1건오류가났다. eba84f9에서상태DOM만분리하고엄격한실제제목/날짜·원문지문·기존8공고를보존했다.
- 수정후재개42163150510은같은근거재사용으로공식HTTP0bytes·후보10중9확인/기존회원이벤트1보류·출처오류0/미처리0으로성공했다. 로컬1097/구조·CI42163137118성공이며DB쓰기/자료발행/사용자앱배포는없다. 최신공개227640c6cf239e14a401412a/30사업을유지한다.
- 매일수집/watcher/일요일감사예약은active다. 최신수정eba84f9이후자동0/6·11/8첫주간예약은아직확인전이다. 수동재생을자동성공에넣거나같은자료를반복수집하지않는다. 다음자동실행부터최신코드후속관계/발행/공개/보관을확인한다.

### LP 오후 정기수집 GEPS DNS 복구 — 2026-11-06

- 정기42177959130(15:20 예정/15:59:57 시작)은 공무원연금4검색 DNS 오류로 최종 실패했다. 정상21개 출처/협회 자료와 기존 공무원연금 근거는 보존해 공개12132e7db1fc858c1cbae3d7/30사업을 유지했다. 실패를 자동 성공으로 세지 않는다.
- 수집기c66c82b는GEPS의 두 번째 직접 시도에서만 typed OS DNS 오류 뒤 고정HTTPS DNS 메타데이터를 검증한다.5초/16KiB/추가조회재시도0·기존2요청/쿠키/공식호스트/SNI/인증서/리다이렉트 검증을 유지한다. Worker는DNS2파일,Lead는 연결/검사/Actions/통합을 맡았다. 로컬1103검사(실패/오류/skip0)·구조/YAML/shell/Python문법과CI42184712822 성공이다(CI GP자료 관련5skip).
- 제어검증42184743379는OS DNS오류2회 주입 후 실제 대체조회1회·공식목록76703bytes/10행·검증TLS를 통과했다. DB접근/발행이 없고 자연 장애 증명과 구분한다.
- 제한복구42184863444 성공: GEPS만6목록/3본문/2첨부 수집, 정상기관124본문/나머지coverage·우선/협회 보고서 동일성 유지, 이전 실패 이력 보존이다. 자연 재수집의DNS는 정상이어서대체조회0회다. 공개8c00113cb416c8ac56a5df2c/16기관30사업72페이지·새사업0·원문검증오류0·기존주소/선정정보 유지, 전체30상세/health/접근경계까지 확인했다. 저장된 정상자료+GEPS 복구를 코드로 집계한 결과22/22 출처정상·직접127본문/130첨부이며 이를 새전체자동수집 성공으로 세지 않는다. 사용자앱2840e0c/Newsletter/GP/DB구조/PE판정은 변경하지 않았다.
- 정기 후 보관42179850420은 성공(110이력/107보관/최신3전체/대상0·72페이지/검토지문 보존)이다. 복구 후 자동보관42185674559도 성공했다.17:13:03 KST 기준111이력/108비공개보관/최신3전체/대상0·DB535145619bytes/Storage405584457bytes·공개72페이지/검토지문 보존·동시변경0이다.
- 다음 작업: 최신 수집기c66c82b 이후 무인6회(현재0/6,다음11/9 09:20/15:20), 첫 일요일주간감사11/8 10:00와 후속보관 결과를 확인한다. 실패예약/수동복구/제어증명을 자동 성공에 넣지 않는다. 활성LP작업/시작유예/기존watchdog 보호와 공식HTTP 공유큐를 유지한다. 완료 기준 달성 전 예약을 끄지 않는다.
- 원시 근거는 /tmp/lp-scheduled-42177959130/, /tmp/lp-geps-dns-42184743379/, /tmp/lp-geps-recovery-42184863444/, /tmp/lp-storage-42179850420/, /tmp/lp-storage-42185674559/이다. 생성물/원문/비밀/DB/기존 사용자 변경은 소스 커밋에 넣지 않는다. 다음 실행은 docs/lp_resume_checkpoint.md와 docs/lp_collection_status.md의 최신 부분을 우선한다.

### LP 2023년 이후 기준·선정 명단·예약 확대 — 2026-11-06

- 사용자 요구가2023-01-01~현재의 기관 비교/통계 기반과 종료 사업의 선정 GP 표시로 구체화됐다.2026년 현재 네 개 연도다. 이전 과거 전수 비확대 지침보다 이 명시된 기간이 우선한다. GP 프로필 연결 후순위는 선정 이름 확보/표시 보류가 아니다. [과거 구축 계획](lp_history_backfill_plan.md)에 순서/완료 기준을 기록했다.
- Lead는 제품 기준·결과 상세/운영반영/예약/통합을, 재사용Worker는 과거경로 읽기검토와 오프라인집계2파일을 맡았다. b206d37의 초기 입력집계는22기관273원문URL(2023/2024/2025/2026=4/8/37/224),농협/수협 입력없음·첨부지문형식보류1·완전성미검증이다. 전체Supabase자료/PE사업 수가 아니며 다음 단계는 읽기전용전체DB메타목록이다.
- 공개30상세를실제로점검해접수마감12개기본사업의결과영역숨김과해당모집GP자료공백을확인했다. 보관된8월총회결과/2026사학VC를다른차수/2023PE에쓰지않는다. 일반기본발행의GP명단추출경로는아직미구축이다. b206d37은마감/결과발표사업의공백과실제결과링크를표시하되모집중/취소에빈영역을추가하지않고기존선정명단을유지한다. 실제선정사를새로확보한수정은아니다.
- 같은소스에신뢰된완료복구의기관근거를0HTTP로재사용하는검사를추가했다. 원본과초기시각/정상기관본문·coverage/URL/실패이력이같아야하고최종원문재검증·기존사업보존검사도유지한다. 실제127원문저장자료재생과로컬1118검사(실패/오류/skip0),구조/YAML/shell/Python문법·CI42221286688성공이다.
- 운영재발행42221332193은원본42177959130+완료복구42184863444를재사용해성공했다. 공식HTTP0·공개66391ec37791f25d07d63006/30사업/127원문/원문검증오류0·외부30상세에서12마감사업결과영역/기존GP이름·링크동일성/health/접근경계를검증했다. 새GP명단은추가하지않았다. 후속보관42222259703도성공했다.22:05:50 KST 기준112이력/109보관/최신3전체/대상0·DB535153811bytes/Storage412481111bytes·공개72페이지/검토지문보존·동시변경0이다. 신규공식HTTP/전체재수집이아니며기존30사업/주소/GP/추가캠코원문을보존해상세만반영한다. 종료뒤공개상세/health와후속자동보관까지확인했다. 사용자앱2840e0c배포·다른서비스·DB구조·PE판정변경은없다.
- lp-db를앱도구로update후저장파일에서검증했다. 같은id/현재채팅/heartbeat/ACTIVE/60분/failed_runs_only를유지하며2023년부터의목록/원문/사업·단계/선정명단구축과사용량회복뒤재시도를포함한다. 새채팅/작업트리/독립예약을만들지않았다. 기존무인6회/첫일요일감사·보관확인도병행한다. 단순대기만하거나과거구축미완료인데예약을종료하지않는다.
- 상세현황/다음단계는lp_resume_checkpoint.md·lp_collection_status.md의최신부분을따른다. 입력보관본은/tmp/lp-history-20261106/·화면점검은/tmp/lp-gp-detail-check-20261106/이며소스커밋에생성물/비밀/DB/기존사용자변경을섞지않는다.

### LP 보관DB 메타목록 운영 확인 — 2026-11-07

- 668d068/읽기전용42224383585는성공했다. LP보관문서577버전전체조회/315URL·연도별4/8/38/265(2023~26)·상한미도달/기관미식별·날짜충돌0·첨부지문형식보류2다. 공식시장전수/315PE사업이아니며협회재게시/범위외도포함한다. source_history_complete=false·전체연도미검증을유지한다.
- Worker는집계/검사2파일,Lead는DBexporter/워크플로/검사/통합을맡았다. 로컬1127/실패·오류·skip0·구조/워크플로문법·CI42224356545성공이며공유큐/watchdog활성보호도유지했다. 원문/HTML/첨부bytes를내보내지않고알려진비공개메타행을제외한다. DB쓰기/공식HTTP/수집/발행/앱/다른서비스변경은없고공개66391ec37791f25d07d63006을유지한다.
- 저장단서:부산2호재공고의10/26결과본문에어펄마캐피탈매니져스코리아가명시되지만공개는접수결과에머문다. 재공고단계일괄제외/모집차수중복제안/신규관련공고보류/명단표제파서가원인이다. 일반원문동일성/단계/명단규칙으로보강하며ID/선정사수동등록과다른차수·트랙혼합을금지한다. 새선정정보는아직공개하지않았다.
- 다음은저장근거를재사용한후속선정연결과2023고정시작·페이지커서과거발견이다. 최신메타목록은/tmp/lp-history-db-42224383585/이며같은DB조회/원문수집을불필요하게반복하지않는다. 다음무인일일창11/9·첫주간예약11/8은별도확인한다. watcher42228855397은window_covered로추가수집없이성공했으며자동6회실적으로세지않는다.

### LP 재공고 최종 선정 자동 연결 운영 반영 — 2026-11-07

- 1613eed/42270998285로 부산미래산업전환펀드2호재공고의 보관된10/26최종결과를 자동 연결했다. 공개fb139f3bf5cc17b448df9f3b의선정GP는어펄마캐피탈 매니져스코리아다. 최초모집2GP와원문/모든기존선정필드·30사업주소는그대로다. 공고ID/선정사수동등록·새공식HTTP·GP별배정액추정은없다.
- Worker는helper/검사2파일,Lead는투영·코호트분리·발행보존/통합/반영을맡았다. 단일트랙/검증인원/정확한사업명·연도·재공고/원문지문·URL·날짜/선행명단이맞는단순본문만자동화한다. 정정·취소·우선협상·예비·조건부·첨부/다중결과는보류한다. 로컬1141검사실패/오류/skip0·구조/문법·CI42270974006성공이다.
- 0HTTP원본42177959130+기관복구42184863444재사용·추가GP1/새사업0·16기관30사업73페이지·127기관원문/검증오류0이다. 외부30상세/health/접근경계·재공고1GP와10/26원문·원모집2GP/원문보존을검증했다. 앱2840e0c/Newsletter/GP/DB구조변경은없다. 후속보관42271809058도성공했다(03:37:07 KST·113이력/110비공개보관/최신3전체/대상0·DB535194771bytes/Storage419398324bytes·73페이지/검토지문보존·동시변경0).
- 다음은2023고정시작/검색·페이지커서과거발견과다른종결사업의결과공백이다. 전체24기관과거DB완료가아니다.1613eed이후자동성공0/6·11/8첫주간감사·11/9다음일일창을확인하고동일채팅lp-db/60분을유지한다. 상세와원시근거경로는lp_resume_checkpoint.md/lp_collection_status.md의최신부분을따른다.

### LP 2023년 이후 과거 목록 경계·이어받기 운영 검증 — 2026-11-07

- 7835f02/1020c74는별도성장금융역사목록경로이며고정2023-01-01~2026-11-06/기관·검색·페이지·원문지문/커서artifact를보관한다. 원본42177959130의12쪽·DB메타목록42224383585를재사용했다. 공식HTTP는Actions공유큐뿐이고새4쪽+직전1쪽검증/기존25초·3시도·12MiB/저장소main·artifact출처/watchdog보호를유지한다.
- 최초42303925104는정상13/14쪽뒤15쪽의동일고정글+일반행중복으로실패했다. 같은제목/날짜/공식URL인경우일반행실제위치로병합하는1020c74로저장실패응답을0HTTP재생했다. 원실패/응답은recovered_failures에유지하며다른실패/취소/제공자차단을재시도하지않는다.
- 42304411602→42304636869→42304866434→42304967533순서재개성공. 최종31쪽/294목록URL(2023=52/2024=69/2025=75/2026=98),31쪽일반행전체2022-10-12~11-18로시작일이전경계를검증했다. listing_window_complete=true이나source_history_complete=false/PE사업수미산정이다. 기존본문관측111/추가확인대기183은실제미보관확정이나PE공고183건이아니다.
- Explorer/Verifier는3기관어댑터/신규경로읽기검토·실패원인검토,Lead는코드/검사/통합/Actions검증이다.1152로컬검사실패/오류/skip0·구조/문법·CI42303897859/42304367659성공. 원문ID선택/기준변경/DB쓰기/본문·첨부HTTP/공개발행/다른서비스변경은없다. 공개fb139f3bf5cc17b448df9f3b/30사업73페이지는그대로라공개상세검증을반복하지않았다.
- 다음은성장금융보관본문재사용·부족본문제한배치와사업/선정연결·실제DB검증,교직원/우정/수출입을시작으로24기관의역사목록확장이다. 최종42304967533커서는완료돼더호출하지않으며/tmp/lp-history-resume-42304967533/의상태·요약을재사용한다. 일일최신수집/기존공개자료·PE판정·DB구조를유지한다. 최신수집기1020c74이후무인0/6·11/8주간감사·11/9일일창/현재채팅60분예약은계속한다.

### LP 과거 본문 실제 DB 보관·교직원 기간목록 — 2026-11-07

- ee63571/본문첫실제42312601991부터정상재개42313125436·추가42313505352→42313701689→42313798258→42313896694까지성공했다. 마지막08:44관측은2023-01-10~07-28원응답검증본문24건·실제documents577→601버전/본문대기122/첨부링크16미수집이다. 서식공식분류59건은목록·원문URL만유지해본문대상235(기존보관관측89/신규검증24/대기122)이며PE사업수나GP확정수가아니다.
- 자동계획4URL만읽기전용DB조회→검증된원응답캐시재사용→최대4본문HTTP→원응답독립재생→기존private.documents에만ON CONFLICT DO NOTHING→원문키DB읽기/공개·검토전후해시동일성검증이다. 신규본문만저장하고스키마/PE기준/다른서비스/공개사업은그대로다. cache운영42312903657은공식HTTP0/INSERT0/추가버전0을검증했다. 이검증을반복하지않는다.
- Worker는대기열2파일/추가본문배치,Lead는수집·원응답/DB검증·통합및독립교직원어댑터다. Worker는4추가성공뒤새dispatch CLI오류/사용량으로중단됐고실패한새Actions run은없다. stderr없이어떤결제/실행한도인지추정하지않으며,그뒤새KTCU2실행은실제로시작/완료됐다. 한도증액/다른계정/실패강제재실행은없고마지막정상42313896694의상태를재개기준으로유지한다. 원시/검증장부는LP체크포인트를따른다.
- b212242/42338158686→42338264602는교직원공제회2023-01-01~2026-11-07의4검색·7쪽/14URL(연도별4/2/4/4)을검증했다. PEF/블라인드는각1쪽의마지막페이지,운용사3쪽·펀드2쪽의모든일반행이2023년이전인경계를확인했다. 총목록8호출(연속성1포함)/본문·첨부/DB쓰기0·미해결0이며관측검색기간경계만완료다. 완료목록을다시요청하지않는다.
- 로컬본문1161/교직원포함1166검사실패·오류·skip0·구조/워크플로문법·CI42312571149/42338114413성공이다. 원문ID수동선택/GP추정/공개발행은없고공개fb139f3bf5cc17b448df9f3b/73페이지·검토지문을보존했다. 공개run이같아30상세/health/보관검증을반복하지않았다.
- 다음은성장금융본문122·첨부16링크/범위·사업·선정연결,교직원14URL의보관캐시/본문·첨부수집·DB보관어댑터,그뒤우정/수출입의과거목록이다. 성장금융body는listing_run42304967533/resume_run42313896694,교직원목록은42338264602 artifact가최신이다.24기관전체미완료/현재채팅lp-db60분/무인0/6·11/8주간감사·11/9일일창을유지한다.

### LP 교직원 과거 본문·기관별 공통 수집 보관 — 2026-11-07 14:40

- 성장금융 Worker 42342267612→42342343048→42342409616→42342478255의4제한배치가성공했다. 신규본문누적40(모두2023)/대기106·첨부23링크미수집,DB617버전관측이다. 이전성공원문/완료목록/캐시운영시험을반복하지않고마지막정상42342478255가재개기준이다.
- e77d85c/ee7e45a는목록kind·기관·URL/ID·인코딩·원응답파서를구분하며기존KGrowth상태/지문을그대로읽는다. 교직원은전체DB메타목록42224383585의네이티브4URL보관관측을재사용하고협회재게시를제외한다. 관측4와독립원응답재검증10을혼동하지않는다. DB스키마/PE판정/기존공개자료/GP정체성은변경하지않았다.
- 교직원42342974140→42343209333→42343269732가4+4+2본문을수집/원응답재생/DB읽기검증해누적10(2023=4/2024=2/2025=4),목록14URL의추가본문대기0·신규첨부27링크미수집이다. 주식/부동산도포함되며PE사업14건이아니다. 2024호텔부지/국내주식을PE블라인드사업으로만들지않는다. 표제상PEF블라인드2후보(2023/2025)는첨부/국내PE범위검증이필요하다.
- 전체신규본문50/실제documents577→627버전·각본문4호출이하/첨부HTTP0·원문키읽기/공개·검토전후해시보존이다. 공개fb139f3bf5cc17b448df9f3b/73페이지는같아30상세/health/보관검증을반복하지않았다. 공개발행/앱/다른서비스배포는없다.
- 최초교직원42342749240은artifact자료이름연결오류로다운로드단계에서실패했다(공식HTTP/DB접근0). ee7e45a는기관별workflow/artifact쌍을등록부에서검사·전달하고생산자/소비자계약검사를추가했다. 실패는보존하고수정뒤새실행을사용했다. 로컬1170검사실패·오류·skip0/구조/워크플로문법·CI42342935698성공이다.
- Worker는성장금융4배치/독립검토,Lead는공통어댑터·교직원통합/운영검증/기록이다. 공식HTTP는Actions공유큐뿐이고기존한도/main·성공artifact출처/정상자료보존을유지한다. Root검증요약은각최신artifact의root-verification-summary.json이다.
- 다음은교직원2023/2025후보공고첨부의자동선별/검증·국내PE범위/조건/일정·기본공개검증을우선하고,성장금융106본문/첨부23링크·사업/선정연결을병행한다. KTbody최신42343269732는본문대기0이라다시수집하지않는다. KGbody는listing_run42304967533/resume_run42342478255다. 이후우정/수출입등24기관으로확장하며전체목표·무인0/6·11/8주간감사·11/9일일창/같은채팅60분재개는계속한다.

### LP 과거 공고문 자동 선택·파일 원본 보관 — 2026-11-07 15:32

- 교직원공제회 2023·2025년 블라인드 PEF 후보의 공고문 HWP 2개를 코드가 자동 선택해 수집·본문 판독·원본 바이트 재생·DB 읽기 검증까지 마쳤다. 공고 ID나 파일을 수동 지정하지 않았고, 제안서 양식·동의서 6개는 다운로드 대상에서 제외했다. 10개 신규 본문의 첨부 링크 27개 중 공고문 2개를 확보한 것이며 모든 첨부나 모든 과거 사업이 완성된 것은 아니다.
- 소스5fb09da / 실행42347150318 성공: 본문 HTTP0·공고문 파일2요청(각 최대25초/3시도)·문서627→629버전이다. 원문과 파일 SHA256·실제 HWP 본문을 독립 재검증했다. 원래 본문 버전은 보존하고 첨부 근거가 붙은 버전2개만 추가했다. 공개/검토 전후 지문은 동일하다.
- 실제 이어받기42347292871도 성공했다. 저장된 두 파일을 재생하고 본문/첨부 HTTP0·신규 INSERT0·629→629버전·공개/검토 보존을 확인했다. 다음 첨부 재개 기준은 이 성공 실행이며 같은 공고문을 다시 받지 않는다. 근거는/tmp/lp-history-attachments-42347150318/와/tmp/lp-history-attachments-42347292871/다.
- 범위 판정 오류도 보완했다(7ad60a7). 운용사의 국내 사무소 요건을 국내 투자 근거로 보지 않는다. 2023년 공고문은 현재 확보 근거만으로 국내 투자 범위를 확정하지 못해 공개 보류다. 2025년은 국내 소재 기업에 펀드 규모70% 이상 투자 의무가 명시돼 PE 블라인드로 판정된다. 연도/공고ID별 예외 없이 문구 규칙으로 구분했다. 기존 저장본문194건 재생에서는 분류 변동0이며 기존 공개 사업을 바꾸지 않았다.
- 로컬 전체1181검사 실패/오류/skip0·구조/워크플로 YAML·shell·내장 Python 검사를 통과했다. 첨부 소스 CI42347092477은 성공(1180검사·실패/오류0·기존 GP 자료 의존5skip)했다. 범위 수정 CI42347442876도 성공했다(1181검사·실패/오류0·기존 GP 자료 의존5skip). Worker는 순수 첨부 큐/범위 판정과 검사, Lead는 원본 수집·공통 DB 보존·workflow·실제 실행/독립 검증을 담당했다.
- 공개fb139f3bf5cc17b448df9f3b /16기관30사업73페이지와 앱2840e0c는 유지했다. 신규 공개 발행·앱 배포·GP 선정 추가는 아직 없다. 결과 명단 탐색/연결도 미완료이며 공고문의 ‘개별 통보’를 결과 미게시의 증명으로 해석하지 않는다. 바뀌지 않은 공개30상세/health는 재검사하지 않았다.
- 다음 작은 완료 단위는 2025년의 금액·선정 계획 수·접수 마감/예정 일정 추출과 기본 공개 검증이다. 2023년은 추가 공식 투자 범위 근거부터 확인한다. 성장금융 본문 재개42342478255(신규40/대기106·첨부23미수집), 다른22기관 과거 경로, 최종 선정 결과 확보가 남았다. 자동0/6(판정 수정7ad60a7 이후)·11/8 첫 주간 감사·11/9 다음 일일 창·동일 채팅60분 재개는 유지한다.


### LP 공개 보완·운영 검증 인계 — 2026-11-08 23:38 KST

- 지난 예정 기간을 미래 일정처럼 보이지 않게 고쳤다. 경과 표시는 실제 완료를 뜻하지 않으며, 월 단위 원문은 그대로 표시한다. 교직원공제회 2026년의 지난 심사/최종선정 계획 3개와 개별통보 안내를 실제 공개 화면에서 확인했다. 날짜가 바뀌면 한국 시간 기준 표시도 갱신된다.
- 저장 공식 원문에서 우정사업본부 일반/루키 우선협상 6개사와 결과 원문을 자동 추출·연결해 공개했다. 최종 선정 명단과 구분하며 최종 GP 추가는0이다. 원문 ID/이름 수동 등록이나 금액 배분 추정은 없다. 반복 단계명·중복 결과 링크도 정리했다.
- 소스2831305/1e4ed7c, 로컬1189검사 실패/오류/skip0·구조/날짜 경계JS 검사, CI42365176916/42365733580 성공(CI 기존GP자료 의존5skip). 첫 발행42365246857에 이어 최종 정리 발행[42365949355](https://github.com/pkkong/korea-pef-db/actions/runs/42365949355)도 성공했다. 기존 정상 저장근거를 재생했고 공식HTTP0·재수집0·새사업0·기존30사업/16기관/73페이지와 모든 최종GP/조건/주소를 보존했다. 남은 출처 실패[]·기관원문 재검증오류0이다.
- 최종 공개run은22ed83c4906a7db7159fae6d다. 11/8 23:36 KST 외부30상세가 같은run/Supabase로 응답했고 health ok/stale=false·공개index/follow·검토noindex/no-store/DENY를 확인했다. Chrome 실제 화면에서 우선협상6행/원문1개·최종명단 미확인 문구, 지난 계획3개/미래형 안내 제거, 반복 단계명 제거를 확인했다. 모바일390(client375)/데스크톱1280(client1265)의 가로넘침0·console경고/오류0이며 임시 화면 크기는 복원했다. 앱release2840e0c와 다른서비스/SQL구조는 변경하지 않았다.
- 발행 후 자동보관[42366384131](https://github.com/pkkong/korea-pef-db/actions/runs/42366384131)도 성공했다.11/7 20:03:44 KST 관측115이력/112비공개보관/최신3보존/대상0·DB537021587bytes/Storage440385172bytes·공개73페이지/검토 지문 보존·동시변경false다. 앞선 자동보관42365676055도 성공했다. 원문 삭제/추가결제/한도변경은 없다.
- 공개 명단 감사는11/7 19:55 KST의 당시30/30페이지를 대상으로 최종명단11사업/28행·우선협상1사업/6이름·최종명단없는19사업·결과영역없는모집중1사업을 관측했다. 19개를 전부 종결사업 또는 공식 미공개로 단정하지 않는다. 이 수치는 당시 공개 화면 범위이며 전체 보관DB/2023년 이후 시장 수집률이 아니다. 발행 시 공백 이유 자동 집계와 저장 근거부터 최종결과 보강이 남았다.
- 첫 일요일 예약 감사[42457362418](https://github.com/pkkong/korea-pef-db/actions/runs/42457362418)는 실제 시작했으나 실패했다.10:00 KST 설정/16:05:45 실제 시작/16:11:10 종료를 구분한다. 최근365일의24기관·116성공목록/123요청 중23기관 정상, 농협은 첫 빈검색만 성공하고 뒤7검색이DNS오류다. 후보7개 중6본문 확인·KFCC1본문 근거불완전 보류이며 목록 실패와 구분한다. 공급자 시작 전 실패/결제 문제로 해석하지 않고 실패 신호를 유지한다. 이번 감사는2023년 이후 과거 전수 감사가 아니며 관측된명시PE미보관0을 전체누락0으로 쓰지 않는다.
- 다음 작은 단계는 정상116목록을 재수집하지 않고 실패한 농협7검색만 제한 진단·재개할 경로를 준비하는 것이다. 기존inventory_run은 실패목록을 그대로 재생하므로 반복 실행하지 않는다. 실제 근거 없이 대체DNS허용기관을 넓히지 않는다. 병행 남은 범위는 교직원2025조건/일정/기본공개, 성장금융106본문/첨부23링크, 다른22기관 과거 경로, 선정 공백 자동 집계, 기관/연도 비교·모집/마감/정정/결과 탐색이다.
- 최신 관련소스1e4ed7c 이후 일일 무인6회는0/6이다. 주간 예약 첫 실행은 실패여서 완료 조건이 아니다.11/9 09:20/15:20 다음 일일 창과 후속보관을 기다리며 유예 전/주말 전체수집·watchdog추가 요청은 하지 않았다. 같은채팅lp-db/ACTIVE/60분과AGENTS 기본 지속 원칙을 유지한다. 전체 서비스는 미완료이며 사용량/일시 공급자 제한에도 체크포인트부터 재개한다.
- 근거: /tmp/lp-polish-final-42365949355/의publication/preflight/remaining-failures/public-verification.json, /tmp/lp-current-public-selection-coverage-20261107.json, /tmp/lp-ops-verify-20261108/verification-summary.json 및 각Actions artifact. Lead는 공개 검증/통합·기록, 기존Worker는 명단 추출, 이번Verifier는 주간감사/보관 읽기검증을 맡았다. 사용자 기존 변경·DB·비밀·원문/생성물은 소스 커밋에서 제외한다.


### LP 농협 실패목록 진단 인계 — 2026-11-09 00:38 KST

- e6f8e7d는 완료된48시간 이내 main 주간감사의 저장 실패 중 농협 첫쪽 검색만 최대2개 자동선택하는 읽기전용 진단이다. 원문ID/검색URL 수동입력·정상116목록 재수집·감사 재실행이 아니다. 기존독립검색계획/기간/실패URL 일치를 먼저 검사하고 중복/외부주소/후속페이지/변조는HTTP전에 거절한다. 첫 오류가 반복되면 다른 검색도 중단한다.
- 실제42495628360은 기존lp-program-collection 공유큐·main에서 성공했다. 원래실패7개 중 공지게시판 운용사/펀드2검색만 기존Session(20초/최대2시도)으로 읽어60243/60240bytes·각0행의 검색양식/빈목록을 판독했다. 원시bytes/지문을 저장하고 로컬에서 지문과 원래파서로 독립 재생했다. 이번 자연 재조회는정상이며 대체DNS/TLS설정/허용기관은 바꾸지 않았다. 해당검색0행은 기관공고부재의 증명이 아니다.
- 원래42457362418의7실패는 그대로 보존하고 audit_recovered=false/publication=false다. 나머지5검색은 미진단이며 전체주간감사/후속페이지 복구는 미완료다. 재진단한2원응답을 다시 요청하지 않는다. 다음은 정상116목록+진단2응답을 재사용하고 나머지5실패검색만 제한배치로 이어갈 검증/합병 경로다. 실패 신호·단계/범위 판정·공개 자료를 변경하지 않는다.
- 로컬1194검사 실패/오류/skip0·구조·YAML/bash/내장Python 검사 통과,CI42495610318 성공(1194검사·실패/오류0·기존GP자료 의존5skip). watchdog의 공유큐 보호 목록에도 새진단workflow를 등록했다. 서로 맞물린 진단함수/검사/큐 연결의 작은 변경이므로 Lead가 단독 통합했다. 사용자기존변경/원문/DB/비밀은 커밋에 넣지 않았다.
- 근거는/tmp/lp-inventory-diagnostic-42495628360/의provenance/plan/result/root-verification.json과 같은run의lp-inventory-failure-diagnostic artifact다. 이번은DB접근/공개발행/앱배포0이며 공개22ed83c4906a7db7159fae6d는 직전 검증값이다. 새공개run이없어30상세/health/화면을 반복 검증하지 않았다. 자동일일0/6·주간첫예약실패·11/9 09:20/15:20창·2023년 이후 구축/선정/비교/탐색 목표·같은채팅60분 재개를 유지한다.


### LP 농협 실패검색 무중복 재개 인계 — 2026-11-09 01:39 KST

- 443cba8은 성공한 진단의 원시응답/지문/원래오류·검색순서·행수를 현재파서로 재생하고 아직 읽지 않은 실패검색만 최대2개씩 이어간다. 같은 감사main/48시간·성공진단/main·원본감사id 일치가 Actions에서 선검증된다. 실패진단/변조응답/다른원본·순서를 재개해 재시도하지 않는다. 정상116목록이나 완료검색을 다시 받지 않는다.
- 제한실행42500522648(재사용2/신규2/남은3)→42500614596(재사용4/신규2/남은1)→42500682441(재사용6/신규1/남은0)이 모두 성공했다. 이번 신규HTTP는 기존실패 첫쪽5검색뿐이며, 기존2응답과 합쳐7개 첫쪽을 검증했다. 자연DNS조회/기존Session으로 정상이며 대체DNS허용기관/TLS/재시도 상한은 바꾸지 않았다. 원시bytes/지문·기존응답 정확보존·실패이력 보존을 독립 재생했다. 완료상태를 다시 재생할 때HTTP0도 로컬에서 검증했다.
- 원래 주간예약42457362418은 여전히 실패다. 진단은audit_recovered=false/publication=false이며 새PE사업/GP결과를 만들지 않았다. 원래농협 정상1목록+진단7응답을0HTTP로 기존감사 파서에 넣어 후속경계를 확인했다. 공지운용사/펀드는빈목록,공지출자·입찰운용사/출자는마지막쪽,두게시판의검색어없는조회는최신1쪽 경계다. 입찰펀드는2쪽응답이 아직 없어미완료다. 이 오프라인 캐시 공백을 새DNS/네트워크실패로 해석하지 않는다. 빈검색/오래된행을 기관PE공고부재로 단정하지 않는다.
- 다음 가장작은 미완료는 원문에서 발견된 농협입찰펀드2쪽을 제한 수집하고 정상116목록/진단7응답과 합병·보관자료 대조를 검증하는 경로다. 현재진단은 첫쪽만 허용하므로 같은진단을 반복해2쪽을 얻으려 하지 않는다. 아직 새목록행의DB보관/공개원문 연결 대조는 하지 않았으며,빈baseline으로 한 오프라인경계검사의자료건수/보관판정은 사용하지 않는다.
- 로컬1196검사 실패/오류/skip0·구조·YAML/bash/내장Python 검사 통과,CI42500505424 성공(1196검사·실패/오류0·기존GP자료 의존5skip). 응답재생/순서·변조·실패진단 거절과 중복HTTP0을 검사했다. 서로 맞물린 작은진단/검사/workflow수정은 Lead 단독 통합했다. 기존사용자변경/비밀/DB/원시생성물은 소스커밋에서 제외했다.
- 최종근거는/tmp/lp-inventory-diagnostic-42500682441/의result.json/root-verification.json·최종Actions의lp-inventory-failure-diagnostic artifact다. 원본/이전진단provenance도 각실행에 남겼다. DB접근/자료발행/앱배포0·기존공개22ed83c4906a7db7159fae6d와다른서비스 유지다. 새공개run이없어30상세/health/화면재검사는 하지 않았다. 일일무인0/6·첫주간예약실패·11/9 09:20/15:20창·2023년 이후 구축/선정/비교/탐색 목표·같은채팅60분 재개는 유지한다.


### LP 농협 후속 목록 경계·다음 대조 — 2026-11-09 02:33 KST

- b089eee는 정상농협1목록+완료진단7응답을 먼저 재생해 원문 페이지제어가 요구하는 다음쪽만 최대2개씩 읽는다. 직전쪽/검색/전체행수 일치를 검사하고 페이지이동 중 총건수변경·변조·실패진단은 승인하지 않는다. URL/원문ID를 사람이 고르지 않고 기존Actions 공유큐·20초/최대2시도·공식호스트/TLS를 유지한다. 첫쪽진단 재실행이나 전체감사/116정상목록 재수집은 없다.
- 실제42505372534 성공: 농협입찰펀드2쪽만1회 신규요청해61806bytes/2행을 확보했다. 원래1쪽의총12행/마지막2쪽 제어와 일치하고 목록9응답(원래정상1+진단7+추가1)의8검색 경계를 확인했다. 입찰펀드최신2026-07-16/최소2021-03-18·관측마지막2쪽이다. 전시장 전수/9PE사업 또는2023년 이후 전체구축 완료가 아니다.
- 원시bytes/지문·현재파서/페이지경계를 독립 재생했고, 완료상태 재개는추가HTTP0·같은9목록을 검증했다. 원래7오류와진단7응답을 보존하며 전체감사복구/보관자료대조/공개발행은false다. 원래첫주간예약42457362418의실패를 성공으로 바꾸지 않는다. 단순캐시공백과 실제네트워크실패를 구분한다.
- 로컬1199검사 실패/오류/skip0·구조·YAML/bash/내장Python 검사 통과,CI42505361773 성공(1199검사·실패/오류0·기존GP자료 의존5skip). 후속자동발견·페이지총건수변경거절·변조/실패재개거절·완료0HTTP를 검사했다. 서로맞물린 작은진단함수/검사/workflow변경은 Lead 단독 통합했다. 사용자기존변경·비밀·DB·원시생성물은 소스커밋에서 제외한다.
- 다음은공식HTTP없이현재읽기전용DB의보관URL/공개원문을 대조하고,정상23기관/원래116목록과새농협9응답의관계를 보존해 감사결과를 합병하는 것이다. 빈baseline의오프라인경계검사는보관/누락판정에 쓰지 않는다. 합병검증 뒤같은수집/진단을늘리지않고교직원2025조건/일정/기본공개·성장금융106본문/23첨부링크·다른기관2023년고정시작과최종선정/비교·탐색을 이어간다.
- 근거:/tmp/lp-boundary-recovery-42505372534/의provenance/plan/result/root-verification.json·같은run의lp-inventory-failure-diagnostic artifact다. 이번DB접근/자료발행/앱배포0·기존공개22ed83c4906a7db7159fae6d와다른서비스는같다. 새공개run이없어상세/health/화면을재검사하지않았다. 일일무인0/6·첫주간예약실패·11/9 09:20/15:20창·현재채팅lp-db/60분은유지한다.


### LP 농협 감사합병·보관 대조 완료 — 2026-11-09 03:37 KST

- ef6b787/2f46337은 저장된농협9목록만 재생하고 현재LP DB를REPEATABLE READ/READ ONLY로조회해 원기관URL/공개원문을 대조한다. 원래116목록의전체접두부와다른23기관의행/검색인덱스를그대로보존해 새농협8응답만추가했다. 실제42510630511은공식HTTP0·DB쓰기0·124목록/24기관·미연결/미측정/남은목록오류0으로성공했고 독립비교를통과했다. 새전체수집이나자동예약성공이 아니다.
- 첫대조42510375841은발행기관NH태그가붙은KOFIA재게시를NH원기관URL로취급해실패했다. 기존전체DB메타목록42224383585로실제협회재게시를확인한뒤원기관키와KOFIA212/17보조키를분리했다. 외부/변조주소는계속거절하며실패실행은보존했다. 수정후같은오류를반복재실행하지않고새코드/새읽기검증42510630511에서완료했다.
- 11/9 03:34:24 KST 현재DB대조는농협태그/원기관호스트로조회한고유URL1개(원기관키0/협회보조키1),현재공개run22ed83c4906a7db7159fae6d/농협공개원문키0을확인했다. 다른23기관의보관판정은원래감사값을유지했으며현재전체DB를재측정한것이아니다. 농협의기간내22행/관련제목2건은DB원기관URL미관측이지만본문미확보나PE사업부재를뜻하지않는다.
- 관련2건은이미검증한41644570867의공식본문/첨부와URL로자동대조해추가공식HTTP없이재생했다. NPL은중앙회가직접계약/자금출자를하지않고회원조합이개별계약한다는공고첨부,미스터리쇼핑은용역입찰본문을확인해중앙회PE출자로공개하지않는기존판정을보존했다. 원기관DB키부재를새미수집으로간주해다시받지않는다. 이검증자료는gitignored exports/lp_inventory_evidence/41644570867/에도보존했다.
- 합병제목집계는미보관관련49개(제목상범위외41/범위미확인7/VC1)다. 시장누락률이나49PE사업이아니다. NH2건의본문근거범위외확인과제목집계를구분한다. 원래후보7개/6본문확인/KFCC1본문불완전·벤치마크파일은바이트동일성으로보존했으며새전체후보판독으로표시하지않는다. 전문건설독립API제한·원래농협7실패/원래요청123회는별도보존한다. 합병summary.requests=124는저장목록재생논리건수이고신규공식HTTP는0이다.
- 로컬1202검사 실패/오류/skip0·구조·YAML/bash/내장Python검사 통과,CI42510363004/42510618002 성공(1202검사·실패/오류0·기존GP자료 의존5skip). 다른23기관/원래116목록·7실패보존·현재보관/공개키분리·잘못된/불완전인덱스거절·읽기전용첫문장을검사했다. 서로맞물린한정합병/검사/workflow는Lead단독통합했다. 사용자기존변경·비밀·DB·생성물은소스커밋에서제외한다.
- 합병원자료는42510630511 Actions artifact의comparison/lp-official-inventory.json/md다. 독립검증/기존본문재생요약은/tmp/lp-inventory-compare-42510630511/의root-verification.json·retained-candidate-evidence.json이며,원본문은gitignored exports/lp_inventory_evidence/41644570867/에보존했다. 새공개/앱배포가없어30상세/health/화면을재검사하지않았다. 원래첫주간예약은실패·수동합병검증성공이며일일무인0/6·11/9 09:20/15:20창·현재채팅60분재개는유지한다. 이농협자료/진단/합병을반복하지않고다음은교직원2025조건/일정/기본공개와성장금융106본문/23첨부링크·2023년이후전체사업/선정·비교/탐색보강을이어간다.


### LP 교직원 과거 조건 추출·다음 운영입력 — 2026-11-09 04:39 KST

- 2cb32d5/b50f714는 교직원공제회의 typed 과거첨부 근거에 한해서 원본문 bytes/지문/파싱결과와 원문에서 연결한 공고문 bytes/지문/재판독 텍스트를 다시 검증한 뒤 단일 PE 블라인드 표를 판독한다. 원문ID/연도 예외목록은 없고 현재2026 고정사업의 기존 경로는 변경하지 않았다. 모집원문과 공고문의 연도/공고일 일치로 월·일 마감의 연도를 묶으며, 잘못된 비율/복수 값·마감충돌·거꾸로 된 예정기간은 보류한다.
- 저장된42343269732 본문/42347292871 첨부를0HTTP로 재생했다.2025년 공고에서 출자예정7,000억원 이내·선정예정10개사 이내·2025-04-04 15:00 KST 마감·펀드규모70%이상 국내소재기업 투자 문구를 추출했다. 4월초~중 1차심사/4월말 현장실사·2차심사/5월중 최종선정은 모두 원문 월단위 예정기간으로 유지한다. 이10개사는 실제선정 명단이나 GP별 배정액이 아니다.
- 공통 기본발행 함수/모델 검증에서2025년1개 사업을 생성했고, 로컬 상세에는 정확한 마감/7,000억원/10개사와 지난예정3개가 표시되는 것을 확인했다. 최종GP는빈값/결과미확인이다.2023년 공고문은 여전히 국내투자 근거부족으로 보류했다. 이번은 로컬 모델·HTML 확인이며 DB쓰기/운영발행/앱배포/실제공개화면 반영은0이다. 전체서비스 완료로 표시하지 않는다.
- 로컬1206검사 실패/오류/skip0·구조 통과,CI42515984370/42516062798 성공이다(기존GP자료 의존5skip). 검사는 원문/첨부변조, 연도와공고일 불일치, 관리운용사 소재지와투자지역 구분, 총액/인원/마감 충돌·비율0/100초과·예정기간 역순을 포함한다. 한기관의조건/증거검증/공통연결이맞물린작은3파일변경이라 Lead가단독통합했다. DB구조/기관/PE판정·다른서비스는변경하지않았다.
- 재사용근거는 gitignored exports/lp_history_evidence/ktcu-20261107/의 history-state/body-state/attachment-state와 manifest.json, verification.json/preview.html이다. 각원본의실행id와내용지문을보존했고 raw/생성물은소스커밋에서제외했다. 2025년로컬기본모델은운영URL 확정이나최종발행id를뜻하지않는다.
- 다음작업은 저장과거자료를 신뢰된Actions성공run에서 자동검증해 운영발행의별도입력으로 연결하는것이다. 최근일일보고서에 과거원문이최신수집된것처럼 섞지않는다. 기존DB의동일URL/본문·첨부지문과대조하고2023보류/2025단일사업·기존30주소/조건/최종GP 보존을 확인한뒤 실제공개/health/모바일을검증한다. 현재공개22ed83c4906a7db7159fae6d/30사업73페이지·앱2840e0c는직전검증값이고이번에재검사하지않았다. 성장금융106본문/23첨부링크·다른기관2023년이후·최종선정/비교·탐색과 무인0/6·11/9창·동일채팅60분재개는계속한다.


### LP 과거 운영입력 DB 대조·다음 실제발행 — 2026-11-09 05:38 KST

f13ffd7/실제42520850697은 교직원 목록/본문/첨부 성공자료의 원시증거·자동대기열을 재생하고 현재DB의 같은 두 문서URL/내용지문/저장JSON을 읽기전용으로 대조했다. 기존30사업의 모든필드·선정GP·일일as_of/검토결정을 보존한31사업 제안을 공통빌드로 검증했다.2025의7,000억원이내/10개사이내/정확한마감/월단위예정3개·최종GP빈값,2023국내투자근거부족보류를 유지한다. 공식HTTP/DB쓰기/공개발행은0이며 현재공개22ed83c4906a7db7159fae6d/30사업73페이지는 같다. 새자료를 최신일일수집으로 표시하거나 실패/수동을 자동성공으로 세지 않는다.

로컬1211검사/구조·workflow문법/CI42520785130 성공이다(CI 기존GP자료 의존5skip). 최초검사에서누락된watchdog활성큐등록을수정해재검증했다. 근거/DB조회/제안이맞물린작은단계라Lead단독통합했으며 다른서비스/DB구조/기존사용자변경은건드리지않았다. 근거는gitignored exports/lp_history_evidence/preflight-42520850697/와같은run의lp-history-publication-preflight artifact다.

다음은동일사전검증반복이아니라원시근거를다시검증한실제발행연결이다. 오래된일일보고서의48시간제한을풀지않고별도과거입력경로로현재DB/검토변경을트랜잭션에서대조한다. 기존검토페이지를보존하고새전체상세/health/모바일·후속보관까지확인한다. 제안빌드73개는검토페이지제외이며운영73페이지와혼동하지않는다. 과거범위/최종선정·비교/탐색·성장금융106본문/23첨부링크·무인0/6·11/9창·현재채팅60분재개는미완료다.
