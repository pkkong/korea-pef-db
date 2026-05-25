# Local vs GitHub Newsletter Quality

## Short Answer

로컬 실행과 GitHub Actions 실행은 같은 Python 파이프라인을 쓰지만, 기본 실행 범위가 다르다.
따라서 제목 정리, 분류, 화면 렌더링 같은 기본 품질 기준은 같고, 기사 커버리지와 후보 수는 달라질 수 있다.

운영 기준은 다음과 같다.

- 로컬 Mac 실행: 공개 배포용 기본본. 더 넓게 긁고 더 자세히 확인한 뒤 GitHub Pages public mirror에 올린다.
- GitHub Actions: 수동 fallback. Mac이 꺼져 있거나 로컬 발행이 실패했을 때만 직접 실행한다.

## Main Differences

| 항목 | 로컬 실행 | GitHub Actions 실행 | 품질 영향 |
| --- | --- | --- | --- |
| 실행 위치 | 사용자 컴퓨터 | GitHub 서버 | GitHub는 로컬 캐시와 수동 DB 상태를 기본으로 갖지 않는다. |
| Naver 키 | `config/daily_news.env` 또는 환경변수 | GitHub Actions secrets | 둘 다 키가 있으면 Naver News API를 쓴다. 한쪽에 키가 없으면 결과 차이가 커진다. |
| 뉴스 소스 | 기본 활성 소스 전체 | workflow의 `NEWSLETTER_SOURCE_CODES` 지정 소스 | GitHub는 빠르고 안정적인 소스 위주라 커버리지가 좁을 수 있다. |
| 뉴스 수집량 | `run_daily_news_today.ps1` 기준 소스당 30개 | workflow 기준 소스당 5개 | 로컬이 더 많은 후보를 보므로 누락 가능성은 낮다. |
| 브리프 기사 수 | 보통 30개까지 후보화 가능 | 30개까지 후보화 가능 | 최종 노출 수는 같아도 GitHub는 앞단 후보 풀이 작다. |
| LP 공고 탭 | 소스당 50개 | 소스당 20개 | Daily 본문과 분리된 별도 페이지/서비스로 관리한다. |
| DB/캐시 | 기존 `db/private_equity.db`, raw cache, exports 활용 | 매 실행마다 GitHub 환경에서 새로 생성 | 로컬은 과거 캐시와 검수 흔적 덕분에 더 풍부할 수 있다. |
| 공개 배포 | public mirror에 자동 push | 수동 실행 시 public mirror에 push | 로컬 Mac이 primary publisher다. |

## Current Practical Judgment

GitHub 결과물이 항상 더 나쁘다는 뜻은 아니다. 공개 뉴스레터로 보기에는 충분히 쓸 수 있게 맞춰져 있다.
다만 로컬 Mac 실행이 더 넓게 훑고 로컬 DB/cache를 활용할 수 있으므로, 현재 운영의 기본 발행 방식은 로컬 Mac으로 둔다.

가장 큰 차이를 만드는 요소는 세 가지다.

1. GitHub의 `--limit-per-source 5`는 속도와 안정성 우선 설정이다.
2. GitHub는 지정된 22개 소스만 돌고, 로컬 기본 실행은 활성 소스 전체를 돌 수 있다.
3. GitHub는 로컬 DB, raw HTML cache, 수동 검수 파일을 기본으로 가져가지 않는다.

## Deployment Guardrails

공개 배포는 빈 결과물을 그대로 덮어쓰지 않도록 막아야 한다.
로컬 발행 스크립트와 GitHub fallback은 다음 조건을 검사한다.

- `article_count > 0`
- `index.html`, `daily-news.html`, `archive.json` 존재

`lp_monitor_count`가 0이면 로컬 발행 스크립트는 경고만 낸다. LP 공고는 별도 탭/서비스이며 뉴스레터 Daily 본문 핵심 콘텐츠가 아니기 때문이다.

또한 deploy builder는 public mirror의 기존 `archive.json`을 seed로 읽어서, 같은 날짜의 기존 비어 있지 않은 뉴스가 새 0건 결과로 덮이지 않게 한다.

## When To Use Which

- 매일 공개 발행: 로컬 Mac launchd 작업을 기준으로 한다.
- 기사 누락이 의심될 때: 로컬에서 더 넓은 source/limit으로 돌린다.
- 소스 품질, 분류, 키워드 룰을 손볼 때: 로컬에서 테스트하고 GitHub 설정에 반영한다.
- Mac 발행이 실패했을 때: GitHub Actions를 수동 fallback으로 실행한다.
- 사용자에게 보여줄 최종 URL 확인: GitHub Pages public URL을 본다.

## Direction

장기적으로는 GitHub 결과와 로컬 결과의 품질 차이를 줄이는 것이 맞다.
그러려면 GitHub에도 필요한 source/limit을 늘리되, 실행 시간이 길어지지 않도록 소스 그룹을 나누거나 캐시 전략을 붙여야 한다.
