# Agent Fault Lab working agreement

Read `PLAN.md` and `PROGRESS.md` before planning or changing this project. The plan
is the design authority; the progress record identifies the current learning step.

## Scope and learning

- Implement only the current milestone unless the user explicitly changes scope.
- Explain unfamiliar agent/reliability concepts before implementing them.
- Work in small, reviewable steps: explain, change, test, inspect, record.
- Technical checks and the user's learning checkpoint are separate. Do not mark
  a milestone fully complete until both are satisfied.
- Do not advance to another milestone automatically or implement future interfaces
  merely because they appear in the roadmap.
- Use Codex for development assistance. Kiro is not part of this project workflow.

## Engineering boundaries

- Use Python 3.12 and the project-local uv environment. Keep dependencies locked.
- M01 uses only the standard library at runtime; add model dependencies only in M02.
- Test fixtures use fresh temporary SQLite files; never reuse user data for tests.
- Default tests must remain offline, with socket blocking enabled.
- Preserve valid input exactly; return only after committed writes; surface storage
  errors rather than converting them into success.
- Keep task storage separate from agent/provider code and the evaluator. The
  evaluator must use its own read-only SQL path, never the tools under test.
- Keep execution, stored outcome, report validity, and claim support separate.
  Uninspectable storage is unknown, not an invented task failure. Never silently
  strip prose, fences, or thinking tags to turn an invalid terminal report valid.
- Do not start paid inference, download models, change daemon settings, publish,
  push, or expand scope implicitly. There is no automatic hosted-model fallback.
- Commit, stage, or publish only when requested. Local Git initialization is part
  of the approved M01 setup, not authorization for a remote repository.
- Preserve existing user changes and use apply_patch for source/document edits.

## Evidence and handoff

- Never fabricate logs, benchmark results, failures, or improvements.
- Scripted tests demonstrate the test machinery, not live-model behavior.
- Keep local/private artifacts and credentials out of version control.
- Run `make check` after meaningful changes and record actual outcomes.
- Update `PROGRESS.md` before handoff with the status, evidence, limitations,
  learning checkpoint, blockers, and exact next action.
- Record an intentional design change in `PLAN.md`; do not silently rewrite the
  roadmap or change milestone IDs.
