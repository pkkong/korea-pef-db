# GitHub-Only Newsletter Operations

## Short Answer

뉴스레터의 정식 운영 경로는 GitHub Actions 하나다. Mac은 매일 수집, 발행, 배포 경로에서 제외한다.

운영 기준은 다음과 같다.

- GitHub Actions: 매일 08:30 KST 자동 수집, 분류, 정적 사이트 생성, public mirror push를 담당한다.
- GitHub Actions 수동 실행: 같은 workflow의 `Run workflow`로 특정 날짜를 재발행한다.
- 로컬 실행: 개발 진단 또는 Project Lead가 승인한 일회성 복구용이다. 기본 실행은 차단된다.

## Operating Contract

- 자동 발행은 `.github/workflows/deploy-newsletter-pages.yml`만 담당한다.
- public mirror는 GitHub Actions가 `NEWSLETTER_PUBLIC_REPO_TOKEN`으로 push한다.
- Naver API 키는 GitHub repository secrets에 둔다.
- 로컬 DB/cache가 있어도 public website는 자동으로 바뀌지 않는다.
- public website는 GitHub Actions가 만든 정적 HTML이 배포되어야 바뀐다.
- Mac launchd, 개인 컴퓨터 상시 실행, 로컬 자동 push는 운영 기준에서 제외한다.

## Local Recovery Guard

`services/newsletter/scripts/publish_newsletter_pages_local.sh`는 기본적으로 종료된다.
일회성 복구가 꼭 필요할 때만 아래처럼 명시적으로 실행한다.

```bash
NEWSLETTER_ALLOW_LOCAL_PUBLISH=1 services/newsletter/scripts/publish_newsletter_pages_local.sh --date YYYY-MM-DD
```

이 경로는 운영 자동화가 아니라 사고 복구 수단이다. 복구가 끝나면 다음 정기 발행은 다시 GitHub Actions가 맡는다.

## Deployment Guardrails

공개 배포는 빈 결과물을 그대로 덮어쓰지 않도록 막아야 한다.
GitHub Actions와 일회성 복구 스크립트는 다음 조건을 검사한다.

- `article_count > 0`
- `index.html`, `daily-news.html`, `archive.json` 존재

`lp_monitor_count`가 0이면 로컬 발행 스크립트는 경고만 낸다. LP 공고는 별도 탭/서비스이며 뉴스레터 Daily 본문 핵심 콘텐츠가 아니기 때문이다.

또한 deploy builder는 public mirror의 기존 `archive.json`을 seed로 읽어서, 같은 날짜의 기존 비어 있지 않은 뉴스가 새 0건 결과로 덮이지 않게 한다.

## When To Use Which

- 매일 공개 발행: GitHub Actions schedule
- 특정 날짜 재발행: GitHub Actions `Run workflow`
- 소스 품질, 분류, 키워드 룰 테스트: 로컬 개발 실행 후 source repo에 반영
- GitHub Actions 장애 복구: Project Lead 판단하에 `NEWSLETTER_ALLOW_LOCAL_PUBLISH=1` 일회성 복구
- 사용자에게 보여줄 최종 URL 확인: GitHub Pages public URL

## Direction

장기적으로는 GitHub Actions 안에서 수집 커버리지, 분류 품질, 요약 품질, 아이콘 품질을 모두 해결한다.
품질을 위해 개인 Mac 상시 실행에 의존하지 않는다.
