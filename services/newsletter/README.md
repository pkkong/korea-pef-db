# Newsletter Service

This folder owns the standalone Korea PEF daily newsletter service.

## Non-Developer Summary

뉴스레터는 GitHub Actions가 매일 수집, 분류, 정적 HTML 생성, public mirror 배포까지 처리하는 구조다. Mac은 정식 운영 경로에서 제외한다.

1. GitHub Actions workflow가 매일 08:30 KST에 실행된다.
2. GitHub Actions가 뉴스 기사를 모으고 뉴스레터용 정적 HTML 파일을 만든다.
3. 공개해도 되는 HTML/CSS/JS 파일만 public mirror 저장소인 `pkkong/kpef-newsletter`의 `gh-pages` 브랜치에 올린다.
4. 사용자는 GitHub Pages 주소 `https://pkkong.github.io/kpef-newsletter/`에서 최신 뉴스레터를 본다.
5. LP 공고는 Daily 본문이 아니라 `lp-notices.html` 별도 탭/페이지로 분리한다.

GitHub Actions 자동 발행에는 원본 저장소 Secrets에 아래 값이 필요하다.

- `NAVER_CLIENT_ID`: Naver News API client ID
- `NAVER_CLIENT_SECRET`: Naver News API client secret
- `NEWSLETTER_PUBLIC_REPO_TOKEN`: private 원본 저장소의 Action이 public mirror `pkkong/kpef-newsletter`에 push할 때 쓰는 GitHub token

자동 실행을 기다리지 않고 바로 만들려면 GitHub의 원본 저장소에서 `Actions` 탭으로 가서
`Deploy newsletter to GitHub Pages` 워크플로를 선택한 뒤 `Run workflow`를 누른다.
날짜를 비워 두면 한국시간 기준 오늘 날짜로 생성된다.

## Layout

- `src/`: Python implementation for collection, review, validation, delivery, source audit, and static deploy bundle generation
- `data/`: maintained newsletter inputs such as source definitions, keyword rules, manual overrides, and GP alias overrides
- `schema/`: SQLite schema for newsletter tables
- `scripts/`: service operating and verification entrypoints
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
```
