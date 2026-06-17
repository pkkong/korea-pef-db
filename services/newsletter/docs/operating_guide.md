# Daily PEF News Clipping 운영 가이드

## 매일 흐름

1. GitHub Actions가 오전 8:37 KST에 뉴스 수집, 분류, 요약 보강, 정적 사이트 생성을 실행한다.
2. 수동 검토가 필요하면 GitHub Actions 결과물 또는 로컬 개발 산출물의 리뷰 화면을 연다.
3. 리뷰 화면 상단의 날짜 선택에서 오늘 또는 과거 클리핑 날짜를 고른다.
4. 리뷰 화면에서 각 기사별로 필요하면 `포함`, `제외`, 카테고리 변경을 선택한다.
5. `저장`을 누른다.
6. 최종 배포본으로 확정할 때 `최종본 확정`을 누른다.

## 수집 기준

- 뉴스레터 기준은 `오늘 발행 기사`가 아니라 `최근 24시간 오전 브리핑`이다.
- 예: 2026-04-30 오전 8:30 실행분은 2026-04-29 08:30부터 2026-04-30 08:30 사이 기사/검색 결과를 대상으로 한다.
- 오전 8:30 이후 발행된 기사는 같은 날 초안이 아니라 다음날 오전 브리핑 후보로 들어가는 것이 기본 운영 기준이다.
- 발행 시간이 확인되는 기사는 이 24시간 창으로 필터링하고, 발행 시간이 없으면 실행 당일 발견된 기사로 처리한다.
- 자동 발행은 토요일과 일요일에도 매일 돈다.
- 월요일도 예외적인 72시간 창을 쓰지 않는다. 주말 수집 실패, 검색 반영 지연, 소스 오류를 회수해야 할 때는 일일 발행 창을 넓히지 말고 별도 backfill/audit 작업으로 처리한다.
- 월요일 브리프에서 기사 수가 줄어 보이면 먼저 토요일·일요일 브리프에 이미 발행되어 `previous export` 중복 제거로 빠졌는지 확인한다.

## 뉴스레터 분류 체계

KPEF Daily의 1차 섹션은 `AI & PE`, `국민성장펀드`, `Deal`, `LP`, `GP`, `Market` 여섯 개다. 상위 섹션은 독자가 먼저 훑는 뉴스레터 흐름이고, GP/LP/인물/포트폴리오 회사명은 별도 태그와 검색 facet으로 함께 관리한다.

각 기사는 상위 섹션 1개와 subtype 1개를 가진다. subtype은 섹션 내부에서 사건을 다시 묶는 논리적 축이며, 회사명이나 기관명이 아니라 기사에서 실제로 벌어진 일과 독자가 얻어야 할 시사점에 맞춘다.

- `AI & PE`: AI가 사모시장 투자판단, 운용 방식, 포트폴리오 밸류업, 리스크 관리에 직접 영향을 주는 기사
  - `AI 전략·운영`: GP의 AI 도입, 투자심사 자동화, 포트폴리오 운영 개선, 밸류업 사례
  - `AI 투자·인프라`: AI 기업 투자, AI 인프라, 데이터센터, 컴퓨트, 반도체, 클라우드 관련 투자 thesis
  - `AI 리스크·규제`: 모델 리스크, 데이터 거버넌스, 저작권/IP, 보안, AI 정책과 규제
- `국민성장펀드`: 국민성장펀드 자체의 출자사업, 선정, 정책펀드 운용, 국민참여형 판매가 중심인 기사
  - `출자·선정`: 간접투자, 위탁운용사 선정, 숏리스트, 최종 GP 발표
  - `운용사 경쟁`: 국민성장펀드 출자사업을 둘러싼 GP 경쟁 구도
  - `정책펀드`: 금융위·정책금융·성장금융 중심의 정책 설계와 운용 방향
  - `프로그램 동향`: 국민참여형 상품, 판매, 수익률, 소진 등 프로그램 업데이트
- `Deal`: 특정 자산이나 회사의 소유권, 지분, 자본구조가 바뀌는 거래 기사
  - `Acquisition`: 바이아웃, 성장투자, 소수지분, 카브아웃, take-private
  - `Auction`: 예비입찰, 본입찰, 원매자, 인수의향, 우선협상, 주관사 선정
  - `Signing·Closing`: SPA, 본계약, 계약 체결, 클로징, 자금 납입, 인수 완료
  - `Exit`: 회수, IPO, 블록딜, 공개매각, 청산
  - `Financing`: 인수금융, 프라이빗크레딧, CB·메자닌, 리파이낸싱, 리캡, 대주단
  - `Ownership`: PMI, 밸류업, 수익성 개선, 구조조정, 포트폴리오 운영 개선
  - `Secondary`: GP-led 세컨더리, LP 지분 세컨더리, 컨티뉴에이션 펀드
  - `Issue`: 무산, 분쟁, 소송, 가격 이견, 부실, 리스크
- `LP`: allocator의 자금배분, 출자 의사결정, 운용사 선정, 포트폴리오 관리가 중심인 기사
  - `출자사업·RFP`: 출자사업 공고, 위탁운용사 선정, 숏리스트, 최종 선정, 출자확약, 앵커 출자
  - `자산배분·정책`: 대체투자 비중, PE 목표비중, 투자정책서, 거버넌스, 리밸런싱
  - `성과·포트폴리오`: LP 수익률, 포트폴리오 노출, 현금흐름, 리스크 점검
  - `유동성·세컨더리`: allocator 관점의 LP 지분 매각, 세컨더리 프로그램, 유동성 관리
- `GP`: 운용사 자체의 펀드, 조직, 전략, 플랫폼, 포트폴리오 관리가 중심인 기사
  - `Fundraising`: 블라인드펀드, 프로젝트펀드, 공동투자 펀드, 1차/최종 클로징, 목표액, 약정총액, 펀딩 목표, 자펀드
  - `People`: 대표/파트너 선임, 팀 이동, 승진, 사무소 개설, 조직개편
  - `Platform`: 신규 플랫폼, 섹터 확장, 운용사 제휴
  - `Track Record`: 회수 성과, 과거 딜, 트랙레코드
  - `Strategy`: 신규 전략, 크레딧/인프라/세컨더리 확장, 하우스 전략
- `Market`: 개별 거래나 기관 공지가 아니라 시장 전체의 방향, 제도, 데이터, 거시 환경을 설명하는 기사
  - `시장동향·데이터`: 드라이파우더, 멀티플, 회수시장, 펀드레이징 환경, 리그테이블, 설문/리포트
  - `거시·금리·크레딧`: 금리, 환율, 유동성, 대출시장, 레버리지 론, 스프레드
  - `규제·세제·정책`: 금융위, 금감원, 금투협, 공정위, 세제, 법 개정, 제재, 소송, 내부통제
  - `전략·전망`: 하우스뷰, CIO/전략가 코멘트, 섹터 전망, 지역별 투자환경

분류 우선순위는 단순 키워드가 아니라 기사 주제다. AI가 핵심 thesis나 운용 변화이면 거래·펀드 기사라도 `AI & PE`로 보낸다. 국민성장펀드가 제목 또는 원천 카테고리의 중심 주제이면 `국민성장펀드`로 보낸다. 특정 인수, 매각, 세컨더리, 파이낸싱이 핵심이면 GP/LP 이름이 들어가도 `Deal`로 본다. 국민연금이나 공제회가 등장해도 공식 출자사업, 자산배분, 포트폴리오 관리, allocator 유동성 이슈가 아니면 `LP`로 보내지 않는다. GP는 운용사 자체의 펀드레이징·조직·전략·포트폴리오 운영이 기사 주제일 때만 쓴다.

반복 오분류 방지 기준:

- `펀딩 목표`, `자펀드`, `블라인드`, `모태펀드 GP 도전`은 LP/국민성장펀드 문맥이 있어도 기사 주제가 운용사 펀드 결성이면 `GP / Fundraising`이다.
- `CB 투입`, `메자닌 인수`, `인수금융`, `리파이낸싱`은 특정 회사·자산의 자본조달 이벤트이면 `Deal / Financing`이다.
- `본입찰`, `예비입찰`, `원매자`, `인수의향`, `제안`은 제목에 `매각`이 있어도 `Deal / Auction`이 우선이다.
- `수익성 개선`, `밸류업`, `PMI`, `손본다`는 포트폴리오 운영 기사이면 `Deal / Ownership`이다.
- `장외파생상품 라이선스`, 금융업 인가, 금감원·금융위 제재와 감독 이슈는 `Market / Regulation`이다.

## 공개 3줄 요약 문체

공개 기사 요약은 빠르게 읽히되, 말투는 투자업계 메모에 가깝게 쓴다. 친근한 뉴스레터식 구어체가 아니라 독자가 링크를 누르기 전에 기사 가치를 판단할 수 있는 짧은 업무 메모다.

- 기본은 3줄이다. 다만 정보가 부족하면 없는 사실을 지어내지 않고 2줄까지만 허용한다.
- 각 줄은 `사건 / 숫자·주체·단계 / PE·LP·GP 관점의 의미` 순서를 우선한다.
- 제목을 그대로 반복하지 않는다.
- `AI generated`, `source evidence`, `confidence`, `자동 생성`, `관리자` 같은 내부 표현은 공개 요약에 절대 노출하지 않는다.
- 마침표를 붙이지 않는다.
- `했어요`, `해요`, `입니다` 같은 뉴닉식 구어체는 쓰지 않는다.
- `했다`, `전망이다`, `사례다`처럼 기사체 결말을 반복하지 않는다.
- 가능한 한 `추진`, `참여`, `확정`, `변수`, `확대`, `가시화`, `완화 포인트` 같은 명사형·메모형으로 끝낸다.
- 숫자, 기관명, GP명, 단계는 문장 뒤가 아니라 앞쪽에 둔다.
- AI/NotebookLM 요약도 같은 규칙을 따르며, 최종 공개 payload에는 `summaryLines` 2~3개로 저장한다.
- 뉴닉형 설명문, 질문형 문장, 독자에게 말을 거는 문장은 쓰지 않는다. 뉴스레터 본문은 친근한 해설이 아니라 투자·운용 실무자가 링크 클릭 여부를 판단하는 사전 메모다.

예시:

```text
성장금융, 국민성장펀드 매칭 출자 라인 개방
블라인드 GP당 최대 300억, 프로젝트는 수시 접수
선정 GP의 민간 펀딩 부담 완화 포인트
```

분류 기준도 같은 원칙을 따른다. 키워드가 아니라 기사 주어를 먼저 본다.

- `국민성장펀드`가 제목에 있어도 IMM, 파라투스, 대신PE 등 특정 GP의 블라인드펀드 조성·펀드레이징 전략이 본문 주제이면 `GP`다.
- 국민성장펀드 사업 자체의 회차, 출자사업, 위탁운용사 선정 결과, 프로그램 규모가 본문 주제이면 `NationalGrowthFund`다.
- `AI`가 제목에 있어도 GP 블라인드펀드 조성이 본문 주제이면 `GP`다. AI 투자 테마와 PE 시장 구조가 본문 주제일 때만 `AI_PE`다.
- 특정 회사의 투자유치, 신규 FI 참여, 지분 투자, 매각·인수 프로세스는 `Deal`이다. 운용사명처럼 보이는 단어가 없으면 GP로 올리지 않는다.
- 사모대출, GP stake, 규제, 컨퍼런스, 업계 단체, 금융권 리스크처럼 시장 구조나 코멘터리 성격이면 `Market`이다.

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

- 매일 발행 작업은 GitHub Actions에서 `NEWSLETTER_BUILD_SERVICES=newsletter` 기준으로 돈다. 통합 사이트 전체 갱신이 필요할 때만 명시적으로 `newsletter,lp,gp`를 사용한다. Wiki는 재기획 전까지 명시적으로 `wiki`를 줄 때만 빌드한다.
- 매일 발행 작업은 초안 생성 직후 `services/newsletter/src/validate_daily_news_pipeline.py` 기준 검증을 남긴다. 검증이 실패하면 public mirror push가 중단되므로, 그날 안에 원인 규칙을 고치고 같은 날짜로 재발행해야 한다.
- 매일 발행 작업은 `scripts/build_site_bundle.py --services newsletter`로 `services/newsletter/deploy/site/`의 뉴스레터 산출물을 갱신하고 public mirror `pkkong/kpef-newsletter`의 `gh-pages` 브랜치에 push한다.
- LP 공고 모니터는 뉴스레터 핵심 콘텐츠가 아니므로 daily newsletter publish 안에서 필수 단계로 묶지 않는다. LP/GP 갱신은 별도 collector 또는 수동 통합 빌드로 처리하고, 이 실패가 당일 뉴스레터 공개를 막으면 안 된다. Wiki는 루틴 갱신 대상이 아니다.
- 발행 완료 기준은 로컬 파일 생성이 아니라 공개 `https://pkkong.github.io/kpef-newsletter/health.json`의 `report_date`가 당일이고 `archive.json`에 당일 기사 수가 존재하는 것이다. GitHub Actions는 push 후 이 공개 확인까지 통과해야 완료로 끝난다.
- GitHub Actions 발행 작업은 종료 시 job summary와 검증 로그를 남긴다. 로컬 `exports/daily_news/ops_status/*` 파일은 진단용 산출물일 뿐이며, 발행 완료 기준은 공개 `health.json`과 `archive.json` 확인이다.
- 별도 LP 공고 탭은 `new_notice`, `deadline_soon`, `shortlist`, `final_selection` 등 이벤트 타입을 우선 노출한다. `program_size`는 정책펀드 전체 규모로 보관하되, 공개 출자규모 합산에는 `allocation_amount`만 사용한다.
- 공개 Daily 화면은 최근 날짜별 `daily_news_brief_YYYYMMDD.md`를 함께 포함하므로, 사용자는 날짜 선택으로 과거 브리프의 주요 뉴스도 볼 수 있다.
- 매일 뉴스 파이프라인은 `scripts/build_service_integration_worklist.py`도 실행해서 뉴스 노출 GP, People DB 커버리지, 담당자별 다음 액션을 하나의 작업 큐로 갱신한다.
- 공개 뉴스 화면은 확인된 GP/관련 인물 같은 독자용 맥락만 표시한다. `프로필 보강`, `식별자 보강`, 리뷰 큐, 작업 담당자 같은 운영 상태는 공개 화면에 노출하지 않는다.
- 공개 DB/서비스 화면은 통합 빌드가 만든 `services/newsletter/deploy/site/` bundle을 기준으로 배포한다. root `public/` 경로는 source repo에서 쓰지 않는 ignored 생성물이다.
- 당일 산출물을 로컬에서 수동 점검하려면 `services/newsletter/scripts/validate_daily_news_today.ps1`을 진단용으로 실행할 수 있다. 이 스크립트는 운영 스케줄러가 아니다.
- 코드 변경 후 전체 점검은 `services/newsletter/scripts/check_daily_news_pipeline.ps1`을 진단용으로 실행한다. 이 스크립트는 Python 컴파일, 핵심 로직 테스트, 당일 산출물 검증을 순서대로 실행한다.
- 검증 항목은 산출물 존재 여부, 최근 24시간 기준 문구, 중복 링크, Google News 중계 링크, 리뷰 카테고리 값, DB 최신 실행 상태, 네이버 API 설정이다.
- 백테스트는 운영 산출물을 덮어쓰지 않도록 `exports/daily_news/backtests/` 아래 별도 폴더에 저장된다.
- PC 의존성을 없애는 클라우드 이전 계획은 `services/newsletter/docs/cloud_migration.md`에 정리했다.

## 분류·태그 품질 게이트

매일 클리핑 품질은 세 층을 모두 확인해야 한다.

1. `exports/daily_news/daily_news_brief_YYYYMMDD.md`: 독자가 보는 섹션 배치
2. `exports/daily_news/daily_news_review_queue_YYYYMMDD.csv`: 운영 CSV의 `current_category`, `section_tags`, `topic_tags`
3. `services/newsletter/deploy/site/archive.json`: 공개 사이트의 `section`, `subCategory`

대표 카테고리와 태그 기준:

- `current_category`와 `section_tags`는 같은 대표 섹션 1개여야 한다.
- `topic_tags`는 검색 보조값이지만 대표 섹션과 충돌하면 안 된다.
- GP 펀드레이징 기사에 `LP` 토픽이 남거나, Deal 기사에 GP명이 등장했다는 이유만으로 `GP` 토픽이 남으면 품질 미달이다.
- `archive.json`의 `section/subCategory`가 CSV 대표 섹션과 다르면 공개 렌더러 규칙까지 고쳐야 한다.

필수 점검 명령:

```bash
python3 services/newsletter/tests/test_daily_news_logic.py
python3 services/newsletter/src/validate_daily_news_pipeline.py --date YYYY-MM-DD
python3 services/newsletter/src/check_newsletter_brand_icons.py --site-dir services/newsletter/deploy/site --report-date YYYY-MM-DD
python3 services/newsletter/src/newsletter_ops_status.py --date YYYY-MM-DD --site-dir services/newsletter/deploy/site --public-base-url https://pkkong.github.io/kpef-newsletter --fail-on-hard
```

`validate_daily_news_pipeline.py` 실패는 발행 차단이다. 브랜드 아이콘 검사는 품질 리포트로 보고, missing/weak 아이콘 1건 때문에 당일 공개 배포를 멈추지 않는다. 아이콘까지 hard gate로 걸어야 하는 수동 점검 때만 `NEWSLETTER_STRICT_ICON_CHECK=1` 또는 `--fail-on-missing`을 쓴다.

## AI 보강 레이어

뉴스레터 발행의 기본 엔진은 수집, 규칙 분류, 회귀 테스트다. NotebookLM 같은 외부 AI는 발행을 대체하지 않고 `exports/daily_news/daily_news_ai_enrichment_YYYYMMDD.json` 보강 파일을 만드는 보조 단계로만 둔다.

- 기본값은 `NEWSLETTER_AI_PROVIDER=local`이며 외부 로그인 없이 `summary_lines` 계약을 만든다.
- NotebookLM은 기사별 query API처럼 쓰지 않는다. 날짜별 리뷰 노트북 하나를 만들고, 그날 기사 source pack과 분류 기준을 자료로 넣은 뒤, 한 번의 구조화 질문으로 전체 기사 요약/분류 결과를 받는 방식만 허용한다.
- 노트북 이름은 `KPEF Newsletter Review YYYY-MM-DD` 형식으로 둔다.
- 업로드 자료는 최소 2개다: `newsletter_classification_rules.md`, `daily_news_source_pack_YYYYMMDD.md`.
- source pack에는 기사별 `url`, `title`, `publisher`, `published_at`, `current_section`, `candidate_tags`, 수집한 snippet/body excerpt를 넣는다. URL만 추가하면 paywall, bot 차단, 동적 렌더링 때문에 NotebookLM이 기사 본문을 충분히 못 읽을 수 있으므로 source pack이 기준이다.
- 질문은 "각 기사에 대해 3줄 요약, 100자 이내 핵심 요약, 대표 섹션, GP/LP/Deal/AI/국민성장펀드 관련 엔티티를 JSON 배열로 반환"처럼 날짜 전체를 한 번에 처리하도록 설계한다.
- 같은 날짜/같은 source pack fingerprint로 이미 결과가 있으면 다시 묻지 않고 캐시된 `daily_news_ai_enrichment_YYYYMMDD.json`을 쓴다.
- NotebookLM 호출 상한은 기본 하루 1회다. 실패 시 자동 재시도 루프를 돌리지 않고 local-rule 결과로 발행한다.
- 기존 batch query 방식은 legacy experiment로만 본다. 전량 백테스트나 5개 기사 단위 반복 query는 채팅 한도를 빠르게 소모하므로 사용하지 않는다.
- NotebookLM은 정식 daily publish 경로가 아니다. 프로젝트 repo 안에 전용 `.venv`나 MCP 서버를 유지하지 않으며, 실험할 때만 외부 CLI 경로를 `NEWSLETTER_NLM_BIN` 또는 `--nlm-bin`으로 명시한다.
- Google 로그인은 한 번 수동으로 필요하다. 예: `nlm login --profile default`.
- NotebookLM은 빈 노트북에 질의할 수 없다. 작업용 노트북을 만들고 분류 기준/source pack 같은 텍스트 소스를 1개 이상 넣어야 한다.
- NotebookLM CLI는 답변 JSON을 `{ "answer": "..." }`로 감싸서 돌려줄 수 있으므로, 파서는 `answer` 내부 JSON까지 풀어야 한다.
- NotebookLM은 내부 API와 브라우저 쿠키 인증을 쓰므로 장애가 나도 당일 발행 전체가 무너지면 안 된다.
- GitHub Actions workflow는 외부 AI 보강이 실패하면 기본적으로 local-rule 보강으로 fallback한다. AI 실패를 발행 차단으로 볼 때만 `NEWSLETTER_AI_STRICT=1`을 둔다.
- 공개 화면은 provider, confidence, notes 같은 내부 필드를 보여주지 않고 `summaryLines`만 사용한다.
- NotebookLM의 `section_suggestion`은 기본적으로 audit에만 남긴다. 공개 섹션에 바로 hard apply하지 않는다.
- 기본 운영에서는 카테고리 자동 변경을 hard apply하지 않는다. AI가 제안한 `section_suggestion`은 우선 품질 검토용으로 쓰고, 반복 오분류가 확인되면 규칙과 테스트로 고정한다.

NotebookLM 질문 출력 스키마:

```json
{
  "articles": [
    {
      "url": "canonical article URL",
      "news_id": "same news_id from source pack",
      "summary_lines": ["line 1", "line 2", "line 3"],
      "short_summary_100": "100자 이내 핵심 요약",
      "section_suggestion": "AI_PE | NationalGrowthFund | Deal | LP | GP | Market",
      "gp_names": [],
      "lp_names": [],
      "deal_targets": [],
      "reason": "분류 근거 1문장"
    }
  ]
}
```

local-rule 수동 실행:

```bash
python3 services/newsletter/src/enrich_daily_news_ai.py --date YYYY-MM-DD --provider local
```

NotebookLM 날짜 리뷰 수동 실행:

```bash
NEWSLETTER_NLM_BIN=nlm python3 services/newsletter/src/enrich_daily_news_ai.py \
  --date YYYY-MM-DD \
  --provider notebooklm \
  --nlm-profile default
```

이 명령은 `exports/daily_news/notebooklm_sources/YYYYMMDD/` 아래에 source pack,
classification rules 복사본, query 파일, fingerprint metadata를 만들고,
`KPEF Newsletter Review YYYY-MM-DD` 노트북에 두 source를 업로드한 뒤 한 번만 질문한다.
NotebookLM이 `RESOURCE_EXHAUSTED` 등으로 실패하면 `NEWSLETTER_AI_STRICT=1`이 아닌 한
local-rule 결과로 fallback하고 실패 사유를 JSON에 남긴다.

NotebookLM 실험을 다시 할 때의 확인 순서:

```bash
nlm login --check --profile default
nlm list notebooks --json --profile default
nlm notebook query "$NOTEBOOK_ID" \
  'Reply with strict JSON only: {"ok": true, "purpose": "newsletter-ai-smoke-test"}' \
  --timeout 120 \
  --profile default
```

`Profile not found: default` 또는 `Login timeout`이면 코드 문제가 아니라 Google/NotebookLM 인증이 끝나지 않은 상태다. 이 경우 공개 발행은 local-rule 보강으로 계속 가고, NotebookLM provider 백테스트만 보류한다.

결과 파일:

```text
exports/daily_news/ai_backtests/daily_news_ai_backtest_latest.md
exports/daily_news/ai_backtests/daily_news_ai_backtest_latest.csv
```

당일 분류 덤프:

```bash
python3 - <<'PY'
import csv
from pathlib import Path
path = Path("exports/daily_news/daily_news_review_queue_YYYYMMDD.csv")
for i, row in enumerate(csv.DictReader(path.open(encoding="utf-8-sig", newline="")), 1):
    print(i, row["current_category"], "| section_tags=", row["section_tags"], "| topic_tags=", row["topic_tags"], "|", row["publisher"], "|", row["title"])
PY
```

공개 payload 덤프:

```bash
PYTHONPATH=scripts python3 - <<'PY'
from scripts.build_service_site import DEFAULT_EXPORT_DIR, article_payload_rows, parse_brief
rows = parse_brief(DEFAULT_EXPORT_DIR / "daily_news_brief_YYYYMMDD.md")
for i, item in enumerate(article_payload_rows(rows), 1):
    print(i, item["section"], "/", item["subCategory"], "|", item["title"])
PY
```

분류나 태그 규칙을 고친 날에는 `services/newsletter/tests/test_daily_news_logic.py`에 실제 기사 제목 기반 회귀 테스트를 추가한다. 테스트 없이 CSV만 수동으로 고치는 것은 다음 수집 때 다시 깨지므로 완료로 보지 않는다.

## 리뷰 기준

- `제외`: PEF 관련성이 약하거나 잡뉴스라고 판단한 기사
- `포함`: 자동 필터에서 빠졌지만 볼 가치가 있는 기사
- `카테고리`: 상위 섹션 또는 subtype 자동 분류가 틀렸을 때만 선택
- LP/GP는 상위 섹션이지만 기관명이 등장했다는 이유만으로 선택하지 않는다. LP 세컨더리는 특정 거래이면 `Deal`, allocator의 유동성 관리 이슈이면 `LP`로 분류한다. GP 펀드 클로징은 `GP`, 특정 포트폴리오 인수·매각은 `Deal`로 분류한다.

## 회사 클리핑 피드백 반영

- 회사 내부 클리핑에서 좋은데 빠진 기사가 보이면 먼저 URL이 `news_document`에 있었는지 확인한다.
- DB에 없던 기사는 `news_sources.csv`의 검색 소스 또는 허용 언론사 구멍으로 보고, 반복 가능성이 있는 검색어만 소스로 추가한다.
- DB에는 있었지만 브리프에서 빠진 기사는 `news_keyword_rules.csv`의 점수 신호 또는 `news_manual_overrides.csv`의 수동 include로 보정한다.
- `ETF LP`처럼 Limited Partner가 아닌 LP 표현은 제외 신호로 관리한다.
- 월요일도 일반 브리프와 같은 최근 24시간 기준을 따른다. 금요일 이후 누락분 보강은 별도 backfill/audit 작업으로 처리한다.

## 발송

아직 자동 발송은 초안 생성과 분리했다. `services/newsletter/scripts/send_daily_news_final.ps1`은 로컬 진단/수동 실험용이며, 정식 발송은 별도 이메일 서비스나 GitHub Actions 기반 발송 경로를 설계한 뒤 연결한다.
`daily_news_final_latest.*`가 최신 초안보다 오래된 경우에는 최종본 확정이 먼저 필요하다.
