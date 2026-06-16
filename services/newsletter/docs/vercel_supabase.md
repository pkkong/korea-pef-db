# Newsletter Vercel/Supabase Operating Notes

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

## 장애 기준

- Supabase sync가 실패해도 GitHub Pages 발행은 계속된다.
- Vercel app은 Supabase가 비어 있거나 장애일 때 기존 public `archive.json`으로 fallback한다.
- Supabase service role key는 GitHub Actions에만 둔다. Vercel에는 publishable key만 둔다.
