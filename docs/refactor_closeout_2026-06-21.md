# 2026-06-21 구조 정리 완료 보고

이 문서는 개발자 내부 로그가 아니라, 사용자가 이번 정리가 제대로 되었는지 확인하기 위한 완료 보고서다.

## 결론

- 공개 서비스 방향은 `브리프 / LP / GP`로 유지했다.
- Wiki는 재기획 전까지 공개 메뉴와 routine build에서 숨긴 상태로 유지했다.
- GitHub, Vercel, Supabase의 역할을 다시 분리했다.
- 중복된 GitHub Actions inline Python 로직을 테스트 가능한 Python CLI로 옮겼다.
- LP/GP/Wiki가 뉴스레터 내부 module에 직접 기대는 구조를 막았다.
- 공개 화면에 내부 상태나 운영자 표현이 새는지 자동 검사하도록 강화했다.
- 390px 모바일과 1280px 데스크톱에서 주요 화면을 실제 Chrome으로 확인했다.
- 이후 사용자 지적에 따라 commit, push, production deploy까지 완료했다.

## 무엇을 고쳤나

### 1. 서비스 경계

기존 문제:

- LP/GP/Wiki가 뉴스레터 내부 구현을 직접 import하는 구조가 있었다.
- 뉴스레터 단독 빌드가 다른 서비스 문제에 끌려갈 위험이 있었다.

이번 조치:

- 공통 helper 기준을 `services/shared/`로 고정했다.
- LP/GP/Wiki는 `services.newsletter.src.*`를 직접 import하지 않도록 정리했다.
- `scripts/check_architecture_contracts.py`를 추가해 이 경계가 깨지면 실패하게 했다.

확인 명령:

```bash
python3 scripts/check_architecture_contracts.py
```

정상 결과:

```text
OK architecture contracts
```

### 2. GitHub Actions 역할 분리

기존 문제:

- newsletter workflow 안에 긴 Python 코드가 직접 들어가 있었다.
- GitHub Pages, Supabase, Vercel의 책임이 다시 섞일 위험이 있었다.

이번 조치:

- `services/newsletter/src/newsletter_public_status.py`를 추가했다.
- mirror freshness, generated artifact 확인, Pages mirror 검증, Supabase archive 다운로드, Vercel 검증, watchdog 판단을 이 CLI로 옮겼다.
- workflow YAML은 실행 순서와 secret 연결만 담당하도록 줄였다.

역할 기준:

- `Build newsletter mirror`: 뉴스 수집, newsletter-only build, GitHub Pages 백업 미러 publish/verify.
- `Sync newsletter Supabase read model`: 검증된 mirror archive를 Supabase에 동기화하고 Vercel health 확인.
- `Deploy newsletter Vercel app`: Vercel 앱 코드 배포만 담당.
- `Apply newsletter Supabase migration`: Supabase schema 변경만 담당.

### 3. 공개 화면 UX

기존 문제:

- 데이터가 비어 있을 때 LP/GP/Market 화면 shell이 약해질 수 있었다.
- 디렉토리 화면이 table-like row 구조를 잃는지 자동으로 확인하기 어려웠다.
- 공개 화면에 내부 표현이 새는지 검사 기준이 부족했다.

이번 조치:

- LP 디렉토리 empty state도 `lp-directory-card` row 안에서 보이게 했다.
- GP 디렉토리 empty state도 `gp-card` row 안에서 보이게 했다.
- Market 데이터가 없어도 `market-trend-chart`, `market-rank-chart` shell이 유지되게 했다.
- `scripts/check_public_frontend.py`가 LP/GP row layout, 하단 메뉴, Wiki 숨김, 내부 표현 유출을 검사하게 했다.

확인 명령:

```bash
python3 scripts/check_public_frontend.py
```

정상 결과 예:

```text
OK public frontend check
```

### 4. 문서와 운영 상태판

기존 문제:

- 오래된 사건 로그가 현재 상태판에 너무 길게 남아 있었다.
- 현재 구조 계약과 실제 코드 검사가 한눈에 연결되지 않았다.

이번 조치:

- 과거 사건 로그는 `docs/project_history_archive.md`로 옮겼다.
- 현재 기준은 `docs/project_lead_control_center.md`에 남겼다.
- 코드로 강제되는 구조 규칙은 `docs/architecture_contracts.md`에 정리했다.
- 이번 완료 보고서는 이 파일, `docs/refactor_closeout_2026-06-21.md`에 따로 남긴다.

## 내가 직접 확인하려면

아래 명령이 모두 통과하면 이번 구조 정리는 로컬 기준으로 정상이다.

```bash
python3 scripts/check_architecture_contracts.py
python3 scripts/check_public_frontend.py
python3 services/newsletter/tests/test_public_status.py
python3 services/newsletter/web/tests/test_newsletter_data.py
python3 services/lp/tests/test_lp_notice_dedupe.py
python3 services/lp/tests/test_lp_notice_gp_link.py
```

뉴스레터 로직 전체 회귀는 아래 명령으로 확인한다.

```bash
python3 services/newsletter/tests/test_daily_news_logic.py
```

빌드는 아래처럼 확인한다.

```bash
python3 scripts/build_newsletter_bundle.py --date 2026-06-21 --archive-limit 30
python3 scripts/build_site_bundle.py --date 2026-06-21 --services newsletter,lp,gp --archive-limit 30
```

Supabase payload dry-run은 아래처럼 확인한다. 이 명령은 DB에 쓰지 않는다.

```bash
python3 services/newsletter/src/sync_newsletter_supabase.py --archive services/newsletter/deploy/site/archive.json --payload-out /tmp/newsletter_supabase_payload.json
```

## 이번에 실제로 통과한 검증

- Python compile 통과.
- `services/newsletter/tests/test_daily_news_logic.py`: 113 checks passed.
- `services/newsletter/tests/test_public_status.py`: 통과.
- `services/newsletter/web/tests/test_newsletter_data.py`: 통과.
- `services/lp/tests/test_lp_notice_dedupe.py`: 통과.
- `services/lp/tests/test_lp_notice_gp_link.py`: 통과.
- `scripts/check_architecture_contracts.py`: 통과.
- `scripts/check_public_frontend.py`: 통과.
- newsletter-only build 통과.
- `newsletter,lp,gp` 통합 build 통과.
- Supabase payload dry-run 통과.
- Vercel/Supabase readiness와 Flask smoke 통과.
- Chrome 390px/1280px smoke 통과.

## UX 확인 결과

로컬 Chrome으로 아래 페이지를 390px 모바일과 1280px 데스크톱에서 확인했다.

- `index.html`
- `lp-notices.html`
- `gps.html`
- `market.html`

확인한 내용:

- console error 없음.
- 하단 메뉴는 `브리프 / LP / GP`.
- Wiki 메뉴 노출 없음.
- 내부 표현 노출 없음.
- horizontal overflow 0px.
- LP/GP/Market은 데이터가 비어 있어도 row/table shell 유지.

스크린샷은 로컬 임시 경로에 남겼다.

```text
/tmp/kpef-*-mobile390.png
/tmp/kpef-*-desktop1280.png
```

## 아직 주의할 점

- 로컬 DB와 export가 비어 있어 이번 로컬 통합 빌드의 LP/GP 데이터 카운트는 0이다. 그래서 이번 UX 수정은 빈 데이터 상태에서도 화면 구조가 무너지지 않는지까지 검증했다.
- `services/lp/src/lp_legacy_service_pages.py`는 아직 남아 있다. 다만 import-time 결합은 차단했고, 남은 cleanup은 별도 품질 backlog에 남겼다.
- 새 아이디어는 바로 코드로 넣지 말고 담당 서비스, public read model, 화면 유형, 검증 명령이 정해진 뒤에 넣어야 한다.

## 배포 상태

- 커밋: `82e9737 refactor: enforce public service boundaries`.
- 원격 반영: `main`에 push 완료.
- GitHub Pages 백업 미러 배포: GitHub Actions run `27906187286` 성공.
- Vercel 앱 코드 배포: GitHub Actions run `27906187275` 성공.
- Supabase data sync: GitHub Actions run `27906477785` 성공.
- Supabase schema migration: 실행하지 않음.
- 공개 URL 검증:
  - Pages `health.json`: `report_date=2026-06-21`, `article_count=2`, `status=ok`.
  - Vercel `health.json?refresh=1`: `report_date=2026-06-21`, `article_count=2`, `issue_count=30`, `data_source=supabase`, `status=ok`.
  - `python3 scripts/check_public_frontend.py --base-url https://pkkong.github.io/kpef-newsletter/` 통과.
