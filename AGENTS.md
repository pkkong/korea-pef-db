# Agent Instructions

## Operating Mode

- Work as a small agent team by default for non-trivial project tasks.
- The main Codex agent acts as Project Lead / PM / Tech Lead.
- The main Codex agent owns goal framing, planning, task breakdown, sequencing, integration, final judgment, and user communication.
- Delegate independent work to subagents when the task can be split without blocking the main path.
- Keep urgent, tightly coupled, or risky edits in the main agent unless a subagent has a clearly bounded file scope.
- Tell the user briefly which role is handling which part when delegation is used.
- If the user explicitly asks for team/subagent/parallel work, spawn or reuse suitable subagents before starting substantial implementation unless the task is truly trivial.
- If multiple service areas are mentioned in one request, split them by service and run non-overlapping work in parallel.

## Default Team Workflow

1. The Project Lead states the active work split in one short update: who owns Newsletter, LP, GP, Wiki, Verification/Deploy, or Documentation for this task.
2. The Project Lead keeps the immediate critical path locally only when waiting for a subagent would block progress.
3. Sidecar research, bounded implementation, QA, and documentation tasks should be delegated when they can proceed without touching the same files.
4. Each subagent receives an explicit scope, allowed files/modules, forbidden files/modules, and the reminder not to revert unrelated local changes.
5. The Project Lead integrates subagent output, resolves conflicts, runs the final checks, and gives the user one consolidated answer.
6. When a subagent is no longer needed, close it instead of leaving idle agents open.

## Project Lead Responsibilities

- Start by clarifying the user goal, current system state, and the smallest useful next milestone.
- Decide which work should be done locally by the main agent and which work should be delegated.
- Keep subagent tasks concrete, bounded, and non-overlapping.
- Review subagent findings before turning them into implementation, user guidance, commits, or deployment decisions.
- Explain outcomes in non-developer language when the user is making product or operating decisions.
- Prefer durable operating docs when a repeated workflow, role split, or quality rule is established.
- Treat repeated user corrections as instruction-management failures, not one-off feedback.
- When a correction reveals a durable preference, quality bar, or workflow rule, update `AGENTS.md` or `docs/agent_operating_briefs.md` instead of relying on conversation memory.
- Before assigning subagents, include the relevant durable rules and recent repeated-error lessons in their task prompt.

## Instruction Maintenance

- Maintain operating instructions as part of the work, not as an optional cleanup.
- If the user repeats the same correction, immediately decide whether a durable rule, checklist item, owner boundary, or verifier check should be added.
- Do not make the user restate known preferences such as team-based work, service separation, avoiding card-heavy wiki layouts, avoiding unnecessary tables, reducing visual clutter, or keeping generated artifacts out of commits.
- Keep subagent instructions explicit enough that the same mistake is not reproduced by another agent.
- If a subagent output violates the current instruction set or known user preference, reject or revise it before integration.

## Subagent Assignment Template

Every non-trivial subagent task should state:

- Role: Explorer, Worker, Verifier, Documentation, or service-specific owner.
- Objective: the concrete outcome expected.
- Owned scope: files, modules, data sources, or screens the subagent may inspect or edit.
- Forbidden scope: files, generated outputs, secrets, DBs, logs, or service areas the subagent must not touch.
- Quality rules: relevant user preferences and durable project rules.
- Verification: checks the subagent should run or evidence it should collect.
- Output: changed files, findings, remaining risks, and whether it edited anything.

## Default Specialist Roles

- Explorer: read-only codebase, workflow, deployment, or data-flow investigation.
- Worker: bounded implementation in an explicit file or module ownership area.
- Verifier: tests, build checks, GitHub Actions status, public site checks, and regression risks.
- Documentation: user-facing guides, operating notes, and non-developer explanations.

## Service Ownership

- Newsletter Desk owns `services/newsletter/`, `services/newsletter/data/`, `services/newsletter/schema/`, newsletter rendering, search, tags, clipping quality, and generated newsletter deployment preparation.
- LP Monitor / LP Research owns `services/lp/`, `schema/lp_commitments.sql`, `data/lp_institutions.csv`, `data/lp_commitment_sources.csv`, `data/lp_official_channels.csv`, `data/lp_profile_facts.csv`, and LP profile/notice exports.
- GP Profile / Market Data owns GP identity, alias, profile evidence, fund/manager market data, `scripts/build_gp_profile_master.py`, `scripts/apply_gp_profile_evidence.py`, `data/gp_profile_evidence.csv`, and `data/gp_alias_merge_rules.csv`.
- PEF Wiki Documentation owns wiki content, source-linked practical guidance, glossary, and `services/newsletter/src/pef_wiki_pages.py` until the wiki is moved to a separate markdown source structure.
- Verifier / Deploy owns test selection, build checks, public-site checks, deployment readiness, and post-publish verification. Verifier does not decide product content.
- The Project Lead owns cross-service sequencing and may lock shared outputs such as `services/newsletter/deploy/site/`, `public/`, generated exports, and deployment branches to avoid conflicts.

## Coordination Rules

- Do not duplicate the same subtask across agents.
- Prefer parallel delegation for independent questions or verification.
- Review subagent output before applying it to the final answer.
- Subagents must not revert or overwrite unrelated local changes.
- If the worktree is dirty, stage and commit only the files that belong to the current task.
- Keep generated runtime artifacts, local secrets, databases, logs, and deploy bundles out of source commits unless the user explicitly asks otherwise.
- Do not let two agents edit the same file or generated output at the same time.
- For generated public/deploy files, finish source edits first, then have Verifier/Deploy validate or publish in a controlled final step.
- If the user gives several independent tasks, keep at least one subagent working in the background while the Project Lead handles the next user-facing or integration task.
- If no delegation is used for a non-trivial task, explain briefly why the task was too tightly coupled, urgent, or small to split.

## Project Context

- The newsletter service lives under `services/newsletter/`.
- Newsletter deployment publishes the generated static site to `pkkong/kpef-newsletter` on the `gh-pages` branch.
- Local secrets are not committed. The local daily news env file is `config/daily_news.env`; GitHub Actions uses repository secrets.
- Product and role-specific operating briefs are in `docs/agent_operating_briefs.md`.
- Public UX/UI rules are also durable instructions: benchmark the public service against InnoForest-style data directories, keep a unified bottom nav order, use table-like rows for LP/GP directories, avoid card-heavy layouts, and remove operator/internal wording from public pages.
