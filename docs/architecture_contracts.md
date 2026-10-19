# 구조 계약

최종 수정: 2026-10-19 KST

이 문서는 말로만 정한 운영 규칙이 아니라, 실제 검사 코드로 강제되는 구조 계약을 정리한다.

## 서비스 경계

- 뉴스레터·LP·GP는 각각 독립 Flask 앱·배포 패키지·Vercel 프로젝트를 가진다. 사용자 연결은 하단 메뉴와 HTTP redirect로만 제공하며 다른 서비스 응답을 기다리는 proxy를 만들지 않는다.
- 각 앱의 `services/<service>/web/`에는 자기 서비스의 데이터 adapter만 둔다. 뉴스레터 패키지에 LP/GP reader를 복사하거나 import하는 것도 금지한다.
- 세 앱의 스타일·아이콘·스크립트는 `services/shared/web/service_assets.py`의 순수 코드에서 가져오고 배포할 때 각 패키지에 복사한다. 다른 서비스 HTTP 주소에서 CSS/JS를 받아야 화면이 성립하는 구조는 금지한다.
- 빌드·배포는 선택한 서비스 패키지만 검증하고 올린다. 뉴스레터 배포에 LP 공고 생성·GP 데이터 검증을 포함하지 않는다. 공통 자산 변경은 각 서비스에 별도 배포한다.
- 같은 Supabase 제공자를 사용하더라도 읽는 테이블·발행 작업은 서비스별로 분리한다. 제공자 전체 장애·계정 한도·공유 DB 장애는 여전히 공통 위험이므로 앱 분리를 완전한 인프라 장애 격리라고 보고하지 않는다.
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
python3 -m unittest scripts.tests.test_service_runtime_isolation
```

분리 검사는 저장소와 형제 서비스가 없는 임시 디렉토리에 실제 앱 하나와 공통 자산만 복사해서 새 프로세스로 실행한다. 외부 네트워크와 형제 adapter import를 차단한 상태에서 자기 서비스 데이터 fixture로 루트·health·CSS·JS를 요청한다. 전체 저장소가 우연히 import 경로에 남아 분리 실패를 숨기지 않도록 `PYTHONPATH`도 임시 패키지와 Flask 설치 경로로 제한한다.

## GitHub Actions 역할

- `Build newsletter mirror`: 뉴스 수집, 뉴스레터 정적 빌드, GitHub Pages 백업 미러 publish/verify만 담당한다.
- `Sync newsletter Supabase read model`: 검증된 mirror archive를 내려받아 Supabase read model에 동기화하고 Vercel 앱을 검증한다.
- `Deploy newsletter Vercel app`: Vercel 앱 코드 배포만 담당한다.
- `Deploy LP Vercel app`, `Deploy GP Vercel app`: 각 서비스의 독립 실행 패키지와 프로젝트만 배포한다. 뉴스레터 배포 성공 여부는 의존성이 아니다.
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
