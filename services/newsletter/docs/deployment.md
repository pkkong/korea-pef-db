# Newsletter Deployment

이 문서는 뉴스레터 단독 운영 기준이다. 뉴스레터 운영은 `Daily Brief`, archive, health, 정적 자산, Vercel 앱용 read model을 다루지만, 실행 책임은 워크플로별로 분리한다. LP/GP/Wiki 화면이나 LP 공고 서비스는 이 문서의 배포 범위가 아니다.

운영 역할은 아래처럼 고정한다.

- `Build newsletter mirror`: Supabase canonical collection 복원, 뉴스 수집/분류, raw HTML과 검수 이력 반영, 정적 미러 생성/검증, GitHub Pages backup publish/verify
- `Sync newsletter Supabase read model`: verified mirror archive를 Supabase에 동기화하고 Vercel health 검증
- `Deploy newsletter Vercel app`: Vercel 앱 코드 배포
- Supabase: 비공개 뉴스 canonical collection과 Vercel 앱이 읽는 공개 read model DB
- Vercel: 사용자가 보는 primary 뉴스레터 앱
- GitHub Pages: 장애 시 확인 가능한 정적 백업 미러
- Mac/local: 개발과 빠른 검증 보조. 정식 발행 경로가 아니다.

## Build

뉴스레터 전용 번들은 아래 스크립트로 만든다. 이 경로는 LP/GP/Wiki 빌더를 import하지 않아야 한다.

```bash
python3 scripts/build_newsletter_bundle.py --date YYYY-MM-DD --archive-limit 30
```

빌드 산출물:

- `services/newsletter/deploy/site/`: GitHub Pages mirror에 올릴 뉴스레터 정적 파일
- `services/newsletter/deploy/site/index.html`: 뉴스레터 화면
- `services/newsletter/deploy/site/archive.json`: 날짜별 기사 archive
- `services/newsletter/deploy/site/health.json`: 발행 상태 확인 파일

Supabase read model 동기화 payload는 아래 스크립트가 만든다.

```bash
python3 services/newsletter/src/sync_newsletter_supabase.py \
  --archive services/newsletter/deploy/site/archive.json \
  --payload-out exports/daily_news/newsletter_supabase_payload.json
```

루틴 운영에서는 `--date`를 넣지 않는다. 기본값은 Pages mirror와 같은 최근 30개
issue 동기화다. `--date YYYY-MM-DD`는 특정 날짜를 재현하거나 디버그할 때만 쓴다.

## Cloud Publish

뉴스레터는 GitHub Actions가 매일 만들고, public static mirror를 먼저 갱신한다. Supabase read model과 Vercel 확인은 별도 후속 workflow가 담당한다.
Mac은 정식 운영 경로에서 제외한다. 비개발자가 보는 기본 주소는 Vercel 앱이고, GitHub Pages는
장애 시 확인 가능한 백업 미러다.

- 원본 저장소: private repo `pkkong/korea-pef-db`
- Public mirror repository: `pkkong/kpef-newsletter`
- Public mirror publish branch: `gh-pages`
- Primary app URL: `https://kpef-newsletter.vercel.app/`
- Static mirror URL: `https://pkkong.github.io/kpef-newsletter/`
- Primary automation workflow: `.github/workflows/deploy-newsletter-pages.yml`
- Mirror workflow name: `Build newsletter mirror`
- Supabase/Vercel sync workflow: `.github/workflows/sync-newsletter-supabase.yml`
- Vercel app deploy workflow: `.github/workflows/deploy-newsletter-vercel.yml`
- GitHub fallback watchdog: `.github/workflows/newsletter-watchdog.yml`
- External fallback watchdog: Supabase Cron migration `services/newsletter/supabase/migrations/20260807093000_newsletter_external_watchdog_cron.sql`

현재 private 원본 저장소는 GitHub Pages endpoint가 열리지 않을 수 있으므로, 공개 가능한 뉴스레터 산출물만
`pkkong/kpef-newsletter`에 복사해서 보여준다. Public mirror에는 `services/newsletter/deploy/site/`의
HTML/CSS/JS/health 파일만 올라간다. 로컬 SQLite DB, raw crawl cache, secrets, operator exports는 올리지 않는다.

GitHub Actions 자동 발행은 두 단계로 실행된다.

```text
Mirror workflow: Build newsletter mirror
1. sync_newsletter_canonical_supabase.py가 Supabase canonical collection을 새 임시 SQLite adapter로 복원한다.
2. run_daily_news_pipeline.py가 그 adapter에서 그날의 뉴스 데이터를 만들고, raw HTML을 private Storage에 보관한 뒤 source/run/document/tag/entity 결과를 Supabase canonical collection에 반영한다.
3. build_newsletter_source_audit.py와 enrich_daily_news_ai.py로 품질 점검과 3줄 요약 보강 파일을 만든다.
4. scripts/build_newsletter_bundle.py로 뉴스레터 전용 정적 사이트 파일을 만든다.
5. `NEWSLETTER_PUBLIC_REPO_TOKEN`으로 public mirror `pkkong/kpef-newsletter`의 `gh-pages` 브랜치에 push한다.
6. GitHub Pages mirror의 `health.json`과 `archive.json`이 오늘 날짜와 기사 수를 보여주는지 확인한다.

Sync workflow: Sync newsletter Supabase read model
7. Verified mirror archive를 Supabase public read model에 동기화한다. 같은 날짜 재동기화 때는 기존 issue-article link와 article metadata를 지우고 현재 archive 기준으로 다시 만든다.
8. Vercel 앱의 `/health.json?refresh=1`이 `data_source=supabase`, 오늘 날짜, 같은 기사 수를 보여주는지 확인한다.
```

자동 실행의 기본 경로는 GitHub Actions schedule이다. 기본 설정은 매일 한국시간 오전 8:37 실행이다.
GitHub 내부 watchdog은 09:22 KST에 한 번 실행되어 mirror와 Vercel 상태를 확인하고 필요한 recovery workflow만 실행한다.
다만 GitHub Actions 자체 장애가 있으면 primary schedule과 GitHub 내부 watchdog이 함께 누락될 수 있다.
이 경우를 막기 위해 Supabase Cron이 GitHub 밖에서 09:05, 09:35, 10:05, 10:35 KST에
`Newsletter publish watchdog` workflow를 `workflow_dispatch`로 깨운다. GitHub watchdog은 이미 fresh이면 아무것도 하지 않고,
mirror가 stale이면 `Build newsletter mirror`를, mirror는 fresh인데 Vercel/Supabase만 stale이면 `Sync newsletter Supabase read model`만 실행한다.

GitHub Actions 화면에서 수동 실행도 그대로 사용할 수 있다. private 원본 저장소의 GitHub 화면에서
`Actions` → `Build newsletter mirror` → `Run workflow`를 누르면 백업 미러 생성이 실행된다. `report_date`를 비워 두면
한국시간 기준 오늘 날짜로 생성되고, 필요한 경우 `YYYY-MM-DD` 형식으로 날짜를 직접 넣을 수 있다. Mirror workflow가 새 mirror를 실제로 만들고 검증하면
`Sync newsletter Supabase read model`을 후속 작업으로 dispatch한다.

로컬 수동 발행과 macOS launchd 자동 발행 경로는 제거했다. 장애 복구도 같은 GitHub Actions workflow의
`Run workflow`로 처리한다.

## Required GitHub Secrets

GitHub Actions 자동 발행에는 private 원본 저장소의 `Settings` → `Secrets and variables` → `Actions`에 아래 값을 넣는다.

- `NAVER_CLIENT_ID`: Naver News API client ID
- `NAVER_CLIENT_SECRET`: Naver News API client secret
- `NEWSLETTER_PUBLIC_REPO_TOKEN`: private 원본 저장소의 Action이 public mirror `pkkong/kpef-newsletter`에 push할 때 쓰는 GitHub token
- `SUPABASE_DB_URL`: Supabase migration과 external watchdog cron 설치에 쓰는 DB connection URL
- `NEWSLETTER_WATCHDOG_DISPATCH_TOKEN`: Supabase external watchdog이 GitHub `Newsletter publish watchdog` workflow를 dispatch할 때 쓰는 token
- `SUPABASE_URL`: 뉴스레터 canonical collection과 public read model의 Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY`: GitHub Actions가 canonical collection과 public read model을 갱신할 때 쓰는 Supabase service role key

`NAVER_CLIENT_ID` 또는 `NAVER_CLIENT_SECRET`이 없으면 워크플로는 실패한다. Naver 소스를 빼고 발행하면 커버리지가 크게 낮아져서 자동 발행으로 인정하지 않는다.
`NEWSLETTER_PUBLIC_REPO_TOKEN`이 없거나 public mirror에 push 권한이 없으면 뉴스레터 파일을 만들 수는 있어도
`pkkong/kpef-newsletter`에 게시할 수 없다.
`SUPABASE_DB_URL`이 없으면 Supabase migration과 external watchdog cron 설치가 실패한다.
`NEWSLETTER_WATCHDOG_DISPATCH_TOKEN`이 없으면 Supabase Cron은 설치되지만 GitHub workflow를 외부에서 dispatch하지 못한다.
`SUPABASE_URL` 또는 `SUPABASE_SERVICE_ROLE_KEY`가 없으면 canonical collection을 복원하거나 기록할 수 없으므로 mirror workflow는 수집을 시작하지 않는다. public read model sync가 실패해도 이미 만들어진 GitHub Pages backup mirror는 유지된다.

Public mirror 저장소의 Pages 설정은 `Settings` → `Pages`에서 Source를 `Deploy from a branch`,
Branch를 `gh-pages`, Folder를 `/ (root)`로 둔다.

## Supabase External Watchdog

Supabase external watchdog은 GitHub Actions 장애로 scheduled workflow가 시작되지 않은 날을 복구하기 위한 별도 안전장치다.
뉴스 수집을 Supabase에서 직접 하지 않는다. Supabase는 GitHub의 `Newsletter publish watchdog` workflow만 깨우고,
기존 GitHub workflow가 freshness check, 중복 실행 방지, mirror build, Supabase sync, Vercel 검증을 계속 담당한다.

설치 절차:

1. GitHub Actions secret `NEWSLETTER_WATCHDOG_DISPATCH_TOKEN`에 workflow dispatch 권한이 있는 GitHub token을 저장한다.
2. `Apply newsletter Supabase migration` workflow를 실행한다. 이 workflow는 `services/newsletter/supabase/migrations/*.sql`을 순서대로 적용하고, GitHub secret을 Supabase Vault의 `newsletter_github_actions_dispatch_token`으로 저장한다.
3. 이 token은 `pkkong/korea-pef-db` 저장소의 Actions workflow dispatch 권한이 있어야 한다. Fine-grained token을 쓴다면 최소한 대상 repo의 Actions read/write 권한이 필요하다.
4. 다음 SQL로 설치 상태를 확인한다.

`Apply newsletter Supabase migration` 로그에서 `external_watchdog_token=stored`와
`external_watchdog_token=configured`가 함께 보여야 한다.

```sql
select jobname, schedule, active
from cron.job
where jobname like 'newsletter-external-watchdog-%'
order by jobname;
```

실행 기록은 아래 SQL로 본다.

```sql
select *
from newsletter_ops.newsletter_external_watchdog_recent_requests
order by created_at desc
limit 20;
```

`status='skipped_missing_token'`이면 cron은 설치됐지만 Supabase Vault secret이 아직 없는 상태다.
이 상태에서는 메일 폭탄은 발생하지 않지만 GitHub 외부 복구도 동작하지 않는다.

## GitHub Actions Readiness Check

이 절차는 Secret 값을 열람하지 않고, private 원본 저장소에 필요한 Secret 이름이 있는지만 확인한다.
정상 준비 기준은 아래 네 가지다.

- Workflow `.github/workflows/deploy-newsletter-pages.yml`의 이름은 `Build newsletter mirror`이고 `schedule`과 `workflow_dispatch`가 모두 있다.
- Workflow `.github/workflows/sync-newsletter-supabase.yml`의 이름은 `Sync newsletter Supabase read model`이고 수동 실행과 mirror workflow의 explicit dispatch를 지원한다.
- Repository secrets에 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `NEWSLETTER_PUBLIC_REPO_TOKEN`, `SUPABASE_DB_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` 이름이 있다.
- `Actions` → `Build newsletter mirror` 화면에 `Run workflow` 버튼이 보인다.
- 실행 성공 후 `https://pkkong.github.io/kpef-newsletter/health.json`과 `https://kpef-newsletter.vercel.app/health.json`이 같은 날짜와 기사 수를 보여준다.

터미널에서 한 번에 점검하려면 private 원본 저장소 루트에서 실행한다.

```bash
python3 services/newsletter/scripts/check_github_actions_readiness.py
```

정상이라면 `schedule trigger present`, `manual workflow_dispatch trigger present`, 필수 Secret 이름이 모두 `[OK]`로 나온다.
`gh CLI not found` 또는 `GitHub secret names not checked`가 나오면 로컬에서 이름 확인만 못 한 상태다. 이때는 GitHub 화면에서
아래 경로로 확인한다.

```text
pkkong/korea-pef-db
→ Settings
→ Secrets and variables
→ Actions
→ Repository secrets
```

비개발자가 GitHub 화면에서 확인할 때는 값이 보이지 않는 것이 정상이다. 목록에 아래 세 이름이 있으면 된다.

```text
NAVER_CLIENT_ID
NAVER_CLIENT_SECRET
NEWSLETTER_PUBLIC_REPO_TOKEN
SUPABASE_DB_URL
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
```

`Actions`에서 수동 점검을 할 때는 `Build newsletter mirror` → `Run workflow`를 누르고,
`report_date`는 비워 두면 한국시간 오늘 날짜로 실행된다. 실행 상세 화면의 job summary에는
`Newsletter GitHub Actions readiness` 표가 남으며, Secret 값은 표시하지 않고 `configured` 또는 `missing`만 표시한다.

문제 대응 기준:

- `NEWSLETTER_PUBLIC_REPO_TOKEN`이 없으면 public mirror push가 실패하므로 즉시 보강한다.
- `NAVER_CLIENT_ID` 또는 `NAVER_CLIENT_SECRET`이 없으면 Naver News 소스가 빠지므로 기사 커버리지가 줄어든다.
- `SUPABASE_DB_URL`이 없으면 Supabase migration과 external watchdog 설치가 실패한다.
- `SUPABASE_URL` 또는 `SUPABASE_SERVICE_ROLE_KEY`가 없으면 Vercel 앱 read model 동기화가 실패한다. 이 경우 Pages mirror 상태와 Vercel 상태를 분리해서 본다.
- 수동 실행은 되지만 schedule 실행 이력이 없으면 workflow 파일의 cron `37 23 * * *` 및 retry cron, Actions enabled 상태를 확인한다.

## Local Smoke Test

```powershell
python scripts\serve_dashboard.py --host 127.0.0.1 --port 8020 --root services\newsletter\deploy\site
```

확인 URL:

- `http://127.0.0.1:8020/`
- `http://127.0.0.1:8020/health.json`

## Server Deploy With Docker

서버에 `services/newsletter/deploy/` 폴더를 올린 뒤:

```bash
cd services/newsletter/deploy
docker build -t kpef-newsletter .
docker rm -f kpef-newsletter 2>/dev/null || true
docker run -d --name kpef-newsletter --restart unless-stopped -p 80:80 kpef-newsletter
curl http://127.0.0.1/health.json
```

도메인은 나중에 붙이면 되고, 우선은 `http://SERVER_IP/`로 확인한다.

SSH 접속 정보가 있으면 로컬에서 바로 실행할 수도 있다.

```powershell
powershell -ExecutionPolicy Bypass -File .\services\newsletter\scripts\deploy_newsletter_ssh.ps1 `
  -HostName SERVER_IP `
  -User root `
  -KeyPath C:\path\to\key.pem `
  -PublishPort 80
```

## Server Deploy Without Docker

```bash
sudo mkdir -p /var/www/kpef-newsletter
sudo rsync -av --delete services/newsletter/deploy/site/ /var/www/kpef-newsletter/
sudo cp services/newsletter/deploy/nginx.conf /etc/nginx/sites-available/kpef-newsletter
sudo ln -sfn /etc/nginx/sites-available/kpef-newsletter /etc/nginx/sites-enabled/kpef-newsletter
sudo nginx -t
sudo systemctl reload nginx
curl http://127.0.0.1/health.json
```

## Update Flow

매일 갱신은 GitHub Actions scheduled workflow가 처리한다. Repository secrets와 public mirror token이 정상이어야
뉴스 수집, 정적 사이트 생성, public mirror push가 순서대로 실행된다.
수동 `Run workflow`는 같은 workflow의 수동 실행 경로로 유지한다.
Mac launchd와 로컬 publish는 사용하지 않는다.

GitHub-only 운영 기준과 로컬 진단 제한은
`services/newsletter/docs/local_vs_github_quality.md`에 정리한다.
