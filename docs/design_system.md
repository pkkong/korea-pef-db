# 공개 디자인 시스템

최종 수정: 2026-06-21 KST

이 문서는 공개 서비스의 UX/UI 기준이다. 코드가 이 문서와 다르면 코드 또는 문서를 바로 맞춘다. 사용자가 직접 확인할 때는 “브리프, LP, GP가 한 제품처럼 보이는지”, “공개 화면에 내부 운영 표현이 없는지”, “모바일에서도 표형 row가 무너지지 않는지”를 먼저 본다.

## 제품 방향

공개 서비스는 마케팅 사이트나 내부 운영 대시보드가 아니라 기관 데이터 디렉토리처럼 보여야 한다. 기준은 혁신의숲 같은 밀도다. 핵심은 검색 가능한 목록, 표에 가까운 row, 출처가 있는 숫자, 절제된 타이포그래피다.

뉴스레터 화면이 현재 기준 구현이다. LP, GP, Wiki 화면은 같은 shell, typography, row density, 40px 원형 로고 슬롯, 하단 메뉴 체계를 따라야 한다.

## 공통 계약

- 공개 서비스는 하나의 제품처럼 보여야 한다. Brief, LP, GP, Wiki가 서로 다른 앱처럼 보이면 실패다.
- 모바일 우선으로 만든다. PC는 모바일 구조를 넓히는 방식이어야 하며 별도 대시보드처럼 바뀌면 안 된다.
- 공개 화면에는 운영자용 표현, source field 이름, 생성 과정 설명, 검토 상태를 노출하지 않는다.
- 흰 배경, 중립 색상, 얇은 border, 구조화된 row를 우선한다. shadow, heavy card, 큰 hero block은 기본 선택지가 아니다.
- GP와 LP는 데이터 디렉토리다. 기본 형태는 카드 묶음이 아니라 table-like row다.
- Wiki는 문서 서비스다. 기본 형태는 본문, 목차, anchor, 관련 참조 링크다.

## 화면 유형

새 화면을 만들거나 바꾸기 전에 아래 유형 중 하나를 먼저 고른다.

- 기사 목록: 매일/주간 브리프 기사용. 평평한 row, section label, 언론사 metadata, 절제된 tag, 원형 언론사 아이콘을 쓴다. 일반 기사 목록에는 table column이나 card grid를 쓰지 않는다.
- 디렉토리 목록: GP/LP 목록용. 비교 가능한 column, 정렬·필터, 원형 CI/logo 슬롯, compact numeric fact를 가진 table-like row를 쓴다. 내부 filter 값에 가까운 entity type badge는 이름 아래에 노출하지 않는다.
- 프로필 상세: GP/LP entity 상세용. identity header, fact matrix, history/news/connection table, source link section, 조용한 typography를 쓴다.
- 공고 row-card: LP 공식 공고처럼 제목, 마감일, 기관, 첨부, source link가 길고 중요한 workflow용. card를 쓰더라도 평평하고 실무적으로 보여야 하며 marketing card처럼 만들지 않는다.
- 문서: Wiki용. 제목, 본문, 목차, 내부 anchor, 법령·규정 link, source reference를 쓴다. 표는 원천 내용이 실제로 표형일 때만 쓴다.

서로 다른 화면 유형이 섞이면 한 화면에 억지로 넣지 말고 tab이나 page를 나눈다. 예를 들어 LP 디렉토리와 LP 공식 공고는 같은 LP 영역이지만 다른 화면 유형이다.

## 데이터 반영 방식

공개 서비스는 현재 정적 생성 사이트다. DB, CSV, exports, crawler output이 원천 데이터이고, 공개 HTML은 build 때 만들어진다.

- crawler, DB import, CSV 수정은 source data만 바꾼다.
- 공개 웹사이트는 site builder가 정적 HTML을 다시 만들고 GitHub Pages 또는 Vercel/Supabase 경로가 검증된 뒤에만 바뀐다.
- article count, LP notice count, GP count, AUM/commitment metric, profile count 같은 숫자는 renderer에 손으로 박지 않는다. build 때 source data에서 읽어 생성 HTML에 반영한다.
- generated public HTML을 직접 고쳐 숫자를 맞추지 않는다. source data 또는 renderer를 고치고, rebuild, verify, publish한다.
- 비개발자에게 freshness를 설명할 때는 “DB 업데이트는 재료이고, build/deploy가 웹사이트에 올리는 단계”라고 설명한다.

## 내비게이션

- 전역 하단 메뉴는 모든 공개 화면에서 `브리프 / LP / GP` 순서로 고정한다.
- Wiki는 사용자가 다시 기획하기 전까지 공개 내비게이션에 보여주지 않는다.
- 공개 content 위에 top-level service tab을 따로 만들지 않는다.
- 페이지 안의 local control은 있어도 현재 화면 안에서만 작동해야 한다.
- 모바일과 PC 모두 같은 하단 메뉴 체계를 쓴다.
- `저장`은 뉴스, LP profile, GP profile, Wiki document 전체에서 동작하기 전까지 전역 tab으로 노출하지 않는다. 뉴스 전용 bookmark control도 공개 뉴스레터에 보여주지 않는다.

## 색과 시각 규칙

- Page background: `#ffffff`
- Muted separator background: `#f7f7f8`
- Surface: `#ffffff`
- Primary text: `#171717`
- Secondary text: `#737373`
- Tertiary text: `#a3a3a3`
- Border: `#e5e5e5`
- Strong border: `#d4d4d4`
- Accent: 상태 의미가 있는 경우가 아니면 black/neutral

shadow보다 border와 whitespace를 먼저 쓴다. 장식용 gradient, 큰 hero, 중첩 card, card-heavy directory 화면은 피한다.

## 공통 토큰

- CSS variables: `--bg #f7f7f8`, `--surface #ffffff`, `--surface-muted #f7f7f8`, `--text #171717`, `--secondary #737373`, `--tertiary #a3a3a3`, `--separator #e5e5e5`, `--accent #171717`.
- 모바일 page gutter: `14-16px`.
- PC reading/list width: `860-900px`.
- Row divider: `1px solid #e5e5e5` 또는 밀도가 높을 때 더 낮은 opacity.
- Section band: full-bleed `#f7f7f8`, 높이 약 `8px`, compact vertical spacing.
- List icon/logo slot: 원형 `40px`, multiline row에서는 top-aligned.
- Bottom nav: fixed, 모든 화면 동일 순서, label 약 `11-12px`, icon 약 `18-23px`, active state는 neutral.

## 타이포그래피

- Font stack: `Pretendard`, `Pretendard Variable`, `Noto Sans KR`, `Apple SD Gothic Neo`, `Malgun Gothic`, `system-ui`, `sans-serif`.
- viewport width로 font-size를 스케일하지 않는다.
- letter spacing은 `0`이다.
- 모바일 product/page title은 보통 21-28px, PC의 진짜 page title만 32-38px를 쓴다.
- 서비스 tab은 보통 13px.
- Section label은 보통 12.5-14.5px.
- Data label, count, tag, metadata는 보통 11-13px.
- 디렉토리 row 제목은 보통 15-16px.
- 뉴스레터 기사 제목은 약 15px medium-bold가 기준이다. hero 크기로 키우지 않는다.

## 공개 화면 틀

- Header는 필요한 utility icon만 둔 compact title row를 쓴다.
- Search는 별도 card나 floating panel이 아니라 header 안에서 열린다.
- Page-local tab은 얇은 neutral baseline과 black active underline을 가진 text tab을 쓴다.
- Bottom nav는 유일한 전역 서비스 navigation이며 `브리프 / LP / GP` 순서를 유지한다.
- PC에서도 navigation hierarchy는 같다. 더 넓은 화면이라고 전혀 다른 product shell로 바꾸지 않는다.

## 디렉토리 row 규칙

- GP와 LP 디렉토리는 table-like row여야 한다.
- PC에서는 비교 가능한 column이 한 row 안에 보여야 한다.
- 모바일에서는 compact row로 줄일 수 있지만 promotional card stack처럼 보이면 안 된다.
- 모바일에서 가로 스크롤에 의존하지 않는다. 모든 column이 안 들어가면 가장 중요한 column을 남긴다.
- Row에는 원형 CI/logo slot을 쓴다. 검증된 public logo가 없으면 같은 크기의 절제된 monogram fallback을 쓴다.
- 주 row action은 detail, source, compare, connected record처럼 목적이 분명해야 한다.
- 공개 row에 내부 enum이나 pipeline 용어를 보여주지 않는다.
- LP/GP 이름 cell 아래에 `ownership_type`, `public/private` 같은 운영 필드를 노출하지 않는다. 필요한 경우 filter로만 쓴다.
- 전체 row가 detail link라면 `상세 프로필` 같은 반복 action text를 넣지 않는다.
- rank, category, source 정보를 같은 row 안에서 여러 번 반복하지 않는다.

## 뉴스레터 기준 패턴

- Background는 white page background다.
- Content는 gray card container가 아니라 flat grouped list다.
- 모바일 side padding은 14-16px다.
- PC reading width는 약 860-900px다.
- Header는 compact title row이며 search는 header 안에서 열린다.
- Top tabs `Daily / Weekly / 출자공고`는 예정 기능 placeholder로 유지할 수 있다. 비활성 tab은 낮은 대비의 text tab이어야 한다.
- Date control은 compact centered pill이다. 장식용 가로선은 쓰지 않는다.
- Section label은 보이되 절제한다. category 구분이 약하면 card wrapper보다 section label과 조용한 full-bleed band를 쓴다.
- Article title은 약 15px medium-bold, 2-line clamp가 기준이다.
- Publisher/meta는 title보다 시각 위계를 낮춘다.
- Publisher icon은 원형 40px slot이며 article row 위쪽에 맞춘다.
- 공개 뉴스레터 목록에는 section count badge를 노출하지 않는다.
- Article-row bookmark는 공개 목록에 보여주지 않는다. saved items가 cross-service feature가 되기 전까지 right-side save icon을 피한다.

## 로고와 브랜드 자산

- 뉴스 언론사, LP, GP 로고 slot은 모두 같은 40px 원형 규칙을 쓴다.
- 로고 slot은 원형 container, 얇은 neutral border, 중앙 정렬된 brand mark가 기준이다.
- asset 우선순위는 공식 compact CI/logo, 그다음 명확히 brand-owned이고 시각적으로 쓸 만한 official touch/app icon이다.
- Google S2, DuckDuckGo 같은 generic favicon service나 임의 favicon으로 coverage를 가짜로 채우지 않는다.
- 검증 asset이 없으면 깨끗한 monogram fallback을 쓴다.
- logo-backed slot은 InnoForest/TheVC directory row처럼 기본 흰 원형 slot을 쓴다. NAVER, 한국경제처럼 단색 mark가 명확한 경우만 domain-based curated background를 쓴다.
- 40px 안에서 공식 wordmark가 너무 얇게 보여 읽히지 않으면 더 나은 공식 symbol을 쓰거나 monogram fallback으로 둔다.
- cross-service renderer는 `services/shared/src/brand_assets.py`를 import한다. curated registry가 역사적으로 newsletter 내부에 있더라도 LP/GP/Wiki가 `services.newsletter.src.*`로 직접 들어가면 안 된다.
- static build는 brand mark를 `assets/brand-marks`에 cache해 CORS, hotlinking, HTTP-only source가 공개 UI에서 깨진 원으로 보이지 않게 한다.

## LP와 GP 적용 기준

- LP/GP 디렉토리는 뉴스레터 기준의 density, typography, neutral palette, row rhythm을 따른다.
- LP/GP list row는 이름, 최신/순위 signal, 핵심 금액·개수, 관련 연결을 비교 가능한 row로 보여준다.
- News, LP, GP list row는 같은 40px 원형 logo slot을 쓴다. Detail hero logo는 더 커도 되지만 muted container, neutral border, monogram fallback 행동은 같아야 한다.
- Detail page는 fact matrix, history/news table, source-linked section, quiet typography를 쓴다.
- LP detail 순서는 identity header, 기본 기관 정보, 투자 현황, 공식 공고, 관련 GP, 관련 뉴스, peer comparison, source/reference link다.
- LP detail 상단에 `자료 성격`, `프로필 항목`, source-status label 같은 collection coverage를 노출하지 않는다. source link와 좁은 caveat는 하단 `자료` 영역에 둔다.
- LP detail header는 “기본 정보와 뉴스를 정리합니다” 같은 generic 설명문을 쓰지 않는다. 기관명, compact identity fact, tab, 즉시 비교 가능한 data section을 보여준다.
- LP notice는 LP 서비스의 주요 workflow 화면이다. current/open notices, selected results, historical notices를 마감일, 금액, 기관, source, attachment와 함께 묶는다.
- GP directory row는 compact해야 한다. 원형 logo, GP명, 대표자 또는 홈페이지, rank/commitment fact, news/LP connection count 정도가 기준이다.
- GP detail page는 모든 source-backed GP에 하나의 profile layout을 적용한다. identity, 4개 핵심 수치, 회사 정보, 주요 인물, 금감원 확인 펀드, LP/기사 연결 순서로 조용하게 구성한다. 특정 GP만 별도 시안으로 남기지 않는다.
- GP directory는 `기준일`, `집계 기준`, `정렬기준` 세 가지 control만 유지한다. 제목에 별도 전체 수를 박지 않고, 현재 조건의 결과 수를 control 위에 표시한다.

## GP 공개 화면 금지 표현

GP 공개 화면에는 `AI-generated`, `operator`, `proxy`, `research`, `verification`, `source/evidence`, `상위 프로필`, `자료 확인` 같은 내부 표현을 노출하지 않는다. 기사 제목이나 industry term으로 AI가 쓰인 경우는 예외다. 공개 label은 `운용 현황`, `약정액 기준`, `출자 연결`, `관련 뉴스`처럼 사용자가 이해하는 표현을 쓴다.

GP directory filter는 짧고 사용자 관점이어야 한다. `전체`, `운용 중`, `뉴스`, `딜`, `출자`를 우선하고 build coverage, verification state, profile-page availability를 visible filter로 노출하지 않는다.

## Wiki 적용 기준

- Wiki는 OpenAI Help/Google Help 같은 documentation 구조를 따른다. 제목, 짧은 subtitle, 본문, sidebar 또는 drawer 목차, 내부 anchor, 관련 reference를 쓴다.
- Wiki를 card gallery, PDF link page, 대화형 summary로 만들지 않는다.
- 표는 underlying content가 실제로 tabular할 때만 쓴다.
- body typography는 data directory보다 차분해야 한다. 과한 bold와 과한 horizontal rule을 피한다.

## 회귀 체크리스트

- Bottom nav label이 정확히 `브리프 / LP / GP`다.
- Newsletter는 flat list, circular publisher icon, restrained section label, 과하지 않은 article title을 유지한다.
- LP/GP list page는 table-like row 구조를 유지하고 card-heavy layout으로 돌아가지 않는다.
- 모바일 390px 안팎에서 이상한 horizontal overflow가 없다.
- PC 1280px 안팎에서 reading list가 의도한 column width 이상으로 늘어나지 않는다.
- 공개 페이지에 `관리자`, `operator`, `자동 생성`, `source/evidence`, `AUM proxy` 같은 내부 표현이 없다. 단, 원천 기사 제목에 들어간 경우는 예외다.
- 데이터가 비어 있어도 LP/GP/Market 화면 shell은 유지된다.

## 검증

공개 frontend를 바꾸기 전에 아래 검사를 실행한다.

```bash
python3 scripts/check_public_frontend.py
```

frontend 작업은 source renderer 수정, generated site rebuild, 위 checker 통과, 390px/1280px 화면 확인까지 끝나야 완료다.

GitHub Pages에 publish한 뒤에는 공개 URL 기준 smoke check를 실행한다.

```bash
python3 scripts/check_public_frontend.py --base-url https://pkkong.github.io/kpef-newsletter/
```
