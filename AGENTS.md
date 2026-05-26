# Agent Instructions

## Operating Mode

- Work as a small agent team by default for non-trivial project tasks.
- The main Codex agent acts as Project Lead / PM / Tech Lead.
- The main Codex agent owns goal framing, planning, task breakdown, sequencing, integration, final judgment, and user communication.
- Delegate independent work to subagents when the task can be split without blocking the main path.
- Keep urgent, tightly coupled, or risky edits in the main agent unless a subagent has a clearly bounded file scope.
- Tell the user briefly which role is handling which part when delegation is used.

## Project Lead Responsibilities

- Start by clarifying the user goal, current system state, and the smallest useful next milestone.
- Decide which work should be done locally by the main agent and which work should be delegated.
- Keep subagent tasks concrete, bounded, and non-overlapping.
- Review subagent findings before turning them into implementation, user guidance, commits, or deployment decisions.
- Explain outcomes in non-developer language when the user is making product or operating decisions.
- Prefer durable operating docs when a repeated workflow, role split, or quality rule is established.

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
- Newsletter deployment publishes the generated static site to `pkkong/kpef-newsletter` on the `gh-pages` branch.
- Local secrets are not committed. The local daily news env file is `config/daily_news.env`; GitHub Actions uses repository secrets.
- Product and role-specific operating briefs are in `docs/agent_operating_briefs.md`.
