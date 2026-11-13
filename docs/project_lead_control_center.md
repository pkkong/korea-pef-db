# 프로젝트 리드 현재 상태판

갱신: 2026-11-13 KST (작성: Claude)

새 작업을 시작하는 에이전트(Codex·Claude)가 가장 먼저 읽는 현재 상태 문서다. 여기에는 지금 유효한 상태·구조·규칙·다음 작업만 둔다. 날짜별 작업 기록은 [`docs/history/`](history/README.md)로 옮긴다. 2026-11-13 이전의 전체 기록은 [history/project_lead_control_center/until-2026-11-13.md](history/project_lead_control_center/until-2026-11-13.md)에 원문 그대로 있다.

## 문서 운영 규칙

- 작업 시작 시 읽는 문서는 네 개다: 이 문서, [LP 수집 현황](lp_collection_status.md), [재개 체크포인트](lp_resume_checkpoint.md), [서비스 품질 백로그](service_quality_backlog.md).
- 이 네 문서는 각각 40KB 이하로 유지한다. `scripts/check_architecture_contracts.py`가 검사한다. 넘기 전에 오래된 날짜별 항목을 `docs/history/<문서명>/YYYY-MM.md`로 옮긴다(원문 그대로, 최신이 위).
- 현재 상태는 고쳐 쓰고, 날짜별 경과는 체크포인트에 쌓는다. 같은 내용을 여러 문서에 복사하지 않는다.
- 사람이 읽을 수 있게 쓴다. 띄어쓰기를 지키고, 실행 ID·바이트 수는 근거로 필요한 만큼만 붙인다.

## 현재 공개 서비스 (2026-11-13 확인)

| 서비스 | 공식 주소 | 데이터 경로 | 상태 |
| --- | --- | --- | --- |
| 브리프(뉴스레터) | https://kpef-newsletter.vercel.app | 매일 수집 → Supabase → Vercel. 백업 미러 https://pkkong.github.io/kpef-newsletter/ | 매일 발행 정상 |
| LP 출자사업 | https://kpef-lp.vercel.app | 평일 2회 수집 → Supabase 공개본 → Vercel | 19기관 40사업 공개(공개 실행 `ef0522eff5f8e6c89a94be01`) |
| GP 운용사 | https://kpef-gp.vercel.app | 금감원 분기 자료 → Supabase 스냅샷 → Vercel | 2025Q4 기준. 프로필에 LP 선정 이력 표시(11/13). 없는 페이지는 404 |
| Wiki | — | — | 사용자가 다시 기획할 때까지 숨김 |

공개 하단 메뉴는 `브리프 / LP / GP` 세 개로 고정한다.

## 시스템 구조

- **GitHub Actions**: 수집·발행·배포·감시를 실행한다. 정기 실행은 아래 workflow 표 참고.
- **Supabase**(프로젝트 `fhigakwodmfjwtttwyyj`, 세 서비스 공용 서버): 서비스별 비공개 원본 스키마와 공개 읽기용 스키마를 가진다. LP 원본은 `lp_program_private`(`program_state`, `collection_runs`, `documents` 등). 큰 수집 보고서는 비공개 Storage 버킷 `lp-collection-reports`에 두고 DB에는 위치만 기록한다(예산 900MB, [보관 운영](lp_report_storage_operations.md)).
- **Vercel**: 서비스마다 독립 앱(`services/<service>/web/`). 공개 읽기 키만 쓴다. 다른 서비스를 import·호출하지 않는다.
- **GitHub Pages**: 뉴스레터 백업 미러만. 공식 경로가 아니다.

### LP 수집·발행 흐름

1. `collect-kgrowth-programs.yml`의 수집 job들이 기관별로 병렬 수집한다: 공유 협회 공고(`collect_shared_lp_notices`), 기관 게시판(`collect_lp_institution_boards` + `lp_board_adapter_*`), 교직원공제회, 우정사업본부, 수출입은행, 한국벤처투자 원문.
2. `collect` job이 `lp_publication_runner.py` → `publish_lp_programs.py`로 판독·검증·발행한다. 사업 단위 묶기·PE 범위 판단은 `lp_notice_publication.py`, 화면 생성은 `lp_program_service.py`·`lp_program_detail.py`.
3. 보도 기준 선정 결과는 `data/lp_reported_results.json`을 발행 때 붙인다(공식 명단이 생기면 자동으로 숨김). 새 보도 후보는 주간 workflow가 찾고 사람·에이전트가 검토해 이 파일을 고친다.
4. 발행 뒤 공개 페이지가 이번 실행과 같은지 확인하고, 마지막에 기관별 접속 장애를 보고한다. 장애 보고 단계만 실패하면 run은 failure지만 공개는 정상일 수 있다.

## 서비스 책임

- 브리프: 매일 클리핑·분류·태그·검색·아카이브. 품질 개선은 별도 담당 채팅이 맡았던 영역이므로 통합 기준과 회귀 조건만 이 문서에서 관리한다.
- LP: 출자기관·출자사업 공고·단계·선정 운용사. 수집 범위는 [LP 수집 현황](lp_collection_status.md).
- GP: 운용사 디렉토리·프로필·시장 통계·People·관련 뉴스.
- 검증·배포: 회귀 검사, 구조 계약, 공개 주소 확인, 배포 상태.

## 반드시 지킬 제품 결정

- 반복되는 사용자 지적은 단순 실수가 아니라 지시 관리 실패로 보고 규칙 문서에 반영한다.
- 공개 화면은 하나의 제품처럼 보여야 한다. 기준은 혁신의숲 같은 데이터 디렉토리 서비스다. 화면 규칙은 [design_system.md](design_system.md).
- 운영자용 표현(`관리자`, `자동 생성`, `source/evidence`, `검토 대기`, `보강 필요` 등)을 공개 화면에 노출하지 않는다. 없는 값은 표시하지 않는다.
- 화면 유형: 뉴스는 평평한 기사 목록, LP/GP 목록은 표에 가까운 행 목록, LP/GP 상세는 프로필, LP 공고는 행 카드, Wiki는 문서형(현재 숨김).
- 생성된 HTML을 직접 고치지 않는다. 원본 코드를 고치고 다시 생성·검증한 뒤 발행한다.
- LP 공개 기준·보도 기준 결과·대형 LP PE 공개·PE·VC 공동 모집 표시는 `AGENTS.md` Project Context의 사용자 결정(2026-11-12)을 따른다.
- 출자기관 공개 목록은 직접 운용사를 선정하는 기관만. OCIO 위임형 기금은 내부 분류로 둔다. 법적 LP 유형(`legal_lp_category`)과 공개 등급(`coverage_tier`, `display_enabled`)은 따로 관리한다.
- 금감원 통계의 GP 수는 펀드별 대표 운용사 기준이며 공동 운용사 수와 섞지 않는다.

## 정기·운영 workflow (31개)

| 구분 | workflow | 시각(KST) / 용도 |
| --- | --- | --- |
| LP 정기 | `collect-kgrowth-programs` | 평일 09:20·15:20 수집·발행 |
| LP 정기 | `lp-collection-watchdog` | 평일 매시 05분, 수집 누락 시 대신 실행 |
| LP 정기 | `maintain-lp-report-storage` | 수집 뒤 자동, 오래된 보고서 보관·정리 |
| LP 정기 | `audit-lp-official-inventory` | 일요일 10:00, 공식 목록 독립 대조 |
| LP 정기 | `find-lp-reported-results` | 월요일 08:43, 브리프 기사에서 선정 결과 보도 후보 찾기(읽기 전용, [절차](lp_reported_results_operations.md)) |
| LP 복구·진단 | `recover-lp-publication`, `diagnose-lp-board-http`, `diagnose-lp-inventory-failures` | 발행 복구, 공식 응답 제한 진단, 감사 실패 진단 |
| LP 과거 이력 | `discover-lp-history`, `discover-ktcu-history`, `inspect-lp-history`, `collect-lp-history-bodies`, `collect-lp-history-attachments`, `collect-kgrowth-history-attachments`, `plan-lp-history-attachments`, `prepare-lp-history-publication`, `publish-lp-history` | 2023년 이후 이력 수집(진행 중 과제) |
| LP 배포·설정 | `deploy-lp-vercel`, `deploy-lp-source-worker`, `configure-lp-reviewer` | 앱 배포, 서울 경유 수집 중계, 검토자 설정 |
| 브리프 | `deploy-newsletter-pages`(매일 08:37), `newsletter-watchdog`(09:22), `sync-newsletter-supabase`, `deploy-newsletter-vercel`, `apply-newsletter-supabase-migration`, `check-newsletter-vercel-readiness` | 미러 수집·빌드 → Supabase 동기화 → Vercel |
| GP | `deploy-gp-fss-pages`, `publish-gp-people-from-supabase`, `deploy-gp-vercel`, `apply-gp-supabase-migrations` | 금감원 자료 발행, People만 재발행, 앱 배포 |
| 공통 | `test-regressions` | push·PR마다 회귀 검사 |

운영 workflow 실행·배포는 사용자 승인 후에만 수동 실행한다. 일회성 진단 workflow는 목적을 다하면 삭제하고 이 표를 고친다.

## 검사·빌드 명령

공통 검사(로컬 기준 환경: Python 3.12 + `services/newsletter/web/requirements.txt` + `olefile==0.47` + `pypdf==6.10.0`):

```bash
python3 scripts/run_regression_tests.py          # 2026-11-13 기준 1,284검사
python3 scripts/check_architecture_contracts.py
npm ci --prefix scripts/tests/sql --ignore-scripts && npm test --prefix scripts/tests/sql
```

전체 금감원 fixture가 없는 checkout에서는 실데이터 검사 5개가 명시적으로 skip된다. 테스트 0개 파일이나 실행 실패를 성공으로 보지 않는다.

기타 자주 쓰는 명령:

```bash
python3 scripts/build_newsletter_bundle.py --date YYYY-MM-DD --archive-limit 30   # 뉴스레터 단독 빌드
python3 scripts/check_public_frontend.py --services newsletter                     # 공개 화면 계약
python3 scripts/check_fss_statistics_ready.py --db db/private_equity.db --expected-latest-period 2025Q4
curl -fsS "https://kpef-newsletter.vercel.app/health.json?refresh=1"
```

`scripts/build_site_bundle.py`(로컬 통합 정적 빌드)는 브리프·GP·Wiki만 만든다. LP는 `services/lp/web` 앱이 Supabase 공개본으로 보여 주며 정적 LP 페이지 경로는 2026-11-13에 삭제했다.

구조 계약 검사는 workflow가 부르는 테스트 모듈·스크립트가 실제로 있는지도 확인한다. 모듈을 지우면 그 이름을 쓰는 workflow도 같이 고친다.

## 완료 보고 전 필수 검증

- 회귀 검사와 구조 계약 검사 통과.
- 화면이 바뀌면 생성 결과를 확인하고, 운영 반영 뒤 공개 주소에서 다시 확인한다. 모바일 390px·데스크톱 1280px 중 못 본 쪽은 보고에 적는다.
- 브리프가 바뀌면 Vercel과 Pages의 `report_date`, 기사 수, 아카이브 순서가 같아야 한다.
- 로컬 완료(코드·검사)와 운영 반영(실행·배포·공개 확인)을 구분해서 보고한다.

## 인계 양식

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

받는 쪽은 대화 기억에 의존하지 않고 `AGENTS.md`와 이 문서부터 읽는다.

## 알려진 리스크 (2026-11-13)

- **LP 과학기술인공제회 목록 410**: 11/13 수동 실행에서 기관 게시판 검색 목록이 HTTP 410을 반환해 장애 보고 단계가 실패했다(공개는 정상). 처음 관측이라 코드 변경 없음. 정기 실행에서 반복되면 게시판 주소·검색 파라미터 변경을 원문으로 확인한다.
- **LP 결과 명단 공백**: 산업은행 결과는 첨부 표 텍스트에서 칸 경계가 사라져 운용사 이름을 자동 분리하지 못한다. 원문 링크만 둔다. 개별 통보 기관은 보도 기준 결과(수동 JSON)로 보완 중이며 정기 갱신 절차가 아직 없다.
- **농협 주간 감사 DNS 실패**: 11/8 주간 감사에서 농협 검색 7개가 DNS 오류였다. 진단은 끝났고 원래 실패 기록은 유지한다.
- **공용 Supabase 서버**: 세 서비스가 같은 서버를 쓴다. 앱·배포는 분리됐지만 DB 서버 장애는 함께 겪는다. DB 용량과 Storage 예산(900MB)을 발행 때 검사한다.
- **뉴스레터**: 분류·태그 품질은 계속 관리 대상이다. 분류 로직을 바꾸면 `services/newsletter/tests/test_daily_news_logic.py`에 제목 기반 회귀 검사를 추가한다. 매일 자동 발행은 `stable` 소스 프로필을 쓴다(전체 67개 소스는 수동 `all` 실행만). 장애 판단은 GitHub Actions 로그와 공개 `health.json`/`archive.json`을 기준으로 한다.
- **금감원 원천**: 2015Q4·2016Q1 `.xls` 두 파일은 SHA로 보존 확인만 하고 DB에는 넣지 않는다.

## 다음 작업

현재 재개 지점과 작은 다음 단위는 [재개 체크포인트](lp_resume_checkpoint.md) 맨 위 항목, 서비스 개선 후보는 [서비스 품질 백로그](service_quality_backlog.md)를 따른다.

## 종료 체크리스트

- 반복될 사용자 지적을 규칙 문서에 반영했는가?
- 생성물을 손으로 고치지 않고 원본에서 다시 만들었는가?
- 검사·빌드·공개 확인을 실행하고 결과를 보고했는가?
- 로컬 완료와 운영 반영을 구분해 보고했는가?
- 체크포인트에 `작성: Claude` 또는 `작성: Codex`로 남기고 commit했는가?
