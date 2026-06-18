# Cloud Newsletter Operations

## Short Answer

뉴스레터의 정식 수집/발행 경로는 GitHub Actions다. Mac은 매일 수집, 발행, 배포 경로에서 제외한다.

운영 기준은 다음과 같다.

- `Build newsletter mirror`: 매일 08:37 KST 자동 수집, 분류, 정적 사이트 생성, public mirror push/verify를 담당한다.
- `Sync newsletter Supabase read model`: verified public mirror archive를 Supabase에 복사하고 Vercel을 검증한다.
- GitHub Actions 수동 실행: 같은 workflow의 `Run workflow`로 특정 날짜를 재발행한다.
- 로컬 실행: 운영 발행에는 사용하지 않는다. 개발 진단은 가능하지만 publish/push 경로는 없다.
- Vercel: 사용자가 보는 primary app이다. 수집은 하지 않고 Supabase read model을 읽는다.
- GitHub Pages: 정적 백업 미러다.

## Operating Contract

- 자동 mirror 발행은 `.github/workflows/deploy-newsletter-pages.yml`의 `Build newsletter mirror`가 담당한다.
- Supabase/Vercel 반영은 `.github/workflows/sync-newsletter-supabase.yml`의 `Sync newsletter Supabase read model`이 담당한다.
- public mirror는 GitHub Actions가 `NEWSLETTER_PUBLIC_REPO_TOKEN`으로 push한다.
- Naver API 키는 GitHub repository secrets에 둔다.
- 로컬 DB/cache가 있어도 public website는 자동으로 바뀌지 않는다.
- public website는 GitHub Actions가 만든 정적 HTML이 배포되어야 바뀐다.
- Mac launchd, 개인 컴퓨터 상시 실행, 로컬 자동 push, 로컬 수동 publish는 운영 기준에서 제외한다.

## Recovery Path

장애 복구도 GitHub Actions에서 처리한다. private 원본 저장소의
`Actions` → `Build newsletter mirror` → `Run workflow`를 사용하고,
필요하면 `report_date`를 `YYYY-MM-DD`로 지정한다.

## Deployment Guardrails

공개 배포는 빈 결과물을 그대로 덮어쓰지 않도록 막아야 한다.
GitHub Actions는 다음 조건을 검사한다.

- `article_count > 0`
- `index.html`, `daily-news.html`, `archive.json` 존재

`lp_monitor_count`는 LP 공고 탭의 보조 상태값이다. LP 공고는 별도 탭/서비스이며 뉴스레터 Daily 본문 핵심 콘텐츠가 아니다.

또한 deploy builder는 public mirror의 기존 `archive.json`을 seed로 읽어서, 같은 날짜의 기존 비어 있지 않은 뉴스가 새 0건 결과로 덮이지 않게 한다.

## When To Use Which

- 매일 공개 발행: GitHub Actions schedule
- 특정 날짜 재발행: GitHub Actions `Run workflow`
- 소스 품질, 분류, 키워드 룰 테스트: 로컬 개발 실행 후 source repo에 반영
- GitHub Actions 장애 복구: workflow 수정 또는 `Run workflow` 재실행
- 사용자에게 보여줄 최종 URL 확인: Vercel app URL
- 백업 미러 확인: GitHub Pages public URL

## Direction

장기적으로는 GitHub Actions 안에서 수집 커버리지, 분류 품질, 요약 품질, 아이콘 품질을 모두 해결한다.
품질을 위해 개인 Mac 상시 실행에 의존하지 않는다.
