# LP 보도 기준 선정 결과 운영

작성: 2026-11-13 (작성: Claude)

## 왜 있는가

여러 출자기관은 선정 결과를 지원 운용사에만 개별 통보하고 공개 공고를 내지 않는다. 사용자 결정(2026-11-12)에 따라, 공식 명단이 없는 사업은 언론 보도로 확인된 결과를 `보도 기준` 표시와 출처 기사와 함께 보여 준다. 공식 선정·우선협상 명단이 생기면 보도 기준 결과는 자동으로 숨는다.

## 데이터

- 원본: `data/lp_reported_results.json` (사람·에이전트가 검토해서 고치는 파일)
- 검증·적용: `services/lp/src/lp_reported_results.py` — LP 발행 때 공개 사업에 붙인다. 알 수 없는 사업, 형식 오류, 공식 결과가 있는 사업, 중복은 공개하지 않고 보류로 남긴다.
- 항목 필드: `program_id`, `stage`(`최종 선정`·`우선협상대상자`·`선정 없음`), `reported_at`, `complete`, `managers`, `note`, `scope_note`, `sources[publisher,title,date,url]`.

## 주간 후보 찾기

`Find LP reported result candidates` workflow(`find-lp-reported-results.yml`)가 매주 월요일 08:43 KST에 돈다. 수동 실행도 된다.

1. 브리프 공개 데이터(`newsletter_public_issue_articles`, 최근 180일)에서 제목이 선정 결과 보도처럼 보이는 기사를 고른다. `뽑는다`, `선정 착수`, `공고`, `앞둔` 같은 예고 기사는 뺀다.
2. 기사 제목에서 출자기관을 찾고(`data/lp_institutions.csv`의 별칭 + 언론 약칭), 같은 기관의 공개 사업 중 연도가 맞는 사업에 묶는다.
3. 이미 `lp_reported_results.json`에 출처로 들어간 기사는 뺀다.
4. 결과는 실행 요약 화면과 artifact(`lp-reported-result-candidates.md/json`)로 남는다. 공개 화면·데이터는 바꾸지 않는다.

후보 분류:

| 분류 | 할 일 |
| --- | --- |
| 결과 미반영 | 기사를 읽고 새 항목을 만든다 |
| 보도 기준 결과가 일부만 반영됨 | 명단을 보강하고, 다 확인되면 `complete: true` |
| 보도 기준 결과 반영됨 — 새 기사 확인 | 명단이 다르면 고치고, 같으면 출처만 추가해도 된다 |
| 공식 명단 있음 | 보통 할 일 없음. 보도와 공식 명단이 다르면 원문을 다시 확인 |
| 공개 사업과 연결되지 않은 결과 기사 | VC 전용·범위 밖이면 무시. PE 사업인데 공개 안 된 것이면 수집 누락을 확인 |

## 항목을 고칠 때 규칙

- 기사 원문을 직접 읽고 운용사 이름을 정식 명칭으로 쓴다(예: `어펄마` → `어펄마캐피탈매니져스코리아`처럼 확인되는 범위에서). 확인이 안 되면 기사 표기를 그대로 쓴다.
- PE·VC 공동 모집이면 PE 부문 운용사만 넣고 `scope_note`에 그 사실을 적는다. 부문을 확인할 수 없으면 넣지 않는다.
- 기사에 일부만 나오면 `complete: false`. 기사들이 전체 수와 이름을 모두 확인해 줄 때만 `complete: true`.
- 출처는 원문 기사 주소로 남긴다. 기사 문장을 길게 옮기지 않는다(`note`는 한두 문장 요약).
- 고친 뒤 `python3 -m unittest services.lp.tests.test_lp_program_service`와 회귀 검사를 돌리고 commit한다. 다음 LP 수집·발행 때 공개 화면에 반영된다.
