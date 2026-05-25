# Agent Instructions

## Operating Mode

- Work as a small agent team by default for non-trivial project tasks.
- The main Codex agent owns direction, integration, final judgment, and user communication.
- Delegate independent work to subagents when the task can be split without blocking the main path.
- Keep urgent, tightly coupled, or risky edits in the main agent unless a subagent has a clearly bounded file scope.
- Tell the user briefly which role is handling which part when delegation is used.

## Default Specialist Roles

- Explorer: read-only codebase, workflow, deployment, or data-flow investigation.
- Worker: bounded implementation in an explicit file or module ownership area.
- Verifier: tests, build checks, GitHub Actions status, public site checks, and regression risks.
- Documentation: user-facing guides, operating notes, and non-developer explanations.

## Coordination Rules

- Do not duplicate the same subtask across agents.
- Prefer parallel delegation for independent questions or verification.
- Review subagent output before applying it to the final answer.
- Subagents must not revert or overwrite unrelated local changes.
- If the worktree is dirty, stage and commit only the files that belong to the current task.
- Keep generated runtime artifacts, local secrets, databases, logs, and deploy bundles out of source commits unless the user explicitly asks otherwise.

## Project Context

- The newsletter service lives under `services/newsletter/`.
- Newsletter deployment publishes the generated static site to `pkkong/kpef-newsletter`.
- Local secrets are not committed. The local daily news env file is `config/daily_news.env`; GitHub Actions uses repository secrets.
- Product and role-specific operating briefs are in `docs/agent_operating_briefs.md`.
