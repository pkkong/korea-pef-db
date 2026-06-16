# Newsletter Service

This folder owns the standalone Korea PEF daily newsletter service.

## Non-Developer Summary

뉴스레터는 GitHub Actions가 매일 수집, 분류, 공개 read model 생성, public mirror 배포까지 처리하는 구조다. Mac은 정식 운영 경로에서 제외한다.

1. GitHub Actions workflow가 매일 08:30 KST에 실행된다.
2. GitHub Actions가 뉴스 기사를 모으고 뉴스레터용 정적 HTML 파일을 만든다.
3. 공개해도 되는 HTML/CSS/JS 파일만 public mirror 저장소인 `pkkong/kpef-newsletter`의 `gh-pages` 브랜치에 올린다.
4. 선택적으로 같은 workflow가 Supabase의 뉴스레터 read model을 갱신한다.
5. 사용자는 GitHub Pages 주소 `https://pkkong.github.io/kpef-newsletter/`에서 최신 뉴스레터를 본다.
6. Vercel 전환 시 `services/newsletter/web/` 앱이 Supabase read model을 먼저 읽고, Supabase가 없으면 기존 public `archive.json`을 fallback으로 읽는다.
7. LP 공고는 Daily 본문이 아니라 `lp-notices.html` 별도 탭/페이지로 분리한다.

GitHub Actions 자동 발행에는 원본 저장소 Secrets에 아래 값이 필요하다.

- `NAVER_CLIENT_ID`: Naver News API client ID
- `NAVER_CLIENT_SECRET`: Naver News API client secret
- `NEWSLETTER_PUBLIC_REPO_TOKEN`: private 원본 저장소의 Action이 public mirror `pkkong/kpef-newsletter`에 push할 때 쓰는 GitHub token
- `SUPABASE_URL` optional: Vercel/Supabase 전환용 Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY` optional: GitHub Actions가 공개 read model을 upsert할 때 쓰는 backend key

자동 실행을 기다리지 않고 바로 만들려면 GitHub의 원본 저장소에서 `Actions` 탭으로 가서
`Deploy newsletter to GitHub Pages` 워크플로를 선택한 뒤 `Run workflow`를 누른다.
날짜를 비워 두면 한국시간 기준 오늘 날짜로 생성된다.

Vercel 앱 배포는 별도 workflow인 `Deploy newsletter Vercel app`에서 처리한다.
이 workflow는 GitHub Pages daily publish와 분리되어 있고, `VERCEL_TOKEN`,
`VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`가 설정된 뒤 실행한다.
계정 연결 전 상태 점검은 `Check newsletter Vercel readiness` workflow를 실행한다.

## Layout

- `src/`: Python implementation for collection, review, validation, delivery, source audit, and static deploy bundle generation
- `data/`: maintained newsletter inputs such as source definitions, keyword rules, manual overrides, and GP alias overrides
- `schema/`: SQLite schema for newsletter tables
- `supabase/`: Supabase/Postgres migrations for the public newsletter read model
- `web/`: standalone Flask/Vercel newsletter app that reads Supabase or public `archive.json`
- `scripts/`: manual diagnostics and verification entrypoints
- `deploy/`: Docker/Nginx runtime files plus ignored generated site artifacts
- `docs/`: service-specific operating, cloud migration, MVP, and deployment notes
- `tests/`: no-network business rule checks

Root-level `scripts/*daily_news*.py` files are compatibility wrappers. New jobs
and docs should prefer the paths in this service folder.

## Common Commands

```powershell
python services/newsletter/src/run_daily_news_pipeline.py
python services/newsletter/src/build_newsletter_deploy.py
python services/newsletter/src/validate_daily_news_pipeline.py
python services/newsletter/tests/test_daily_news_logic.py
python services/newsletter/src/sync_newsletter_supabase.py --date YYYY-MM-DD
```
