# Newsletter Vercel/Supabase Operating Notes

## Current Production Setup

- Vercel project: `kpef-newsletter`
- Vercel production URL: `https://kpef-newsletter.vercel.app`
- Vercel root directory: `services/newsletter/web`
- Supabase project: `kpef-newsletter`
- Supabase project ref: `fhigakwodmfjwtttwyyj`
- Source repo: `pkkong/korea-pef-db`
- Public static mirror: `https://pkkong.github.io/kpef-newsletter/`
- Public mirror repo: `pkkong/kpef-newsletter`, branch `gh-pages`

2026-06-16 기준 GitHub Actions secrets와 Vercel environment variables는 설정되어 있다.
비밀값은 문서, 로그, 코드에 기록하지 않는다.

## 운영 구조

```text
GitHub Actions
-> run_daily_news_pipeline.py
-> build_newsletter_bundle.py
-> validate_daily_news_pipeline.py
-> sync_newsletter_supabase.py
-> GitHub Pages mirror

Vercel
-> services/newsletter/web/index.py
-> services/newsletter/web/app.py
-> Supabase newsletter_public_issue_articles
```

Vercel은 수집기를 돌리지 않는다. Vercel은 사용자가 보는 웹 화면만 담당한다.
수집, 분류, 중복 제거, 발행 검증은 GitHub Actions가 계속 담당한다.

## Supabase 적용 순서

1. Supabase SQL editor에서 `services/newsletter/supabase/migrations/20260616090000_newsletter_read_model.sql`을 적용한다.
2. GitHub Actions secrets에 `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`를 넣는다.
3. Vercel project root를 `services/newsletter/web`로 잡는다.
4. Vercel env에 `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`를 넣는다.
5. GitHub Actions `Deploy newsletter to GitHub Pages`를 수동 실행해 Supabase sync 로그를 확인한다.
6. Vercel `/health.json`에서 `data_source=supabase`와 최신 `report_date`를 확인한다.

운영 검증 기준:

- GitHub Actions `Deploy newsletter Vercel app`가 성공해야 한다.
- GitHub Actions `Deploy newsletter to GitHub Pages`가 성공해야 한다.
- `https://kpef-newsletter.vercel.app/health.json?refresh=1`이 `data_source=supabase`를 반환해야 한다.
- `https://pkkong.github.io/kpef-newsletter/health.json`은 GitHub Pages CDN 반영 지연이 있을 수 있으므로,
  workflow 검증은 이번 빌드의 `built_at`과 `article_count`까지 비교한다.

## 자동 배포 Workflow

`Check newsletter Vercel readiness` workflow는 계정 연결 전에도 성공해야 하는
preflight다. 파일 존재, Python compile, import isolation, Flask smoke test,
필요 secret의 존재 여부를 보여준다.

`Deploy newsletter Vercel app` workflow는 Vercel 앱만 배포한다. 매일 08:30
뉴스레터 발행 workflow와 분리되어 있으므로, Vercel 쪽 장애가 daily publish를
막지 않는다.

필요한 GitHub Actions secrets:

- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`
- `SUPABASE_DB_URL` optional: migration SQL을 Actions에서 직접 적용할 때 사용
- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`

`SUPABASE_DB_URL`이 없으면 migration 적용만 건너뛴다. `VERCEL_*` 3개가 없으면
Vercel deploy 단계는 실패 처리한다.

## 장애 기준

- Supabase sync가 실패해도 GitHub Pages 발행은 계속된다.
- Vercel app은 Supabase가 비어 있거나 장애일 때 기존 public `archive.json`으로 fallback한다.
- Supabase service role key는 GitHub Actions에만 둔다. Vercel에는 publishable key만 둔다.
