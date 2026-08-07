# Newsletter Vercel/Supabase Operating Notes

## Current Production Setup

- Vercel project: `kpef-newsletter`
- Vercel production URL: `https://kpef-newsletter.vercel.app`
- Vercel root directory: `services/newsletter/web`
- Supabase project: `kpef-newsletter`
- Supabase project ref: `fhigakwodmfjwtttwyyj`
- Source repo: `pkkong/korea-pef-db`
- Public static mirror: `https://pkkong.github.io/kpef-newsletter/`
- Public mirror repo: `pkkong/kpef-newsletter`, branch `gh-pages`

2026-06-16 기준 GitHub Actions secrets와 Vercel environment variables는 설정되어 있다.
비밀값은 문서, 로그, 코드에 기록하지 않는다.

## 운영 구조

```text
GitHub Actions
-> run_daily_news_pipeline.py
-> build_newsletter_bundle.py
-> validate_daily_news_pipeline.py
-> GitHub Pages mirror

GitHub Actions
-> sync_newsletter_supabase.py
-> Supabase newsletter_issues + newsletter_public_issue_articles

Vercel
-> services/newsletter/web/index.py
-> services/newsletter/web/app.py
-> Supabase newsletter_issues + newsletter_public_issue_articles
```

역할은 아래처럼 고정한다.

- `Build newsletter mirror`: 기사 수집, 분류, 중복 제거, 정적 미러 생성/검증, GitHub Pages publish/verify
- `Sync newsletter Supabase read model`: verified mirror archive를 Supabase에 동기화하고 Vercel health 검증
- `Deploy newsletter Vercel app`: Vercel 앱 코드 배포
- Supabase: 뉴스레터 read model 저장. 기본 동기화 범위는 static mirror와 맞춘 최근 30개 이슈다.
- Vercel: 사용자가 보는 웹 화면. 수집기나 장시간 빌드를 돌리지 않는 읽기 전용 런타임
- GitHub Pages: 정적 백업 미러와 archive fallback. canonical app은 Vercel

Vercel과 GitHub Pages가 모두 공개 URL을 갖지만 책임은 다르다. Vercel은 primary app이고,
GitHub Pages는 장애 시 확인 가능한 static mirror다.

두 공개 URL은 같은 UI 원본을 써야 한다. 뉴스레터 HTML/CSS/JS의 단일 원본은
`services/newsletter/web/newsletter_ui.py`이며, Vercel Flask app과 GitHub Pages 정적
builder가 모두 이 모듈을 사용한다. Vercel 전용 Jinja template이나 별도
`web/static/service.css`를 만들지 않는다.

Vercel archive는 Supabase에서 두 계층을 읽어 복원한다.

- `newsletter_issues`: 날짜 이동과 최근 30개 issue skeleton
- `newsletter_public_issue_articles`: 기사 내용, `rank`, `section_order`

`newsletter_public_issue_articles`만 읽으면 기사 0건 issue가 사라진다. `section_order=0`은
첫 번째 섹션이라는 정상 값이므로 fallback으로 덮으면 안 된다. Vercel의 article order와
section order는 GitHub Pages `archive.json`과 같아야 한다.

## Supabase 적용 순서

1. Supabase SQL editor에서 `services/newsletter/supabase/migrations/20260616090000_newsletter_read_model.sql`을 적용한다.
2. GitHub Actions secrets에 `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`를 넣는다.
3. Vercel project root를 `services/newsletter/web`로 잡는다.
4. Vercel env에 `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`를 넣는다.
5. DB schema를 바꿔야 할 때만 GitHub Actions `Apply newsletter Supabase migration`을 수동 실행한다.
6. GitHub Actions `Build newsletter mirror`를 수동 실행해 GitHub Pages mirror를 만든다.
7. `Sync newsletter Supabase read model` workflow가 이어서 Supabase sync와 Vercel health 확인을 수행한다.
8. Vercel `/health.json`에서 `data_source=supabase`와 최신 `report_date`를 확인한다.

운영 검증 기준:

- GitHub Actions `Deploy newsletter Vercel app`가 성공해야 한다.
- GitHub Actions `Build newsletter mirror`가 성공해야 한다.
- GitHub Actions `Sync newsletter Supabase read model`가 성공해야 한다.
- 정상 경로에서는 `https://kpef-newsletter.vercel.app/health.json?refresh=1`이 `data_source=supabase`를 반환해야 한다.
- `services/newsletter/web/vercel.json`에는 전체 요청을 `/index.py`로 보내는 catch-all rewrite를 두지 않는다. 이 설정은 Vercel Flask 라우팅에서 공식 URL을 404로 만들 수 있다.
- GitHub Actions나 Pages CDN 장애 중에는 Vercel이 raw `gh-pages` archive fallback으로 오늘자를 보여줄 수 있다. 이때
  `data_source=archive_fallback`, 최신 `report_date`, 최신 `article_count`이면 사용자 화면은 복구된 상태로 본다.
- `https://pkkong.github.io/kpef-newsletter/health.json`은 GitHub Pages CDN 반영 지연이 있을 수 있으므로,
  workflow 검증은 이번 빌드의 `built_at`과 `article_count`까지 비교한다.

## 자동 배포 Workflow

`Check newsletter Vercel readiness` workflow는 계정 연결 전에도 성공해야 하는
preflight다. 파일 존재, Python compile, import isolation, Flask smoke test,
필요 secret의 존재 여부를 보여준다.

`Deploy newsletter Vercel app` workflow는 Vercel 앱만 배포한다. 매일 08:37
뉴스레터 발행 workflow와 분리되어 있으므로, Vercel 쪽 장애가 daily publish를
막지 않는다.

`Apply newsletter Supabase migration` workflow는 Supabase schema 변경과 Supabase Cron 설치만 담당한다.
Vercel 앱 배포와 DB migration을 섞지 않는다. 이 workflow는 `services/newsletter/supabase/migrations/*.sql`을 순서대로 적용한다.

`Build newsletter mirror` workflow는 수집, 정적 미러 생성, GitHub Pages static mirror
publish/verify만 담당한다. GitHub Pages CDN 검증이 지연되어도 `gh-pages` 원본 archive push가 끝났으면
별도 Supabase sync workflow를 dispatch한다. Supabase sync와 Vercel app health 검증은 별도 workflow가 담당한다.

`Newsletter publish watchdog` workflow는 GitHub 내부 fallback 판단기다. primary
publish schedule이 GitHub 내부 지연/누락으로 실행되지 않았을 때 Vercel app과
sync 가능한 archive source를 확인한다. Pages mirror 또는 raw `gh-pages` archive 중 하나라도
오늘자이면 sync source가 fresh인 것으로 본다. sync source가 stale이면 mirror build workflow를
dispatch하고, sync source는 fresh인데 Vercel app만 stale이면 `Sync newsletter Supabase
read model` workflow만 dispatch한다. Vercel app이 `archive_fallback`으로 오늘자를 보여주면
사용자 화면은 fresh로 판단한다. 이 watchdog도 수집을 직접 하지 않는다.

Supabase external watchdog은 GitHub Actions 자체 장애로 primary schedule과 GitHub 내부 watchdog이 모두 누락되는 경우를 보완한다.
Supabase Cron은 09:05, 09:35, 10:05, 10:35 KST에 GitHub `Newsletter publish watchdog` workflow를 외부에서 dispatch한다.
이 기능은 Supabase Vault secret `newsletter_github_actions_dispatch_token`을 필요로 한다.

`Sync newsletter Supabase read model` workflow는 GitHub Pages mirror의 verified
`archive.json`을 읽어 최근 30개 이슈를 Supabase read model로 다시 동기화하고 Vercel health를 확인한다.
Pages URL이 stale이면 raw `gh-pages` archive를 fallback으로 사용한다.
Vercel/Supabase만 뒤처졌을 때 전체 뉴스 수집을 다시 돌리지 않기 위한 복구 경로다.

필요한 GitHub Actions secrets:

- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`
- `SUPABASE_DB_URL` optional: migration SQL을 Actions에서 직접 적용할 때 사용
- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`

`SUPABASE_DB_URL`은 `Apply newsletter Supabase migration`에만 필요하다. `VERCEL_*`
3개가 없으면 Vercel deploy 단계는 실패 처리한다.

## 장애 기준

- Supabase sync가 실패해도 GitHub Pages mirror 발행은 이미 끝난 뒤여야 한다.
- Vercel app은 Supabase가 비어 있거나 장애일 때, 또는 Supabase보다 raw/public archive가 더 최신일 때
  `archive_fallback`으로 사용자 화면을 먼저 복구한다.
- Supabase service role key는 GitHub Actions에만 둔다. Vercel에는 publishable key만 둔다.
- 정상 Daily publish 완료 기준은 Vercel `/health.json?refresh=1`의 `data_source=supabase`,
  최신 `report_date`, 최신 `article_count`와 GitHub Pages `health.json`/`archive.json`
  일치 여부다. 장애 중 임시 복구 기준은 Vercel `data_source=archive_fallback`과 최신 날짜/기사 수다.
- Vercel archive의 최신 issue order와 article row order는 GitHub Pages `archive.json`과 같아야 한다.
- 같은 날짜를 다시 sync할 때는 `newsletter_issue_articles`, tags, entities를 archive 기준으로 재생성하고 stale links를 남기지 않는다.
