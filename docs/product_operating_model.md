# 제품 운영 모델

최종 수정: 2026-09-03 KST

이 문서는 제품 운영의 최상위 기준이다. 새 기능, 새 데이터 소스, 새 화면을
추가하기 전에 먼저 이 문서의 서비스 책임선과 공개 정책을 확인한다.

## 핵심 원칙

공개 사이트는 하나의 제품이지만, 운영 책임은 서비스별로 분리한다.

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

## 완료 기준

운영 체계상 완료는 소스 수정만으로 끝나지 않는다.

- 서비스 책임선이 맞다.
- public view 또는 public export 기준으로 화면이 생성된다.
- 내부/운영자 표현이 공개 화면에 없다.
- 빌드와 검증 명령이 통과한다.
- 변경된 결정이 control center, backlog, 관련 운영 문서에 남아 있다.
- 배포 여부와 공개 URL 검증 여부가 별도로 보고된다.
