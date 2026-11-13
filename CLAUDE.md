# CLAUDE.md

이 저장소는 GPT(Codex)와 Claude가 번갈아 작업한다. **공통 운영 규칙의 단일 원본은 `AGENTS.md`다.** 작업 전에 반드시 `AGENTS.md` 전체를 읽고 따른다. 이 파일에는 Claude에만 해당하는 차이만 둔다. 규칙을 바꿀 때는 이 파일이 아니라 `AGENTS.md`(또는 그 파일이 가리키는 `docs/` 운영 문서)를 고친다.

## 시작 순서

1. `AGENTS.md` — 특히 `Codex ↔ Claude Alternation` 절
2. `git status`, `git log -10` — 미커밋 변경은 Codex의 미완료 작업일 수 있다. 되돌리지 말고 체크포인트와 대조한다.
3. 작업 시작 문서 네 개: `docs/project_lead_control_center.md`, `docs/lp_resume_checkpoint.md`(맨 위 `현재 재개 지점`), `docs/lp_collection_status.md`, `docs/service_quality_backlog.md`. 지난 기록은 `docs/history/`에 있다.

## Claude 전용 읽기 규칙

- `AGENTS.md`의 "Codex", "main Codex agent"는 현재 작업 중인 에이전트, 즉 Claude 자신으로 읽는다.
- 하위 에이전트는 Claude의 Agent 도구로 실행하되, 인원 상한과 배정 템플릿은 `AGENTS.md`를 그대로 따른다.
- 예약 작업은 Codex automation이 꺼진 것을 사용자에게 확인한 뒤에만 만든다. 둘을 동시에 켜지 않는다.
- Claude Project 문서나 메모리에만 결정을 남기지 않는다. 기록은 저장소 문서와 commit이 기준이다.
- 체크포인트 항목에는 `작성: Claude`를 붙인다.
