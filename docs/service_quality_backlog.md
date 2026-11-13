# 서비스 품질 백로그

갱신: 2026-11-13 KST (작성: Claude)

다음에 할 개선 과제와 서비스별 상시 원칙을 둔다. 끝난 과제는 `완료` 절에 한 줄로 남기고, 자세한 경과는 [재개 체크포인트](lp_resume_checkpoint.md)에 쓴다. 2026-11-13 이전 전체 기록은 [history/service_quality_backlog/until-2026-11-13.md](history/service_quality_backlog/until-2026-11-13.md)에 있다. 과제 번호(A·B·C·D)는 2026-11-12 LP 공고 서비스 점검에서 붙인 것을 이어 쓴다.

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

## 열린 과제 (위에서부터 우선)

### LP 콘텐츠

- **B-3 과거 이력**: 2023-01-01 이후 공고 백필. 11/6 사용자 승인 범위다. 성장금융 과거 본문·첨부와 교직원공제회 과거 공고가 진행 중이며 기준은 [과거 구축 계획](lp_history_backfill_plan.md). 계획 금액을 실제 운용사별 배정액으로 집계하지 않는다.
- **B-5 산업은행 결과 명단 (코드 완료, 다음 수집에서 반영)**: 결과 첨부 표의 붙은 이름을 이미 공개된 운용사 이름과 운용사 이름 끝말(파트너스·인베스트먼트·프라이빗에쿼티 등) 규칙으로 나눈다. 읽는 방법이 하나일 때만 쓰고, PE·VC 표는 PE 칸만 쓴다. 저장 원문 기준 예상: 남부권 PE 2곳(더함파트너스·릴슨프라이빗에쿼티), 세컨더리 중형 2곳(아이엠엠인베스트먼트·엘비인베스트먼트). 남은 것: 국민성장 1차 정책성펀드는 5/27 선정 결과 공고가 사업에 연결되지 않았고(현재 상태 `접수 결과`), 리그별 인원수 표 형식 판독도 아직 없다.
- **B-6 보도 기준 결과 검토 대기**: 주간 후보 workflow(`find-lp-reported-results.yml`, 절차는 [운영 문서](lp_reported_results_operations.md))가 생겼다. 11/13 첫 검토에서 과학기술인공제회는 6곳으로 보강했다. 남은 후보: 총회연금재단 2026 하반기 2차(11/11 보도 4곳, PE·VC 구분 미확인), 수출입은행 하반기 글로벌 성장펀드(11/10 노앤파트너스 선정 보도), 교직원공제회 2026·중소기업중앙회 2026(결과 기사 미발견).
- **관찰**: 과학기술인공제회 검색 목록 HTTP 410(11/13). 정기 실행에서 반복되면 게시판 주소·검색 파라미터를 원문으로 확인한다.

### LP 화면

- **C-9 운용사 이름 통합·LP↔GP 연결 (코드 완료, 운영 반영 대기)**: 표기 변형(법인 형태, 띄어쓰기, 에퀴티/에쿼티, 매니져스/매니저스, `gp_alias_merge_rules.csv` 검토 별칭)을 같은 운용사로 묶는다. LP 선정 이력·상세 페이지에 GP 공개 프로필 링크를 단다(GP 게시 프로필 59곳 중 이름이 하나로 맞을 때만). GP 프로필의 LP 선정 이력은 새 RPC `lp_public_notice_context()`로 읽는다. 운영 반영 순서: ① Supabase에 `services/lp/supabase/migrations/20261113090000_lp_public_notice_context.sql` 적용 ② LP 수집·발행 1회(계약 데이터 저장) ③ GP 재배포(`deploy-gp-fss-pages`). 셋 다 사용자 승인 필요. 기사 약칭(`JKL`, `우리PE`)과 GP 표시명(`어펄마캐피탈`) 같은 별칭은 확인 전까지 묶지 않는다.
- **C-10 검색 노출**: 설명·공유 메타는 반영됐다. sitemap은 LP 앱(`services/lp/web`) 배포가 필요하다. 일부 사업 주소가 해시값인 문제는 기존 주소 유지 원칙과 함께 검토한다.

### 코드·운영 부담

- **D-3 현황표 자동 생성**: `lp_collection_status.md`의 기관별 표를 정기 실행 결과(`build_lp_collection_health.py`)에서 생성하는 방안.
- **D-10 남은 구버전 공개 데이터 경로**: `scripts/build_public_service_data.py`(옛 `service_data.json`의 `lp_commitment_notices`), `lp_public_visibility.py`, `check_public_frontend.py`의 `check_public_lp_json_contract`, 로컬 대시보드 스크립트(`build_dashboard_data.py`, `open_dashboard.py` 등)는 운영 workflow가 쓰지 않는다. 쓰는 사람이 없는지 확인한 뒤 정리한다.
- **관찰: 수출입은행 목록 기간**: `lp_kexim_listing.py`는 옛 모니터의 기준을 그대로 옮겨 2024-01-01 이전 공고를 버린다. 2023년 이력 백필(B-3)에서 수출입은행을 다룰 때 이 기준을 2023-01-01로 바꿀지 확인한다.
- **D-5 큰 파일 분할**: `gp_service_pages.py`(5,600줄), `run_daily_news_pipeline.py`(3,700줄). 해당 기능을 고칠 때 함께 나눈다. 따로 일정을 잡지 않는다.
- **D-6 수집기 공통 틀**: 기관별 수집기·어댑터·전송 우회 파일이 기관마다 늘어난다. 다음 기관 추가 때 공통 어댑터 인터페이스로 모은다.
- **D-7 import 경로 정리**: 파일 79개가 `sys.path`를 직접 조작한다. 패키지 import로 바꾸는 작업. 우선순위 낮음.
- **D-8 운영 지침 문서 정리**: `docs/agent_operating_briefs.md`(114KB)에 날짜별 LP 규칙이 쌓여 있다. 주제별(전송·판독·공개 범위)로 합치고 날짜별 경과는 history로 옮긴다.
- **D-9 로컬 수동 갱신 스크립트 확인**: `services/ops/scripts/run_data_nightly_refresh.sh`와 `scripts/run_pipeline.py`는 개인 PC에서 금감원 자료를 다시 만드는 수동 도구다(11/13 LP 단계 제거). 아직 쓰는지 확인하고 아니면 정리한다.

## 뉴스레터

- 현재 뉴스레터 분류·태그 품질 개선은 별도 채팅방이 active owner다. 이 문서는 통합 기준과 회귀 조건만 유지한다.
- 태그 더보기 버튼을 작은 텍스트형 컨트롤로 정리한다. `+N`만 보이는 어두운 버튼은 쓰지 않는다.
- 0건 날짜는 아카이브에서 숨기거나 `발행 없음` 상태로 명확히 표시한다.
- 과거 백테스트 기사에도 최신 GP/LP 태그 로직을 다시 적용한다.
- Google News 중계 링크가 최종 발행본에 남지 않게 검증을 강화한다.
- 유사 제목 중복은 경고가 아니라 발행 차단 기준으로 올린다.
- 검색 placeholder는 `뉴스·기관·운용사 검색`처럼 실제 검색 범위와 맞춘다.

## LP 상시 원칙

- 출자기관 디렉토리는 직접 GP/위탁운용사를 선정하는 LP만 보여준다. OCIO 또는 전담운용사가 하위 운용사 선정 실무를 맡는 공적기금·위임형 자금 주체는 `coverage_tier=ocio`, `display_enabled=0`으로 별도 pool에 보관하고 공개 기본 목록에서 제외한다.
- 출자기관 공개 노출은 공식 기관 성격이 아니라 실제 PE/VC/대체 출자공고·선정 이력 기준으로 판단한다. 이력 0건 기관은 후보로 숨기고, KIC·수협·캠코처럼 사용자가 명시한 전략기관만 예외로 공개 유지한다.
- 기관 분류는 자본시장법상 기관전용 사모집합투자기구 LP 적격 유형을 기준으로 `legal_lp_category`에 둔다. 공개 여부와 서비스 중요도는 `display_enabled`, `coverage_tier`에서 따로 관리한다.
- LP 디렉토리를 `docs/design_system.md`의 LP/GP shared row contract에 맞춘다. 카드형 KPI와 가로 스크롤을 줄이고, 모바일에서도 핵심 컬럼이 남는 표형 row를 우선한다.
- LP 유형과 자산군은 화면에 한국어 라벨로 표시한다. 예: `정책금융기관`, `공제회`, `사모대출`, `부동산`, `모태펀드`.
- `0/0`, `자료 정리 중`, `검증 필요` 같은 운영 상태를 공개 화면에 노출하지 않는다.
- 첫 공개는18대상 기관의 공식 출자공고 자동 발견·본문/첨부 판독·모집/후속 연결에 집중한다. 기관 일반현황·AUM·조직 전수 보강과 GP 프로필/히스토리 연결은 뒤로 둔다.
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

## 완료 (2026-11-12~13, 작성: Claude)

- A-1 정기 발행 실패: 수집 보고서를 Storage에 보관하고 DB에는 위치만 기록(34cf1a6). 11/12 운영 확인.
- B-1 보도 기준 결과 10개 사업, B-2 대형 LP PE 공고 공개(31→39사업), B-4 PE·VC 공동 모집 표시. 기업은행 결과 명단 자동 추출(7d082cb).
- C-1~C-8 목록·상세 표시 정리(연도, 접수 중 우선·D-day, 상태명, 사업명, 기관명, 미확인 문구, 진행 단계, 출자기관 목록).
- D-1 특정 사업 하드코딩 제거, D-2 일회성 workflow 정리(40→30개)와 사용하지 않는 모듈 삭제(863bbf7).
- GP 서비스: 없는 페이지 503→404(060524c, 11/13 배포 확인). 우정사업본부 TLS 대체 접속.
- 운영 문서를 현재 상태 문서와 history로 분리(8e0d550).
- B-6 선정 결과 보도 후보 주간 탐색(브리프 공개 데이터 → LP 사업 매칭, 검토 후 반영) 추가(2026-11-13).
- D-4 구버전 LP 정적 화면·옛 모니터 경로 삭제(약 1만 8천 줄). 수출입은행 목록 판독만 `lp_kexim_listing.py`로 옮김. workflow가 부르는 모듈 존재 검사 추가(2026-11-13).
