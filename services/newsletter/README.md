# Newsletter Service

This folder owns the standalone Korea PEF daily newsletter service.

## Non-Developer Summary

뉴스레터는 역할을 겹치지 않게 나눈다. Mac은 정식 운영 경로에서 제외하고, 운영은 GitHub Actions, Supabase, Vercel이 각각 자기 일만 맡는다.

1. GitHub Actions workflow가 매일 08:37 KST에 실행되고 retry/watchdog window가 보조한다.
2. `Build newsletter mirror`가 뉴스 기사를 모으고, 뉴스레터용 정적 HTML/CSS/JS를 만든 뒤 GitHub Pages 백업 미러만 갱신한다.
3. `Sync newsletter Supabase read model`이 검증된 GitHub Pages archive를 Supabase DB에 복사하고 Vercel 화면이 같은 날짜/기사 수를 읽는지 확인한다.
4. Supabase Cron은 GitHub Actions 장애로 스케줄이 누락된 날을 외부에서 감시하고, 필요하면 GitHub `Newsletter publish watchdog`을 다시 깨운다.
5. 사용자는 Vercel 공식 앱 `https://kpef-newsletter.vercel.app/`에서 최신 뉴스레터를 본다.
6. GitHub Pages `https://pkkong.github.io/kpef-newsletter/`는 장애 시 확인하는 백업 미러와 archive fallback이다.
7. `Deploy newsletter Vercel app`은 앱 코드 배포만 맡는다. 뉴스 수집이나 Supabase 동기화를 하지 않는다.
8. `services/newsletter/web/` 앱은 Supabase read model을 먼저 읽고, Supabase가 없거나 장애이면 기존 public `archive.json`을 fallback으로 읽는다.
9. LP 공고는 Daily 본문이 아니라 `lp-notices.html` 별도 탭/페이지로 분리한다.

GitHub Actions 자동 발행에는 원본 저장소 Secrets에 아래 값이 필요하다.

- `NAVER_CLIENT_ID`: Naver News API client ID
- `NAVER_CLIENT_SECRET`: Naver News API client secret
- `NEWSLETTER_PUBLIC_REPO_TOKEN`: private 원본 저장소의 Action이 public mirror `pkkong/kpef-newsletter`에 push할 때 쓰는 GitHub token
- `SUPABASE_DB_URL`: Supabase migration과 external watchdog cron 설치에 쓰는 DB connection URL
- `SUPABASE_URL`: Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY`: GitHub Actions가 공개 read model을 upsert할 때 쓰는 backend key
- `SUPABASE_PUBLISHABLE_KEY`: Vercel 앱이 read model을 읽을 때 쓰는 public key

GitHub Actions 자체가 장애인 날을 자동 복구하려면 Supabase Vault에 아래 secret이 필요하다.

- `newsletter_github_actions_dispatch_token`: `pkkong/korea-pef-db`의 Actions workflow dispatch 권한이 있는 GitHub fine-grained token

자동 실행을 기다리지 않고 바로 만들려면 GitHub의 원본 저장소에서 `Actions` 탭으로 가서
`Build newsletter mirror` 워크플로를 선택한 뒤 `Run workflow`를 누른다.
날짜를 비워 두면 한국시간 기준 오늘 날짜로 생성된다. 이 워크플로가 새 mirror를 실제로 만들고 검증하면
`Sync newsletter Supabase read model`을 별도 후속 작업으로 dispatch해 Supabase와 Vercel을 갱신한다.

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

Newsletter public HTML/CSS/JS has one source: `services/newsletter/web/newsletter_ui.py`.
The GitHub Pages mirror uses it through `services/newsletter/src/newsletter_renderer.py`;
the Vercel app imports it directly. Do not add a separate Vercel template or
`web/static/service.css`.

Root-level `scripts/*daily_news*.py` files are compatibility wrappers. New jobs
and docs should prefer the paths in this service folder.

`services/newsletter/src/build_newsletter_deploy.py` is also only a compatibility
wrapper. The old monolithic implementation was removed from the newsletter
service; do not add LP, GP, Wiki, or public-site renderer code back there.

## Common Commands

```powershell
python services/newsletter/src/run_daily_news_pipeline.py
python scripts/build_newsletter_bundle.py --date YYYY-MM-DD --archive-limit 30
python services/newsletter/src/validate_daily_news_pipeline.py
python services/newsletter/src/newsletter_public_status.py mirror-freshness --report-date YYYY-MM-DD --mirror-url https://pkkong.github.io/kpef-newsletter/ --event-name workflow_dispatch
python services/newsletter/tests/test_daily_news_logic.py
python services/newsletter/tests/test_public_status.py
python services/newsletter/src/sync_newsletter_supabase.py --archive services/newsletter/deploy/site/archive.json
python services/newsletter/web/tests/test_newsletter_data.py
python scripts/check_architecture_contracts.py
```
