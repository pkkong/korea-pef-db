# 작업 기록 보관

현재 상태 문서에서 옮겨 온 지난 기록이다. 내용은 원문 그대로 두고 고치지 않는다. 지금 유효한 상태·규칙은 `docs/` 바로 아래 문서와 `AGENTS.md`를 따른다.

## 구성

- `<문서명>/until-2026-11-13.md`: 2026-11-13 문서 분리 전의 전체 원문. 실행 ID·건수·당시 판단 근거를 찾을 때 본다.
  - `project_lead_control_center/`
  - `lp_collection_status/`
  - `lp_resume_checkpoint/`
  - `service_quality_backlog/`
- `<문서명>/YYYY-MM.md`: 이후 현재 문서에서 옮긴 날짜별 항목. 같은 달 파일 맨 위에 최신 항목을 붙인다.
- `notes/`: 특정 날짜의 검토·계획·완료 보고 문서(2026-06~09). 지금은 참고용이다.

## 옮기는 규칙

- 작업 시작 시 읽는 네 문서(`project_lead_control_center.md`, `lp_collection_status.md`, `lp_resume_checkpoint.md`, `service_quality_backlog.md`)는 각각 40KB 이하로 유지한다. `scripts/check_architecture_contracts.py`가 검사한다.
- 넘으면 가장 오래된 날짜별 항목부터 해당 달 파일로 옮긴다. 현재 상태 표·규칙은 옮기지 말고 고쳐 쓴다.
- 옮긴 기록을 근거로 현재 상태를 말할 때는 관측 날짜를 붙인다.
