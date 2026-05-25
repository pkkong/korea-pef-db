# Daily PEF News Clipping 운영 가이드

## 매일 흐름

1. 자동 작업이 오전 8:30에 `services/newsletter/scripts/run_daily_news_today.ps1`로 초안을 생성한다.
2. `services/newsletter/scripts/start_daily_news_review.ps1`을 실행해 리뷰 화면을 연다.
3. 리뷰 화면 상단의 날짜 선택에서 오늘 또는 과거 클리핑 날짜를 고른다.
4. 리뷰 화면에서 각 기사별로 필요하면 `포함`, `제외`, 카테고리 변경을 선택한다.
5. `저장`을 누른다.
6. 최종 배포본으로 확정할 때 `최종본 확정`을 누른다.

## 수집 기준

- 뉴스레터 기준은 `오늘 발행 기사`가 아니라 `최근 24시간 오전 브리핑`이다.
- 예: 2026-04-30 오전 8:30 실행분은 2026-04-29 08:30부터 2026-04-30 08:30 사이 기사/검색 결과를 대상으로 한다.
- 오전 8:30 이후 발행된 기사는 같은 날 초안이 아니라 다음날 오전 브리핑 후보로 들어가는 것이 기본 운영 기준이다.
- 발행 시간이 확인되는 기사는 이 24시간 창으로 필터링하고, 발행 시간이 없으면 실행 당일 발견된 기사로 처리한다.

## 뉴스레터 분류 체계

KPEF Daily의 1차 섹션은 `AI & PE`, `Deal`, `LP`, `GP`, `Market` 다섯 개다. 상위 섹션은 독자가 먼저 훑는 뉴스레터 흐름이고, GP/LP/인물/포트폴리오 회사명은 별도 태그와 검색 facet으로 함께 관리한다.

각 기사는 상위 섹션 1개와 subtype 1개를 가진다. subtype은 섹션 내부에서 사건을 다시 묶는 논리적 축이며, 회사명이나 기관명이 아니라 기사에서 실제로 벌어진 일과 독자가 얻어야 할 시사점에 맞춘다.

- `AI & PE`: AI가 사모시장 투자판단, 운용 방식, 포트폴리오 밸류업, 리스크 관리에 직접 영향을 주는 기사
  - `AI 전략·운영`: GP의 AI 도입, 투자심사 자동화, 포트폴리오 운영 개선, 밸류업 사례
  - `AI 투자·인프라`: AI 기업 투자, AI 인프라, 데이터센터, 컴퓨트, 반도체, 클라우드 관련 투자 thesis
  - `AI 리스크·규제`: 모델 리스크, 데이터 거버넌스, 저작권/IP, 보안, AI 정책과 규제
- `Deal`: 특정 자산이나 회사의 소유권, 지분, 자본구조가 바뀌는 거래 기사
  - `인수·투자`: 바이아웃, 성장투자, 소수지분, 카브아웃, take-private, 우선협상
  - `매각·엑시트`: 매각, IPO, 블록딜, 공개매각, 회수 성과
  - `세컨더리·컨티뉴에이션`: GP-led 세컨더리, LP 지분 세컨더리, 컨티뉴에이션 펀드
  - `파이낸싱`: 인수금융, 프라이빗크레딧, 메자닌, 리파이낸싱, 리캡, 대주단
- `LP`: allocator의 자금배분, 출자 의사결정, 운용사 선정, 포트폴리오 관리가 중심인 기사
  - `출자사업·RFP`: 출자사업 공고, 위탁운용사 선정, 숏리스트, 최종 선정, 출자확약, 앵커 출자
  - `자산배분·정책`: 대체투자 비중, PE 목표비중, 투자정책서, 거버넌스, 리밸런싱
  - `성과·포트폴리오`: LP 수익률, 포트폴리오 노출, 현금흐름, 리스크 점검
  - `유동성·세컨더리`: allocator 관점의 LP 지분 매각, 세컨더리 프로그램, 유동성 관리
- `GP`: 운용사 자체의 펀드, 조직, 전략, 플랫폼, 포트폴리오 관리가 중심인 기사
  - `펀드레이징`: 블라인드펀드, 프로젝트펀드, 공동투자 펀드, 1차/최종 클로징, 목표액, 약정총액
  - `조직·인력`: 대표/파트너 선임, 팀 이동, 승진, 사무소 개설, 조직개편
  - `전략·상품`: 신규 전략, 섹터 플랫폼, 크레딧/인프라/세컨더리 확장, GP stake, 운용사 제휴
  - `포트폴리오·밸류업`: 포트폴리오 회사 실적, PMI, 구조조정, 운영 개선, 밸류업
- `Market`: 개별 거래나 기관 공지가 아니라 시장 전체의 방향, 제도, 데이터, 거시 환경을 설명하는 기사
  - `시장동향·데이터`: 드라이파우더, 멀티플, 회수시장, 펀드레이징 환경, 리그테이블, 설문/리포트
  - `거시·금리·크레딧`: 금리, 환율, 유동성, 대출시장, 레버리지 론, 스프레드
  - `규제·세제·정책`: 금융위, 금감원, 금투협, 공정위, 세제, 법 개정, 제재, 소송, 내부통제
  - `전략·전망`: 하우스뷰, CIO/전략가 코멘트, 섹터 전망, 지역별 투자환경

분류 우선순위는 `AI & PE`, `Deal`, `LP`, `GP`, `Market` 순서다. AI가 핵심 thesis나 운용 변화이면 거래·펀드 기사라도 `AI & PE`로 보낸다. 특정 인수, 매각, 세컨더리, 파이낸싱이 핵심이면 GP/LP 이름이 들어가도 `Deal`로 본다. 국민연금이나 공제회가 등장해도 공식 출자사업, 자산배분, 포트폴리오 관리, allocator 유동성 이슈가 아니면 `LP`로 보내지 않는다. GP는 운용사 자체의 펀드레이징·조직·전략·포트폴리오 운영이 기사 주제일 때만 쓴다.

## 산출물

- 초안: `exports/daily_news/daily_news_brief_latest.md`
- 리뷰 화면: `exports/daily_news/daily_news_review_latest.html`
- 리뷰 CSV: `exports/daily_news/daily_news_review_actions_latest.csv`
- 날짜별 리뷰 CSV: `exports/daily_news/daily_news_review_actions_YYYYMMDD.csv`
- 최종본: `exports/daily_news/daily_news_final_latest.md`
- 최종본 HTML: `exports/daily_news/daily_news_final_latest.html`
- 날짜별 최종본: `exports/daily_news/daily_news_final_YYYYMMDD.md`
- GP 업데이트 큐: `exports/daily_news/news_gp_update_worklist_latest.csv`
- 뉴스/People/GP 통합 작업 큐: `exports/service_integration_worklist_latest.csv`
- LP 출자사업 모니터: `exports/lp_commitment_monitor_latest.csv`

## 검증

- 매일 로컬 Mac 발행 작업은 초안 생성 직후 `services/newsletter/src/validate_daily_news_pipeline.py` 기준 검증을 남긴다.
- 매일 로컬 Mac 발행 작업은 `services/newsletter/src/build_newsletter_deploy.py`로 `services/newsletter/deploy/site/`를 만들고 public mirror `pkkong/kpef-newsletter`에 push한다.
- 매일 로컬 Mac 발행 작업은 `scripts/build_lp_commitment_monitor.py`를 실행해서 주요 LP 출자사업 공고/선정/뉴스 후보를 갱신한다. LP 공고 모니터는 뉴스레터 핵심 콘텐츠가 아니므로 공개 Daily와 분리하는 방향을 기본으로 둔다.
- 별도 LP 공고 탭은 `new_notice`, `deadline_soon`, `shortlist`, `final_selection` 등 이벤트 타입을 우선 노출한다. `program_size`는 정책펀드 전체 규모로 보관하되, 공개 출자규모 합산에는 `allocation_amount`만 사용한다.
- 공개 Daily 화면은 최근 날짜별 `daily_news_brief_YYYYMMDD.md`를 함께 포함하므로, 사용자는 날짜 선택으로 과거 브리프의 주요 뉴스도 볼 수 있다.
- 매일 뉴스 파이프라인은 `scripts/build_service_integration_worklist.py`도 실행해서 뉴스 노출 GP, People DB 커버리지, 담당자별 다음 액션을 하나의 작업 큐로 갱신한다.
- 공개 뉴스 화면은 확인된 GP/관련 인물 같은 독자용 맥락만 표시한다. `프로필 보강`, `식별자 보강`, 리뷰 큐, 작업 담당자 같은 운영 상태는 공개 화면에 노출하지 않는다.
- 공개 DB 화면은 `public/db.html`과 `public/data/service_data.json`을 사용한다. 운영 큐와 DB 품질 점검은 `dashboard/` 운영 콘솔에만 둔다.
- 당일 산출물과 자동화 상태를 수동으로 점검하려면 `services/newsletter/scripts/validate_daily_news_today.ps1`을 실행한다.
- 코드 변경 후 전체 점검은 `services/newsletter/scripts/check_daily_news_pipeline.ps1`을 실행한다. 이 스크립트는 Python 컴파일, 핵심 로직 테스트, 당일 산출물 검증을 순서대로 실행한다.
- 검증 항목은 산출물 존재 여부, 최근 24시간 기준 문구, 중복 링크, Google News 중계 링크, 리뷰 카테고리 값, DB 최신 실행 상태, 네이버 API 설정, Windows 예약 작업 상태다.
- 백테스트는 운영 산출물을 덮어쓰지 않도록 `exports/daily_news/backtests/` 아래 별도 폴더에 저장된다.
- PC 의존성을 없애는 클라우드 이전 계획은 `services/newsletter/docs/cloud_migration.md`에 정리했다.

## 리뷰 기준

- `제외`: PEF 관련성이 약하거나 잡뉴스라고 판단한 기사
- `포함`: 자동 필터에서 빠졌지만 볼 가치가 있는 기사
- `카테고리`: 상위 섹션 또는 subtype 자동 분류가 틀렸을 때만 선택
- LP/GP는 상위 섹션이지만 기관명이 등장했다는 이유만으로 선택하지 않는다. LP 세컨더리는 특정 거래이면 `Deal`, allocator의 유동성 관리 이슈이면 `LP`로 분류한다. GP 펀드 클로징은 `GP`, 특정 포트폴리오 인수·매각은 `Deal`로 분류한다.

## 발송

아직 자동 발송은 초안 생성과 분리했다. 최종본을 확정한 뒤 발송하려면 `services/newsletter/scripts/send_daily_news_final.ps1`을 사용한다.
`daily_news_final_latest.*`가 최신 초안보다 오래된 경우에는 최종본 확정이 먼저 필요하다.
