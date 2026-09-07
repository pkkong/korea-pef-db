# 프로젝트 오류 수정 결과

수정 검토: 2026-09-06 / 인계 정리: 2026-09-07 KST

## 사용자가 알아둘 결과

검토에서 확인한 중요 오류를 코드에서 수정했다. 자료 갱신에 실패해도 기존 자료를
보존하고, 수정된 운용사 자료에 이전 자료가 섞이지 않도록 했다. 출자공고가 잘못
나뉘는 문제와 GP 메뉴, 오래된 화면이 계속 남는 문제도 고쳤다.

**로컬 코드 수정과 검증은 완료했다. commit/push, 운영 DB 변경, 공개 사이트 배포는
아직 실행하지 않았다.** 기존 운영 자료가 실제로 유실됐다는 진단은 아니며,
오류를 인위적으로 발생시켜 확인한 위험과 재현된 화면·분류 문제를 수정한 것이다.

## 수정 범위

| 기존 문제 | 수정 후 동작 |
| --- | --- |
| 뉴스·인물 자료를 먼저 지워서 갱신 실패 시 자료가 사라짐 | 준비된 자료를 DB에서 한 번에 교체하며 오류 시 기존 상태 유지 |
| 같은 금감원 자료를 고쳐 올리면 이전 운용사 행이 남음 | 변환 내용이 달라지면 새 버전으로 발행하고 과거 버전은 보존 |
| 오래된 원문 파일 정리 실패가 당일 뉴스 발행을 막음 | 정리 오류는 경고로 남기고 발행 계속 |
| 출자공고 사업명·회차를 잘못 판단해 공고가 나뉨 | 제목에서 확인한 사업명·회차 반영, 다른 연도·자산군과 혼합 방지 |
| 다른 GP 페이지 조회가 오래된 페이지의 유효기간까지 연장 | 페이지별 만료 시각을 관리하고 새 자료 버전 확인 시 기존 페이지 제거 |
| 뉴스 자료 조회 장애가 일반 서버 오류로 표시됨 | 일정 시간 마지막 정상 자료 제공, 사용할 자료가 없으면 명시적인 일시 장애 응답 |
| 브리프의 GP 메뉴가 백업 사이트로 연결됨 | 공식 앱의 `/gps.html`로 연결 |
| 일부 테스트가 실행되지 않아 오류가 숨음 | 모든 테스트 자동 발견, 0개 실행 실패 처리, PR/push 검사 추가 |

기사 제목·요약의 일반 단어를 내부 필드 유출로 잘못 판단하던 공개 화면 검사도
수정했다. 실제 내부 필드와 UI 문구는 계속 검사한다. 언론사 아이콘 누락은 기존
운영 규칙대로 품질 경고이며 발행을 막지 않는다.

LP의 Vercel 이전은 별도 제품 과제다. 아직 없는 LP 경로로 메뉴를 바꾸지 않고
현재 연결을 유지했다. Wiki, 뉴스 편집 기준과 프로필 내용 보강은 이번 수정 범위가 아니다.

## 검증 결과

- 자동 회귀 검사: **241개 통과**, 실패·오류·skip 0개, 21개 파일 실행.
- PostgreSQL 17 기반 임시 DB: **14개 통과**. 적재 누락, 마지막 단계 참조 오류,
  재시도, 부분 교체, 공개 자료 변경 차단과 기존 데이터 보존을 실제 SQL로 검증했다.
- 실제 로컬 FSS 자료 **60,269행**, People **877행**을 별도 임시 DB에 적재하고
  내용 대조 및 공개 전환을 확인했다. 운영 DB와 원본 SQLite는 수정하지 않았다.
- `newsletter,lp,gp` 통합 소스 빌드, 공개 HTML 검사, 구조 계약 검사 통과.
- 수정된 로컬 Flask 앱이 읽기 전용 공개 자료로 9월 5일자 기사 16건을 제공하는
  smoke 검사 통과. 이는 Vercel에 새 코드를 배포한 결과가 아니다.
- 통합 archive 기사 491행 검사 통과. 기존 뉴스프리존 아이콘 경고 2개는 남아 있다.
- 로컬 LP 입력이 없어 LP 전체 실제 데이터 화면은 검증하지 못했다. 빈 화면 구조와
  LP 사업명·회차 관련 회귀 검사는 통과했다.

신규 checkout에 전체 FSS DB fixture가 없으면 기존 실데이터 검사 5개를 명시적으로
skip한다. 이번 로컬 검사에서는 fixture가 있어 전부 실행했다. 새 SQL 실패 검사는
운영 자격증명 없이 자체 fixture로 실행한다.

```bash
python3 scripts/run_regression_tests.py
npm ci --prefix scripts/tests/sql --ignore-scripts
npm test --prefix scripts/tests/sql
python3 scripts/check_architecture_contracts.py
python3 services/newsletter/scripts/check_vercel_supabase_readiness.py --smoke-app
```

## 운영에 반영할 순서

새 클라이언트는 새 DB 함수를 요구한다. **DB migration을 먼저 적용하고 새 동기화를
실행해야 한다.** 배포 담당자는 진행 중인 발행 작업과 순서를 조율해야 한다.

1. 검증한 소스를 저장소에 반영하고 PR/push 자동 검사를 확인한다.
2. `Apply newsletter Supabase migration`으로
   `20260906090000_newsletter_atomic_sync.sql`을 적용한다. 뉴스레터 workflow는
   GP/FSS 소유 migration을 제외한다.
3. `Apply GP Supabase migrations`로
   `20260906100000_gp_canonical_safe_publish.sql`을 적용한다. 기존 FSS/People
   schema가 전제다. 이 workflow는 새 안전성 migration만 적용하며, 과거 GP 페이지
   제약 migration은 재실행하지 않는다. 이미 공개된 People 페이지와 충돌할 수 있다.
4. 뉴스 수집·미러 빌드와 별도 Supabase read model 동기화를 새 코드로 실행해
   날짜·기사 수·순서가 일치하는지 확인한다. GP 변경은 해당 GP workflow로 실행한다.
   GP 두 발행 workflow와 migration은 `gp-publish`로 직렬 실행한다.
5. `Deploy newsletter Vercel app`으로 앱 코드를 배포한다. 이 단계는 자료 동기화를
   대신하지 않는다. LP 수정은 LP를 포함한 빌드·게시 후 확인한다.
6. 실제 공개 브리프·GP 메뉴, 날짜 이동, GP/People 상세와 LP 공고 묶음을 확인한 뒤
   control center에 run ID, 소스 commit, 운영 적용 결과를 기록한다.

새 schema 적용 후 옛 GP 클라이언트로 되돌리면 공개 행 보호 장치 때문에 재발행이
거부될 수 있다. DB 보호를 제거하는 대신 새 클라이언트를 유지하거나 수정해서
다시 실행한다. DB 버전과 클라이언트를 별개로 되돌리지 않는다.

## 인계 경계

- 근거 기록: `docs/project_review_2026-09-06.md`는 수정 전 검토로 보존한다.
- 최신 계약: `docs/data_operating_model.md`, `docs/product_operating_model.md`,
  `docs/project_lead_control_center.md`, `docs/service_quality_backlog.md`.
- 생성된 HTML, 임시 DB, 로그, 의존성 설치 폴더와 자격증명은 소스에 포함하지 않는다.
- SQL 검사 패키지와 고정된 dependency lock은 회귀 검사 소스로 관리한다.
