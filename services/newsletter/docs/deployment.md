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

뉴스레터는 로컬 Mac이 만들고, 공개 가능한 정적 파일만 별도 public mirror 저장소에 올린다.
비개발자는 GitHub Pages 주소만 확인하면 된다.

- 원본 저장소: private repo `pkkong/korea-pef-db`
- Public mirror repository: `pkkong/kpef-newsletter`
- Public URL: `https://pkkong.github.io/kpef-newsletter/`
- Local publisher: `services/newsletter/scripts/publish_newsletter_pages_local.sh`
- macOS scheduler installer: `services/newsletter/scripts/install_newsletter_local_publisher_launchd.sh`
- Private workflow fallback: `.github/workflows/deploy-newsletter-pages.yml`
- Workflow fallback name: `Deploy newsletter to GitHub Pages (fallback)`

현재 private 원본 저장소는 GitHub Pages endpoint가 열리지 않을 수 있으므로, 공개 가능한 뉴스레터 산출물만
`pkkong/kpef-newsletter`에 복사해서 보여준다. Public mirror에는 `services/newsletter/deploy/site/`의
HTML/CSS/JS/health 파일만 올라간다. 로컬 SQLite DB, raw crawl cache, secrets, operator exports는 올리지 않는다.

로컬 Mac 발행은 다음 순서로 실행된다.

```text
1. run_daily_news_pipeline.py로 그날의 뉴스 데이터를 만든다.
2. build_newsletter_deploy.py로 정적 사이트 파일을 만든다.
3. services/newsletter/deploy/site/ 결과물만 모은다.
4. 로컬 GitHub 인증으로 public mirror pkkong/kpef-newsletter에 push한다.
5. GitHub Pages가 https://pkkong.github.io/kpef-newsletter/ 주소로 보여준다.
```

자동 실행은 macOS launchd가 담당한다. 기본 설정은 로컬 시간 매일 오전 8:30 실행이다.
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

GitHub Actions는 수동 fallback으로만 사용한다. private 원본 저장소의 GitHub 화면에서 `Actions` → `Deploy newsletter to GitHub Pages (fallback)`
→ `Run workflow`를 누르면 실행된다. `report_date`를 비워 두면 한국시간 기준 오늘 날짜로 생성되고, 필요한 경우
`YYYY-MM-DD` 형식으로 날짜를 직접 넣을 수 있다.

## Required GitHub Secrets

로컬 Mac 발행에는 `config/daily_news.env`의 Naver 키와 public mirror 저장소에 push할 수 있는 로컬 GitHub 인증이 필요하다.

GitHub Actions fallback을 쓰려면 private 원본 저장소의 `Settings` → `Secrets and variables` → `Actions`에 아래 값을 넣는다.

- `NAVER_CLIENT_ID`: Naver News API client ID
- `NAVER_CLIENT_SECRET`: Naver News API client secret
- `NEWSLETTER_PUBLIC_REPO_TOKEN`: private 원본 저장소의 Action이 public mirror `pkkong/kpef-newsletter`에 push할 때 쓰는 GitHub token

`NAVER_CLIENT_ID` 또는 `NAVER_CLIENT_SECRET`이 없으면 워크플로는 Naver News 소스를 건너뛰고
Google/RSS/HTML 소스만으로 빌드한다.
`NEWSLETTER_PUBLIC_REPO_TOKEN`이 없거나 public mirror에 push 권한이 없으면 뉴스레터 파일을 만들 수는 있어도
`pkkong/kpef-newsletter`에 게시할 수 없다.

Public mirror 저장소의 Pages 설정은 `Settings` → `Pages`에서 Source를 `Deploy from a branch`,
Branch를 `main`, Folder를 `/ (root)`로 둔다.

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

매일 갱신은 로컬 Mac launchd가 처리한다. Mac이 켜져 있고 네트워크와 GitHub 인증이 정상이어야
뉴스 수집, 정적 사이트 생성, public mirror push가 순서대로 실행된다.
GitHub Actions는 자동 schedule/push 실행 없이 수동 fallback으로만 둔다.

로컬 실행과 GitHub Actions 실행의 품질/커버리지 차이는
`services/newsletter/docs/local_vs_github_quality.md`에 정리한다.
