# Agent Operating Briefs

## 목적

이 문서는 뉴스레터 담당 에이전트와 People DB 담당 에이전트가 같은 제품 원칙, 같은 키, 같은 산출물 경로를 기준으로 움직이게 하는 운영 지시서다. 두 담당은 각각 독립된 작업을 하되, 뉴스가 GP/인물 DB 갱신 신호가 되고 People DB가 GP/뉴스 맥락 엔진이 되도록 매일 연결 상태를 유지한다.

## Codex 팀 운영 원칙

- 프로젝트 작업은 기본적으로 팀 단위로 진행한다. 메인 Codex는 방향, 통합, 최종 판단, 사용자 커뮤니케이션을 맡는다.
- 작업이 읽기 조사, 구현, 검증, 문서화로 나뉠 수 있으면 서브에이전트에 역할을 나누어 병렬로 맡긴다.
- 서브에이전트 기본 역할은 `Explorer`(읽기 조사), `Worker`(명확한 파일 범위의 구현), `Verifier`(테스트·배포·공개 사이트 확인), `Documentation`(운영 문서·비개발자 설명)로 둔다.
- 긴급하거나 파일 간 결합도가 높은 변경은 메인 Codex가 직접 처리하고, 서브에이전트에는 독립적으로 끝낼 수 있는 범위만 맡긴다.
- 서브에이전트 결과는 메인 Codex가 검토한 뒤 반영한다. 서로 같은 일을 중복 수행하지 않게 하고, 로컬에 이미 존재하는 사용자 변경은 되돌리지 않는다.
- 작업 시작 또는 중간 보고에서 누가 어떤 역할을 맡았는지 짧게 공유한다.

## 공통 제품 원칙

- 뉴스레터는 독립 발행 서비스다. 매일 읽을 수 있는 결과물 자체가 품질 기준이며, 동시에 GP 프로필과 People DB를 갱신할 신호를 남겨야 한다.
- People DB는 단순 인명록이 아니다. GP별 핵심 인물, 역할, 경력, 학력, 뉴스 연결을 통해 GP 페이지와 뉴스 해석에 맥락을 제공하는 엔진이다.
- 공개 화면에서는 뉴스, GP, 펀드, 인물을 같은 서비스의 다른 진입점으로 보여준다. 뉴스레터 카드는 기사 링크만 나열하지 않고 확인된 GP/관련 인물 맥락을 보여주되, 프로필 보강·식별자 보강·작업 담당자 같은 운영 상태는 보여주지 않는다.
- 운영 콘솔은 `dashboard/`에 둔다. 작업 큐, DB 품질, 수집 로그, 원천 관리, 검토 대기 상태는 실제 사용자용 `public/` 화면과 분리한다.
- 뉴스 담당은 기사 단위의 사실, 출처, GP 연결, 갱신 액션을 보존한다. People DB 담당은 인물 단위의 식별, 역할, 출처, 뉴스 연결을 보존한다.
- 두 담당 모두 추정으로 빈칸을 채우지 않는다. 공개 반영은 출처가 있고 검토 상태가 분명한 데이터만 사용한다.
- 운영 산출물은 재생성 가능한 파일과 DB 경로에 남긴다. 일회성 메모, 로컬 캡처, 수동 SQLite 수정만으로 운영 결정을 남기지 않는다.

## 공통 키

두 담당은 아래 키를 모든 작업 메모, CSV, 큐, 검토 요청에서 같은 의미로 사용한다.

| 키 | 의미 | 사용 기준 |
| --- | --- | --- |
| `source_gp_id` | GP 원천 식별자. `gp_profile.source_gp_id` 또는 `gp_house.gp_id`와 연결한다. | GP가 식별된 뉴스, People 역할, GP 업데이트 큐에 반드시 포함한다. |
| `standard_gp_name` | 표준 GP 표시명. | 사람이 검토할 산출물에는 `source_gp_id`와 함께 표기한다. |
| `person_id` | People DB 인물 식별자. | 기존 인물과 연결될 때 사용하고, 신규 후보는 비워 둔 채 `update_action`으로 생성 필요를 표시한다. |
| `news_id` | 뉴스 문서 식별자. | 뉴스 담당 산출물에서 People DB 작업으로 넘어가는 기사 단위 연결 키다. |
| `source_url` | 기사, 팀 페이지, 공시, 공식 프로필 등 원문 URL. | 모든 비-FSS 사실의 최소 증거 필드다. |
| `update_action` | 다음 작업 지시. | 예: `publish_only`, `gp_profile_update`, `identifier_update`, `people_create`, `people_role_update`, `people_news_link`, `hold`, `exclude`. |

## 뉴스레터 담당 운영 지시

### 역할명

뉴스레터 담당 에이전트의 운영상 이름은 `뉴스레터 데스크`로 둔다. 뉴스레터 데스크는 발행물의 편집 품질, 핵심 매체 커버리지, 공개 카드 표시 언어를 함께 책임진다.

### 입력

- 뉴스 소스와 수집 설정: `services/newsletter/data/news_sources.csv`
- 키워드 및 분류 규칙: `services/newsletter/data/news_keyword_rules.csv`
- GP 별칭 보정: `services/newsletter/data/news_gp_alias_overrides.csv`
- 수동 포함/제외 보정: `services/newsletter/data/news_manual_overrides.csv`
- 원문 저장 위치: `data/raw/daily_news/YYYY-MM-DD/`
- 뉴스 DB 스키마: `services/newsletter/schema/daily_news.sql`
- 운영 DB: `db/private_equity.db`

### 출력

- 초안 브리프: `exports/daily_news/daily_news_brief_latest.md`
- 초안 HTML: `exports/daily_news/daily_news_brief_latest.html`
- 날짜별 초안: `exports/daily_news/daily_news_brief_YYYYMMDD.md`, `exports/daily_news/daily_news_brief_YYYYMMDD.html`
- 리뷰 큐: `exports/daily_news/daily_news_review_queue_latest.csv`, `exports/daily_news/daily_news_review_queue_YYYYMMDD.csv`
- 리뷰 화면: `exports/daily_news/daily_news_review_latest.html`
- 리뷰 액션: `exports/daily_news/daily_news_review_actions_latest.csv`, `exports/daily_news/daily_news_review_actions_YYYYMMDD.csv`
- 최종 발행본: `exports/daily_news/daily_news_final_latest.md`, `exports/daily_news/daily_news_final_latest.html`
- 날짜별 최종본: `exports/daily_news/daily_news_final_YYYYMMDD.md`, `exports/daily_news/daily_news_final_YYYYMMDD.html`
- 소스 커버리지 감사: `exports/daily_news/newsletter_source_audit_latest.md`, `exports/daily_news/newsletter_source_audit_latest.csv`
- GP 업데이트 큐: `exports/daily_news/news_gp_update_worklist_latest.csv`, `exports/daily_news/news_gp_update_worklist_YYYYMMDD.csv`
- 뉴스/People/GP 통합 작업 큐: `exports/service_integration_worklist_latest.csv`, `exports/service_integration_worklist_YYYYMMDD.csv`
- newsletter public mirror 반영 파일: `services/newsletter/deploy/site/`, public mirror `pkkong/kpef-newsletter`의 `gh-pages` 브랜치
- legacy public 반영 파일: `public/daily-news.html`, `public/index.html`
- 운영 로그: `exports/daily_news/logs/daily_news_YYYYMMDD_HHMMSS.log`

### 품질 기준

- 발행물은 최근 24시간 오전 브리핑 기준을 따른다. 발행 시간이 확인되는 기사는 운영 창에 맞춰 필터링하고, 시간이 없으면 발견일 기준으로 처리한다.
- 각 기사에는 제목, 출처, 날짜, `source_url`, 관련 GP, 분류, 포함/제외 판단이 있어야 한다.
- GP가 확인되면 `source_gp_id`와 `standard_gp_name`을 함께 남긴다. 이름만 있고 GP 식별이 불확실하면 큐에 `update_action=identifier_update` 또는 `hold`로 남긴다.
- 기사에서 인물 이동, 대표 변경, 신규 파트너, 팀 페이지 변경, 딜 관여 인물 등 People DB에 영향을 주는 신호가 있으면 `person_id` 확인 여부와 함께 `update_action=people_create`, `people_role_update`, `people_news_link` 중 하나로 넘긴다.
- 발행 후보와 DB 갱신 후보를 분리한다. 독자가 읽을 가치가 낮아 발행에서 제외된 기사라도 GP/People 갱신 신호가 있으면 큐에는 남긴다.
- 공개 뉴스 카드에는 운영용 표현을 노출하지 않는다. `GP 스톤브릿지캐피탈`, `관련 인물 3명`처럼 DB 작업 상태가 드러나는 라벨은 피하고, 확정 GP명 1개와 추가 개수 정도만 조용히 표시한다.
- 뉴스 카드 메타는 중복 카테고리를 반복하지 않는다. 섹션 헤더가 이미 카테고리 역할을 하므로 카드 안에는 언론사만 표시하고, 기자명이 안정적으로 수집되면 `언론사 · 기자명`으로 확장한다.
- 매일 발행 후 `services/newsletter/src/build_newsletter_source_audit.py`를 실행해 더벨, 딜사이트, 인베스트조선, 블로터, 뉴스토마토, 뉴스톱 등 핵심 매체가 수집/리뷰/브리프 단계에서 어디까지 도달했는지 확인한다.
- 검증은 `services/newsletter/src/validate_daily_news_pipeline.py` 또는 `services/newsletter/scripts/validate_daily_news_today.ps1` 기준을 통과해야 한다.

### 금지사항

- Google News 중계 링크, 검색 결과 링크, 추적 URL을 최종 `source_url`로 남기지 않는다.
- 기사 본문에 없는 GP, 인물, 역할, 직함, 딜 맥락을 추정해 추가하지 않는다.
- `standard_gp_name`만 적고 `source_gp_id`를 비워 둔 상태로 확정 업데이트 큐를 만들지 않는다. 식별 불가 상태는 별도 검토로 남긴다.
- People DB 입력 파일을 뉴스 담당이 직접 대량 수정하지 않는다. People 담당에게 `news_id`, `source_url`, `update_action`이 포함된 작업 신호로 넘긴다.
- 발행 품질과 무관한 장기 리서치 항목을 뉴스레터 본문에 억지로 포함하지 않는다.

## People DB 담당 운영 지시

### 입력

- 인물 기본 입력: `data/people_input.csv`
- 역할 입력: `data/person_role_input.csv`
- 학력 입력: `data/person_education_input.csv`
- 입력 템플릿: `data/people_import_template.csv`, `data/person_role_import_template.csv`, `data/person_education_import_template.csv`
- 이름 보정: `data/person_name_overrides.csv`
- 학교명 보정: `data/school_name_aliases.csv`
- 뉴스 담당 신호: `exports/daily_news/news_gp_update_worklist_latest.csv`, `exports/daily_news/daily_news_review_actions_latest.csv`
- People DB 스키마: `schema/people.sql`
- 운영 DB: `db/private_equity.db`

### 출력

- 인물 요약: `exports/people_profile_summary.csv`
- 현 소속 GP 뷰: `exports/people_current_gp.csv`
- 역할 이력: `exports/people_roles.csv`
- 학력 뷰: `exports/people_education.csv`
- People 리서치 작업 목록: `exports/people_research_worklist_top50.csv`
- 뉴스/People/GP 통합 작업 큐: `exports/service_integration_worklist_latest.csv`
- GP 프로필 연동 산출물: `exports/gp_profile_master.csv`, `exports/gp_profile_master.xlsx`
- dashboard 반영 데이터: `dashboard/data/dashboard_data.json`
- public 반영 파일: `public/index.html`, `public/daily-news.html`

### 품질 기준

- 공개 표시 대상 인물은 최소 하나 이상의 `person_source` 또는 동등한 공식/권위 출처를 가져야 한다.
- `person_id`는 동일 인물을 안정적으로 추적하는 기준이다. 동명이인, 영문/국문 표기 차이, 전/현 소속 혼재가 있으면 신규 생성 전에 중복 가능성을 검토한다.
- GP 소속은 `person_role.org_type='GP'` 기준으로 관리하고, 가능한 경우 `source_gp_id`와 `standard_gp_name`을 함께 보존한다.
- 뉴스에서 나온 인물 신호는 `news_id`와 `source_url`을 통해 `person_news_link` 또는 후속 연결 구조로 추적 가능해야 한다.
- 직함, 역할 기간, 학력, 전직 이력은 출처가 확인된 범위까지만 입력한다. 미확인 기간은 비워 두거나 검토 상태로 둔다.
- People DB 갱신 후 `scripts/import_people_csv.py`, `scripts/export_people_views.py`, 필요 시 `scripts/build_dashboard_data.py` 산출물이 일관되게 갱신되는지 확인한다.

### 금지사항

- 개인 민감정보, 비공개 연락처, 출처 없는 생년/나이/학번/개인 SNS를 입력하지 않는다.
- 기사 한 건의 표현만으로 현직, 퇴직, 승진, 담당 업무를 단정하지 않는다. 공식 팀 페이지, 보도자료, 공시, 신뢰 가능한 기사 등으로 확인한다.
- `person_id` 중복 가능성을 확인하지 않고 새 인물을 생성하지 않는다.
- 뉴스 담당의 발행 판단을 People DB 담당이 임의로 바꾸지 않는다. People 담당은 DB 갱신 필요 여부와 근거만 남긴다.
- GP 식별이 불확실한 인물 역할을 확정 소속으로 입력하지 않는다.

## 매일 운영 흐름

1. 뉴스 수집: `services/newsletter/src/run_daily_news_pipeline.py` 또는 `services/newsletter/scripts/run_daily_news_today.ps1`로 수집하고 `data/raw/daily_news/YYYY-MM-DD/`, `db/private_equity.db`, `exports/daily_news/`를 갱신한다.
2. 발행 후보 검토: 뉴스 담당은 `exports/daily_news/daily_news_review_latest.html`과 `exports/daily_news/daily_news_review_queue_latest.csv`를 검토해 발행 포함/제외와 분류를 확정한다.
3. GP update queue 생성: 뉴스 담당은 `exports/daily_news/news_gp_update_worklist_latest.csv`에 `source_gp_id`, `standard_gp_name`, `source_url`, 갱신 액션을 남긴다.
4. 통합 작업 큐 생성: 운영자는 `scripts/build_service_integration_worklist.py`로 `exports/service_integration_worklist_latest.csv`를 갱신한다. 이 파일이 뉴스 담당, GP 프로필 담당, People DB 담당의 공통 작업판이다.
5. People worklist 생성: People 담당은 통합 큐와 기존 People 산출물을 대조해 `exports/people_research_worklist_top50.csv` 또는 입력 CSV 갱신 후보를 만든다.
6. People DB 반영: People 담당은 `data/people_input.csv`, `data/person_role_input.csv`, `data/person_education_input.csv`를 출처 기반으로 갱신하고 `scripts/import_people_csv.py`, `scripts/export_people_views.py`를 실행한다.
7. newsletter public mirror 반영: 로컬 Mac 발행 작업은 `services/newsletter/src/build_newsletter_deploy.py`로 `services/newsletter/deploy/site/`를 만들고 `services/newsletter/scripts/publish_newsletter_pages_local.sh`로 public mirror `pkkong/kpef-newsletter`의 `gh-pages` 브랜치에 push한다.
8. dashboard/public 반영: 운영자는 `scripts/build_dashboard_data.py`, `scripts/build_service_site.py`를 통해 `dashboard/data/dashboard_data.json`, `dashboard/index.html`, `public/index.html`, `public/daily-news.html`을 최신 상태로 만든다.
9. 상태 점검: `scripts/build_operational_status_report.py`로 `exports/operational_status_latest.md`를 갱신하고, 뉴스와 People의 미처리 `update_action`을 다음날 작업 목록으로 넘긴다.

## repo 기준 핵심 경로

- 운영 DB: `db/private_equity.db`
- 뉴스 스키마: `services/newsletter/schema/daily_news.sql`
- People 스키마: `schema/people.sql`
- 뉴스 입력 설정: `services/newsletter/data/news_sources.csv`, `services/newsletter/data/news_keyword_rules.csv`, `services/newsletter/data/news_gp_alias_overrides.csv`, `services/newsletter/data/news_manual_overrides.csv`
- People 입력: `data/people_input.csv`, `data/person_role_input.csv`, `data/person_education_input.csv`
- 뉴스 원문: `data/raw/daily_news/YYYY-MM-DD/`
- 뉴스 발행/검토/큐: `exports/daily_news/`
- 뉴스/People/GP 통합 작업 큐: `exports/service_integration_worklist_latest.csv`
- People 검토/뷰: `exports/people_profile_summary.csv`, `exports/people_current_gp.csv`, `exports/people_roles.csv`, `exports/people_education.csv`, `exports/people_research_worklist_top50.csv`
- GP 프로필/식별자: `exports/gp_profile_master.csv`, `exports/gp_profile_master.xlsx`, `exports/gp_identifier.csv`, `exports/gp_profile_sources.csv`
- dashboard 데이터와 앱: `dashboard/data/dashboard_data.json`, `dashboard/index.html`, `dashboard/assets/app.js`, `dashboard/assets/app.css`
- public 서비스 파일: `public/index.html`, `public/daily-news.html`, `public/assets/service.js`, `public/assets/service.css`
- 운영 상태 보고서: `exports/operational_status_latest.md`, `exports/operational_status_YYYYMMDD_HHMMSS.md`
