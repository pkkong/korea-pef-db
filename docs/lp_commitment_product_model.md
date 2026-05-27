# LP Intelligence Product Model

## 제품 위치

LP는 GP Stat의 보조 필터가 아니라 별도 제품 축이다. 본체는 기관별
일반현황, 투자현황, 투자전략, 투자조직, 공개 인물, 출자공고 히스토리,
선정 GP 히스토리, 최근/과거 뉴스를 한 화면에서 보는 LP 인텔리전스
서비스다. 출자공고 모니터는 이 본체를 구성하는 데이터 파이프라인 중
하나이며, 나중에 뉴스레터 알림 재료로도 재사용한다.

## 1차 범위

- 주요 LP 마스터: 국민연금, 한국벤처투자, 한국성장금융, 산업은행, 우정사업본부, 주요 공제회/연금.
- LP 프로필 확인 항목: 공개 자료 기반 일반현황, 운용 원칙, PE 관련 조직,
  공개 인물, 확인 필요 데이터 공백.
- 공고 소스 레지스트리: 국민연금 거래기관 선정공고, 벤처투자종합포털 출자공고.
- 후보 생성: 공식 공고 목록과 최근 뉴스 클리핑에서 출자사업/위탁운용/선정/숏리스트 관련 항목을 `lp_commitment_notice`에 적재.
- 서비스 노출: `dashboard/data/dashboard_data.json`, `public/data/service_data.json`, 공개 DB LP 탭.

## 핵심 테이블

- `lp_institution`: LP 기관 기본정보, 담당팀, 자산군, alias.
- `lp_profile_fact`: 공개 출처가 붙은 LP별 정성/정량 팩트.
- `lp_commitment_source`: 공식 공고/뉴스 후보 소스.
- `lp_commitment_notice`: 출자사업 공고, 선정결과, 뉴스 후보.
- `lp_notice_gp_link`: LP 공고/뉴스 이벤트와 GP 마스터의 연결.
- `lp_notice_news_link`: LP 이벤트와 원 뉴스 문서의 연결.
- `v_lp_institution_stats`: LP별 공고/금액/최근 업데이트.
- `v_lp_commitment_yearly_stats`: 연도별 LP 출자사업 합계.

## LP 일반현황

LP 화면은 GP 프로필처럼 먼저 기관의 일반현황을 보여준 뒤 출자 이벤트를 붙인다.
최소 공개 필드는 `lp_name`, `lp_name_en`, `lp_type`, `ownership_type`, `default_team`,
`focus_asset_classes`, `homepage_url`, `notice_url`, `aliases`, `notes`다. 통계 필드는
공개 가능한 공고 기준으로 `notice_count`, `official_notice_count`, `news_notice_count`,
`allocation_amount_krw_100mn`, `latest_event_date`, `latest_notice_title`을 병합한다.
금액은 자동 추출값이므로 검증 전에는 참고값으로만 다룬다.

## LP 인텔리전스 섹션

- `general`: 설립, 회원 수, 총자산, 법적 성격, 공식 홈페이지.
- `investment_status`: 총 운용자산, 자산군별 비중, 수익률, 지역/해외 비중.
- `investment_strategy`: 운용 원칙, 중장기 방향, 선호 자산군, 리스크 관점.
- `investment_org`: 이사장, 기금운용이사, PE/기업투자 관련 부서 및 하위 조직.
- `investment_governance`: 투자심의위원회, 투자실무협의회, 리스크관리위원회 등 의사결정 구조.
- `public_people`: 공식/신뢰 가능한 공개자료에서 확인되는 이사, CIO, 부서장, 담당자.
- `notice_history`: 과거 공고, 공고 조건, 주목적, 규모, 접수 결과, 경쟁률, 최종 선정.
- `news`: 뉴스레터/뉴스 DB에서 연결된 최근 및 과거 기사.
- `data_gap`: 공개자료로 확인되지 않는 영역. 추정하지 않고 공백 자체를 표시한다.

교직원공제회 1차 샘플은 `lp_profile_fact`로 일반현황, 투자전략,
기금운용 조직, 투자 의사결정, 공개 인물, 확인 필요 항목을 넣는다.
하위 팀 구성과 실무 담당자는 공개자료로 구조화 확인이 어려우므로
검증 전에는 추정 데이터로 노출하지 않는다.

## 벤치마크 기준

LP 페이지는 단순 소개 페이지가 아니라 투자 데이터 상품의 프로필 페이지처럼 구성한다.
공개적으로 확인 가능한 벤치마크는 아래 기준으로 해석한다.

- Preqin형 LP 프로필: 기관 개요, 사모시장 활동 스냅샷, 자산군별 활동,
  주요 연락/의사결정자, 관계, 타임라인, 뉴스, 미래 계획, 리소스/RFP 링크를
  탭과 타일로 나눠 보여준다.
- THE VC형 기업/투자자 프로필: 대시보드, 핵심 지표, 최근 뉴스, 투자 유치/집행,
  펀드, 임직원, 유사 회사/피어 비교, 잠금/출처 상태를 한 화면에서 빠르게 스캔하게 한다.
- 우리 LP 서비스의 공개 버전: 유료 데이터베이스처럼 비공개 정보를 추정하지 않고,
  공개자료 기반 `Overview`, `Activity`, `Network`, `Peers`, `Sources`로 나눈다.
- 화면 우선순위는 `기관 스냅샷 -> 데이터 커버리지 -> 출자 활동 -> 선정 GP 신호 -> 피어 비교 -> 공개 출처` 순서다.
- 수집 우선순위는 공식 공고/입찰, 경영공시·조직도, 과거 출자 보도,
  뉴스레터 DB 연결, GP 마스터 연결 순서다.

## 모니터 이벤트 타입

출자사업 모니터는 아래 이벤트만 우선 노출한다.

- `new_notice`: 신규 출자사업 공고
- `deadline_soon`: 접수 마감 임박
- `deadline_closed`: 접수 마감
- `shortlist`: 숏리스트 / 1차 선정
- `final_selection`: 최종 선정 GP 발표
- `revision`: 정정공고 / 조건 변경 / 재공고
- `cancellation`: 취소 / 유찰 / 미달
- `performance_update`: 회수, DPI, 출자 성과 업데이트

## 금액 구분

금액은 하나의 `출자규모`로 합산하지 않는다.

- `program_size_krw_100mn`: 정책펀드 전체 규모. 예: 국민성장펀드 150조.
- `allocation_amount_krw_100mn`: 이번 출자사업 배정/예정 규모.
- `commitment_amount_krw_100mn`: 기존 호환 필드. 현재는 검증 가능한 allocation 금액만 미러링한다.

공개 LP 공고 화면은 기본적으로 `allocation_amount_krw_100mn`만 표시하고, 프로그램 총액은 출자규모로 합산하지 않는다.

## 다음 확장

- 공고문 PDF/HWP 원문 저장과 텍스트 추출.
- 같은 LP의 과거 공고문 비교: 출자규모, 전략, 지원 자격, 평가 항목, 수수료/핵심운용인력 조건.
- 선정 GP 히스토리 정규화: GP master와 연결하고 선정연도/전략/리그/출자액을 별도 테이블로 분리.
- 뉴스 연계: `news_entity_link`에 `LP` 엔티티를 추가하고, 뉴스레터의 LP 후보를
  LP 서비스의 최근/과거 뉴스로 재사용.
- 담당팀/담당자 구조화: LP 조직도, 투자위원회/대체투자 담당 부서 변동 이력.
- 알림 규칙: `notice`와 `selection_result`는 별도 LP 공고 탭/서비스에 우선 노출, `candidate`는 리뷰 큐에서 검증 후 승격.
