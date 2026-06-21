# 데이터 운영 모델

최종 수정: 2026-06-21 KST

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
- LP Notice는 계속 `사업 1개 = 공개 카드 1개`를 기준으로 삼고, 후보 source와 stale deadline은 public view/export 단계에서 제거한다.
