# Korea PEF Intelligence 비전공자용 시스템 도식

작성일: 2026-06-10

이 문서는 `docs/non_developer_system_overview.md`를 그림 중심으로 다시 정리한 것이다.
각 그림은 하나의 레이어를 설명한다.

## 0. 네 개의 레이어가 겹쳐진 서비스

```mermaid
flowchart TB
    A["1. 서비스맵<br/>사용자가 보는 메뉴와 화면"] --> B["2. 데이터 흐름도<br/>원천자료가 화면이 되는 과정"]
    B --> C["3. DB 설계<br/>서비스가 기억하는 주요 대상과 관계"]
    C --> D["4. 운영 워크플로우<br/>매일 수집, 검토, 빌드, 배포하는 순서"]
    D --> E["완성된 서비스<br/>공개 화면 + 내부 운영 + 반복 가능한 데이터 갱신"]
```

읽는 법:

| 레이어 | 핵심 질문 |
| --- | --- |
| 서비스맵 | 사용자는 어디로 들어가서 무엇을 보는가? |
| 데이터 흐름도 | 데이터는 어디서 들어와서 어디로 나가는가? |
| DB 설계 | 서비스가 무엇을 기억하고 무엇끼리 연결하는가? |
| 운영 워크플로우 | 사람이 어떤 순서로 서비스를 굴리는가? |

## 1. 서비스맵

```mermaid
flowchart TB
    User["외부 사용자"] --> Brief["브리프<br/>오늘의 PEF 뉴스"]
    User --> LP["LP<br/>출자기관, 출자공고, 선정 GP"]
    User --> GP["GP<br/>운용사, 펀드, 인물, 뉴스"]

    Operator["내부 운영자"] --> Dashboard["dashboard<br/>운영 콘솔"]
    Operator --> Exports["exports<br/>검토용 CSV/엑셀"]
    Operator --> Docs["docs<br/>운영 규칙과 설계 문서"]

    Brief --> Public["newsletter deploy site<br/>공개 정적 페이지"]
    LP --> Public
    GP --> Public
```

핵심:

| 구역 | 의미 |
| --- | --- |
| `services/newsletter/deploy/site/` | GitHub Pages로 배포되는 공개 사이트 bundle |
| `services/newsletter/deploy/site/` | GitHub Pages로 배포되는 공개 사이트 bundle |
| `dashboard/` | 내부 운영자가 보는 콘솔 |
| `exports/` | 사람이 검토하는 작업 파일 |

## 2. 데이터 흐름도

```mermaid
flowchart LR
    subgraph Sources["원천자료"]
        FSS["FSS PEF 엑셀"]
        News["뉴스 기사"]
        LPNotice["LP 공식 공고"]
        CSV["수동 CSV<br/>GP 별칭, LP 기관, 인물, 근거"]
    end

    subgraph Collect["수집/정제"]
        Scripts["Python scripts"]
        Newsletter["services/newsletter"]
        LPService["services/lp"]
        Shared["services/shared"]
    end

    subgraph Store["저장"]
        DB["db/private_equity.db"]
        Raw["data/raw"]
        Maintained["data/*.csv"]
    end

    subgraph Outputs["산출물"]
        ExportFiles["exports/*.csv / *.xlsx"]
        DashboardJSON["dashboard/data/dashboard_data.json"]
        PublicJSON["public read model / deploy JSON"]
    end

    subgraph Screens["화면"]
        Dashboard["내부 dashboard"]
        Public["공개 public 사이트"]
        NewsletterSite["뉴스레터 GitHub Pages"]
    end

    FSS --> Scripts
    News --> Newsletter
    LPNotice --> LPService
    CSV --> Scripts
    CSV --> Newsletter
    CSV --> LPService

    Scripts --> DB
    Newsletter --> DB
    LPService --> DB
    Scripts --> Raw
    Scripts --> Maintained

    DB --> ExportFiles
    DB --> DashboardJSON
    DB --> PublicJSON
    ExportFiles --> DashboardJSON
    DashboardJSON --> PublicJSON

    DashboardJSON --> Dashboard
    PublicJSON --> Public
    PublicJSON --> NewsletterSite
```

핵심:

```text
수집 완료 = 공개 완료가 아니다.
DB 저장, 산출물 생성, 정적 페이지 빌드, 배포까지 끝나야 사용자가 본다.
```

## 3. DB 주요 엔티티 관계도

```mermaid
erDiagram
    GP ||--o{ FUND : manages
    GP ||--o{ PERSON_ROLE : has_people
    GP ||--o{ NEWS_ENTITY_LINK : mentioned_in_news
    GP ||--o{ LP_NOTICE_GP_LINK : selected_by_lp

    FUND ||--o{ FUND_PERIOD_SNAPSHOT : has_quarterly_snapshot
    FUND ||--o{ FUND_EVENT : has_event
    REPORTING_PERIOD ||--o{ FUND_PERIOD_SNAPSHOT : defines_period
    SOURCE_DOCUMENT ||--o{ FUND_PERIOD_SNAPSHOT : source_of

    LP ||--o{ LP_PROFILE_FACT : has_fact
    LP ||--o{ LP_COMMITMENT_NOTICE : publishes_notice
    LP_COMMITMENT_NOTICE ||--o{ LP_NOTICE_GP_LINK : links_selected_gp
    LP_COMMITMENT_NOTICE ||--o{ LP_NOTICE_NEWS_LINK : links_news

    NEWS_DOCUMENT ||--o{ NEWS_TAG : has_tag
    NEWS_DOCUMENT ||--o{ NEWS_ENTITY_LINK : links_entity
    NEWS_DOCUMENT ||--o{ LP_NOTICE_NEWS_LINK : supports_notice
    NEWS_DOCUMENT ||--o{ PERSON_NEWS_LINK : mentions_person

    PERSON ||--o{ PERSON_ROLE : has_role
    PERSON ||--o{ PERSON_EDUCATION : has_education
    PERSON ||--o{ PERSON_SOURCE : has_source
    PERSON ||--o{ PERSON_NEWS_LINK : linked_news
```

읽는 법:

| 엔티티 | 쉬운 의미 |
| --- | --- |
| `GP` | PEF 운용사 |
| `FUND` | PEF 펀드 |
| `LP` | 출자기관 |
| `LP_COMMITMENT_NOTICE` | 출자공고, 선정 결과, 변경 공고 |
| `NEWS_DOCUMENT` | 뉴스 기사 |
| `PERSON` | 운용사/기관 관련 인물 |
| `SOURCE_DOCUMENT` | FSS 원천자료 같은 공식 문서 |
| `REPORTING_PERIOD` | 기준 분기 |

핵심:

```text
이 서비스의 가치는 개별 표가 아니라 연결에 있다.
GP가 펀드, 뉴스, 인물, LP 선정 결과와 연결될수록 데이터 상품이 된다.
```

## 4. 운영 워크플로우

```mermaid
flowchart TB
    Start["운영 시작"] --> NewsFlow["뉴스레터 운영"]
    Start --> LPFlow["LP 공고 모니터링"]
    Start --> FSSFlow["FSS/시장 데이터 갱신"]
    Start --> ProfileFlow["GP/LP/People 프로필 보강"]

    NewsFlow --> NewsCollect["뉴스 수집"]
    NewsCollect --> NewsReview["리뷰 큐 검토"]
    NewsReview --> NewsFinal["최종 브리프 생성"]
    NewsFinal --> NewsDeploy["뉴스레터 배포"]

    LPFlow --> LPCollect["공식 공고 수집"]
    LPCollect --> LPNormalize["사업명, 마감일, 금액, 선정 GP 정규화"]
    LPNormalize --> LPExport["LP 공고 산출물 생성"]

    FSSFlow --> FSSFetch["FSS 원천 파일 확보"]
    FSSFetch --> FSSIngest["DB 적재"]
    FSSIngest --> MasterBuild["GP/펀드 마스터 생성"]
    MasterBuild --> Analytics["분석/품질 리포트 생성"]

    ProfileFlow --> Evidence["출처 기반 근거 입력"]
    Evidence --> Apply["DB 반영"]
    Apply --> ProfileExport["프로필 산출물 생성"]

    NewsDeploy --> PublicBuild["공개 사이트 빌드"]
    LPExport --> PublicBuild
    Analytics --> PublicBuild
    ProfileExport --> PublicBuild

    PublicBuild --> Verify["공개 화면 확인"]
    Verify --> Done["사용자가 최신 화면을 봄"]
```

핵심:

| 단계 | 의미 |
| --- | --- |
| 수집 | 원천자료를 가져온다 |
| 정제 | 이름, 날짜, 금액, URL을 맞춘다 |
| 검토 | 사람이 포함/제외, 출처, 품질을 확인한다 |
| DB 반영 | 반복 가능한 저장소에 넣는다 |
| 산출물 생성 | CSV, JSON, HTML을 만든다 |
| 빌드 | 공개 화면용 파일을 다시 만든다 |
| 배포 | 사용자가 보는 위치에 올린다 |
| 확인 | 공개 화면에 이상이 없는지 본다 |

## 5. 정적 페이지 관점의 공개 구조

```mermaid
flowchart LR
    DB["db/private_equity.db"] --> BuildData["데이터 빌드"]
    BuildData --> ServiceJSON["public read model / deploy JSON"]
    ServiceJSON --> HTML["services/newsletter/deploy/site/*.html"]
    HTML --> Browser["사용자 브라우저"]

    StaticAssets["CSS / JS / 이미지"] --> Browser
```

정적 페이지는 "미리 만들어 둔 파일을 사용자가 보는 방식"이다.

```text
DB가 바뀌어도 public 화면이 자동으로 바뀌지 않는다.
service_data.json과 HTML을 다시 만들고 배포해야 화면이 바뀐다.
```

이 서비스는 HTML 파일을 수천 개 만드는 방식보다는, 비교적 적은 HTML과 큰 JSON 데이터를 조합하는 방식에 가깝다.

## 6. 완성도 지도

```mermaid
flowchart TB
    subgraph High["완성도 높음"]
        PublicNav["공개 메뉴 구조"]
        Newsletter["뉴스레터 수집/리뷰/발행"]
    end

    subgraph MediumHigh["중상"]
        FSSData["FSS 기반 GP/Fund 데이터"]
        LPNotice["LP 공고 모니터"]
    end

    subgraph Medium["중간"]
        GPProfile["GP 프로필"]
        PeopleDB["People DB"]
        Wiki["Wiki<br/>보류"]
        Dashboard["내부 운영 콘솔"]
    end

    subgraph Early["초기/미구축"]
        DealDB["Deal DB"]
        ReportLibrary["Report Library"]
        FullAutomation["완전 자동 운영 검증"]
    end

    High --> MediumHigh
    MediumHigh --> Medium
    Medium --> Early
```

핵심:

| 상태 | 해석 |
| --- | --- |
| 완성도 높음 | 이미 반복 운영 가능한 핵심 구조가 있음 |
| 중상 | MVP가 있고 품질 보강이 필요함 |
| 중간 | 기반은 있으나 출처, 화면, 연결 품질을 더 쌓아야 함 |
| 초기/미구축 | 장기 제품 가치가 크지만 아직 본격 설계 또는 구현 전 |

## 7. 하나의 예시로 보는 전체 연결

예시 질문:

```text
"MBK파트너스는 어떤 운용사이고, 어떤 펀드와 뉴스, LP 선정 결과가 연결되어 있나?"
```

서비스가 이 질문에 답하는 방식:

```mermaid
flowchart TB
    Question["사용자 질문<br/>이 GP는 무엇인가?"] --> GPPage["GP 상세 화면"]

    GPPage --> GPDB["GP DB<br/>표준 운용사 정보"]
    GPPage --> FundDB["Fund DB<br/>운용 펀드와 약정액 기준 지표"]
    GPPage --> NewsDB["News DB<br/>관련 기사"]
    GPPage --> PeopleDB["People DB<br/>관련 인물"]
    GPPage --> LPDB["LP DB<br/>선정 GP 이력"]

    GPDB --> Sources["공식 출처 / FSS / 뉴스 / CSV 근거"]
    FundDB --> Sources
    NewsDB --> Sources
    PeopleDB --> Sources
    LPDB --> Sources

    Sources --> Build["public 데이터 빌드"]
    Build --> Public["사용자가 보는 정적 페이지"]
```

이 예시가 이 서비스의 핵심이다.

```text
단순히 GP 이름 하나를 보여주는 것이 아니라,
그 GP와 연결된 펀드, 뉴스, 인물, LP 선정 이력을 하나의 프로필로 묶는 것이 목표다.
```

## 한 장 요약

```mermaid
flowchart TB
    Sources["원천자료<br/>FSS, 뉴스, LP 공고, CSV"] --> Pipeline["파이프라인<br/>수집, 정제, 검토"]
    Pipeline --> DB["DB<br/>GP, Fund, LP, News, People"]
    DB --> Outputs["산출물<br/>exports, dashboard JSON, public JSON"]
    Outputs --> Screens["화면<br/>브리프, LP, GP, dashboard<br/>Wiki는 보류"]
    Screens --> Users["사용자<br/>외부 사용자와 내부 운영자"]

    Users --> Feedback["검토, 보강, 운영 판단"]
    Feedback --> Sources
```

최종 결론:

```text
이 서비스는 원천자료를 모으는 도구가 아니라,
원천자료를 엔티티와 관계로 바꿔서 반복적으로 공개 가능한 데이터 상품으로 만드는 시스템이다.
```
