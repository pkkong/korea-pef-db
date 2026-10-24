# 프로젝트 리드 현재 상태판

기관별 LP 구축 현황은 [LP 공고 수집 구축 현황](lp_collection_status.md)을 우선한다. 일반 현황 질문은 이 표로 답하고, 작업 완료 시 해당 행을 갱신한다. 아래 날짜별 기록은 이력이며 최신 구축 상태와 혼동하지 않는다.

최종 수정: 2026-10-24 KST

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
