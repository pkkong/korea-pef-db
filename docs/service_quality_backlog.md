# 서비스 품질 백로그

이 문서는 뉴스레터, LP, GP 담당 영역이 다음 작업을 이어받기 위한 제품 품질 백로그다. 담당 영역명은 실제로 계속 켜져 있는 하위에이전트가 아니라 서비스 소유권 라벨이다. 공개 화면에는 운영 상태, 제작자 설명, 원천 데이터 필드명을 노출하지 않는 것을 기본 원칙으로 한다. Wiki는 재기획 전까지 현재 작업이 아니라 보류 작업으로 둔다.

## 공통

- 하단 메뉴는 `브리프 → LP → GP` 순서를 모든 서비스에서 고정한다. Wiki는 재기획 전까지 공개 메뉴에 노출하지 않는다.
- 서비스별 소유권 라벨을 실행 중인 하위에이전트 수로 취급하지 않는다. 실제 병렬 작업은 `Lead`, `Worker`, `Verifier`, `Documentation` 중 필요한 소수 역할만 사용한다.
- Project Lead는 작업 전후에 `docs/project_lead_control_center.md`를 확인하고, 서비스별 소유자·검증·배포 상태·반복 오류를 갱신한다.
- Project Lead는 별도 채팅방이 맡은 서비스를 방치하지 않는다. 해당 서비스는 그 채팅방이 구현하되, 이 문서와 control center에는 소유권, 통합 조건, 검증 조건, 남은 리스크를 유지한다.
- 별도 채팅방이나 서브에이전트에 업무를 넘길 때는 control center의 handoff template을 사용한다. 사용자가 같은 결정을 다시 설명하게 만들면 운영 실패로 본다.
- 공개 UX/UI 개선은 `docs/design_system.md`를 기준으로 한다. 뉴스레터에서 정리한 flat list, 원형 아이콘, restrained typography, table-like row 원칙을 LP/GP/Wiki에 확장한다.
- 공개 화면 금지 표현은 `docs/agent_operating_briefs.md`의 공개 화면 문구 원칙을 따른다.
- 생성 HTML 기준 금지 표현 스캔, 모바일 렌더링, 콘솔 에러 확인을 배포 전 필수 검증으로 둔다.
- 새 아이디어는 담당 서비스, public-view 계약, 검증 방법이 정해지기 전까지 바로 화면이나 DB에 섞지 않는다. 먼저 `docs/product_operating_model.md`와 `docs/data_operating_model.md` 기준으로 분류한다.

## 현재 우선순위

2026-09-06 검토에서 확인한 오류는 소스 수정과 로컬 검증을 완료했다.
검토 근거는 `docs/project_review_2026-09-06.md`, 수정 결과와 운영 반영 순서는
`docs/project_fixes_2026-09-06.md`를 따른다. 2026-09-07 뉴스·GP DB 보호 장치와 Vercel 앱을 운영에 반영했다. 최종 자료 발행 상태는 control center를 따른다.

- 소스 수정 완료: 뉴스 태그·기사 연결과 People을 한 DB transaction에서 교체하고 실패 시 기존 자료를 보존한다.
- 소스 수정 완료: FSS 변환 결과가 달라지면 새 버전을 만들며 공개된 과거 행의 변경을 차단한다.
- 소스 수정 완료: 원문 cache cleanup의 목록 조회 실패도 경고로 처리한다.
- 소스 수정 완료: 테스트 자동 수집, 0개 실행 방지, PR/push 검사와 LP 사업/회차 병합 오류를 수정했다.
- 소스 수정 완료: GP 페이지별 cache 만료와 제한된 마지막 정상 자료 제공, 뉴스 장애 상태 응답, 공식 GP 메뉴 연결을 반영했다.
- 운영 반영: 뉴스·GP migration과 Vercel 앱 배포 완료. 새 뉴스·GP 동기화/발행과 공개 검증까지 성공했다. GP migration은 과거 profile 제약 migration 전체를 재실행하지 않는다.
- 별도 제품 과제: LP의 Vercel route/public read model 이관을 완료한 뒤 LP 메뉴를 전환한다.

1. `scripts/check_architecture_contracts.py`와 `scripts/check_public_frontend.py`가 실패하면 구조 리팩터링이나 UX 작업은 완료로 보지 않는다.
2. 남은 legacy public-site cleanup은 `scripts/build_service_site.py`와 `services/lp/src/lp_legacy_service_pages.py`의 실행 시점 의존을 서비스별 helper로 더 줄이는 것이다. import-time 결합은 architecture contract로 차단한다.
3. LP Notice를 사업 단위 서비스로 안정화한다. 같은 사업의 공고, 서류심사, 선정결과, 정정, 취소가 여러 카드로 흩어지면 실패다.
4. LP Notice 상태를 최신 이벤트와 마감일 기준으로 다시 검증한다. 2025년 마감 공고가 현재 모집중처럼 보이면 실패다.
5. LP/GP 디렉토리는 뉴스레터에서 정리한 타이포그래피, 40px 원형 로고 슬롯, table-like row 구조를 유지한다.
6. 뉴스레터 별도 채팅방 결과는 이 프로젝트의 통합 빌드, architecture contract, 공개 frontend 검증을 통과해야만 배포 완료로 본다.

## 최근 처리

- 2026-09-08 완료 확인: 브리프·GP 배포와 새 동기화 검증 완료. 공개 브리프는 Vercel/Pages 모두 9월 8일자 19건으로 일치한다. 최종 CI 244개 발견·실패 0(전체 DB fixture 없는 5개 skip), SQL 실패 검사 14개 통과. LP 공고 화면은 아래 원본 복원 과제가 남아 기존 공개본을 보존한다.

- 2026-09-07 운영 확인: 같은 날짜의 백업 기사 수가 더 많다는 이유로 정정 전 기사가 되살아나는 문제를 수정했다. 같은 날짜는 Supabase 공개본을 우선하며 0건 정정도 보존한다. Deal 세부 분류의 작성/검사 우선순위를 통일하고 LP schema 갱신의 최신 SQLite 호환 문제도 수정했다.

- 2026-09-07 인계: 안정성 수정의 로컬 자동 검사 241개와 PostgreSQL 실패/rollback 검사 14개를 통과했다. 통합 frontend 검사는 기사 원문에 들어간 일반 영어 단어를 내부 필드로 오인하지 않으며, 아이콘 누락은 기존 운영 규칙대로 경고 처리한다. 이후 사용자의 배포 지시로 뉴스·GP DB와 Vercel 앱에 반영했다. LP 화면은 전체 원본 복원 전까지 보존한다.

- 2026-06-21: LP/GP/Market empty-state UX를 table-like shell 안에 고정했다. 로컬 DB나 export가 비어도 `lp-directory-card`, `gp-card`, Market chart container가 사라지지 않으며, `scripts/check_public_frontend.py`와 390px/1280px browser smoke가 이를 확인한다.
- 2026-06-21: 구조 재발 방지 계약을 코드로 추가했다. `scripts/check_architecture_contracts.py`는 LP/GP/Wiki의 newsletter-private import, newsletter-only/Vercel import isolation, newsletter workflow 역할 침범, generated output tracking을 검사한다. Newsletter workflow의 mirror freshness, archive download, public mirror verification, Vercel verification, watchdog freshness 판단은 `services/newsletter/src/newsletter_public_status.py`로 이동했다.
- 2026-06-18: 뉴스레터 독립화 정리를 추가로 진행했다. 큰 legacy `services/newsletter/src/build_newsletter_deploy.py` 파일은 `services/lp/src/lp_legacy_service_pages.py`로 이동했고, 뉴스레터 경로에는 `scripts/build_newsletter_bundle.py`로 위임하는 얇은 compatibility wrapper만 남겼다. LP 공개 helper는 `services/lp/src/lp_public_views.py`로 분리했으며, 뉴스레터 테스트는 더 이상 legacy deploy module을 import하지 않는다. 뉴스레터 로컬 스크립트도 LP/dashboard/public-site builder가 아니라 `scripts/build_newsletter_bundle.py`를 호출한다.
- 2026-06-17: 뉴스레터 Vercel/GitHub Pages UI 원본을 `services/newsletter/web/newsletter_ui.py`로 단일화했다. Vercel app은 공식 화면, GitHub Pages는 static backup mirror로 고정하고, 둘 다 같은 CSS/JS를 제공한다.
- 2026-06-17: Vercel archive가 `newsletter_issues`와 `newsletter_public_issue_articles`를 함께 읽도록 고정했다. 기사 0건 issue도 archive에 남기고, `section_order=0`을 정상 값으로 보존해 Pages와 Vercel의 표시 순서가 달라지지 않게 했다.
- 2026-06-17: Vercel data/UI contract test를 Actions readiness/deploy workflow에 연결했다. 별도 Vercel template/CSS 부활, LP/GP/Wiki/legacy import, empty issue 누락, `section_order=0` 손실을 회귀로 본다.
- 2026-06-11: 뉴스레터 자동 발행 장애를 정리했다. 08:30 수집·검증은 성공했지만 아시아경제 `www.asiae.co.kr` 로고 1건 missing icon hard gate 때문에 public push 전 중단됐다. 아시아경제 도메인 매핑을 추가하고, 아이콘 검사는 기본적으로 품질 리포트만 남기며 당일 공개 배포를 막지 않도록 바꿨다. 최종 공개 배포 `ae5d291`은 `health.json report_date=2026-06-11`, 기사 30건으로 확인했다.
- 2026-06-11: `newsletter_ops_status.py`는 로컬 진단 산출물을 남길 수 있다. 정식 발행 완료 기준은 GitHub Actions 로그와 공개 `health.json`/`archive.json` 확인이며, 개인 컴퓨터의 로컬 빌드 상태를 운영 기준으로 삼지 않는다.
- 2026-06-10: `newsletter-only`와 `integrated-site` 빌드 계약을 분리했다. 뉴스레터 단독 빌드는 LP/GP 산출물을 요구하지 않고, 배포 mirror에서는 기존 LP/GP 파일을 보존한 채 브리프 파일만 갱신한다.
- 2026-06-10: 운영 체계 문서를 추가했다. 제품 책임선은 `docs/product_operating_model.md`, DB/public-view/build 계약은 `docs/data_operating_model.md`를 기준으로 한다. Wiki는 기본 공개 빌드에서 제외하고 명시 요청 시에만 빌드한다.
- 2026-06-10: 뉴스레터 public archive contract를 강화했다. `tagVersion=news-taxonomy-v1`, GP/LP entity chip link contract, publisher icon, Google News redirect 금지를 `scripts/check_public_frontend.py`에서 검사한다.
- 2026-06-10: LP public JSON은 공식 source, 승인된 candidate parser, stale deadline 제거, supporting document/noise 제거, 내부 필드 제거 조건을 통과해야 한다. renderer가 숨기는 방식만으로는 공개 품질을 통과한 것으로 보지 않는다.
- 2026-06-10: GP Market 페이지는 금감원 최신 source registry 기간, 대표 운용사 기준 GP count 문구, People disabled 상태, 정적 trend/top-GP chart markup을 공개 검증에서 확인한다.
- 2026-06-09: LP Notice 공개 게이트를 조정해 공식 후보라도 명시 허용된 public-ready 소스만 노출한다. `vcs_investment_notice` 후보는 공개에서 제외한다.
- 2026-06-09: LP Notice 사업명 추출에서 포털 메뉴, 약관/동의 문구, 투자성향 설명문이 사업명으로 들어오는 경우를 차단했다.
- 2026-06-09: LP Notice 카드 병합 키에 자산군과 연도를 포함해 서로 다른 연도·자산군 공고가 한 카드에 섞이는 위험을 줄였다.
- 2026-06-09: Wiki가 숨겨진 상태이므로 public frontend check에서 Wiki 필수 검사를 제거하고 LP Notice 전용 금지 문구 검사를 추가했다.
- 2026-08-30: LP collector가 뉴스·GP 내부 SQLite 테이블을 외래키로 요구하던 결함을 제거했다. LP build는 독립적으로 동작하며 기존 DB는 link table migration으로 호환한다. 자동 발견한 official candidate도 public HTML/JSON/GP signal에는 넣지 않고 `validated` 이후에만 공개한다. 요청한 source limit을 벤처투자포털 한 곳이 무시해 500건을 강제하던 동작도 제거했다.

## 뉴스레터

- 현재 뉴스레터 분류·태그 품질 개선은 별도 채팅방이 active owner다. 이 문서는 통합 기준과 회귀 조건만 유지한다.
- 태그 더보기 버튼을 작은 텍스트형 컨트롤로 정리한다. `+N`만 보이는 어두운 버튼은 쓰지 않는다.
- 0건 날짜는 아카이브에서 숨기거나 `발행 없음` 상태로 명확히 표시한다.
- 과거 백테스트 기사에도 최신 GP/LP 태그 로직을 다시 적용한다.
- Google News 중계 링크가 최종 발행본에 남지 않게 검증을 강화한다.
- 유사 제목 중복은 경고가 아니라 발행 차단 기준으로 올린다.
- 검색 placeholder는 `뉴스·기관·운용사 검색`처럼 실제 검색 범위와 맞춘다.

## LP

- 배포 차단(2026-09-07): 전체 검수 monitor/DB를 복원해야 LP 공고 재배포가 가능하다. 공개 legacy JSON은 현재 공고 대표 원문 5개와 검수 필드가 누락되어 대체 원본으로 부적합하다. `build_lp_service_pages.py --monitor`가 목록에도 동일한 입력을 사용하도록 계약을 정리한 뒤, 기존 83개 공고의 출처·이력과 상세 URL 보존을 확인한다. 이번 오류 수정 배포에서는 기존 LP 공개본을 보존했다.

- 출자기관 디렉토리는 직접 GP/위탁운용사를 선정하는 LP만 보여준다. OCIO 또는 전담운용사가 하위 운용사 선정 실무를 맡는 공적기금·위임형 자금 주체는 `coverage_tier=ocio`, `display_enabled=0`으로 별도 pool에 보관하고 공개 기본 목록에서 제외한다.
- 출자기관 공개 노출은 공식 기관 성격이 아니라 실제 PE/VC/대체 출자공고·선정 이력 기준으로 판단한다. 이력 0건 기관은 후보로 숨기고, KIC·수협·캠코처럼 사용자가 명시한 전략기관만 예외로 공개 유지한다.
- 기관 분류는 자본시장법상 기관전용 사모집합투자기구 LP 적격 유형을 기준으로 `legal_lp_category`에 둔다. 공개 여부와 서비스 중요도는 `display_enabled`, `coverage_tier`에서 따로 관리한다.
- LP 디렉토리를 `docs/design_system.md`의 LP/GP shared row contract에 맞춘다. 카드형 KPI와 가로 스크롤을 줄이고, 모바일에서도 핵심 컬럼이 남는 표형 row를 우선한다.
- LP 유형과 자산군은 화면에 한국어 라벨로 표시한다. 예: `정책금융기관`, `공제회`, `사모대출`, `부동산`, `모태펀드`.
- `0/0`, `자료 정리 중`, `검증 필요` 같은 운영 상태를 공개 화면에 노출하지 않는다.
- 18개 LP 전체에 일반현황, 투자현황, 담당 조직, 출자공고, 선정 GP 히스토리의 최소 커버리지를 맞춘다.
- 공고 모니터와 LP 프로필은 연결하되, 공고 수집 상태는 운영 화면으로 분리한다.
- 다음 LP Notice 과제는 `candidate`를 무조건 많이 보여주는 것이 아니라, 소스별 parser readiness를 올려 공개 가능한 공고 수를 다시 늘리는 것이다. 특히 `vcs_investment_notice`는 좋은 discovery source지만 현재 public parser로는 부적합하다.
- KOFIA 목록 응답은 bounded retry로 보강했다. 다음 수집 runs에서 retry 빈도와 최종 실패율을 source health로 기록해, 재시도가 반복되는 채널은 parser/transport 개선 대상으로 분리한다.

## GP

- GP 디렉토리를 `docs/design_system.md`의 LP/GP shared row contract에 맞춘다. 무한 스크롤, 반복 순위, 반복 `상세 프로필` 텍스트, 과한 헤더 타이포를 정리한다.
- GP 디렉토리는 금감원 명단 뷰가 아니라 운용사 프로필 서비스처럼 보여야 한다.
- 결핍 정보는 크게 노출하지 않는다. 홈페이지, 분류, 대표자, 설명이 없으면 조용히 생략한다.
- 상위 120개 GP부터 홈페이지, 대표자, 법인명, 회사 설명, 출처를 보강한다.
- 공개 화면에 enum, proxy, source/evidence 영문 라벨이 나오지 않게 생성 HTML 회귀 검사를 둔다.
- FSS 수집 내부 번호를 외부 GP identity로 사용하지 않는다. profile evidence와 공개 URL이 장기적으로 안정된 GP canonical ID를 필요로 하면 `fss_gp_<source_gp_id>`에서 분리하는 migration을 별도 설계한다.
- GP alias·프로필 evidence 검증은 오류를 발견해 수정할 운영 신호다. 원본 통계가 정상인 경우 이 품질 경고만으로 public snapshot 배포를 막지 않는다.

## 보류: PEF Wiki

- Wiki는 재기획 전까지 공개 메뉴와 routine build에서 제외한다.
- Wiki는 PDF 링크 모음이 아니라 본문형 문서 서비스다.
- Wiki source는 Newsletter 밖으로 이동했다. 앞으로 Wiki markdown과 refs는 `services/wiki/content/wiki/` 아래에 둔다.
- 우선 문서 범위는 실무안내 제1장, 관련 법률·규정, 세무신고, 금감원·금융위원회 보고, 실무 체크리스트다.
- 각 문서는 `본문`, `관련 조문`, `보고/제출`, `실무 확인`, `출처`로 이동 가능해야 한다.
- 표는 원문이나 비교 구조상 꼭 필요한 경우에만 사용한다.


## 서비스 실행·배포 분리 완료

뉴스레터·LP·GP는 각각 별도 web 앱·Vercel 프로젝트·배포 workflow로 전환했다. 브리프 kpef-newsletter.vercel.app, LP kpef-lp.vercel.app, GP kpef-gp.vercel.app. 공통 자산은 각 앱에 포함하고 다른 서비스 서버에서 읽지 않는다. 자료·옛 링크 보존, 서비스별 분리 실행, CI 및 외부 모바일 검증 완료. 상세 배포 기록은 control center의 독립 서비스 운영 전환 완료 절을 따른다.

잔여 범위: 공유 Supabase 서버/호스팅 계정 장애는 물리적으로 분리되지 않았다. LP 수집범위 완성·확인된 신규공고 노출·정정/마감 검사와 정식출시는 별도 과제이며, 앱 분리를 LP 서비스 전부 완성으로 세지 않는다.


## LP 기본 공고 자동 공개 반영

공식 국내 PE 블라인드 모집의 기본 공개를 모집조건 전체/GP 명단과 분리했다. 과기공·군인·전문건설3사업 자동 추가(17→20), 우정1차 심사 원문 연결, 기존URL·자료 보존을 실제 수집/발행으로 확인했다. 금투협 HTTP200 불완전 응답 복구와 제한 재시도, 재공고/정정/취소·마감 및 월 단위 일정 표시도 보완했다. 최종소스68cda73/운영39254941732 성공.

다음은 지방행정공제회·경찰공제회·사학연금·신협중앙회 및 사용자 우선기관의 실제 수집 경로 확장이다. 기관별 구축·운영 상태는 docs/lp_collection_status.md 한곳에서 관리한다. GP 프로필 연결·과거 전수·로그인은 다음 수집 확대의 선행조건이 아니다.


## LP 네 기관 직접 수집 연결

행정공제회·경찰공제회·사학연금·신협중앙회를 공고 ID 목록에 의존하지 않는 공식 게시판 수집으로 연결했다. 혼합 PE/VC·공동투자 금액과 펀드별 상한을 구분하며 원문 날짜를 보존한다. 운영 결과는 `docs/lp_collection_status.md`에 기록한다. 다음 대상은 새마을금고중앙회와 정책은행 등 추가 우선기관의 미연결 경로다. 현재 부분 연결 기관의 독립 발견과 모호한 후속 공고 연결도 계속 남아 있다. GP 연결·로그인·과거 전수는 뒤로 미룬다.


## LP 출시 마감 항목 — 2026-10-20

산업·기업은행50본문 운영 저장, 기존25공개 주소 보존 완료. 새마을금고는 로컬 수집/PE판독/모바일 확인은 끝났지만 GitHub macOS/Linux 모두 HTTP400 Request Blocked로 운영 미완료다. 해당 차단의 공식 대체 수집 경로나 실행 환경을 우선 확인한다. 공고ID를 골라 수동 등록하지 않는다. 오늘 예약의 공무원연금DNS·전문건설HTTP400은 별도 추적하며 수동 성공으로 해결 완료 처리하지 않는다. docs/lp_first_release_checklist.md의 남은 조건을 통과하기 전 정식 오픈 완료라 보고하지 않는다. GP·로그인·과거 전수 복원은 이후 작업이다.


## LP 출시 마감 갱신 — 2026-10-21

새마을금고 지속 차단은 인증된 서울 전송기로 해소했다. 운영 `39536759687`에서 5본문·첨부 4건을 자동 수집하고 2025년 PE 사업 1건을 공개했다. 기존 25주소 보존·26상세·모바일 포함 9화면 검증을 완료했다. 공식 자료 판독은 기존 경로를 사용하며 벤치마킹 감지 목록은 별도 자동 누락 대조에만 쓴다. 직접 운영 9+부분 연결 8, 추가 확인 7기관을 유지한다.

다만 같은 실행의 최종 결과는 신협 목록 2요청의 macOS DNS 오류로 실패다. 기존 신협 자료 보존과 로컬 200을 운영 복구로 오인하지 않는다. 다음 작업은 신협 실행 경로 진단, 이전 예약 장애 추적, 수정 후 실제 예약 성공 확인이다. 09:20/15:20 예약과 실패 알림은 유지한다. 새마을금고 해결을 정식 오픈 전체 완료로 세지 않는다. 현황과 끝내는 기준은 `docs/lp_collection_status.md`와 `docs/lp_first_release_checklist.md`를 따른다.


## LP DNS 복구 검증 및 운영 정상 종료 — 2026-10-21

신협의 typed DNS 오류 대응을 구현하고 산업은행에서도 확인된 같은 형태의 오류에 공통 IPv4 HTTPS 복구를 연결했다. 쿠키·허용 호스트·원래 hostname/SNI·TLS·크기/시간 한도와 직접2시도 예산을 유지한다. 공식 사이트를 호출하는 시험과 운영 수집은 같은 실행 대기열로 묶었다. Ubuntu 전체 전환은 산업은행 TLS EOF 검증 실패로 적용하지 않았다.

최종 운영39541070805(Source f740c2d)는6작업/발행/장애보고까지 모두 성공했다. 이번69본문·첨부66건, 기존26사업·주소 보존,26상세/외부12화면 검증을 완료했다. DNS 오류 주입 시험과 실제 운영을 구분하며 중간 KDB DNS·KFCC502 실패 기록을 지우지 않는다. 과거 오류 원인은 미확인으로 남긴다. 다음은 이후 실제 예약 수집의 성공 확인과 재발 관찰이다. 범위/끝내는 기준은 docs/lp_collection_status.md와 docs/lp_first_release_checklist.md를 따른다. 새 기관·GP·로그인·과거 전수를 새로운 선행조건으로 늘리지 않는다.
