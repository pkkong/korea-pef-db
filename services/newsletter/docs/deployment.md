# Newsletter Deployment

오늘 배포 범위는 뉴스레터 서비스만이다. GP/LP DB 화면은 서버 번들에서 제외하고, `Daily Brief`, 저장함, 공식 출자공고 패널만 포함한다.

## Build

```powershell
python services\newsletter\src\run_daily_news_pipeline.py --date 2026-05-22 --allow-insecure-ssl --google-date-window
python services\newsletter\src\build_newsletter_deploy.py --date 2026-05-22
```

빌드 산출물:

- `services/newsletter/deploy/site/`: 서버에 올릴 정적 파일
- `services/newsletter/deploy/kpef-newsletter-site.zip`: 압축 배포본
- `services/newsletter/deploy/deploy-manifest.json`: 배포 메타데이터
- `services/newsletter/deploy/Dockerfile`: Docker 배포용
- `services/newsletter/deploy/nginx.conf`: Nginx 설정

## GitHub Pages Deploy

뉴스레터만 먼저 어디서든 볼 수 있게 하기 위해 GitHub Pages 배포 워크플로를 둔다.

- Public mirror repository: `pkkong/kpef-newsletter`
- Public URL: `https://pkkong.github.io/kpef-newsletter/`
- Private workflow: `.github/workflows/deploy-newsletter-pages.yml`

현재 private 원본 저장소는 GitHub Pages endpoint가 열리지 않을 수 있으므로,
일단 공개 가능한 정적 뉴스레터 산출물만 별도 public 저장소에 배포한다.
배포 저장소에는 `services/newsletter/deploy/site/`의 HTML/CSS/JS/health 파일만 올라가며,
로컬 SQLite DB, raw crawl cache, secrets, operator exports는 포함하지 않는다.

private workflow는 GitHub Actions 안에서 다음 순서로 실행되도록 준비되어 있다.

```text
run_daily_news_pipeline.py
→ build_newsletter_deploy.py
→ services/newsletter/deploy/site 생성
→ gh-pages 브랜치에 정적 파일 배포
```

private repo Pages를 쓰려면 GitHub 저장소 Settings → Pages에서 Source를
`Deploy from a branch`, Branch를 `gh-pages`, Folder를 `/ (root)`로 설정해야 한다.
계정/플랜에서 private Pages가 지원되지 않으면 public mirror 저장소를 계속 사용한다.
Naver News까지 정상 수집하려면 저장소 Secrets에 아래 두 값을 넣는다.

- `NAVER_CLIENT_ID`
- `NAVER_CLIENT_SECRET`

Secrets가 없으면 워크플로는 Naver News 소스를 건너뛰고 Google/RSS/HTML 소스만으로 빌드한다.
수동 배포는 GitHub Actions 화면에서 `Deploy newsletter to GitHub Pages`를 실행하면 된다.

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

매일 갱신은 같은 방식으로 새 번들을 만들고 서버의 `site/`만 교체하면 된다. 수집 자체를 서버에서 자동 실행하려면 다음 단계에서 서버 crontab 또는 Cloud Run/Railway Cron으로 `run_daily_news_pipeline.py`와 `build_newsletter_deploy.py`를 묶는다.
