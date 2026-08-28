# 데이터 운영 모델

최종 수정: 2026-08-28 KST

이 문서는 DB와 공개 화면 사이의 책임선을 정의한다. 핵심 원칙은
`raw source -> canonical entity -> review/evidence -> public view -> static HTML`이다.

## 데이터 흐름

1. `Raw source` 원천 자료
   - 크롤러, 뉴스 원문, CSV, 금감원 자료, 공식 공고, PDF/HWP, 수동 seed URL.
   - 원문 보존이 목적이다. 공개 화면이 직접 읽지 않는다.

2. `Canonical entity` 표준 entity
   - GP, Fund, LP Institution, LP Commitment Program, Notice Event, Person, News.
   - 안정적인 ID와 표준 이름을 갖는다.

3. `Evidence / Review` 근거와 검토
   - 어떤 값이 어디서 왔는지, 공개 가능한지, 검토가 필요한지 저장한다.
   - 추정값은 공개 facts로 승격하지 않는다.

4. `Public read model` 공개 read model
   - 공개 화면이 읽는 DB view, JSON export, archive contract.
   - 내부 상태와 후보 데이터를 제거한 후의 결과다.

5. `Public surface` 공개 화면
   - LP/GP와 GitHub Pages mirror는 public read model을 HTML로 구운 결과다.
   - 공식 Brief 앱은 검증된 mirror archive를 Supabase public read model로 동기화한 뒤 Vercel에서 읽는 결과다.
   - 공식 GP Market/Directory는 FSS readiness를 통과한 `gp_public_snapshots`와 두 public page artifact를 Supabase에 atomically publish한 뒤 Vercel에서 읽는 결과다. GitHub Pages는 정적 backup mirror일 뿐 Vercel GP 화면의 runtime source가 아니다.
   - DB나 CSV가 바뀌어도 build, sync, deploy, public verification 전까지 공개 화면은 바뀌지 않는다.

## 상태값 분리 원칙

상태값을 한 필드에 섞지 않는다.

- 법적 유형: 자본시장법상 기관전용 사모집합투자기구 LP 적격 유형.
- 서비스 등급: 핵심 직접 LP, 정책펀드, OCIO pool, 후보.
- 공개 여부: 공개 화면에 올릴지 말지.
- 검토 상태: 후보, source-derived, verified, conflict, rejected.
- 사업 진행 상태: 공고중, 접수마감, 1차 선정, 선정완료, 취소, 히스토리.
- 출처 신뢰도: official, authoritative media, derived, weak.

예를 들어 `coverage_tier=candidate`는 서비스 운영 등급이고, 법적 LP 유형이나
공개 문구가 아니다. 공개 row에 등급 배지처럼 노출하지 않는다.

## LP 출자사업 모델

LP Notice는 공고 row 목록이 아니라 출자사업 lifecycle이다.

- `LP Institution`: 출자기관 또는 자금 주체.
- `Commitment Program`: 하나의 출자사업. 예: `은행권 중견기업 밸류업펀드 3차`.
- `Notice Event`: 공고, 정정, 서류심사, 1차 선정, 최종 선정, 취소.
- `Selected GP`: 사업에 연결된 선정 GP.
- `Source Evidence`: 공식 공고, 첨부문서, 기사, 원문 URL.

원칙은 `사업 1개 = 공개 카드 1개`다. 공고/서류심사/선정결과가 각각 카드로
쪼개지면 실패다. 새 이벤트가 들어오면 같은 사업 카드의 상태와 이력이 갱신되고,
최신 이벤트 기준으로 목록 위치가 올라간다.

현재 `lp_commitment_notice`는 notice event 성격이 강하다. 장기적으로는
`lp_commitment_program` 또는 동등한 canonical program layer를 추가하고,
기존 notice row는 event로 연결한다. 그 전까지 public lifecycle view에서
사업 단위 병합을 책임진다.

## 공개 노출 기준

공개 LP/Notice 데이터는 아래 조건을 통과해야 한다.

- 기관은 직접 GP/위탁운용사를 선정하거나, 사용자가 명시한 전략기관이어야 한다.
- OCIO/위임형 공적기금은 별도 pool에 두고 기본 LP 디렉토리에서 제외한다.
- PE/VC/대체 출자공고·선정 이력이 없는 기관은 후보 pool에 둔다.
- KIC, 수협, 캠코는 사용자 지정 전략기관 예외로 공개 유지한다.
- 후보 parser나 weak source에서 온 공고는 public-ready가 되기 전까지 숨긴다.
- 과거 마감일만 있는 row를 오늘의 모집중 공고처럼 표시하지 않는다.

## 공개 renderer 계약

Renderer는 public read model을 HTML로 표현하는 역할만 한다.

- 후보 row를 renderer에서 숨기는 방식만으로 공개 품질을 보장하지 않는다.
- DB view/export 단계에서 공개 가능 데이터만 남긴다.
- 화면에는 `candidate`, `monitor_status`, `confidence`, `source/evidence`,
  `자동 생성`, `검토 대기` 같은 내부 표현을 노출하지 않는다.
- 공개 숫자와 목록은 손으로 HTML에 박지 않는다. source data에서 읽어 빌드한다.

## 뉴스레터 Supabase read model

뉴스레터의 Vercel/Supabase 전환은 운영 DB 전체 이전이 아니라 public read model부터 시작한다.

- `newsletter_issues`: 발행일 단위 issue.
- `newsletter_articles`: URL 기준 canonical article.
- `newsletter_issue_articles`: 특정 issue에 노출되는 기사와 순서.
- `newsletter_article_tags`, `newsletter_article_entities`: 공개 가능한 태그와 GP/LP 링크.
- `newsletter_public_issue_articles`: Vercel 앱이 읽는 article-level public view.

GitHub Actions의 `Build newsletter mirror`가 기존 archive를 만들고 GitHub Pages mirror를 먼저 검증한 뒤, 별도 `Sync newsletter Supabase read model` workflow가 `sync_newsletter_supabase.py`로 이 read model을 갱신한다. 기본 동기화 범위는 Pages mirror와 맞춘 최근 30개 이슈다. Vercel app은 Supabase를 우선 읽고, Supabase가 비어 있거나 장애일 때는 기존 public `archive.json`으로 fallback한다. Mirror는 최신인데 Vercel/Supabase만 뒤처졌을 때는 mirror build가 아니라 `Sync newsletter Supabase read model` recovery workflow로 read model만 다시 맞춘다. 같은 발행일을 재동기화할 때는 기존 `newsletter_issue_articles` 연결을 먼저 지우고 archive 기준으로 다시 넣어야 한다. 그렇지 않으면 public mirror보다 Supabase/Vercel 기사 수가 많아지는 stale link가 생긴다.

Vercel archive 재구성은 두 층을 함께 읽어야 한다.

- `newsletter_issues`가 날짜 이동과 30일 archive skeleton의 source of truth다. 기사 0건인 날짜도 GitHub Pages archive와 동일하게 유지해야 한다.
- `newsletter_public_issue_articles`는 기사 content와 `rank`, `section_order`를 제공한다. 이 view만 읽으면 article inner join 때문에 빈 issue가 사라진다.
- `archive.json`은 발행일 순서, 섹션 순서, issue 안 기사 row 순서의 canonical source다. Vercel은 이 순서를 Supabase에서 복원해야 하며 독자적으로 재정렬하지 않는다.
- `section_order=0`은 정상적인 첫 섹션 값이다. `0`을 falsy 값으로 처리해 `999` 같은 fallback으로 바꾸면 Vercel과 GitHub Pages가 같은 기사라도 다른 순서로 보인다.

## GP Supabase public read model

FSS GP는 raw workbook, SQLite 분석 결과, 정적 renderer 산출물을 차례로 검증한 뒤
Supabase에서 하나의 published snapshot으로 전환한다.

- `gp_public_snapshots`: reporting period, 기준일, FSS source ID/SHA-256, 핵심 수치, publish status를 저장한다. Snapshot ID는 FSS 원본 SHA와 검증된 두 public page의 content SHA를 함께 반영하므로, 같은 분기라도 집계 또는 화면 결과가 바뀌면 새 snapshot을 발행한다.
- `gp_public_pages`: 하나의 snapshot에 속한 `market.html`, `gps.html`, source-backed GP의 `gp-<id>.html` public artifact와 content SHA-256을 저장한다.
- `publish_gp_public_snapshot(snapshot_id)`: `market.html`과 `gps.html`이 모두 존재할 때만 이전 published snapshot을 retire하고 새 snapshot을 publish한다. GP detail page는 함께 versioned 되어 Vercel의 `/gp-<id>.html` 경로에서 읽는다.
- Vercel은 anon key로 published snapshot만 읽고, HTML content SHA-256을 다시 확인한 뒤 응답한다. Supabase 장애 때에는 같은 serverless instance의 마지막 정상 snapshot만 짧게 유지하고, GitHub Pages HTML을 runtime fallback으로 사용하지 않는다.

이 모델은 HTML을 직접 수정하는 저장소가 아니다. GP renderer가 검증된 FSS public
view를 HTML로 만든 뒤, 검증된 artifact를 versioned read model로 발행하는 경로다.

GP detail은 근거 있는 회사 정보와 금감원 펀드 이력을 한 화면에 함께 보여준다. 펀드 행은
`fund_master`의 GP 연결을 기준으로 하며, 최신 운용 중 펀드뿐 아니라 과거에 확인된 펀드도
`최대 총약정액`, 설정일, 마지막 확인 분기와 함께 보존한다.

GP People은 `person_role`의 현재 GP 소속과 공식 출처가 함께 확인된 인물만 profile에 표시한다.
People 입력 CSV의 GP 숫자 ID는 FSS 재수집 때 달라질 수 있는 hint일 뿐이다. 적재 시에는
`current_gp_name` 또는 GP role의 `org_name`을 표준명으로 먼저 해석해 최신 `gp_house.gp_id`를
다시 연결하며, 이름을 찾을 수 없을 때만 입력 ID를 보존한다.
초기 공개 범위는 MBK profile의 `주요 인물` section이며, 전체 People 탭이나 출처 없는 인물
목록으로 확장하지 않는다. FSS rebuild는 People table을 포함하지 않으므로 `Deploy GP FSS market`
workflow가 public page build 전에 maintained People CSV를 SQLite에 다시 적재한다.

### GP profile evidence binding

`data/gp_profile_evidence.csv`는 홈페이지, 대표자, 법인명처럼 금감원 원천만으로 채울 수 없는
GP 프로필 필드의 canonical source다. CSV의 `source_gp_id`는 수집 실행마다 달라질 수 있는
ingestion-local 번호이므로 evidence binding key가 아니다. 적용과 재빌드 모두 `standard_gp_name`을
정규화한 `gp_name_norm`으로 정확히 한 GP에 연결한다. 이름이 없거나 중복되면 운영 warning으로 남기고
근거 CSV를 수정한다. 이 품질 경고만으로 금감원 통계 공개를 중단하지 않는다.

- `scripts/apply_gp_profile_evidence.py`는 FSS GP profile master를 만든 뒤 canonical evidence를
  적용하고, 기존 manual evidence를 CSV 기준으로 완전히 동기화한다.
- `scripts/check_gp_profile_evidence_ready.py`는 활성 CSV 행과 DB의 `manual_*` source가 일치하고,
  source-backed profile이 `FSS_NAME_ONLY`로 남지 않았는지를 확인한다. CI에서는 warning으로 기록하고
  다음 evidence 정리 작업에서 수정한다.
- `Deploy GP FSS market`은 `FSS ingest → approved alias merge → market analytics → GP master → evidence apply → GP master
  export → evidence readiness → People CSV import → public snapshot` 순서를 지켜야 한다. raw FSS 재수집만으로 source-backed
profile 필드가 사라지거나 다른 GP에 옮겨가면 안 된다.

## FSS / People canonical Supabase DB

금감원 원천을 해석한 GP·펀드·People 운영 DB의 기준 위치는 Supabase다. SQLite는 기존
분석기와 정적 renderer를 유지하는 동안에만 쓰는 임시 계산 파일이며, 공개 서비스의 영속
원본이 아니다.

- `fss_canonical_snapshots`와 `fss_*` 테이블은 한 FSS 기준일의 원천 문서, 표준 GP/펀드,
  펀드×분기 행, 이벤트, 검증된 GP 명칭 병합 이력을 함께 보관한다. 이전 분기 snapshot은
  삭제하지 않으며 새 분기만 새 snapshot으로 추가한다.
- `people_*` 테이블은 현재 People 입력과 출처를 보관한다. People은 FSS snapshot과 별도
  수명주기를 가지며 `people_data_state.fss_snapshot_id`로 어느 FSS 기준 GP에 연결됐는지만
  기록한다.
- `Deploy GP FSS market`은 **새 금감원 분기 자료가 확인됐을 때만** 실행한다. 이 경로는
  `원본 수집 → 정규화 → analytics → People 재연결 → canonical Supabase snapshot publish`
  순서다.
- `Publish GP and People from Supabase`는 People CSV, 프로필 evidence, 페이지 UI를 고칠 때
  실행한다. 이 경로에는 `fetch_fss_pef_sources.py`가 없으며, published canonical snapshot을
  새 임시 SQLite 파일에 복원해 기존 계산기와 renderer를 돌린 뒤 People과 GP public read
  model만 갱신한다.
- `gp_public_snapshots`는 위 canonical DB의 공개 HTML read model이다. canonical FSS data와
  public HTML artifact를 혼동하거나, 로컬 `db/private_equity.db` 파일을 Vercel runtime source로
  취급하지 않는다.

이 분리는 "People 수정 때문에 금감원 재수집"과 "개발자 로컬 SQLite가 서비스 기준"이라는
두 운영 오류를 막기 위한 계약이다.

### FSS 원본 보관

금감원 Excel은 `data/raw/fss_pef/`와 `data/source_registry_fss_pef.csv`에 Git으로
버전 관리한다. 현재 2015Q4~2025Q4 공식 원본은 이 저장소에 보관하며, GitHub Actions의
`Deploy GP FSS market`은 그 versioned 원본만으로 rebuild한다. 이 배포 workflow는 금감원
사이트에 접속하거나 다운로드하지 않는다.

새 분기 자료가 나왔을 때만 원본 수집 명령을 실행해 새 Excel과 registry 행을 추가하고,
raw SHA 검증 후 함께 commit한다. 그 commit을 기준으로 `Deploy GP FSS market`을 실행해
Supabase canonical snapshot과 공개 GP snapshot을 갱신한다. 금감원 게시판 장애는 이미
확보해 둔 분기 데이터의 재발행이나 People/프로필 갱신을 막지 않는다.

## GP ranking audit data pack

외부 배포 또는 투자자 검토용 GP 순위는 공개 Market HTML만으로 근거를 대신하지 않는다.
`scripts/build_gp_ranking_datapack.py`는 FSS readiness를 통과한 SQLite의 `gp_profile`과
정규화 analytics table을 읽는다. Excel은 웹 GP 서비스와 경쟁하는 별도 집계물이 아니라, 그 공개
DB 스냅샷과 원본 가공 이력을 검증하는 데이터팩이다. 생성 파일은 `exports/` 아래의 ignored artifact이며
모바일 전달용 검증 사본만 Vercel asset으로 versioned 한다.

- 최종 순위 명칭은 `YYYY년 말 기준 기관전용 PEF 누적 운용자산 순위 (금감원 공시 총약정액 기준)`이다. FSS 원천은 NAV/AUM이 아니라 펀드별 `총약정액(합계)`을 공시하므로 이 한계를 함께 표시한다.
- `analytics_gp_cumulative_fund_credit`은 `fund_gp_affiliation`의 펀드×업무집행사원 GP 관계별로 펀드의 최대 공시 총약정액을 전액 반영한다. 금감원 이력에 공동 GP가 기재된 펀드는 각 GP에 중복 반영하므로 누적 순위의 합계는 경제적 펀드 전체 총약정액보다 클 수 있다. `analytics_gp_cumulative_multi_gp_detail`은 복수 GP 펀드의 반영 내역을 보존한다.
- `누적 순위` 시트는 웹 GP 서비스가 읽는 `gp_profile` 누적 순위와 동일해야 한다. `펀드별 반영`과 `검증` 시트는 이 스냅샷을 펀드×GP 행 및 총약정액으로 대사한다. `기간별 요약`과 `기간별 GP 순위`는 기간별 대시보드 DB view를 보존한다.
- `원천 목록`, `GP 명칭 정리`, `원본 시트 목록`, 분기별 `Raw YYYYQ#` 시트는 금감원 파일명, URL, SHA-256, 검증된 alias rule, 원본 셀값을 보여준다. 2015Q4·2016Q1 legacy `.xls`는 파일 SHA와 보존 경로를 표시하며 표준 `.xlsx` parser의 행 단위 입력 대상은 아니다.

## 빌드 계약

기본 공개 통합 빌드는 active public services만 포함한다.

```bash
python3 scripts/build_site_bundle.py --services newsletter,lp,gp --date YYYY-MM-DD
```

뉴스레터 단독 발행은 LP/GP 실패와 분리한다.

```bash
python3 scripts/build_newsletter_bundle.py --date YYYY-MM-DD
```

Wiki는 재기획 전까지 루틴에서 제외한다. 필요할 때만 명시적으로 실행한다.

```bash
python3 scripts/build_site_bundle.py --services wiki --date YYYY-MM-DD
```

## 구조 안전장치

구조 정리와 public read model 계약은 코드 검사로 함께 고정한다.

- `scripts/check_architecture_contracts.py`는 LP/GP/Wiki가 newsletter-private module을 직접 import하지 않는지, newsletter workflow가 자기 책임 밖 작업을 하지 않는지, generated output이 source tracking에 들어오지 않는지 확인한다.
- `services/newsletter/src/newsletter_public_status.py`는 GitHub Pages mirror, Supabase sync, Vercel health, watchdog freshness 판단을 한 구현으로 묶는다.
- `scripts/check_public_frontend.py`는 공개 화면의 내부 용어 유출과 LP/GP table-like directory 구조를 확인한다.
- `services/gp/src/sync_gp_public_read_model.py`는 verified GP artifact를 Supabase snapshot으로 발행한다. 두 GP 페이지와 source hash가 모두 맞지 않으면 Vercel에 새 데이터를 공개하지 않는다.
- `scripts/check_gp_profile_evidence_ready.py`는 GP profile evidence가 현재 FSS rebuilt DB와 표준명 기준으로 일치하는지 검사한다. 프로필/alias 품질 문제는 warning과 정리 backlog로 남기며, 통계 snapshot 발행 자체를 막지 않는다.
- LP Notice는 계속 `사업 1개 = 공개 카드 1개`를 기준으로 삼고, 후보 source와 stale deadline은 public view/export 단계에서 제거한다.
