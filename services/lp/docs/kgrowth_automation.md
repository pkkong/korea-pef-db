# 한국성장금융 수집 운영

## 범위

한국성장금융 공식 출자사업 게시판 최신 목록 1페이지와 검토된 밸류업펀드3차 공고 1047·1075·1090·1100을 추적한다. 과거 전체 공고 백필이 아니다. 최신목록 밖으로 빠진 미검토 공고는 별도 검토/추적대상 등록이 필요하다.

수집 workflow `Collect Korea Growth LP programs`는 평일 09:20·15:20 KST 실행. GitHub schedule 지연 가능. 수동 workflow_dispatch 가능.

현재 자동 반영 범위는 검토된 밸류업3차의 공식본문 재검증, 접수17팀·숏리스트6팀·최종3사 명단 대조와 페이지 발행이다. 신규사업 자동분류/신규GP명부 생성/첨부 투자조건 자유추출은 구현되지 않았다. 신규 12건 같은 미검토 공고는 검토대기로 보관하며 자동 공개하지 않는다.

## 데이터와 발행

- `lp_program_private.collection_runs`: 실행별 수집/검토보고서.
- `documents`: URL과 문서지문별 원문 근거.
- `program_state`: 기존 5사업 데이터와 승인된 원문지문, 렌더링된 페이지. 한 트랜잭션으로 교체.
- 공개는 `public.lp_program_page` RPC를 통한 HTML만. 원문/검토대기 데이터 접근권한은 공개하지 않는다.
- Vercel `/samples/lp/`는 Supabase를 읽는다. DB 읽기실패는503, 없는페이지404. 옛배포사본으로 조용히되돌리지 않는다.
- 수집실패·빈결과·명단불일치는 발행중단. 본문/첨부변경은 requires_review로 기존사업보존. 승인된 fingerprint를 DBbaseline으로 재사용해 다음실행에서 변경이 자동승인되지 않게 한다.

## 검수와 한계

수집보고서는 GitHub Actions artifact `kgrowth-collection` 및 DB collection_runs에서 확인. 변경원문 검수 후 명시적으로 승인된지문/사업자료를 갱신하는 관리UI는 아직 없다. 정정공고의 기존사업 영향은 수동검토 대상이다. 다른4기관 일정상태는 샘플시점이므로 자동최신으로 설명하지 않는다.

검사:
`python3 -m unittest services.lp.tests.test_kgrowth_collection services.lp.tests.test_lp_program_publish services.lp.tests.test_lp_program_service services.newsletter.web.tests.test_lp_program_data`


## 2026-09-28 운영 반영 확인

- 소스 `57617d3`; Vercel 배포 `36394544005` 성공.
- 실제 서버 수집 `36394189210`, `36394584105` 모두 성공. 각 16건 수집, 12건 검토 대기. 두 번째 실행에서 최초 원문 지문 유지 확인.
- Vercel 공개 응답은 `X-LP-Data-Source: supabase`. 재배포 없이 수집 실행 식별자가 `761ec3f4196de45d1532a877`에서 `ebb947ad47574dafed68aedd`로 바뀐 것을 확인했다.
- 공개 목록 및 5개 상세 HTTP 200. 한국성장금융 접수 17팀·1차 통과 6팀·최종 선정 3개사 표시, 모바일 320/390px 가로 넘침 없음 및 접수 명단 펼침 확인.
- 평일 09:20·15:20 예약 실행 등록. 실제 검증은 수동 실행 2회이며, 예약 시각의 실행은 GitHub 스케줄에 의존한다.
- 한국성장금융 기존 검토 사업 1건의 수집·DB·공개 화면 연결까지 완료. 신규 사업 자동 구조화/검수 승인 화면/다른 4기관 자동 수집은 미완료다.
