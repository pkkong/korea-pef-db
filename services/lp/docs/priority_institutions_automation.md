# 우정사업본부·교직원공제회·수출입은행 PE 출자사업 운영

2026-10-03 기준. 기존 한국성장금융과 같은 `services/lp/src/lp_program_service.py` 사업·일정·단계별 GP 화면 및 Supabase 공개 읽기 모델을 사용한다. 로그인 없이 `/admin/lp`에서 공개 원문과 새 단계 연결 후보를 읽는다.

## 수집·공개 경로

- `.github/workflows/collect-kgrowth-programs.yml`이 평일 09:20·15:20 KST에 한국성장금융과 아래 세 기관을 수집한다. GitHub 예약 실행은 정시를 보장하지 않는다.
- 수출입은행 공식 사이트는 GitHub의 Ubuntu 실행 서버에 공고 대신 차단 화면을 반환한다. 따라서 같은 workflow의 macOS 실행 서버에서 수은 원문·첨부를 수집하고, 그 실행의 증거 파일만 Ubuntu 게시 작업에 전달한다. 파일이 누락되거나 2시간 이상 오래되면 수은 수집 실패로 처리하며 기존 공개본을 유지한다.
- `collect_priority_lp_programs.py`가 기관별 수집 결과를 합친다. 각 수집기는 원문과 핵심 첨부의 SHA-256을 검토 기록과 대조하고 사업·일정·GP 명단을 다시 계산한다. `publish_lp_programs.py`는 수집기의 `programs` 필드를 공개 허가로 신뢰하지 않고 원문에서 재투영한다.
- 새 단계/정정/결과 공고는 `/admin/lp`에 사업 연결 후보로만 표시한다. 원문·첨부 변경이나 GP 명단 불일치는 해당 사업의 마지막 정상 공개본을 유지한다. 출처 장애는 다른 기관의 공개를 지우지 않되 workflow를 실패로 표시한다.
- 처음 수집된 사업의 출자규모·주목적·GP는 공식 PDF/HWP 원본을 사람이 대조해 검토 기록에 넣는다. 이후 동일 원문/첨부 해시일 때만 반복 발행한다. 새 결과의 GP는 무검토 자동 공개하지 않는다.

## 기관별 공식 범위

| 기관 | 공식 게시판 | 현재 사업 | 공개 단계 |
| --- | --- | --- | --- |
| 우정사업본부 | [우체국금융 예금 공지](https://www.kpasset.go.kr/board.es?mid=a10510000000&bid=0041) | 2026 국내 블라인드 PEF | 9/28 접수 마감, 공식 후속 GP 결과 없음 |
| 한국교직원공제회 | [공지사항](https://www.ktcu.or.kr/PPW-CSB-000101) | 2026 블라인드 PEF | 9/11 접수 마감, 공식 후속 GP 결과 없음 |
| 한국수출입은행 | [출자사업 공고](https://www.koreaexim.go.kr/HPHKBI039M01) | 상반기 공급망·지역주도성장, 하반기 글로벌성장 PE | 상반기 2건은 선정 결과 발표, 하반기 PE는 접수 14팀 |

수은 공급망은 접수 5팀→서류 4팀→결과 2팀이며 공동운용 2개사를 접수 1팀으로 센다. 지역주도성장은 15→12→6팀이다. 두 결과 공고는 각각 기금운용심의회 의결, 수은·재경부 승인을 거친 뒤 확정된다는 단서가 있으므로 승인 완료로 표시하지 않는다. 하반기 접수 PDF의 PE 14팀과 VC 21팀을 분리하며 VC는 이 사업에 연결하지 않는다. 수은 결과 PDF의 GP별 출자 예정액은 공고 수치의 합계와 대조한다.

## 검토 파일과 검사

- 우정: `data/koreapost_program_review.json`, `collect_koreapost_program.py`. 후속 결과가 생기면 `stages`에 공식 출처·해시·명단 근거를 검토해 추가한다.
- 교직원: `data/ktcu_program_review.json`, `collect_ktcu_program.py`. 게시글 첨부 다운로드 URL의 토큰은 매번 바뀌므로 파일명·내용 해시로 검증하며 게시글 URL을 원문 링크로 쓴다.
- 수은: `data/kexim_program_reviews.json`, `collect_kexim_programs.py`. PE 3개 사업의 모집/접수/서류/결과 원문을 사업별로 묶는다. PDF/HWP의 복잡한 표에서 GP를 런타임에 추측하지 않고 검토한 명단과 원본 파일 해시를 묶는다. macOS 수집 실패는 다른 기관의 검증 데이터를 지우지 않지만 workflow 실패로 드러난다.
- 테스트: `python3 -m unittest services.lp.tests.test_collect_ktcu_program services.lp.tests.test_collect_koreapost_program services.lp.tests.test_collect_kexim_programs services.lp.tests.test_lp_program_publish services.lp.tests.test_lp_review_preview` 및 `python3 scripts/check_architecture_contracts.py`.

기존 로컬 파일·생성 HTML·개인 DB는 운영 원본이 아니다. workflow의 수집 보고서와 Supabase 공개 실행 식별자, Vercel 상세 페이지가 일치해야 배포 완료로 기록한다.

## 운영 확인 (2026-10-03)

- [GitHub Actions 실행 37067600096, 재시도 2회차](https://github.com/pkkong/korea-pef-db/actions/runs/37067600096): 전체 성공. 첫 시도는 우정사업본부 공식 사이트의 일시적 응답 지연으로 실패했으며, 이미 공개된 자료는 유지됐다.
- 최종 수집 보고서: 교직원공제회 공고 1건·사업 1개, 우정사업본부 공고 1건·사업 1개, 수출입은행 공고 14건·사업 3개. 세 기관 모두 보류 0건, 소스 오류 0건.
- 수은 GP 단계: 공급망 펀드 접수 5→서류 4→선정 결과 발표 2팀, 지역주도성장 펀드 15→12→6팀, 하반기 글로벌성장 PE 접수 14팀. 앞의 두 사업은 승인 완료 전인 원문 표현대로 `선정 결과 발표` 상태다.
- Vercel `/samples/lp/index.html`과 다섯 상세 페이지가 모두 HTTP 200, 동일한 공개 실행 식별자 `a44b1bbb9cb18db8cf3e3d88`을 반환한다. `/admin/lp`도 로그인 없이 HTTP 200이다.
