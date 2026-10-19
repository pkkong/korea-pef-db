# 제품 운영 모델

최종 수정: 2026-09-07 KST

이 문서는 제품 운영의 최상위 기준이다. 새 기능, 새 데이터 소스, 새 화면을
추가하기 전에 먼저 이 문서의 서비스 책임선과 공개 정책을 확인한다.

## 핵심 원칙

뉴스레터·LP·GP는 각각 독립 서비스이며, 사용자에게는 공통 메뉴와 링크로 연결한다.

### 런타임과 데이터의 우선순위

1. **Vercel**: 사용자가 보는 유일한 공식 서비스 runtime이다. `브리프 / LP / GP`의 공개 URL과 배포 확인은 Vercel 기준으로 한다.
2. **Supabase**: 서비스의 영속 canonical DB와 versioned public read model의 기준 위치다. Vercel은 published public data만 읽는다.
3. **GitHub**: 코드, versioned raw input, migration, workflow를 관리하는 개발·운영 저장소다. GitHub Pages는 검증·장애 대비용 정적 backup mirror일 뿐 공식 서비스가 아니다.

SQLite는 parser·정규화·renderer를 위한 임시 계산 파일로만 허용한다. 로컬 SQLite나 GitHub Pages HTML을 공개 서비스의 runtime DB 또는 기본 화면으로 취급하지 않는다.

- `Brief`: 매일 읽는 뉴스 클리핑 서비스다. 기사 수집, 분류, 태그, 중복 제거,
  언론사 로고, 검색, 아카이브, 발행 품질만 책임진다.
- `LP`: 출자기관, 출자사업, 공식 공고, 서류심사, 선정결과, 선정 GP, LP 관련
  뉴스 연결만 책임진다.
- `GP`: 운용사 목록, GP 프로필, 금감원 기반 시장 통계, 펀드, People/뉴스 연결만
  책임진다.
- `Shared`: 공통 shell, 하단 메뉴, 검색 패턴, 디자인 토큰, 브랜드 자산,
  통합 빌드와 배포 계약을 책임진다.
- `Wiki`: 재기획 전까지 공개 메뉴와 루틴 빌드에서 제외한다. 기존 코드는 보존하되
  새 작업 대상이 아니다.

## 공개 제품 범위

현재 공개 1차 목적지는 `브리프 / LP / GP` 세 개다. Wiki와 저장함은 설계가
다시 잡히기 전까지 전역 메뉴에 넣지 않는다.

공개 화면은 반드시 정리된 public-facing 데이터만 읽는다. 후보 데이터, 검토 중
데이터, 내부 상태, source/evidence 필드명, 자동화 설명은 공개 화면으로 새면 안
된다.

## 서비스별 인터페이스

각 서비스는 자기 산출물만 만든다.

- Brief builder: `scripts/build_newsletter_bundle.py`가 `index.html`, `daily-news.html`, `archive.json`, `health.json`, 뉴스레터 assets를 만든다. LP, GP, Wiki, legacy deploy monolith를 import하면 안 된다.
- Brief/GP Vercel app: `services/newsletter/web/`는 Vercel의 독립 runtime이다. Brief는 Supabase 공개 read model row를 먼저 읽고, 장애나 빈 데이터가 있으면 기존 public `archive.json`으로 fallback한다. GP는 published `gp_public_snapshots`/`gp_public_pages`만 읽고 GitHub Pages HTML을 runtime fallback으로 사용하지 않는다. 뉴스 수집을 하지 않고 LP/GP/Wiki crawler나 renderer 코드를 import하지 않는다. Supabase는 기본 최근 30개 issue를 유지해 Vercel 날짜 이동이 GitHub Pages mirror와 같아야 한다. Vercel은 날짜 skeleton용 `newsletter_issues`와 기사 내용·순서용 `newsletter_public_issue_articles`를 함께 읽어야 한다. 화면은 GitHub Pages mirror와 같은 `services/newsletter/web/newsletter_ui.py` HTML/CSS/JS 원본으로 렌더링한다.
- LP builder: `lp-*.html`, `lp-notices.html`, `lp-official-notices.html`,
  `lp-notice-*.html`, LP public data.
- GP builder: `market.html`, `gps.html`, `gp-*.html`, GP public data.
- Wiki builder: 명시적으로 요청될 때만 `pef-wiki.html`을 만든다.
- Bundle builder: 서비스 산출물을 `services/newsletter/deploy/site/`로 모으고
  `health.json`, 공통 assets, zip artifact를 만든다.
- 공개 상태 검사기: `services/newsletter/src/newsletter_public_status.py`가 뉴스레터 workflow에서 반복 쓰는 mirror freshness, verified archive, Vercel health, watchdog 검사를 담당한다.
- 구조 검사기: `scripts/check_architecture_contracts.py`가 cross-service private import, newsletter workflow 역할 drift, generated output tracking을 막는다.

서비스 renderer는 다른 서비스의 원천 데이터나 화면 규칙을 직접 고치지 않는다.
다른 서비스 데이터가 필요하면 public view, export, shared helper를 통해 읽는다.

## 독립 서비스와 공개 연계

Brief, LP, GP는 하나의 제품 안에서 보이지만 각각 독립적으로 수집·정규화·검수·발행할 수 있는 서비스다.

- 각 서비스는 자기 raw source, canonical DB, review 상태, public read model을 소유한다.
- 다른 서비스의 SQLite table, raw source, crawler, renderer를 직접 import하거나 외래키로 참조하지 않는다. 다른 서비스의 canonical DB를 수정하지도 않는다.
- 서비스 간 연결은 versioned public contract만 사용한다. Brief는 공개 archive의 GP/LP entity link를 발행하고, LP는 검수된 lifecycle과 선정 GP를 `lp-notices.json`으로 발행하며, GP는 검증된 public snapshot/profile을 발행한다.
- 연계 정보는 enrichment다. 상대 서비스의 public context가 없거나 일시적으로 읽히지 않아도 자기 서비스의 수집·공개 발행은 계속된다. 기존 public context를 빈 결과로 덮어쓰지 않는다.
- Shared는 공통 shell, nav, 디자인 언어, 배포 검증만 책임진다. Shared가 서비스별 raw data ownership을 합치거나 하나의 거대한 runtime DB를 뜻하지는 않는다.

따라서 사용자는 한 제품 안에서 뉴스 기사에서 GP/LP로, LP 공고에서 선정 GP로, GP 프로필에서 뉴스·LP 이력으로 이동할 수 있어야 한다. 하지만 Brief, LP, GP 중 하나를 떼어 별도 서비스로 운영해도 나머지 서비스의 수집·DB·발행이 멈추면 안 된다.

## 화면 유형

화면을 만들 때 먼저 뷰 타입을 고른다.

- 기사: 평평한 article list.
- LP/GP 목록: 표에 가까운 directory row.
- LP/GP 상세: profile detail.
- LP 출자공고: 사업 단위 row-card.
- Market: 통계 section과 compact table.
- Wiki: 문서형 화면. 현재는 숨김.

이 체계를 벗어나는 새 화면은 바로 구현하지 말고
`docs/service_quality_backlog.md`에 먼저 적는다.

## 새 아이디어 처리 기준

새 아이디어는 즉시 공개 화면에 섞지 않는다.

1. 어떤 서비스 소관인지 정한다.
2. 공개 데이터인지 후보 데이터인지 정한다.
3. 필요한 DB/public view/export가 있는지 확인한다.
4. renderer 변경 전에 `docs/data_operating_model.md`와 `docs/design_system.md`를 확인한다.
5. 구현 후 control center와 backlog를 갱신한다.

## 운영 흐름

- 매일 08:37 KST: `Build newsletter mirror`가 Brief 수집, 분류, GitHub Pages 백업 미러 생성/검증만 수행한다.
- Mirror가 새로 생성/검증된 경우: `Build newsletter mirror`가 `Sync newsletter Supabase read model`을 dispatch하고, sync workflow가 verified mirror archive를 Supabase에 복사한 뒤 Vercel 공식 앱을 검증한다.
- 매일 09:22 KST: `Newsletter publish watchdog`이 한 번만 freshness를 확인한다. 최근 6시간 안에 mirror build가 실패했으면 같은 실패를 다시 dispatch하지 않고 종료한다.
- 필요 시: `Deploy newsletter Vercel app`은 Vercel 앱 코드 배포만 수행한다. 뉴스 수집, Pages 미러 생성, Supabase 동기화는 하지 않는다. GP FSS 발행 workflow는 검증된 GP snapshot만 Supabase에 publish하며, Vercel은 다음 요청에서 그 snapshot을 읽는다.
- 하루 1-3회: LP 공고 수집, 사업 상태 갱신, public-ready 공고만 공개 빌드.
- 주기적: GP/LP 프로필, 로고, People, 뉴스 연결 보강.
- 필요 시: 통합 사이트 빌드와 배포.
- Wiki: Wiki 기획이나 본문 변경이 있을 때만 명시적으로 빌드.

Brief와 GP는 현재 이 `Supabase → Vercel` 경로로 공개된다. LP는 local collector와 static export에서 Supabase canonical/public read model로 옮기는 작업이 남아 있으며, 이 전환이 끝나기 전까지 GitHub Pages나 로컬 export를 LP 서비스의 기본 운영 경로로 보지 않는다.

2026-09-06 점검 당시 LP Vercel 경로는 아직 없고 Pages 공고 페이지가 실제 메뉴 연결 대상이었다. 따라서 이번 오류 수정은 Brief의 GP 메뉴만 공식 `/gps.html`로 연결하고 LP 링크는 이전 완료까지 유지한다. 데이터 갱신 안전성·장애 응답 수정은 2026-09-07 뉴스·GP DB와 Vercel 앱에 반영했다. LP 화면은 전체 검수 원본 복원이 필요해 기존 공개본을 보존한다. 상세 운영 적용 결과는 `docs/project_lead_control_center.md`와 `docs/project_fixes_2026-09-06.md`에서 구분한다.

## 완료 기준

운영 체계상 완료는 소스 수정만으로 끝나지 않는다.

- 서비스 책임선이 맞다.
- public view 또는 public export 기준으로 화면이 생성된다.
- 내부/운영자 표현이 공개 화면에 없다.
- 빌드와 검증 명령이 통과한다.
- 변경된 결정이 control center, backlog, 관련 운영 문서에 남아 있다.
- 배포 여부와 공개 URL 검증 여부가 별도로 보고된다.


## 독립 실행·배포 서비스 전환 (사용자 확정 지시)

사용자는 뉴스레터·LP·GP가 각각 독립 제품이며 사용자에게 메뉴와 링크로만 연결된다고 명시했다. 각 서비스는 자기 웹앱, Vercel 프로젝트, 배포 workflow, 공개 읽기 설정과 데이터 공간을 소유한다. 다른 서비스가 설치되지 않아도 실행·빌드·배포되어야 한다. 뉴스레터가 LP/GP 코드를 불러오거나 빌드·검사·파일을 요구하던 기존 구조는 이 기준에 맞게 제거한다.

공통 CSS/JS/아이콘은 services/shared/web/service_assets.py의 단일 순수 함수 원본을 각 배포 패키지에 포함한다. 다른 서비스의 실행 서버에서 공통 assets를 가져오지 않는다. newsletter_ui.py는 뉴스레터 HTML의 단일 원본을 유지하고 기존 정적 미러를 위해 자산 함수를 재노출한다. 옛 주소는 다른 서버를 조회하지 않고 각 서비스로 redirect한다.

현재 Supabase 서버/계정은 공유하지만 논리 데이터 공간과 앱별 설정을 분리한다. LP/GP 전용 Supabase 공개 읽기 secret이 있으면 각 배포가 그것을 사용하며 기존 공용 설정은 전환용 기본값이다. 물리 DB 서버 장애까지 완전히 분리됐다고 표현하지 않는다. 실행 앱에는 DB URL/관리자 service-role key를 전달하지 않는다. 배포 전환 완료 여부와 실제 주소는 상태판의 후속 검증 기록을 따른다.


운영 전환 완료: 브리프 `https://kpef-newsletter.vercel.app/`, LP `https://kpef-lp.vercel.app/`, GP `https://kpef-gp.vercel.app/`가 각각 별도 Vercel 프로젝트에서 실행된다. 메뉴와 옛 주소 이동만 연결하며 한 서비스 코드 배포에 다른 서비스가 포함되지 않는다. LP 앱 주소 분리는 수집범위 확대·발행게이트 변경·정식출시 완료를 뜻하지 않는다.


## LP 신규 공고 자동 공개 기준 — 사용자 승인

공식 국내 PE 블라인드 모집이 확인되면 기관·제목·게시일·원문으로 기본 공고를 공개한다. 금액·선정 수·주목적·마감은 검증된 값만 추가하며, 모든 조건이나 GP 명단의 완성을 공고 노출의 선행조건으로 삼지 않는다. 혼합 모집은 PE 트랙이 독립 검증된 경우만 공개한다. 미확인 범위·불명확한 사업 연결은 보류한다.

후속 단계는 기관·연도·사업·차수의 원문 근거로 연결하며, 기존 사업 주소를 유지한다. 재공고를 최초 모집에 합치거나 GP 결과를 추정하지 않는다. 정정·취소 후 이전 마감·예정 일정은 현재 정보로 노출하지 않는다. 이 기준은 기존 연결 기관 전체에 적용하며 미연결 기관의 수집 완료를 뜻하지 않는다.
