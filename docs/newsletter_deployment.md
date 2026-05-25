# Newsletter Deployment

오늘 배포 범위는 뉴스레터 서비스만이다. GP/LP DB 화면은 서버 번들에서 제외하고, `Daily Brief`, 저장함, 공식 출자공고 패널만 포함한다.

## Build

```powershell
python scripts\run_daily_news_pipeline.py --date 2026-05-22 --allow-insecure-ssl --google-date-window
python scripts\build_newsletter_deploy.py --date 2026-05-22
```

빌드 산출물:

- `deploy/newsletter/site/`: 서버에 올릴 정적 파일
- `deploy/newsletter/kpef-newsletter-site.zip`: 압축 배포본
- `deploy/newsletter/deploy-manifest.json`: 배포 메타데이터
- `deploy/newsletter/Dockerfile`: Docker 배포용
- `deploy/newsletter/nginx.conf`: Nginx 설정

## GitHub Pages Deploy

뉴스레터만 먼저 어디서든 볼 수 있게 하기 위해 GitHub Pages 배포 워크플로를 둔다.

- Workflow: `.github/workflows/deploy-newsletter-pages.yml`
- Published branch: `gh-pages`
- Site root: `/`
- URL: `https://pkkong.github.io/korea-pef-db/`

워크플로는 GitHub Actions 안에서 다음 순서로 실행된다.

```text
run_daily_news_pipeline.py
→ build_newsletter_deploy.py
→ deploy/newsletter/site 생성
→ gh-pages 브랜치에 정적 파일 배포
```

처음 한 번은 GitHub 저장소 Settings → Pages에서 Source를 `Deploy from a branch`,
Branch를 `gh-pages`, Folder를 `/ (root)`로 설정해야 한다.
Naver News까지 정상 수집하려면 저장소 Secrets에 아래 두 값을 넣는다.

- `NAVER_CLIENT_ID`
- `NAVER_CLIENT_SECRET`

Secrets가 없으면 워크플로는 Naver News 소스를 건너뛰고 Google/RSS/HTML 소스만으로 빌드한다.
수동 배포는 GitHub Actions 화면에서 `Deploy newsletter to GitHub Pages`를 실행하면 된다.

## Local Smoke Test

```powershell
python scripts\serve_dashboard.py --host 127.0.0.1 --port 8020 --root deploy\newsletter\site
```

확인 URL:

- `http://127.0.0.1:8020/`
- `http://127.0.0.1:8020/health.json`

## Server Deploy With Docker

서버에 `deploy/newsletter/` 폴더를 올린 뒤:

```bash
cd deploy/newsletter
docker build -t kpef-newsletter .
docker rm -f kpef-newsletter 2>/dev/null || true
docker run -d --name kpef-newsletter --restart unless-stopped -p 80:80 kpef-newsletter
curl http://127.0.0.1/health.json
```

도메인은 나중에 붙이면 되고, 우선은 `http://SERVER_IP/`로 확인한다.

SSH 접속 정보가 있으면 로컬에서 바로 실행할 수도 있다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_newsletter_ssh.ps1 `
  -HostName SERVER_IP `
  -User root `
  -KeyPath C:\path\to\key.pem `
  -PublishPort 80
```

## Server Deploy Without Docker

```bash
sudo mkdir -p /var/www/kpef-newsletter
sudo rsync -av --delete deploy/newsletter/site/ /var/www/kpef-newsletter/
sudo cp deploy/newsletter/nginx.conf /etc/nginx/sites-available/kpef-newsletter
sudo ln -sfn /etc/nginx/sites-available/kpef-newsletter /etc/nginx/sites-enabled/kpef-newsletter
sudo nginx -t
sudo systemctl reload nginx
curl http://127.0.0.1/health.json
```

## Update Flow

매일 갱신은 같은 방식으로 새 번들을 만들고 서버의 `site/`만 교체하면 된다. 수집 자체를 서버에서 자동 실행하려면 다음 단계에서 서버 crontab 또는 Cloud Run/Railway Cron으로 `run_daily_news_pipeline.py`와 `build_newsletter_deploy.py`를 묶는다.
