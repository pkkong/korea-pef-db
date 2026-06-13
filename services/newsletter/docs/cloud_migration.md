# Daily PEF News Cloud Migration

## 결론

현재 로컬 MVP는 매일 08:30 Windows 스케줄러로 실행된다. 따라서 PC가 꺼져 있거나 절전 상태면 뉴스 수집도 멈춘다.

서비스처럼 운영하려면 수집 실행 위치를 개인 PC에서 클라우드 서버로 옮겨야 한다.

## 추천 구조

```text
Cloud Scheduler
→ Daily News Job
→ News API / RSS 수집
→ Hosted DB 저장
→ public HTML 생성
→ 검수/발송 대기
```

## 1단계: 지금 바로 가능한 개선

- `services/newsletter/deploy/site/index.html`: 서비스 랜딩 페이지
- `services/newsletter/deploy/site/daily-news.html`: 오늘자 Daily Clipping 페이지
- `scripts/build_service_site.py`: 매일 수집 후 public 페이지 자동 갱신
- `services/newsletter/src/validate_daily_news_pipeline.py`: 수집 결과, public 페이지, DB, 스케줄러 상태 검증

이 단계는 여전히 PC가 켜져 있어야 한다.

## 2단계: 클라우드 이전 MVP

가장 현실적인 구조는 다음이다.

- 실행: Cloud Run Job 또는 Railway Cron
- DB: Supabase Postgres 또는 Cloud SQL Postgres
- 정적 페이지: Cloudflare Pages, Vercel, Netlify, 또는 같은 서버에서 호스팅
- 비밀키: 플랫폼의 Environment Variables에 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` 저장

이렇게 하면 PC가 꺼져 있어도 매일 수집이 돈다.

## 3단계: 앱 구조

```text
/public
  index.html
  daily-news.html

services/newsletter/src
  run_daily_news_pipeline.py
  validate_daily_news_pipeline.py

scripts
  build_service_site.py

/db
  local SQLite for development only

Cloud DB
  news_document
  news_run
  news_tag
  news_entity_link
```

## Apps Script 선택지

Google Apps Script로도 가능하지만, 지금 Python 파이프라인을 거의 새로 짜야 한다.

Apps Script가 적합한 경우:

- Google Sheets를 DB처럼 쓰고 싶다.
- 수집량이 작다.
- 복잡한 원문 파싱보다 링크/제목/스니펫 중심이면 충분하다.

Apps Script가 불리한 경우:

- source_url 기반 DB를 장기 누적하고 싶다.
- GP/Deal/LP DB와 연결해야 한다.
- 수집, 검수, 발송, 웹페이지를 하나의 서비스처럼 키우고 싶다.

따라서 현재 방향에서는 Python 파이프라인을 유지하고 클라우드 실행 환경으로 옮기는 쪽이 낫다.

## 다음 결정

다음 중 하나를 선택하면 된다.

- 빠른 MVP: Railway Cron + Supabase Postgres
- Google 중심: Cloud Run Job + Cloud SQL
- 가장 단순한 실험: Google Apps Script + Google Sheets로 별도 프로토타입

내 추천은 `Railway Cron + Supabase Postgres`다. 설정이 비교적 단순하고, 지금 Python 코드를 가장 적게 바꾸면 된다.
