# 프로젝트 개선 방향 및 중요 오류 검토 — 2026-09-06

검토 기준: `b6d35688bee93ef20f429ae4e9c9b8ed4fc7a925`. 공개 상태는 2026-09-06 00시대 KST에 확인했고 보고서는 01:00 KST에 정리했다.
범위: 운영 계약, Newsletter/Vercel/Supabase, GP canonical publication, LP 공고 identity, 기존 테스트와 GitHub Actions, 공개 HTTP 응답.
Project Lead가 runtime·배포·통합을 검토하고 Verifier 1명이 GP/LP와 테스트 실행을 병행했다. 주요 반례는 Lead가 재확인했다.

후속 상태: 사용자의 수정 요청에 따라 아래 결함을 코드에서 수정하고 로컬 검증을 완료했다.
수정 내역·검증 수치·운영 반영 순서는 `docs/project_fixes_2026-09-06.md`를 따른다.
이 문서의 코드 위치와 재현 결과는 수정 전 검토 기록이며, 운영 DB와 배포는 아직 변경하지 않았다.

## 판단

현재 우선할 일은 기능 확대보다 데이터 갱신의 안전성과 검증 신뢰도를 높이는 것이다.
서비스별 소유권, Supabase 기준 DB, Vercel 공식 앱, 공통 뉴스레터 UI라는 방향은 유지한다.
실제 구현에는 비원자적 DB 교체, canonical snapshot 재사용, 테스트 실행 누락,
공식 앱에서 백업 미러로 빠지는 내비게이션이 남아 있다.

이 검토에서는 서비스 코드, DB, 배포를 변경하지 않았다. 아래 장애 반례는 mock REST,
메모리 캐시, Flask test client, 기존 테스트를 이용한 로컬 재현이다. 운영 DB의 실제 손상이나
진행 중인 전체 서비스 장애를 확인했다는 뜻은 아니다.

## 현재 운영 상태

- Vercel `/health.json?refresh=1`: HTTP 200, `status=ok`, `data_source=supabase`,
  `report_date=2026-09-05`, 기사 16건, issue 30개. 확인 시각은 9월 6일 일일 발행 전이다.
- Pages health도 9월 5일자 16건이다. 두 archive는 30개 issue, 기사 row 491개로 일치한다.
  날짜·기사 순서·제목·URL·분류·요약·GP/LP 이름·sectionOrder·rank를 대조해 차이가 없었다.
- Vercel `/gps.html`, `/market.html`: HTTP 200, `supabase-public-snapshot`, `2025Q4`,
  snapshot `fss-2025q4-ec864d1a2f16-7d07989aa5c4`.
- Vercel `/lp-notices.html`: HTTP 404. Pages의 LP 공고 페이지는 HTTP 200이다.
- 최신 확인한 실제 발행: mirror run `33931796847`, Supabase sync run `33932027983` 성공.
  9월 4일 raw HTML MIME 장애 이후 정상 발행이 이어진 상태다.

검증 URL:
[공식 health](https://kpef-newsletter.vercel.app/health.json?refresh=1),
[공식 GP](https://kpef-newsletter.vercel.app/gps.html),
[최신 확인 sync](https://github.com/pkkong/korea-pef-db/actions/runs/33932027983).

## 우선 수정할 오류

### R1 · P1 — DB를 먼저 비우고 다시 넣어 실패 시 기존 데이터가 사라짐

근거:

- `services/newsletter/src/sync_newsletter_canonical_supabase.py:399`: canonical 태그와
  entity link 전체를 DELETE한 뒤 별도 REST 요청으로 재삽입한다.
- `services/gp/src/sync_fss_canonical_supabase.py:440`: People 전체를 DELETE한 뒤 재삽입한다.
  `20260828100000_fss_people_canonical_data.sql`의 People 자식 테이블 5개도 CASCADE 삭제된다.
- `services/newsletter/src/sync_newsletter_supabase.py:355`: 공개 issue 연결도 선택한 날짜
  전체를 먼저 지운 뒤 재삽입한다. routine sync는 최근 30개 issue가 대상이다.

재현: canonical DELETE 성공 직후 첫 POST에 오류를 주면 뉴스 태그·entity link가 각각 0건이
남는다. People도 같은 실험에서 기존 인물 1명이 0명으로 바뀐다. 복구나 rollback은 없다.
이 상태를 다음 임시 SQLite 복원의 원본으로 읽을 수 있다는 점이 특히 위험하다.
공개 archive fallback은 canonical 원본 손상을 복구하는 장치가 아니다.

수정 방향: payload 사전 검증 → 임시 버전 적재 → 건수·참조 대사 → DB transaction/RPC에서
한 번에 교체. 실패한 실행은 마지막 정상 버전을 유지해야 한다. People과 뉴스 태그도
전체 삭제 대신 변경 범위 또는 version을 기준으로 교체한다.

완료 기준: DELETE 이후와 각 적재 batch 사이에 오류를 넣어도 이전 canonical/public 상태가
그대로 남고, 같은 payload 재실행으로 정확히 복구된다.

### R2 · P1 — 같은 FSS 원본의 재발행이 기존 canonical snapshot을 오염시킴

근거: `services/gp/src/sync_fss_canonical_supabase.py:333,425`.
canonical snapshot ID가 최신 원본 Excel SHA만 반영한다. 기존 snapshot header는
`ignore-duplicates`로 보존하면서 하위 행은 같은 ID에 upsert한다. 삭제 대상 행을 제거하는
처리는 없고, 기존 published snapshot을 수정하지 못하게 하는 검사도 없다.

재현: 기존 GP 2개를 alias 정리 후 1개로 줄인 payload를 같은 snapshot에 적용하면,
DB에는 새 GP 1개와 제거돼야 할 기존 GP 1개가 함께 남는다. header의 GP count도 기존 2개를
유지한다. 동일한 원본에서 parser·alias를 수정하고 재발행할 때 발생할 수 있다.

수정 방향: 전체 원천 manifest, 승인된 alias 규칙, 변환 결과를 식별하는 버전을 포함해
새 immutable canonical snapshot을 만든다. published ID 재사용은 동일 payload일 때만
허용하며, publish 직전에 모든 table의 count/hash를 확인한다. GP public HTML snapshot과
FSS canonical snapshot은 서로 다른 모델이므로 둘 모두 이 검증이 필요하다.

### R3 · P1 — 원문 캐시 정리의 조회 실패가 당일 발행을 중단시킴

근거: `services/newsletter/src/sync_newsletter_canonical_supabase.py:328,411`.
`purge_raw_html_cache()`의 개별 DELETE/PATCH 오류는 잡지만, 정리 대상 목록을 읽는
`_read_all()`은 예외 처리 밖에 있다. `apply_payload()`가 이 함수를 직접 호출한다.

재현: canonical 적재 이후 cleanup 목록 조회에 `CanonicalNewsletterError`를 주면
`apply_payload()` 전체가 실패한다. mirror workflow는 이 sync 다음에 공개 build를 실행하므로
원문 정리용 조회 장애가 당일 공개 발행까지 막는다.

수정 방향: cleanup 전체를 발행 필수 경로에서 분리하고 조회·페이지네이션·삭제 실패를
경고로 기록한다. 다음 실행에서 정리를 재시도한다. DB 본문 적재 실패와 cache cleanup
실패를 같은 성공/실패 상태로 취급하지 않는다.

### R4 · P2 — 실행되지 않는 테스트가 LP 공고 회귀를 숨김

근거: `services/newsletter/tests/test_daily_news_logic.py:3453`의 수동 실행 목록과
`services/lp/tests/test_lp_notice_gp_link.py`의 `__main__` 목록.
정의된 테스트 중 각각 8개, 4개가 빠져 있다. 일반 unittest discovery는 이 함수형 테스트들을
수집하지도 않는다. 등록된 테스트만 실행하면 모두 통과한다.

누락된 12개를 추가 실행한 결과 10개 통과, 2개 실패:

- `test_lp_notice_placeholder_round_is_not_a_new_business_card` (`:850`, 실패 assertion `:879`).
  은행권 중견기업 밸류업펀드의 명시된 `3차` 공고와 차수 없는 종료 이벤트가
  `...|3차|2026`, `...|2026`으로 나뉘어 2개 카드가 된다. 사업명이 제목에서만 구체화되고
  저장된 programName은 generic인 경우, 보완한 roundName이 identity 추론에서 다시 무시된다.
  관련 구현: `services/lp/src/lp_notice_view.py:501`,
  `services/lp/src/lp_notice_identity.py:433`.
- `test_lp_notice_round_not_duplicated_when_program_already_includes_round` (`:833`, 실패 `:845`).
  기대 사업명 `모태펀드(우주항공청 등) 2026년 2차 정시 출자사업` 대신
  `모태펀드(우주항공청 등)`이 반환된다. 최종 label은 `모태펀드(우주항공청 등) 2차`다.
  연도·정시 구분을 유지할 표시 계약과 정규화 identity를 먼저 맞춰야 한다.

첫 번째는 사업 카드 분리 반례를 확인했다. 두 번째는 사업명 표시 기대값의 불일치이며,
이 결과만으로 운영 DB에서 서로 다른 사업이 잘못 합쳐졌다고 단정하지 않는다.
공개 candidate 차단을 유지하면서 validated lifecycle에서도 같은 분류가 일관돼야 한다.

수정 방향: 테스트 자동 수집과 0개 실행 방지, LP 테스트의 서비스 소유권 정리,
PR/push CI 연결. 현재 workflow에는 PR/push를 계기로 전체 회귀를 실행하는 구성이 없다.
사업 identity를 program·year·asset·round로 일관되게 확정한 뒤 화면과 export가 함께 쓰게 한다.

### R5 · P2 — GP 페이지별 캐시 만료가 서로 연장됨

근거: `services/newsletter/web/app.py:61,75`.
캐시는 페이지별로 저장하지만 만료 시각은 모든 페이지가 하나를 공유한다.

재현: t=0에 구버전 gps.html을 캐시한 뒤, t=301에 새 snapshot의 gp-1.html을 읽고,
t=302에 gps.html을 요청하면 300초가 지났어도 구버전 directory가 반환된다.
다른 페이지 갱신이 반복되면 이전 페이지의 만료도 계속 뒤로 밀릴 수 있다.

수정 방향: 페이지별 TTL과 snapshot ID를 저장하거나 active snapshot이 바뀔 때 전체
page cache를 폐기한다. 장애 때 마지막 정상 버전을 제공하는 시간에도 상한을 둔다.

### R6 · P2 — 공식 브리프의 GP 메뉴가 백업 미러로 연결됨

근거: `services/newsletter/web/newsletter_ui.py:244,284`와
`services/newsletter/web/app.py`의 `daily_news()` 호출.
Vercel에서도 `service_base_url`을 전달하지 않아 기본 Pages URL을 쓴다.
공개 `/` HTML에서 GP 링크가 `https://pkkong.github.io/kpef-newsletter/gps.html`인 것을 확인했다.
`web/tests/test_newsletter_data.py:265`는 오히려 이 오래된 링크를 기대해 회귀를 잡지 못한다.

영향: Vercel GP가 정상인데도 주 사용자 동선은 백업 서비스로 빠진다. 미러 발행 지연·장애가
공식 UX에 영향을 준다. LP는 아직 Vercel route가 없으므로 단순히 공통 base URL만 바꾸면
LP 404를 만들 수 있다.

수정 방향: GP 링크를 공식 경로로 연결하고 서비스별 URL 계약을 검사한다. LP는 별도
canonical/public read model과 Vercel route를 갖춘 뒤 정식 전환한다. 문서의 목표 구조와
현재 운영 경로를 구분해 표시한다.

### R7 · P2 — 외부 archive 장애 때 정상 캐시가 있어도 HTTP 500

근거: `services/newsletter/web/newsletter_data.py:278`.
Supabase와 Pages/raw fallback이 모두 실패하면 최종 `fetch_archive_url()`의 예외가 빠져나간다.
이미 보관된 마지막 정상 archive를 돌려주는 경로가 없다.

재현: 기존 issue 1개가 든 만료 캐시를 두고 upstream 요청에 URLError를 주면 Flask `/`와
`/health.json` 모두 500이다.

수정 방향: 제한된 기간의 마지막 정상 archive를 반환하고 health에서 degraded/stale 상태와
마지막 성공 시각을 구분한다. 캐시가 전혀 없는 cold start는 제어된 503으로 응답한다.
정상 Supabase를 읽었을 때도 Pages와 raw를 매번 순차 조회하는 경로에는 별도 시간 예산을 둔다.

## 추가 경계 사례

`sync_newsletter_supabase.prepare_payload()`에 같은 URL을 두 날짜로 주면 article은 1개로
합쳐지지만 같은 primary key의 tag/entity row는 중복 생성된다. 같은 URL의 오래된 issue가
기사 본문 필드를 덮어쓸 수도 있다. 현재 공개 30개 issue에는 반복 URL이 없었다.
실제 Supabase에 이 payload를 적용하는 실험은 하지 않았다. 재발행·정정 기능을 확대하기 전에
중복 metadata key 제거와 날짜별 기사 표현 계약을 검증해야 한다.

## 검증 결과와 한계

- Architecture contracts: 통과.
- 기존 실행 경로: 210개 검사 통과.
  Newsletter 158개, scripts unittest 10개, GP unittest 20개,
  LP unittest 3개 + dedupe 17개 + GP link 2개.
- 누락된 함수형 검사 12개 추가: 10개 통과, 위 LP 관련 2개 실패.
  합계 222개 실행, 220개 통과, 2개 실패.
- Lead 재현: 위 실패 테스트 2개 재확인; 뉴스/People DELETE→POST 실패,
  FSS 동일 snapshot 재발행, cleanup 조회 오류, GP 캐시 만료, Flask outage 응답 확인.
- 공개 HTTP/health/archive와 최근 Actions 실행 결과를 읽기 전용으로 확인했다.
- 이번에는 production DB를 변경하거나 전체 canonical DB를 대사하지 않았다.
  원천 재수집, 전체 새 bundle build, 모바일 시각 검수, 신규 production 배포도 실행하지 않았다.

## 개선 실행 순서

1. **다음 안정화 변경:** R3 cleanup 오류 분리, R5/R7 캐시·장애 응답 보완,
   R4 테스트 자동 수집을 함께 넣어 실패 사례를 지속 검사한다. R6 GP 링크도 이 단계에서 고친다.
   완료 기준은 전체 테스트 실제 실행, LP 실패 해소 또는 명시된 표시 계약 정합화,
   Vercel GP 메뉴 이동 확인이다.
2. **데이터 안전성 변경:** R1/R2를 서비스별로 구현하되 공통 publish 원칙을 적용한다.
   immutable version, transaction, 전체 count/hash 검증, 마지막 정상 버전 복구가 필요하다.
   스키마와 rollback 절차를 검토하고 작은 데이터로 실패 주입 검증한 뒤 운영 반영한다.
3. **제품 통합:** LP의 `Supabase canonical → published read model → Vercel` 전환을 완료한다.
   LP 공고의 정확한 사업 단위 묶음과 기준일, GP 프로필의 출처·최근 확인일·People 커버리지를
   먼저 개선한다. 신규 탭·Wiki 확장은 기존 결정대로 보류한다.

중기에는 4천~5천 행 규모의 collector/renderer/legacy 파일을 파서·사업 identity·public export·
화면 모듈로 점진 분리한다. 전면 재작성보다 위 장애 테스트를 먼저 확보하고 경계를 나누는 것이
낫다. 운영 상태판은 긴 과거 사건 목록과 현재 계약을 분리하고, 서비스별 현재 공개 버전·
마지막 성공 시각·복구 경로를 한곳에서 확인하게 한다.

이 순서는 착수 순서다. R1/R2의 중요도가 낮다는 의미가 아니며, 데이터 안전성 설계는
빠른 runtime 수정과 독립적으로 진행할 수 있다.
