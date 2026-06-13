# Agent Operating Briefs

## 목적

이 문서는 뉴스레터, LP, GP, PEF Wiki, People DB, 검증·배포 담당 에이전트가 같은 제품 원칙, 같은 키, 같은 산출물 경로를 기준으로 움직이게 하는 운영 지시서다. 각 담당은 독립된 작업을 병렬로 수행하되, 뉴스가 GP/인물/LP DB 갱신 신호가 되고 각 DB가 뉴스와 서비스 화면의 맥락 엔진이 되도록 매일 연결 상태를 유지한다.

## Codex 팀 운영 원칙

- 프로젝트 작업은 기본적으로 팀 단위로 진행한다. 메인 Codex는 방향, 통합, 최종 판단, 사용자 커뮤니케이션을 맡는다.
- 작업이 읽기 조사, 구현, 검증, 문서화로 나뉠 수 있으면 서브에이전트에 역할을 나누어 병렬로 맡긴다.
- 서브에이전트 기본 역할은 `Explorer`(읽기 조사), `Worker`(명확한 파일 범위의 구현), `Verifier`(테스트·배포·공개 사이트 확인), `Documentation`(운영 문서·비개발자 설명)로 둔다.
- 긴급하거나 파일 간 결합도가 높은 변경은 메인 Codex가 직접 처리하고, 서브에이전트에는 독립적으로 끝낼 수 있는 범위만 맡긴다.
- 서브에이전트 결과는 메인 Codex가 검토한 뒤 반영한다. 서로 같은 일을 중복 수행하지 않게 하고, 로컬에 이미 존재하는 사용자 변경은 되돌리지 않는다.
- 작업 시작 또는 중간 보고에서 누가 어떤 역할을 맡았는지 짧게 공유한다.

## 기본 멀티에이전트 운영 모델

- 메인 Codex는 Project Lead / PM / Tech Lead다. 사용자 목표, 현재 시스템 상태, 가장 작은 다음 마일스톤을 정리하고 작업 분해, 순서, 최종 통합 판단을 맡는다.
- Project Lead는 구현자가 아니라 운영 책임자다. 기능 수정 자체보다 현재 결정, 작업 소유자, 진행 상태, 검증 결과, 배포 상태, 남은 리스크가 문서에 남아 있는지를 먼저 관리한다.
- 새 작업을 시작하기 전 Project Lead는 `docs/project_lead_control_center.md`, `docs/product_operating_model.md`, `docs/data_operating_model.md`, `docs/service_quality_backlog.md`, `docs/design_system.md`를 확인하고, 사용자에게 이미 확정된 기준을 다시 묻지 않는다.
- 서비스 하나가 별도 채팅방, 서브에이전트, 또는 다른 담당에게 넘어가면 Project Lead는 해당 서비스의 handoff brief를 durable docs에 남긴다. 다른 채팅방은 대화 기억이 아니라 문서 기준으로 이어받아야 한다.
- 기본 서브에이전트는 `Explorer`, `Worker`, `Verifier`, `Documentation`이다. `Explorer`는 읽기 전용 조사, `Worker`는 명시된 파일·모듈 구현, `Verifier`는 테스트·빌드·배포·공개 사이트 확인, `Documentation`은 운영 문서와 비개발자 설명을 맡는다.
- 작업이 서로 독립적인 조사, 구현, 검증, 문서화로 나뉘고 메인 경로를 막지 않을 때 서브에이전트를 둔다. 긴급 수정, 위험한 데이터 변경, 파일 간 결합도가 높은 변경은 메인 Codex가 직접 처리한다.
- 사용자가 팀, 서브에이전트, 병렬 작업을 명시하면 메인 Codex는 실질 구현 전에 적절한 서브에이전트를 먼저 배정한다. 단순 답변이나 파일 하나의 즉시 수정처럼 분할 실익이 없는 경우에만 예외로 둔다.
- 로고 보완, 데이터 빈칸 채우기, 백필, 리서치, QA처럼 오래 걸리고 반복적인 sweep 작업은 기본적으로 전담 `Worker`, `Explorer`, 또는 `Verifier`에게 맡긴다. 메인 Codex가 직접 장시간 수행하면 사용자가 동시에 다른 요청을 맡기기 어려우므로, 메인 Codex는 대화, 새 작업 접수, 우선순위 조정, 병렬 조율을 위해 비워 둔다.
- 반복 sweep 중 메인 Codex의 책임은 목표 정의, handoff prompt 작성, 체크포인트 검토, 결과 통합, 최종 검증, 커밋·배포 판단이다. 직접 손을 대는 경우는 critical-path 통합, blocker 해소, 또는 서브에이전트 지시를 명확히 하기 위한 작은 샘플 작업으로 제한한다.
- sweep 담당 서브에이전트는 항목 하나마다 메인 Codex의 지시를 기다리지 말고 배치 단위로 진행한다. 보고에는 처리 범위, 성공/보류/실패 항목, 근거, 남은 리스크, 다음 배치 제안을 포함한다.
- 병렬 작업은 중복 없이 나눈다. 각 서브에이전트는 입력, 기대 산출물, 금지 범위, 완료 기준이 분명한 단위만 맡고, 다른 에이전트의 파일이나 관련 없는 로컬 변경을 되돌리지 않는다.
- 파일 소유권은 작업 지시의 경로와 역할 범위로 제한한다. 생성 산출물, 배포 디렉터리, 로컬 비밀값, DB, 로그는 사용자가 명시하지 않는 한 수정·커밋 대상에서 제외한다.
- 통합은 메인 Codex가 담당한다. 서브에이전트 결과를 검토한 뒤 실제 반영 여부를 결정하고, 필요한 테스트·빌드·검증·공개 화면 확인을 완료 기준에 맞춰 수행한다.
- 사용자 커뮤니케이션은 간결하게 한다. 시작·중간 보고에는 `Lead`, `Explorer`, `Worker`, `Verifier`, `Documentation` 중 누가 무엇을 맡는지 한두 문장으로 알리고, 최종 보고에는 변경 파일, 검증 결과, 남은 리스크만 남긴다.

## Project Lead Control Loop

- 모든 실질 작업은 `상태 파악 → 작업 분배/직접 처리 판단 → 소스 수정 → 빌드/검증 → 문서 업데이트 → 커밋/배포 판단 → 사용자 보고` 순서로 닫는다.
- `docs/project_lead_control_center.md`는 살아 있는 운영판이다. 메뉴 체계, 현재 공개 URL, 서비스별 소유자, 진행 중인 외부 채팅방, 최신 배포 커밋, 검증 명령, known issues를 최신으로 유지한다.
- 사용자가 “또 말해야 하냐”, “왜 문서화 안 하냐”, “서비스가 따로 놀고 있다”고 지적하면 즉시 control center와 해당 서비스 운영 문서를 갱신한다.
- 기능 작업 후 문서가 바뀌어야 하는데 바뀌지 않았으면 작업 미완료로 본다. 문서 업데이트가 필요 없다고 판단한 경우에는 최종 보고에 그 이유를 짧게 남긴다.
- 별도 채팅방이 한 서비스를 맡고 있어도 Project Lead는 통합 기준을 포기하지 않는다. 외부 채팅방 결과를 통합할 때는 source diff, 생성 산출물, 공개 URL, 회귀 테스트를 확인한다.

## 반복 오류 방지

- 사용자가 같은 수정을 반복해서 지적하면 단순 작업 실수가 아니라 지시 관리 실패로 취급한다. Project Lead는 반복 지적을 durable docs에 반영하고, 이후 같은 유형의 작업에서 기본 운영 규칙으로 적용한다.
- 반복 지적의 핵심 문장은 이후 서브에이전트 프롬프트에 명시한다. 특히 파일 범위, 금지 범위, 산출물 품질, 공개/배포 파일 취급, 사용자 선호와 관련된 correction은 누락하지 않는다.
- 모든 서브에이전트 배정에는 `role`, `objective`, `owned files`, `forbidden files`, `quality rules`, `known user preferences`, `verification`, `expected output`을 포함한다.
- 서브에이전트가 같은 실수를 반복하지 않도록 Project Lead는 배정 전 known user preferences와 금지 파일을 최신 지시와 대조하고, 완료 후 결과가 그 지시를 지켰는지 확인한다.
- 공개 UI 작업은 소스 수정, 생성 산출물 재생성, frontend checker, 390px/1280px 화면 확인, 클릭/키보드 이동 확인이 끝나기 전에는 완료로 보고하지 않는다. 못 한 검증은 완료가 아니라 미검증 리스크로 보고한다.

## 공개 화면 문구 원칙

- 뉴스레터, LP, GP, PEF Wiki 공개 화면에는 운영자에게 말하는 문장, 작업 상태, AI가 만든 듯한 메타 설명을 노출하지 않는다.
- 공개 화면 금지 표현은 `작업 큐`, `검토 대기`, `보강 필요`, `프로필 팩트`, `자동 매칭`, `데이터 수집`, `관리자`, `operator`, `source/evidence` 영문 라벨, `AUM proxy`, 불필요한 `신호` 표현이다. 기사 제목이나 원천 고유명사에 포함된 경우만 예외로 둔다.
- 공개 화면에서는 `프로필 항목`, `자료 기준`, `관련 뉴스`, `출자 이력`, `딜 관련`, `약정액 기준 지표`처럼 사용자가 바로 이해할 수 있는 표현을 쓴다.
- 접근성 라벨과 숨은 DOM 텍스트도 공개 화면의 일부로 본다. `내부 이동`, `내부 검토용`처럼 운영자 관점 표현을 쓰지 않는다.
- Wiki는 PDF 링크 모음이나 카드형 요약 페이지가 아니다. 원문 내용을 위키 본문으로 옮기고, 법령·규정·세무·보고·체크리스트로 바로 이동할 수 있는 앵커와 참조 구조를 제공한다.
- 표는 원문 또는 실무 비교에 실제로 필요한 경우에만 쓴다. 필요 없는 표, 카드형 레이아웃, 대화형 해설 문구, `요약했습니다` 같은 제작자 코멘트는 금지한다.
- PEF Wiki 화면은 OpenAI Developers/Help Center 같은 문서 사이트 구조를 기준으로 한다. 상단 브랜드 헤더, 짧은 주제 탭, 사이드/모바일 목차, 본문 중심 타이포그래피를 사용한다.
- Wiki 첫 화면은 인덱스나 카드 목록이 아니라 실제 문서 제목과 본문으로 시작한다. 상세 목차와 빠른 이동은 사이드바, 모바일 드로어, 본문 내부 앵커로 제공한다.
- Wiki 타이포그래피는 과한 볼드와 과한 구분선을 피한다. 본문·링크·목차는 400-650 수준의 차분한 굵기를 기본으로 하고, H1/H2만 필요한 만큼 강조한다.

## 공통 UX/UI 원칙

- 공개 UX/UI의 기준 문서는 `docs/design_system.md`다. Newsletter, LP, GP, Wiki 담당은 공개 화면을 고치기 전에 이 문서의 navigation, typography, directory row, newsletter reference pattern을 먼저 적용한다.
- 공개 화면의 기본 뷰 체계는 `docs/design_system.md`의 `View Taxonomy`를 따른다. 뉴스는 article list, LP/GP 목록은 directory table, LP/GP 상세는 profile detail, 출자공고는 notice row-card, Wiki는 document view로 본다.
- 공개 사이트는 정적 생성물이다. 크롤러, DB, CSV가 갱신되어도 공개 화면은 자동으로 실시간 변경되지 않으며, source renderer 빌드와 GitHub Pages 배포가 끝나야 새 숫자와 새 행이 반영된다.
- 뉴스레터/LP/GP가 같이 쓰는 날짜, CSV, URL 정규화, GP alias, HTML parsing 유틸은 `services/shared/src/daily_news_common.py`를 기준 모듈로 둔다. `services/newsletter/src/daily_news_common.py`와 `scripts/daily_news_common.py`는 호환용 shim으로만 남기고, LP/GP 코드는 뉴스레터 내부 경로인 `services.newsletter.src.daily_news_common`를 직접 import하지 않는다.
- 공개 서비스는 혁신의숲 같은 데이터룸/디렉토리 서비스 톤을 기준으로 한다. 뉴스레터, LP, GP, Wiki가 서로 다른 제품처럼 보이지 않게 폰트, 색상, 여백, 버튼, 탭, 표 header, row 스타일, 하단 메뉴를 맞춘다.
- 주요 목록과 디렉토리는 카드 나열보다 표 또는 표에 가까운 row layout을 기본으로 한다. 모바일에서도 핵심 컬럼은 남기고, 불필요한 가로 스크롤을 만들지 않는다.
- 공개 서비스의 주 메뉴는 `브리프 / LP / GP` 순서의 하단 메뉴 하나로 통일한다. Wiki는 재기획 전까지 공개 메뉴에 노출하지 않는다. 모바일과 PC 모두 같은 하단 메뉴를 쓰고, 상단 서비스 탭은 만들지 않는다. 상단·하단에 같은 서비스 메뉴가 동시에 보이면 회귀로 본다. 전역 저장함은 뉴스, LP, GP, Wiki 저장이 모두 구현되기 전까지 하단 메뉴에 두지 않는다.
- 상단 제품 헤더는 모든 공개 페이지에서 같은 구조를 쓰되 브랜드, 검색, 홈/목차 버튼만 둔다. 서비스별로 별도 브랜드 바, 전체 기관 칩 목록, 과거 네비게이션을 중복 노출하지 말고, 세부 이동은 해당 페이지 안의 짧은 섹션 탭이나 문서 목차로 제한한다.
- 뉴스레터 화면은 공개 UI의 기준 구현이다. LP, GP, Wiki 담당은 폰트, 색, 여백, 원형 로고 슬롯, 섹션 구분 밴드, row divider, 하단 메뉴를 바꿀 때 `docs/design_system.md`의 `Shared Tokens`, `Public Shell`, `Row Anatomy`, `Section Bands`를 먼저 따른다.
- 타이포그래피는 서비스별 임의 크기를 금지한다. 공개 화면 기준 H1은 모바일 28px 안팎, PC 36-38px 안팎, 목록 row 제목은 15-16px, 보조 정보는 11-13px 범위로 맞춘다.
- 대량 GP/LP 목록은 끝없이 긴 무한 스크롤로 두지 않는다. 검색·필터·정렬과 동기화되는 페이지네이션 또는 더보기 방식을 사용한다.
- LP/GP 디렉토리 row는 혁신의숲처럼 원형 CI/로고 영역을 포함한 표형 row를 기본으로 한다. 공식 홈페이지가 있으면 공식 compact CI/로고를 우선하고, 공식 touch/app icon은 명확히 브랜드 소유이고 시각적으로 쓸 만할 때만 사용한다. 검증 로고가 없거나 로드 실패 시에는 동일 크기·얇은 링·절제된 톤의 임시 CI형 모노그램을 쓴다. 모바일에서도 이름, 최신/순위, 핵심 숫자 컬럼은 표 구조를 유지하고, 버튼·칩이 row 밖으로 튀거나 가로 overflow를 만들면 회귀로 본다.
- 뉴스레터 언론사, LP 기관, GP 운용사 로고 슬롯은 같은 40px 원형 규칙을 쓴다. 로고가 있으면 기본은 혁신의숲/TheVC처럼 흰 원형 슬롯과 얇은 neutral border를 쓰고, 네이버·한국경제처럼 배경색이 명확한 로고는 도메인 기반 curated brand background로 원을 채운다. 작은 favicon을 억지로 넣어 품질을 낮추지 말고, 원 안에 별도 내부 원이나 링을 추가하지 않는다.
- 로고 보완 작업은 `services/newsletter/src/brand_assets.py`를 단일 registry로 삼는다. 새 언론사/LP/GP 로고는 공식 홈페이지의 compact CI, 공식 touch/app icon 순으로 검증하고, HTTP-only 또는 hotlink 차단 가능성이 있는 자산은 정적 빌드의 `assets/brand-marks` 캐시를 거쳐 노출한다. Google S2, DuckDuckGo 같은 외부 favicon 서비스는 공개 산출물에 남기지 않는다. 검증된 로고가 없거나 40px 원형 슬롯에서 공식 워드마크가 너무 얇게 보여 품질이 떨어지면 억지로 채우지 말고 깨끗한 텍스트 슬롯으로 남긴다. 배포 전 뉴스/LP/GP 주요 화면에서 `google.com/s2`, `duckduckgo`, 외부 hotlink, 깨진 이미지, `fallback-only`가 보이는지 확인한다.
- 공식 워드마크가 40px 슬롯에서 가독성이 떨어지는 경우에는 회사가 직접 제공하는 공식 심볼형 아이콘을 쓸 수 있다. 단, 단순 파비콘 수집을 로고 보완으로 간주하지 말고, 공식 소유·시각 품질·원형 슬롯 적합성을 함께 확인한다.
- LP의 `ownership_type` 같은 `public/private` 성격값은 이름 셀 아래에 노출하지 않는다. 해당 값은 필터와 정렬 데이터로만 활용하고, 목록 row에는 기관명과 핵심 숫자 위주로 표시한다.
- LP 상세는 기관명과 핵심 숫자 이후 `기본 정보 → 투자 현황 → 출자공고 → 관련 GP → 뉴스 → 기관 비교 → 자료` 순서로 정리한다. 자료 커버리지, 출처 링크, 참고사항은 상단 요약이 아니라 하단 보조 영역에 둔다.
- LP 상세 상단에는 `기본 정보, 투자 현황, 뉴스 정리` 같은 범용 설명문을 쓰지 않는다. 기관명, 유형, 담당 조직, 최신 공고, 핵심 숫자처럼 즉시 비교 가능한 데이터만 둔다.
- LP 수집 항목은 벤치마크 데이터 서비스 기준으로 `기관 일반현황`, `운용자산/AUM`, `현재·목표 배분`, `관심 자산군·전략`, `과거 출자공고·출자 이력`, `관련 GP`, `공개 담당자·자문사`, `자료/RFP/보고서`, `관련 뉴스`를 우선한다.
- LP universe는 일반 금융회사 목록이 아니다. 1차 대상은 국민연금·공제회·정책금융기관·모태펀드·지역/산업 정책펀드처럼 실제 GP/위탁운용사 선정, 출자공고, 커밋먼트가 확인되는 자금 주체다.
- 직접 GP를 선정하지 않고 OCIO 또는 전담운용사를 통해 하위 운용사를 선정하는 공적기금·위임형 자금 주체는 `coverage_tier=ocio`, `display_enabled=0`으로 별도 pool에 둔다. 산재보험기금, 고용보험기금, 예금보험기금, 주택도시기금처럼 `기금` 이름이 있더라도 직접 GP 선정 주체가 아니면 공개 출자기관 디렉토리와 일반 LP Notice 기본 화면에 올리지 않는다.
- 보험사, 증권사, 금융지주는 명시적인 출자공고, OCIO mandate, 별도 기금 운용, 또는 사모펀드 LP 커밋먼트가 확인될 때만 LP 화면에 올린다. 일반 대체투자자, 자기자본 투자자, 딜 플레이어 성격이면 LP 디렉토리가 아니라 뉴스/Market/GP 연결 신호로 관리한다.
- LP 원천 CSV의 기관 분류는 자본시장법상 기관전용 사모집합투자기구 LP 적격 유형을 기준으로 한다. `legal_lp_category`와 `legal_lp_basis`에는 자본시장법 시행령 제271조의14 및 제10조의 열거 유형에 맞춰 `금융기관`, `법률상 기금/기금관리법인`, `법률상 공제사업 법인`, `특수법인/전문투자자`, `정책펀드/모태펀드 운용기관`, `OCIO 위임형 법정기금/공적자금`처럼 기록한다.
- LP 원천 CSV는 `legal_lp_category`, `legal_lp_basis`, `coverage_tier`, `display_enabled`, `notice_tracking_enabled`, `profile_status`를 사용해 법적 분류, 서비스상 중요도, 공개 화면을 분리한다. `coverage_tier`는 필터/정렬 데이터로만 쓰고, 공개 row에 등급 배지나 내부 상태 문구처럼 노출하지 않는다.
- `coverage_tier` 기본값은 `core`, `ocio`, `policy`, `candidate`다. `core`는 핵심 직접 출자기관, `ocio`는 OCIO/위임형 공적기금 pool, `policy`는 직접 출자사업을 운영하는 정책펀드·공공기관성 출자 주체, `candidate`는 화면 노출 전 검토 후보로 둔다.
- 공개 출자기관은 원칙적으로 확인된 PE/VC/대체투자 출자공고 또는 선정 이력이 있어야 한다. 다만 KIC, 수협, 캠코처럼 사용자가 전략적으로 필요하다고 지정한 기관은 `display_enabled=1` 예외로 유지할 수 있다. 그 외 출자 이력 0건 기관은 `coverage_tier=candidate`, `display_enabled=0`으로 후보 pool에 둔다.
- `display_enabled=1`인 LP는 빈 상세 페이지로 두지 않는다. 최소 공개 facts는 `기관 유형`, `홈페이지`, `담당 조직`, `관심 자산군`이며, 공식 공고 채널이 확인된 경우 `공식 공고 채널`도 함께 넣는다. 총자산, 배분, 담당자, 선정 GP처럼 공식 근거가 부족한 값은 추정하지 않고 비워 둔다.
- LP 서비스의 중심 화면은 출자공고다. 기관 목록은 디렉토리로 유지하고, 출자공고 화면은 `공고중`, `접수마감`, `1차 선정`, `선정완료`, `취소`, `히스토리`를 구분해 마감일, 규모, 기관, 원문, 첨부자료, 연결 GP가 체계적으로 보이게 한다.
- LP Notice의 사업명 정규화와 라운드 판정은 `services/lp/src/lp_notice_identity.py`를 기준 모듈로 둔다. 공개 화면의 상태 판정과 공고/서류심사/선정결과 카드 병합은 `services/newsletter/src/lp_notice_view.py`에 두고, `services/newsletter/src/build_newsletter_deploy.py`에는 이 규칙을 다시 직접 붙이지 않고 화면 조립과 배포 산출물 생성만 남긴다.
- LP Notice 상태는 사업 lifecycle 기준으로 판단한다. `선정완료`와 `1차 선정`은 마감일보다 우선하고, 그 다음에 유효 마감일 기준으로 `공고중` 또는 `접수마감`을 판단한다. 마감일이 과거인 공고를 매일 `deadline_closed` 신규 이벤트처럼 만들지 않는다. 공고일이 없고 과거 마감일만 있는 공고는 `event_date=오늘`로 저장하지 않는다.
- LP Notice 사업명은 저장된 특정 사업명이 깨끗하면 우선 사용하고, 본문 메뉴·지원자격·운용계획 문장에서 뽑힌 긴 후보는 버린다. 같은 사업 카드라도 최신 이벤트와 18개월 이상 떨어진 과거 이벤트/마감일은 현재 카드 상태와 진행 이력에 섞지 않는다.
- LP/GP 상세 fact row에서 출처명, 날짜, `공식 확인` 같은 긴 메타 문자열을 값 아래 반복 노출하지 않는다. 필요한 출처는 홈페이지·자료·기사·LinkedIn을 구분하는 작은 아이콘 링크로 표시하고, 긴 출처 목록은 하단 `자료` 영역에 둔다.
- LP 상세에서 `프로필 항목`, `자료 성격`, `공개자료 기준`처럼 수집 커버리지나 내부 판단에 가까운 항목은 본문 콘텐츠처럼 노출하지 않는다. 자료 링크와 제한적 참고사항만 하단 `자료` 영역에 둔다.
- `상세 프로필`, 중복 순위, 반복되는 자료/근거 문구처럼 모든 row에서 같은 의미를 되풀이하는 텍스트는 줄인다. 사용자에게 필요한 핵심 값만 표 컬럼과 row 안에 둔다.
- GP 화면은 뉴스레터 UI를 기준 구현으로 삼는다. GP 목록은 흰 배경, 얇은 row divider, 원형 CI 슬롯, 표형 row, 모바일 우선 컬럼 구성을 사용하고, 큰 hero·카드형 KPI·강한 pill badge를 기본값으로 두지 않는다. GP 상세는 회사 식별 정보, 운용 현황, 펀드 이력, LP 연결, 관련 뉴스/딜을 조용한 fact matrix와 리스트로 정리한다.
- GP 공개 화면에서 `proxy`, `research`, `verification`, `source/evidence`, `operator`, `AI-generated` 같은 내부 표현은 금지한다. 기사 제목이나 원문에 포함된 AI 산업 용어는 그대로 둔다. 필요한 경우 `운용 현황`, `약정액 기준`, `출자 연결`, `관련 뉴스`로 바꾼다.
- GP 목록의 공개 필터는 짧고 사용자가 바로 이해할 수 있는 기준만 둔다. `상위 프로필`, `자료 확인`, profile page availability, 검증 상태, 빌드 coverage 같은 내부 기준은 화면에 노출하지 않는다.
- 서비스별 임의 강조색을 쓰지 않는다. 기본은 흑백·회색·얇은 border 중심이고, 활성 상태도 공통 `var(--accent)`, `var(--surface-muted)`, `var(--separator)` 계열로 맞춘다.
- 기사 row 오른쪽 책갈피처럼 목적지가 불분명한 저가치 아이콘은 공개 화면에서 제거한다. 저장 기능은 뉴스, LP, GP, Wiki 전체에 적용되는 명확한 저장함이 설계된 뒤 전역 기능으로 다룬다.

## 서비스별 기본 담당

- 공개 사이트 빌드는 서비스별 빌드와 통합 배포를 분리한다. Newsletter, LP, GP는 active public builder entry point를 갖고, 최종 공개 산출물은 `scripts/build_site_bundle.py`가 한 폴더인 `services/newsletter/deploy/site/`로 합친다. Wiki builder는 보존하되 재기획 전까지 explicit-only다.
- 기본 통합 빌드 명령은 `python3 scripts/build_site_bundle.py --services newsletter,lp,gp --date YYYY-MM-DD`다. 특정 서비스만 다시 굽는 경우에는 `--services lp`, `--services gp`처럼 좁혀서 실행한다. Wiki는 사용자가 다시 기획했을 때만 `--services wiki`로 명시 실행한다.
- 서비스별 source renderer를 고치지 않고 `services/newsletter/deploy/site/`의 생성 HTML을 직접 고치는 것은 금지한다. 생성물은 빌드 검증이나 배포 결과로만 다룬다.
- Wiki는 뉴스레터처럼 매일 수집·재분류되는 서비스가 아니다. Wiki 본문이나 공통 shell이 바뀌었을 때만 Wiki builder를 실행하고, 루틴 뉴스/LP 갱신이 Wiki 콘텐츠를 불필요하게 다시 쓰지 않게 한다.
- 기존 호환 파일인 `services/newsletter/src/build_newsletter_deploy.py`는 당분간 남길 수 있지만, 새 자동화와 새 작업은 서비스별 builder와 `scripts/build_site_bundle.py`를 우선한다.

- `뉴스레터 데스크`: `services/newsletter/`, 뉴스 수집·분류·태그·검색·발행 화면·뉴스레터 배포 준비를 맡는다. LP/GP 원천 CSV와 People 입력 파일은 직접 대량 수정하지 않는다.
- `LP Monitor / LP Research`: `services/lp/`, LP 기관 프로필, 출자공고, 출자 히스토리, 공식 채널, LP profile facts를 맡는다. 뉴스레터 편집 판단과 GP evidence 파일은 직접 바꾸지 않는다.
- `GP Profile / Market Data`: GP 식별자, 별칭, profile evidence, FSS 기반 운용사·펀드 데이터, GP profile master 산출물을 맡는다. 뉴스레터 본문 판단과 LP 리뷰 상태는 직접 바꾸지 않는다.
- `PEF Wiki Documentation`: PEF Wiki 콘텐츠, 실무 안내, 법령·규정 참조, 용어집, 출처 링크를 맡는다. 현재 핵심 파일은 `services/newsletter/src/pef_wiki_pages.py`이며, 장기적으로는 별도 markdown source로 분리한다.
- `Verifier / Deploy`: 테스트, 빌드, 공개 사이트 확인, 배포 전후 검증을 맡는다. 제품 내용 판단은 하지 않고, 생성 산출물 커밋 여부는 메인 Codex가 결정한다.
- `Project Lead`: 서로 다른 서비스 요청을 병렬로 배정하고, 같은 파일·DB·배포 산출물을 만지는 작업은 순서를 잠근다. 최종 커밋·배포·사용자 보고는 Project Lead가 통합한다.

## 공통 제품 원칙

- 뉴스레터는 독립 발행 서비스다. 매일 읽을 수 있는 결과물 자체가 품질 기준이며, 동시에 GP 프로필과 People DB를 갱신할 신호를 남겨야 한다.
- People DB는 단순 인명록이 아니다. GP별 핵심 인물, 역할, 경력, 학력, 뉴스 연결을 통해 GP 페이지와 뉴스 해석에 맥락을 제공하는 엔진이다.
- 공개 화면에서는 뉴스, GP, 펀드, 인물을 같은 서비스의 다른 진입점으로 보여준다. 뉴스레터 카드는 기사 링크만 나열하지 않고 확인된 GP/관련 인물 맥락을 보여주되, 프로필 보강·식별자 보강·작업 담당자 같은 운영 상태는 보여주지 않는다.
- 운영 콘솔은 `dashboard/`에 둔다. 작업 큐, DB 품질, 수집 로그, 원천 관리, 검토 대기 상태는 실제 사용자용 공개 사이트 화면과 분리한다.
- 뉴스 담당은 기사 단위의 사실, 출처, GP 연결, 갱신 액션을 보존한다. People DB 담당은 인물 단위의 식별, 역할, 출처, 뉴스 연결을 보존한다.
- 두 담당 모두 추정으로 빈칸을 채우지 않는다. 공개 반영은 출처가 있고 검토 상태가 분명한 데이터만 사용한다.
- 운영 산출물은 재생성 가능한 파일과 DB 경로에 남긴다. 일회성 메모, 로컬 캡처, 수동 SQLite 수정만으로 운영 결정을 남기지 않는다.

## PEF Wiki 확장 원칙

- Wiki 담당은 `기관전용 사모집합투자기구 실무안내`만 처리하지 않는다. 장기 범위는 실무안내 전 장, 관련 법률·시행령·감독규정, 세무 신고, 금융위원회·금감원 보고 작성, 설립·운용·투자·청산 체크리스트까지 포함한다.
- 각 Wiki 문서는 `본문`, `관련 조문`, `보고/제출`, `실무 체크`, `출처`가 서로 이동 가능해야 한다.
- 법령·세무·보고 항목은 시행일, 제출기한, 제출기관, 적용 대상, 필요 서류가 확인된 경우에만 확정 문장으로 쓴다.
- PDF는 원천 출처로만 남긴다. 사용자가 읽는 기본 화면은 PDF 이동이 아니라 위키 본문이어야 한다.
- 원천 링크는 마지막 출처 목록에만 몰아넣지 않고, 관련 본문 근처에도 작게 연결한다. 다만 원문 PDF 보기 버튼이나 출처 링크가 본문보다 더 중요한 행동처럼 보이면 안 된다.

## 공통 키

두 담당은 아래 키를 모든 작업 메모, CSV, 큐, 검토 요청에서 같은 의미로 사용한다.

| 키 | 의미 | 사용 기준 |
| --- | --- | --- |
| `source_gp_id` | GP 원천 식별자. `gp_profile.source_gp_id` 또는 `gp_house.gp_id`와 연결한다. | GP가 식별된 뉴스, People 역할, GP 업데이트 큐에 반드시 포함한다. |
| `standard_gp_name` | 표준 GP 표시명. | 사람이 검토할 산출물에는 `source_gp_id`와 함께 표기한다. |
| `person_id` | People DB 인물 식별자. | 기존 인물과 연결될 때 사용하고, 신규 후보는 비워 둔 채 `update_action`으로 생성 필요를 표시한다. |
| `news_id` | 뉴스 문서 식별자. | 뉴스 담당 산출물에서 People DB 작업으로 넘어가는 기사 단위 연결 키다. |
| `source_url` | 기사, 팀 페이지, 공시, 공식 프로필 등 원문 URL. | 모든 비-FSS 사실의 최소 증거 필드다. |
| `update_action` | 다음 작업 지시. | 예: `publish_only`, `gp_profile_update`, `identifier_update`, `people_create`, `people_role_update`, `people_news_link`, `hold`, `exclude`. |

## 뉴스레터 담당 운영 지시

### 역할명

뉴스레터 담당 에이전트의 운영상 이름은 `뉴스레터 데스크`로 둔다. 뉴스레터 데스크는 발행물의 편집 품질, 핵심 매체 커버리지, 공개 카드 표시 언어를 함께 책임진다.

### 입력

- 뉴스 소스와 수집 설정: `services/newsletter/data/news_sources.csv`
- 키워드 및 분류 규칙: `services/newsletter/data/news_keyword_rules.csv`
- GP 별칭 보정: `services/newsletter/data/news_gp_alias_overrides.csv`
- 수동 포함/제외 보정: `services/newsletter/data/news_manual_overrides.csv`
- 원문 저장 위치: `data/raw/daily_news/YYYY-MM-DD/`
- 뉴스 DB 스키마: `services/newsletter/schema/daily_news.sql`
- 운영 DB: `db/private_equity.db`

### 출력

- 초안 브리프: `exports/daily_news/daily_news_brief_latest.md`
- 초안 HTML: `exports/daily_news/daily_news_brief_latest.html`
- 날짜별 초안: `exports/daily_news/daily_news_brief_YYYYMMDD.md`, `exports/daily_news/daily_news_brief_YYYYMMDD.html`
- 리뷰 큐: `exports/daily_news/daily_news_review_queue_latest.csv`, `exports/daily_news/daily_news_review_queue_YYYYMMDD.csv`
- 리뷰 화면: `exports/daily_news/daily_news_review_latest.html`
- 리뷰 액션: `exports/daily_news/daily_news_review_actions_latest.csv`, `exports/daily_news/daily_news_review_actions_YYYYMMDD.csv`
- 최종 발행본: `exports/daily_news/daily_news_final_latest.md`, `exports/daily_news/daily_news_final_latest.html`
- 날짜별 최종본: `exports/daily_news/daily_news_final_YYYYMMDD.md`, `exports/daily_news/daily_news_final_YYYYMMDD.html`
- 소스 커버리지 감사: `exports/daily_news/newsletter_source_audit_latest.md`, `exports/daily_news/newsletter_source_audit_latest.csv`
- GP 업데이트 큐: `exports/daily_news/news_gp_update_worklist_latest.csv`, `exports/daily_news/news_gp_update_worklist_YYYYMMDD.csv`
- 뉴스/People/GP 통합 작업 큐: `exports/service_integration_worklist_latest.csv`, `exports/service_integration_worklist_YYYYMMDD.csv`
- newsletter public mirror 반영 파일: `services/newsletter/deploy/site/`, public mirror `pkkong/kpef-newsletter`의 `gh-pages` 브랜치
- 공개 사이트 번들: `services/newsletter/deploy/site/index.html`, `services/newsletter/deploy/site/daily-news.html`
- 운영 로그: `exports/daily_news/logs/daily_news_YYYYMMDD_HHMMSS.log`

### 품질 기준

- 발행물은 최근 24시간 오전 브리핑 기준을 따른다. 발행 시간이 확인되는 기사는 운영 창에 맞춰 필터링하고, 시간이 없으면 발견일 기준으로 처리한다.
- 현재 자동 발행은 토요일과 일요일에도 매일 08:30 KST에 돈다. 월요일 72시간 창은 주말을 쉬기 위한 설정이 아니라 주말 수집 실패, 검색 반영 지연, 소스 오류를 월요일에 회수하기 위한 안전장치다. 월요일 브리프를 평가할 때는 금요일 08:30 이후 이미 주말 브리프에 발행된 기사가 `previous export`로 빠질 수 있음을 먼저 확인한다.
- 각 기사에는 제목, 출처, 날짜, `source_url`, 관련 GP, 분류, 포함/제외 판단이 있어야 한다.
- 중복 제거는 세 단계로 본다. 먼저 매체별 모바일·AMP·카테고리 suffix·추적 파라미터를 제거한 `normalized_source_url`로 같은 기사를 합치고, 다음으로 같은 매체의 거의 같은 제목을 제거하며, 마지막으로 국민성장펀드 운용사 선정처럼 여러 매체가 같은 이벤트를 반복 보도하는 경우 이벤트 단위로 묶어 발행 밀도를 낮춘다.
- 회사 담당자 또는 외부 클리핑 리스트와 대조할 때는 `미수집`, `DB 수집`, `리뷰 후보`, `발행`, `운영창 밖`을 분리해서 판단한다. 오전 브리핑 운영창인 08:30 이후 기사나 전일 이전 기사는 같은 날짜 발행 누락으로 보지 않고, 다음 발행 창 또는 과거 백필 대상인지 따로 표시한다.
- 외부 리스트에서 실제로 놓친 고품질 기사가 확인되면 일회성 강제 포함보다 `news_sources.csv`의 출처/쿼리 보강, `news_keyword_rules.csv`의 제목·본문 신호 보강, `run_daily_news_pipeline.py`의 분류·중복·URL 정규화 테스트를 우선 업데이트한다.
- 매일 발행 전에는 세 층을 모두 대조한다. 첫째 `daily_news_brief_YYYYMMDD.md`의 섹션, 둘째 `daily_news_review_queue_YYYYMMDD.csv`의 `current_category`, `section_tags`, `topic_tags`, 셋째 `services/newsletter/deploy/site/archive.json`의 공개 `section`과 `subCategory`다. 이 셋이 같은 기사에 대해 서로 다른 신호를 내면 발행 품질 미달로 본다.
- 리뷰 CSV에서 `current_category`와 `section_tags`는 대표 섹션 1개로 일치해야 한다. `topic_tags`는 검색 보조값이지만 대표 섹션과 충돌하면 안 된다. 예를 들어 GP 펀드레이징 기사에 `LP` 토픽이 남거나, Deal 기사에 GP명이 등장했다는 이유만으로 `GP` 토픽이 남으면 보정 대상이다.
- 분류는 독자 관점의 기사 주제를 우선한다. `LP`는 KIC, 국민연금, 공제회, 모태펀드, 성장금융, 위탁운용사 선정, 출자공고, 커밋먼트처럼 명시적인 출자자·allocator·mandate 맥락이 있을 때만 붙인다. 일반 기업이 펀드에 돈을 넣었다는 의미의 `출자`나 소송 문맥의 투자문서 제출은 LP로 보지 않는다.
- `Deal`은 실제 거래 이벤트에만 쓴다. 매각, 인수, 우선협상, 본입찰, SPA, 리캡, 특정 기업의 DIP/인수금융/리파이낸싱처럼 대상 회사·자산·펀드와 거래 행위가 보이는 기사여야 한다. 사모대출, 프라이빗크레딧, 고금리, 스페셜시추에이션, 컨퍼런스 인터뷰처럼 시장 환경이나 전략을 설명하는 기사는 `Market`이다.
- `Market`은 시장 구조, 규제·소송·리스크, 업계 단체, GP 지분거래/GP 스테이크 같은 주제다. `GP 스테이크`는 특정 운용사의 펀드레이징이 아니라 운용사 지분 투자 시장 구조이므로 기본 분류를 `Market`으로 둔다.
- `NationalGrowthFund`는 제목 또는 원천 카테고리에서 국민성장펀드가 주제인 경우 별도 섹션으로 우선 분류한다. 국민성장펀드가 본문에서 부수적으로만 언급되고 제목의 주제가 AI, Deal, LP 등 다른 범주이면 해당 주제를 우선한다.
- `AI & PE`는 제목이나 기사 중심 주제가 AI와 사모시장 변화일 때만 우선한다. 제목은 LP 패널·출자자 전략인데 요약이나 본문에 AI가 한 번 언급된 정도라면 LP 섹션을 우선한다.
- 반복 오분류는 테스트로 고정한다. `펀딩 목표`, `자펀드`, `블라인드`, `모태펀드 GP 도전`은 LP/국민성장펀드 맥락이 있어도 기사 주제가 운용사 펀드 결성이면 `GP / Fundraising`이다. `CB 투입`, `메자닌 인수`는 `Deal / Financing`이고, `본입찰`, `예비입찰`, `원매자`, `인수의향`, `제안`은 단순 `Exit`이 아니라 `Deal / Auction`이다. `장외파생상품 라이선스`처럼 금융업 인가·라이선스 이슈는 `Market / Regulation`이다.
- GP 태그는 표준 GP명과 별칭 사전을 기준으로만 붙인다. 기사에 `IMM인베스트먼트`처럼 영문 약어와 한글이 섞인 이름이 나오는데 태그가 빠지면 `services/newsletter/data/news_gp_alias_overrides.csv`에 별칭을 추가하고 테스트로 고정한다.
- GP가 확인되면 `source_gp_id`와 `standard_gp_name`을 함께 남긴다. 이름만 있고 GP 식별이 불확실하면 큐에 `update_action=identifier_update` 또는 `hold`로 남긴다.
- 기사에서 인물 이동, 대표 변경, 신규 파트너, 팀 페이지 변경, 딜 관여 인물 등 People DB에 영향을 주는 신호가 있으면 `person_id` 확인 여부와 함께 `update_action=people_create`, `people_role_update`, `people_news_link` 중 하나로 넘긴다.
- 발행 후보와 DB 갱신 후보를 분리한다. 독자가 읽을 가치가 낮아 발행에서 제외된 기사라도 GP/People 갱신 신호가 있으면 큐에는 남긴다.
- 공개 뉴스 카드에는 운영용 표현을 노출하지 않는다. `GP 스톤브릿지캐피탈`, `관련 인물 3명`처럼 DB 작업 상태가 드러나는 라벨은 피하고, 확정 GP명 1개와 추가 개수 정도만 조용히 표시한다.
- 뉴스 카드 메타는 중복 카테고리를 반복하지 않는다. 섹션 헤더가 이미 카테고리 역할을 하므로 카드 안에는 언론사만 표시하고, 기자명이 안정적으로 수집되면 `언론사 · 기자명`으로 확장한다.
- 뉴스레터 기사 목록은 회색 배경 위 둥근 카드 묶음으로 만들지 않는다. 흰 배경 위에 섹션 제목과 row divider가 이어지는 평평한 리스트를 기본으로 한다.
- 뉴스레터 기사 요약은 `summaryLines` 3줄을 기본으로 한다. 정보가 부족할 때만 2줄을 허용하고, 없는 사실을 채워 넣지 않는다. 쉽게 읽히되 말투는 투자업계 메모에 맞춘다. 뉴닉식 구어체나 제목 반복은 피하고, `했어요`, `해요`, `입니다` 같은 말투와 `했다`, `전망이다`, `사례다` 같은 반복 기사체 결말을 쓰지 않는다. `AI generated`, `source evidence`, `confidence`, `자동 생성`, `관리자` 같은 내부 표현은 공개 요약에 절대 노출하지 않는다. `사건 / 숫자·주체·단계 / PE·LP·GP 관점의 의미` 순서로 짧게 쓰고 마침표는 붙이지 않는다.
- NotebookLM/외부 AI는 뉴스레터 핵심 발행 엔진이 아니라 `daily_news_ai_enrichment_YYYYMMDD.json`을 만드는 보조 레이어로 둔다. 공개 화면은 `summaryLines`만 사용하고 provider, confidence, notes 같은 내부 값은 노출하지 않는다. AI의 `section_suggestion`은 기본적으로 audit에 남기고, 최근 기사 백테스트에서 품질이 확인된 뒤 `NEWSLETTER_AI_APPLY_SECTIONS=1`로 공개 섹션 반영을 켠다. 반복 오분류는 규칙과 테스트로 고정한다.
- 뉴스레터는 가로 구분선을 과하게 겹치지 않는다. 날짜 영역의 장식선, 목록 상단선, 마지막 row 하단선처럼 중복되는 선은 피하고 row 사이의 얇은 구분만 남긴다.
- 뉴스레터 상단의 `Daily / Weekly / 출자공고` 탭은 예정 기능의 자리표시자로 유지할 수 있다. 다만 비활성 탭은 낮은 대비의 텍스트 탭으로 표현하고, 진한 비활성 버튼이나 카드형 탭처럼 보이게 하지 않는다.
- 하단 메뉴는 1차 서비스 이동만 담당한다. 뉴스 기사만 저장하는 기능은 전역 `저장` 탭이나 뉴스레터 헤더 유틸리티로 노출하지 않는다. 전역 저장함은 LP/GP/Wiki 저장까지 구현된 뒤에만 하단 메뉴로 승격한다.
- 매일 발행 후 `services/newsletter/src/build_newsletter_source_audit.py`를 실행해 더벨, 딜사이트, 인베스트조선, 블로터, 뉴스토마토, 뉴스톱 등 핵심 매체가 수집/리뷰/브리프 단계에서 어디까지 도달했는지 확인한다.
- 검증은 `services/newsletter/tests/test_daily_news_logic.py`, `services/newsletter/src/validate_daily_news_pipeline.py`, `services/newsletter/src/check_newsletter_brand_icons.py`를 실행해야 한다. `validate_daily_news_pipeline.py` 실패는 발행 차단이고, 아이콘 검사의 missing/weak 리포트는 품질 보완 backlog로 남기되 당일 뉴스레터 공개를 막지 않는다. 아이콘 이슈까지 강제 차단하려면 `NEWSLETTER_STRICT_ICON_CHECK=1`을 명시한다. 분류·태그·서브카테고리를 고친 날에는 `test_daily_news_logic.py`에 해당 기사 제목 기반 회귀 테스트를 추가한 뒤 통과시킨다.
- 매일 08:30 KST 뉴스레터 발행은 GitHub Actions workflow에서 `NEWSLETTER_BUILD_SERVICES=newsletter`로 실행한다. LP/GP/Wiki 수집·빌드 실패가 당일 뉴스레터 공개를 막으면 운영 실패로 본다.
- 발행 완료는 로컬 `daily_news_brief_YYYYMMDD.md` 생성이 아니라 public mirror push와 공개 확인까지다. GitHub Actions는 공개 `health.json`의 `report_date`와 `article_count`, `archive.json`의 당일 entry를 확인한 뒤에만 성공 종료해야 한다.
- 매일 발행 후 `exports/daily_news/ops_status/newsletter_ops_status_latest.md`를 우선 확인한다. 이 파일의 `Status`가 `ok`이고 hard failure가 없어야 “수집/공개 완료”로 보고할 수 있다. 사용자가 “오늘 수집 안 된 것 같다”고 하면 로그부터 파지 말고 이 status report의 Collection, Local, Public, Quality 섹션을 먼저 본다.

### 금지사항

- Google News 중계 링크, 검색 결과 링크, 추적 URL을 최종 `source_url`로 남기지 않는다.
- 기사 본문에 없는 GP, 인물, 역할, 직함, 딜 맥락을 추정해 추가하지 않는다.
- `standard_gp_name`만 적고 `source_gp_id`를 비워 둔 상태로 확정 업데이트 큐를 만들지 않는다. 식별 불가 상태는 별도 검토로 남긴다.
- People DB 입력 파일을 뉴스 담당이 직접 대량 수정하지 않는다. People 담당에게 `news_id`, `source_url`, `update_action`이 포함된 작업 신호로 넘긴다.
- 발행 품질과 무관한 장기 리서치 항목을 뉴스레터 본문에 억지로 포함하지 않는다.

## People DB 담당 운영 지시

### 입력

- 인물 기본 입력: `data/people_input.csv`
- 역할 입력: `data/person_role_input.csv`
- 학력 입력: `data/person_education_input.csv`
- 입력 템플릿: `data/people_import_template.csv`, `data/person_role_import_template.csv`, `data/person_education_import_template.csv`
- 이름 보정: `data/person_name_overrides.csv`
- 학교명 보정: `data/school_name_aliases.csv`
- 뉴스 담당 신호: `exports/daily_news/news_gp_update_worklist_latest.csv`, `exports/daily_news/daily_news_review_actions_latest.csv`
- People DB 스키마: `schema/people.sql`
- 운영 DB: `db/private_equity.db`

### 출력

- 인물 요약: `exports/people_profile_summary.csv`
- 현 소속 GP 뷰: `exports/people_current_gp.csv`
- 역할 이력: `exports/people_roles.csv`
- 학력 뷰: `exports/people_education.csv`
- People 리서치 작업 목록: `exports/people_research_worklist_top50.csv`
- 뉴스/People/GP 통합 작업 큐: `exports/service_integration_worklist_latest.csv`
- GP 프로필 연동 산출물: `exports/gp_profile_master.csv`, `exports/gp_profile_master.xlsx`
- dashboard 반영 데이터: `dashboard/data/dashboard_data.json`
- 공개 사이트 번들: `services/newsletter/deploy/site/index.html`, `services/newsletter/deploy/site/daily-news.html`

### 품질 기준

- 공개 표시 대상 인물은 최소 하나 이상의 `person_source` 또는 동등한 공식/권위 출처를 가져야 한다.
- `person_id`는 동일 인물을 안정적으로 추적하는 기준이다. 동명이인, 영문/국문 표기 차이, 전/현 소속 혼재가 있으면 신규 생성 전에 중복 가능성을 검토한다.
- GP 소속은 `person_role.org_type='GP'` 기준으로 관리하고, 가능한 경우 `source_gp_id`와 `standard_gp_name`을 함께 보존한다.
- 뉴스에서 나온 인물 신호는 `news_id`와 `source_url`을 통해 `person_news_link` 또는 후속 연결 구조로 추적 가능해야 한다.
- 직함, 역할 기간, 학력, 전직 이력은 출처가 확인된 범위까지만 입력한다. 미확인 기간은 비워 두거나 검토 상태로 둔다.
- People DB 갱신 후 `scripts/import_people_csv.py`, `scripts/export_people_views.py`, 필요 시 `scripts/build_dashboard_data.py` 산출물이 일관되게 갱신되는지 확인한다.

### 금지사항

- 개인 민감정보, 비공개 연락처, 출처 없는 생년/나이/학번/개인 SNS를 입력하지 않는다.
- 기사 한 건의 표현만으로 현직, 퇴직, 승진, 담당 업무를 단정하지 않는다. 공식 팀 페이지, 보도자료, 공시, 신뢰 가능한 기사 등으로 확인한다.
- `person_id` 중복 가능성을 확인하지 않고 새 인물을 생성하지 않는다.
- 뉴스 담당의 발행 판단을 People DB 담당이 임의로 바꾸지 않는다. People 담당은 DB 갱신 필요 여부와 근거만 남긴다.
- GP 식별이 불확실한 인물 역할을 확정 소속으로 입력하지 않는다.

## 매일 운영 흐름

1. 뉴스 수집: `services/newsletter/src/run_daily_news_pipeline.py` 또는 `services/newsletter/scripts/run_daily_news_today.ps1`로 수집하고 `data/raw/daily_news/YYYY-MM-DD/`, `db/private_equity.db`, `exports/daily_news/`를 갱신한다.
2. 발행 후보 검토: 뉴스 담당은 `exports/daily_news/daily_news_review_latest.html`과 `exports/daily_news/daily_news_review_queue_latest.csv`를 검토해 발행 포함/제외와 분류를 확정한다.
3. GP update queue 생성: 뉴스 담당은 `exports/daily_news/news_gp_update_worklist_latest.csv`에 `source_gp_id`, `standard_gp_name`, `source_url`, 갱신 액션을 남긴다.
4. 통합 작업 큐 생성: 운영자는 `scripts/build_service_integration_worklist.py`로 `exports/service_integration_worklist_latest.csv`를 갱신한다. 이 파일이 뉴스 담당, GP 프로필 담당, People DB 담당의 공통 작업판이다.
5. People worklist 생성: People 담당은 통합 큐와 기존 People 산출물을 대조해 `exports/people_research_worklist_top50.csv` 또는 입력 CSV 갱신 후보를 만든다.
6. People DB 반영: People 담당은 `data/people_input.csv`, `data/person_role_input.csv`, `data/person_education_input.csv`를 출처 기반으로 갱신하고 `scripts/import_people_csv.py`, `scripts/export_people_views.py`를 실행한다.
7. newsletter public mirror 반영: GitHub Actions가 `services/newsletter/src/build_newsletter_deploy.py`와 `scripts/build_site_bundle.py`로 `services/newsletter/deploy/site/`를 만들고 public mirror `pkkong/kpef-newsletter`의 `gh-pages` 브랜치에 push한다.
8. 공개 사이트 반영: 운영자는 서비스별 builder와 `scripts/build_site_bundle.py`를 통해 `services/newsletter/deploy/site/` 번들을 최신 상태로 만든다.
9. 상태 점검: `scripts/build_operational_status_report.py`로 `exports/operational_status_latest.md`를 갱신하고, 뉴스와 People의 미처리 `update_action`을 다음날 작업 목록으로 넘긴다.

## repo 기준 핵심 경로

- 운영 DB: `db/private_equity.db`
- 뉴스 스키마: `services/newsletter/schema/daily_news.sql`
- People 스키마: `schema/people.sql`
- 뉴스 입력 설정: `services/newsletter/data/news_sources.csv`, `services/newsletter/data/news_keyword_rules.csv`, `services/newsletter/data/news_gp_alias_overrides.csv`, `services/newsletter/data/news_manual_overrides.csv`
- People 입력: `data/people_input.csv`, `data/person_role_input.csv`, `data/person_education_input.csv`
- 뉴스 원문: `data/raw/daily_news/YYYY-MM-DD/`
- 뉴스 발행/검토/큐: `exports/daily_news/`
- 뉴스/People/GP 통합 작업 큐: `exports/service_integration_worklist_latest.csv`
- People 검토/뷰: `exports/people_profile_summary.csv`, `exports/people_current_gp.csv`, `exports/people_roles.csv`, `exports/people_education.csv`, `exports/people_research_worklist_top50.csv`
- GP 프로필/식별자: `exports/gp_profile_master.csv`, `exports/gp_profile_master.xlsx`, `exports/gp_identifier.csv`, `exports/gp_profile_sources.csv`
- dashboard 데이터와 앱: `dashboard/data/dashboard_data.json`, `dashboard/index.html`, `dashboard/assets/app.js`, `dashboard/assets/app.css`
- 공개 사이트 번들: `services/newsletter/deploy/site/`
- 운영 상태 보고서: `exports/operational_status_latest.md`, `exports/operational_status_YYYYMMDD_HHMMSS.md`
