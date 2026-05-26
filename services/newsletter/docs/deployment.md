# Newsletter Deployment

오늘 배포 범위는 뉴스레터 서비스와 별도 LP 공고 탭이다. GP/LP DB 화면은 서버 번들에서 제외하고, `Daily Brief`, 저장함, `LP 공고` 페이지를 포함한다. LP 공고는 Daily 본문 패널로 붙이지 않는다.

## Build

```powershell
python services\newsletter\src\run_daily_news_pipeline.py --date 2026-05-22 --allow-insecure-ssl --google-date-window
python services\newsletter\src\build_newsletter_deploy.py --date 2026-05-22
```

빌드 산출물:

- `services/newsletter/deploy/site/`: 서버에 올릴 정적 파일
- `services/newsletter/deploy/site/lp-notices.html`: 별도 LP 공식 공고 페이지
- `services/newsletter/deploy/kpef-newsletter-site.zip`: 압축 배포본
- `services/newsletter/deploy/deploy-manifest.json`: 배포 메타데이터
- `services/newsletter/deploy/Dockerfile`: Docker 배포용
- `services/newsletter/deploy/nginx.conf`: Nginx 설정

## GitHub Pages Deploy

뉴스레터는 기본적으로 GitHub Actions가 매일 만들고, 공개 가능한 정적 파일만 별도 public mirror 저장소에 올린다.
Mac launchd 발행은 GitHub Actions가 실패하거나 수동 복구가 필요할 때 쓰는 보조/백업 경로다.
비개발자는 GitHub Pages 주소만 확인하면 된다.

- 원본 저장소: private repo `pkkong/korea-pef-db`
- Public mirror repository: `pkkong/kpef-newsletter`
- Public mirror publish branch: `gh-pages`
- Public URL: `https://pkkong.github.io/kpef-newsletter/`
- Primary automation workflow: `.github/workflows/deploy-newsletter-pages.yml`
- Workflow name: `Deploy newsletter to GitHub Pages`
- Local backup publisher: `services/newsletter/scripts/publish_newsletter_pages_local.sh`
- macOS backup scheduler installer: `services/newsletter/scripts/install_newsletter_local_publisher_launchd.sh`

현재 private 원본 저장소는 GitHub Pages endpoint가 열리지 않을 수 있으므로, 공개 가능한 뉴스레터 산출물만
`pkkong/kpef-newsletter`에 복사해서 보여준다. Public mirror에는 `services/newsletter/deploy/site/`의
HTML/CSS/JS/health 파일만 올라간다. 로컬 SQLite DB, raw crawl cache, secrets, operator exports는 올리지 않는다.

GitHub Actions 자동 발행은 다음 순서로 실행된다.

```text
1. run_daily_news_pipeline.py로 그날의 뉴스 데이터를 만든다.
2. build_newsletter_deploy.py로 정적 사이트 파일을 만든다.
3. services/newsletter/deploy/site/ 결과물만 모은다.
4. NEWSLETTER_PUBLIC_REPO_TOKEN으로 public mirror pkkong/kpef-newsletter의 `gh-pages` 브랜치에 push한다.
5. GitHub Pages가 https://pkkong.github.io/kpef-newsletter/ 주소로 보여준다.
```

자동 실행은 GitHub Actions schedule이 담당한다. 기본 설정은 매일 한국시간 오전 8:30 실행이다.
GitHub cron 표현은 UTC 기준 `30 23 * * *`이며, 실행 시 `report_date`는 Asia/Seoul 기준 오늘 날짜로 계산한다.

GitHub Actions 화면에서 수동 fallback도 그대로 사용할 수 있다. private 원본 저장소의 GitHub 화면에서
`Actions` → `Deploy newsletter to GitHub Pages` → `Run workflow`를 누르면 실행된다. `report_date`를 비워 두면
한국시간 기준 오늘 날짜로 생성되고, 필요한 경우 `YYYY-MM-DD` 형식으로 날짜를 직접 넣을 수 있다.

Mac launchd는 GitHub Actions 장애나 public mirror push 복구가 필요할 때 쓰는 보조/백업 자동화다.
기본 설정은 로컬 시간 매일 오전 8:30 실행이다.
설치:

```bash
services/newsletter/scripts/install_newsletter_local_publisher_launchd.sh
```

수동으로 바로 만들고 공개하려면:

```bash
services/newsletter/scripts/publish_newsletter_pages_local.sh
```

특정 날짜를 만들려면:

```bash
services/newsletter/scripts/publish_newsletter_pages_local.sh --date 2026-05-25
```

빌드와 검증만 하고 push하지 않으려면:

```bash
services/newsletter/scripts/publish_newsletter_pages_local.sh --no-push
```

## Required GitHub Secrets

GitHub Actions 자동 발행에는 private 원본 저장소의 `Settings` → `Secrets and variables` → `Actions`에 아래 값을 넣는다.

로컬 Mac 백업 발행에는 `config/daily_news.env`의 Naver 키와 public mirror 저장소에 push할 수 있는 로컬 GitHub 인증이 필요하다.

- `NAVER_CLIENT_ID`: Naver News API client ID
- `NAVER_CLIENT_SECRET`: Naver News API client secret
- `NEWSLETTER_PUBLIC_REPO_TOKEN`: private 원본 저장소의 Action이 public mirror `pkkong/kpef-newsletter`에 push할 때 쓰는 GitHub token

`NAVER_CLIENT_ID` 또는 `NAVER_CLIENT_SECRET`이 없으면 워크플로는 Naver News 소스를 건너뛰고
Google/RSS/HTML 소스만으로 빌드한다.
`NEWSLETTER_PUBLIC_REPO_TOKEN`이 없거나 public mirror에 push 권한이 없으면 뉴스레터 파일을 만들 수는 있어도
`pkkong/kpef-newsletter`에 게시할 수 없다.

Public mirror 저장소의 Pages 설정은 `Settings` → `Pages`에서 Source를 `Deploy from a branch`,
Branch를 `gh-pages`, Folder를 `/ (root)`로 둔다.

## GitHub Actions Readiness Check

이 절차는 Secret 값을 열람하지 않고, private 원본 저장소에 필요한 Secret 이름이 있는지만 확인한다.
정상 준비 기준은 아래 네 가지다.

- Workflow `.github/workflows/deploy-newsletter-pages.yml`에 `schedule`과 `workflow_dispatch`가 모두 있다.
- Repository secrets에 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `NEWSLETTER_PUBLIC_REPO_TOKEN` 세 이름이 있다.
- `Actions` → `Deploy newsletter to GitHub Pages` 화면에 `Run workflow` 버튼이 보인다.
- 실행 성공 후 `https://pkkong.github.io/kpef-newsletter/`와 `/health.json`이 열린다.

터미널에서 한 번에 점검하려면 private 원본 저장소 루트에서 실행한다.

```bash
python3 services/newsletter/scripts/check_github_actions_readiness.py
```

정상이라면 `schedule trigger present`, `manual workflow_dispatch trigger present`, 세 Secret 이름이 모두 `[OK]`로 나온다.
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
```

`Actions`에서 수동 점검을 할 때는 `Deploy newsletter to GitHub Pages` → `Run workflow`를 누르고,
`report_date`는 비워 두면 한국시간 오늘 날짜로 실행된다. 실행 상세 화면의 job summary에는
`Newsletter GitHub Actions readiness` 표가 남으며, Secret 값은 표시하지 않고 `configured` 또는 `missing`만 표시한다.

문제 대응 기준:

- `NEWSLETTER_PUBLIC_REPO_TOKEN`이 없으면 public mirror push가 실패하므로 즉시 보강한다.
- `NAVER_CLIENT_ID` 또는 `NAVER_CLIENT_SECRET`이 없으면 Naver News 소스가 빠지므로 기사 커버리지가 줄어든다.
- 수동 실행은 되지만 schedule 실행 이력이 없으면 workflow 파일의 cron `30 23 * * *`와 Actions enabled 상태를 확인한다.

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
수동 `Run workflow`는 같은 workflow의 fallback 실행 경로로 유지한다.
Mac launchd는 Actions 장애, 장시간 지연, 또는 토큰 문제 복구 중 임시 백업으로 사용한다.

로컬 실행과 GitHub Actions 실행의 품질/커버리지 차이는
`services/newsletter/docs/local_vs_github_quality.md`에 정리한다.
