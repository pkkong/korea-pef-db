# 구조 계약

최종 수정: 2026-06-21 KST

이 문서는 말로만 정한 운영 규칙이 아니라, 실제 검사 코드로 강제되는 구조 계약을 정리한다.

## 서비스 경계

- 공통 유틸은 `services/shared/`를 기준으로 둔다.
- LP, GP, Wiki 코드는 `services.newsletter.src.*`를 직접 import하면 안 된다.
- 뉴스레터 단독 빌드와 Vercel 앱 런타임은 LP, GP, Wiki, 로컬 SQLite 서비스 빌더, legacy public-site renderer를 import하면 안 된다.
- LP 서비스 entrypoint는 module import 시점에 legacy LP renderer를 불러오면 안 된다.
- legacy LP renderer도 legacy all-in-one CLI가 GP/Wiki 페이지 생성을 명시적으로 요청하기 전까지 GP/Wiki module을 import하면 안 된다.
- 서비스 간 연계는 versioned public export/read model을 읽는 enrichment로만 구현한다. 다른 서비스의 canonical SQLite table을 foreign key로 참조하거나 write하면 안 된다.
- LP schema는 `gp_house`, `news_document` 같은 GP/Brief canonical table을 foreign key로 참조하면 안 된다.
- 생성 산출물은 source tracking 대상이 아니다. 특히 `services/newsletter/deploy/site/`, `exports/`, `public/`, local DB 파일은 직접 수정하거나 commit하지 않는다.

검사 명령:

```bash
python3 scripts/check_architecture_contracts.py
```

## GitHub Actions 역할

- `Build newsletter mirror`: 뉴스 수집, 뉴스레터 정적 빌드, GitHub Pages 백업 미러 publish/verify만 담당한다.
- `Sync newsletter Supabase read model`: 검증된 mirror archive를 내려받아 Supabase read model에 동기화하고 Vercel 앱을 검증한다.
- `Deploy newsletter Vercel app`: Vercel 앱 코드 배포만 담당한다.
- `Apply newsletter Supabase migration`: Supabase schema 변경만 담당한다.

뉴스레터 workflow의 mirror freshness, archive 다운로드, public mirror 검증, Vercel health 검증, watchdog 판단은 `services/newsletter/src/newsletter_public_status.py`가 담당한다.

즉 workflow YAML은 실행 순서와 secret 연결만 표현하고, 긴 Python 업무 로직을 직접 품지 않는다.

## 공개 화면 UX 계약

- 공개 하단 메뉴는 `브리프 / LP / GP`만 유지한다.
- Wiki는 사용자가 다시 기획하기 전까지 공개 메뉴와 routine build에서 숨긴다.
- LP/GP 디렉토리는 카드 묶음이 아니라 table-like row 구조를 유지한다.
- 데이터가 비어 있어도 LP/GP/Market 화면은 같은 row/table shell을 유지해야 한다.
- 공개 HTML/JS에는 내부 상태와 운영자 표현이 나오면 안 된다. 예: `candidate`, `monitor_status`, `review_status`, `public_visible`, `confidence`, `source/evidence`, `자동 생성`, `관리자`, `operator`.

검사 명령:

```bash
python3 scripts/check_public_frontend.py
```
