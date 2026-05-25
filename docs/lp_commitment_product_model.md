# LP Commitment Product Model

## 제품 위치

LP는 GP Stat의 보조 필터가 아니라 별도 제품 축이다. 공개 서비스에서는 `public/db.html#lp`에서 주요 LP, 출자사업 공고/선정결과/관련 뉴스, 연도별 출자 규모를 보여준다. 뉴스레터에서는 Daily 상단의 `출자사업 모니터`가 같은 데이터를 사용한다.

## 1차 범위

- 주요 LP 마스터: 국민연금, 한국벤처투자, 한국성장금융, 산업은행, 우정사업본부, 주요 공제회/연금.
- 공고 소스 레지스트리: 국민연금 거래기관 선정공고, 벤처투자종합포털 출자공고.
- 후보 생성: 공식 공고 목록과 최근 뉴스 클리핑에서 출자사업/위탁운용/선정/숏리스트 관련 항목을 `lp_commitment_notice`에 적재.
- 서비스 노출: `dashboard/data/dashboard_data.json`, `public/data/service_data.json`, Daily, 공개 DB LP 탭.

## 핵심 테이블

- `lp_institution`: LP 기관 기본정보, 담당팀, 자산군, alias.
- `lp_commitment_source`: 공식 공고/뉴스 후보 소스.
- `lp_commitment_notice`: 출자사업 공고, 선정결과, 뉴스 후보.
- `v_lp_institution_stats`: LP별 공고/금액/최근 업데이트.
- `v_lp_commitment_yearly_stats`: 연도별 LP 출자사업 합계.

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

공개 화면과 Daily 모니터는 기본적으로 `allocation_amount_krw_100mn`만 표시하고, 프로그램 총액은 출자규모로 합산하지 않는다.

## 다음 확장

- 공고문 PDF/HWP 원문 저장과 텍스트 추출.
- 같은 LP의 과거 공고문 비교: 출자규모, 전략, 지원 자격, 평가 항목, 수수료/핵심운용인력 조건.
- 선정 GP 히스토리 정규화: GP master와 연결하고 선정연도/전략/리그/출자액을 별도 테이블로 분리.
- 담당팀/담당자 구조화: LP 조직도, 투자위원회/대체투자 담당 부서 변동 이력.
- 알림 규칙: `notice`와 `selection_result`는 Daily 우선 노출, `candidate`는 리뷰 큐에서 검증 후 승격.
