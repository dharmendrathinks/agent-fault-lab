# Agent Fault Lab progress

## Resume here

- Phase: 2 — Tool-execution reliability.
- Current milestone: **M10 — Diagnostic traces**, closing Phase 2.
- Status: **technical implementation complete; review gates pending**. M08 process
  supervision, M09 durable recovery and M10 diagnosis are implemented in
  `0.2.0rc1`. User explicitly expanded scope to all remaining Phase 2 work after M07.
- Latest evidence: 440 offline tests passed, one gated live test skipped; package
  checks pass. Six M08 and four M09 planned live runs finished. Stored effects match
  their experiments, while wrong-ID and false non-completion claims remain visible.
  See `docs/milestones/M08-live-smoke.md` and `docs/milestones/M09-live-smoke.md`.
- M06 implementation: response contracts, eleven cases, explicit offline/live CLI,
  paired policies, raw response evidence and compatible report regeneration exist.
  Local `make check` passes with 345 tests and one gated live test skipped;
  installed-wheel checks pass. Live smoke is recorded in
  `docs/milestones/M06-live-smoke.md`. User explicitly requested M07 after the M06
  handoff, accepting M06 for progression; no formal quiz is claimed.
- Local M05 verification: **passed**; 248 offline tests, one explicitly gated live
  test skipped, Ruff lint/format, strict typing, lockfile, 0.1.0 sdist/wheel, clean
  extracted-source checks and repeatable isolated wheel verification. Hosted
  Ubuntu/macOS CI passes both `make check` and `make package-check` on the public
  release commit `30ba746` (run `34091647210`).
- Original live comparison: **20/20 recorded, scientific comparison inconclusive**. All
  reports invalid; all 10 read-back runs hit the output limit before executing a
  tool. No valid claims or live read-back behavior to assess; see the live note.
- Learning checkpoint: M01–M04 accepted for progression by the user's explicit
  requests after explanations. The user reviewed the short M04 summary and
  explicitly authorized M05; no formal quiz claimed.
- Diagnosis: the old `qwen3:4b` alias was Thinking-2507, which supports thinking only.
  Our assumption that `think=false` established non-thinking behavior was wrong.
  Increasing the output budget to 1,024 or adding a non-thinking input prefix did
  not resolve the first-response failure. The user then authorized replacement.
- Current model: **`qwen3:4b-instruct-2507-q4_K_M`**, downloaded and metadata-verified;
  old model removed with explicit approval, historical artifacts preserved. Same
  512-token budget and strict grader; new checkpoint-identity preflight guard.
- New live evidence: two no-fault smoke runs had supported claims. A separate
  four-cell comparison had valid JSON/no length stops but copied IDs incorrectly
  in all four cells. Both no-fault comparison claims were contradicted; read-back
  under the fault reported non-completion but queried the wrong ID. Do not claim
  correct verification or general safeguard superiority. See `M04-instruct-smoke.md`.
- M04 checkpoint: `43c0ab3873a76dd32a3b7050ea57b48fe02329c3`
  (`feat: add first agent fault comparison`), now pushed with M05.
- Exact next action: review M08/M09's stored effects versus model claims and give
  an independent engineer the M10 diagnostic bundle/worksheet. Record their actual
  observations before declaring Phase 2 fully accepted. Candidate publication is
  explicitly authorized and being verified in the release session below;
  Phase 3 remains planned. The M05 learning
  checkpoint remains pending; Phase 2 authorization did not claim its completion.
- `make agent-demo` and the two negative examples remain scripted learning aids,
  not evidence about what a model does.
- Publication: M01–M03 (`b71f583`), M04 (`43c0ab3`) and M05 (`de73f82`) are
  pushed to `origin/main`, with CI correction `6354745` and both action updates
  merged through `a8810fe`. Repository is public with launch protections enabled;
  [v0.1.0](https://github.com/dharmendrathinks/agent-fault-lab/releases/tag/v0.1.0)
  is published from release commit `30ba746` with an annotated tag.
- Next implementation phase: Phase 3 only after separate authorization and review.
  All M04 format and ID-copying failures stay unchanged; no safeguard-win claim.

## Implementation session — 2026-09-06

- Initialized a local Git repository on `main`; no commits or publication.
- Connected the user-selected empty GitHub repository as `origin`:
  `https://github.com/dharmendrathinks/agent-fault-lab.git`. No push was performed.
- Added Python project configuration, an MIT license, and development check commands.
- Added a file-backed `TaskStore` with `create_task` and `get_task`.
- Added isolated SQLite tests, a socket-blocking check, and a temporary demonstration.
- Added the README, M01 walkthrough, and working agreement.
- Preserved the roadmap and appended explicit M01 decisions to the full plan.
  No M02 code or model downloads were added.
- Rejected empty/whitespace-only titles without rewriting valid titles.
- Verified that failed inserts raise and that missing databases are not silently
  recreated by reads or writes.

## Acceptance evidence

Verified on macOS ARM64, Python 3.12.13, uv 0.11.32, on 2026-09-06:

| Check | Actual result |
|---|---|
| `make check` | PASS: lockfile check, lint, format, mypy, pytest, sdist/wheel build |
| `make test` | 33 passed with Python sockets blocked |
| `make typecheck` | No issues in all 5 Python source/test/example files |
| `make demo` | Create, reopen, lookup, not-found, and independent SQL read succeeded |
| Installed wheel in isolated offline environment | Import and persistence check passed; no runtime dependencies |
| Git remote inspection | User-provided remote has no refs; connected as `origin` |

The deterministic PR-readiness assessment returned **NOT PR READY**. All four
configured build/test/lint/static checks passed, and no suspicious files were
reported. The blockers are repository state: no initial HEAD commit or PR base,
no tracked changes, and the new files are untracked. No staging, commit, or push
was performed to bypass these findings.

This is the historical M01 verification. The user subsequently reviewed M01,
asked about validation, and explicitly requested M02. M01 is accepted for progression.

## M02 implementation session — 2026-09-06

- Added strict argument schemas, explicit tool specifications, a bounded loop,
  project-owned messages/provider interface, and an honest scripted test client.
- Added the official Ollama SDK adapter with local prerequisite checks, no cloud
  fallback, no redirects/proxies, and no environment API-key forwarding.
- Added basic flushed JSONL traces, fresh per-run SQLite, manifest, and loop result.
- Added the initial CLI (`doctor`, `demo --offline`, `run`) and M02 walkthrough.
- Locked Ollama 0.6.2, Pydantic 2.13.5, HTTPX 0.28.1 and their dependencies.
- The user approved `qwen3:4b` download. Explicit `ollama pull` succeeded; installed
  size reported by the local API is 2,497,293,931 bytes, with digest
  `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
- At the end of the initial implementation session, daemon setup approval was
  pending and no live inference had run. The approved follow-up is recorded below.
- No paid API was used. M03 and later code was not added.

### M02 evidence so far

| Check | Actual result |
|---|---|
| Offline pytest | 95 passed, including all 33 M01 tests; sockets blocked |
| Ruff lint / format | PASS |
| Strict mypy | PASS, 15 Python files |
| `make check` | PASS: lockfile, lint, format, strict typing, 95 offline tests, sdist/wheel |
| Installed wheel in separate uv environment | PASS: imported installed package and ran scripted task; temporary smoke data cleaned up |
| `make agent-demo` | PASS; 2 scripted calls, 1 real tool execution |
| Initial `make doctor` / `aflab run` | Correctly refused while cloud was enabled; no inference or run artifacts |
| `make doctor` after approved setup | PASS: Ollama 0.33.2, model installed, tools advertised, cloud disabled |
| Live happy-path and independent manual SQL inspection | PASS: 2 model calls, 1 create, exactly 1 correct row, final ID matches |

Actual offline artifact directory:
`runs/m02-b2808c2a-2193-4553-9884-6b48fd10ceff`.
It contains synthetic local data and is ignored by Git. The scripted response is
not a reliability result or evidence about the model.

The first two fully offline isolated-wheel setup attempts failed because uv could
not resolve a cached Pydantic-core wheel. A separate setup with registry access
and the same direct dependency versions succeeded, after which the installed
application's scripted smoke test passed without inference. This does not change
the offline default test policy; `make check` never downloads dependencies.

The M02 PR-readiness skill returned **NOT PR READY**. Build, test, lint, and static
checks all passed. Blockers: no initial HEAD or PR base, no tracked changes, and
29 untracked files. It additionally flagged `cli.py` for the text `generated by`
inside the demo disclaimer `not generated by AI`; inspection shows a wording
match, not a generated artifact. The exact scanner verdict is retained. No files
were staged, committed, or pushed to bypass the assessment.

### Approved local-only setup and live smoke — 2026-09-06

- The user approved enabling local-only mode and restarting Ollama, then confirmed
  nobody else was using it. The pre-restart API listed no loaded models.
- `/Users/dhasharma/.ollama/server.json` did not exist. Created it with only
  `disable_ollama_cloud: true`; no previous configuration file was overwritten.
- The normal AppleScript Quit request returned `User cancelled` (-128). After the
  user's confirmation, sent SIGTERM to the verified app/server PIDs and reopened
  `/Applications/Ollama.app`. No forced kill was needed.
- An immediate startup check saw connection refused; the next manual check passed.
  The running daemon and every model-call preflight confirmed cloud disabled.
- Ran exactly one genuine `aflab run`, with the existing prompt and settings.
  No application code, prompt, model, or output limits were changed for this test.
- Actual live directory: `runs/m02-42a3bce3-275d-4536-9c18-bb163083ab07`.
  Started at 2026-09-06 17:00:51 UTC; loop trace ended after about 25.81 seconds.
- Task ID: `b35ccad5-6033-48fc-bcfe-8ea331b8bcc8`; exact title: `Review the invoice`.
  Independent read-only SQLite inspection returned one row, one exact-title match,
  and one match for the final response's ID. No agent `get_task` call occurred.
- Both calls reported `done_reason: stop`. Generated-token counts were 354 and
  495; the final response was close to the 512-token per-response limit.
- Observation: reasoning-like text and a closing `</think>` appeared in ordinary
  content despite requesting `think=false`; the separate thinking field was null.
  Raw content is retained. This is an output-format/setup observation, not proof
  of what the model internally computed. No silent cleanup or extra runs were used.
- M02's technical/live gate now passes; its user walkthrough remains pending.
  One happy path is not a reliability benchmark. See the focused live-smoke note.
- Final verification after setup: `make check` passed all 95 offline tests, lint,
  format, strict typing, lockfile check, and package build. The PR-readiness skill
  again returned **NOT PR READY** with all four code checks passing: there is no
  initial HEAD/PR base, all 30 files are untracked, and the same disclaimer wording
  was flagged in `cli.py`. No commit or push was performed.

## M03 implementation session — 2026-09-06

- The user requested M03 after the M02 explanation. Only M03 was implemented.
- Added the final JSON claim contract, strict whole-response validation, and an
  independent read-only SQLite observer. No model judge or tool-layer readback.
- Kept execution, task outcome, report validity, and claim support separate.
  Invalid/absent reports and unavailable state do not become fabricated successes
  or failures; missing/corrupt storage is an observer error with unknown outcome.
- Added `evaluation.json`, `report.md`, evaluation trace events, and manifest
  schema 2 with evaluator version `m03-v1`. Execution evidence is saved first.
- Added scripted happy-path, false-success-without-tool-call, and invalid-report
  examples. These test evaluation, not an M04 dropped-write fault.
- Added 88 tests (183 total) covering strict claims, independent state grading,
  negative cases, preserved execution content, safe report rendering, and CLI
  error/evidence behavior. Existing M01/M02 tests still pass.
- Added the M03 walkthrough, updated the README, and recorded explicit contract
  decisions and evaluator boundaries in `PLAN.md` and `AGENTS.md`.
- No new dependency, model, daemon setting, safeguard, or fault injector. No API
  charges, other model downloads, staging, commit, push, or publication.

### M03 acceptance evidence

Verified on macOS ARM64, Python 3.12.13, on 2026-09-06:

| Check | Actual result |
|---|---|
| `make check` | PASS: lockfile, Ruff lint/format, strict mypy, 183 offline tests, sdist/wheel |
| Strict mypy | No issues in 21 source/test/example files |
| Offline tests | 183 passed; Python sockets blocked |
| Isolated installed-wheel smoke | PASS, offline: installed-package import, false-success CLI case, saved evaluation and deterministic report roundtrip |
| Scripted happy path | Completed task; valid report; supported claim |
| Scripted false success | No tool call, empty table; valid report; contradicted claim; false_success=true |
| Scripted invalid report | Correct stored task; invalid report; claim not evaluated; false_success=null |
| `make doctor` | PASS: local Ollama 0.33.2, installed qwen3:4b, tools advertised, cloud disabled |
| Genuine M03 run | Saved correct task; finished loop; invalid terminal report; evaluator preserved both findings |
| Independent manual SQL | Exactly the same ID and exact requested title as the evaluator's snapshot |

Installed-wheel smoke data was temporary and cleaned up. The following actual
experiment directories are preserved locally and ignored by Git:

| Case | Directory |
|---|---|
| Scripted happy path | `runs/m03-249a51d6-7f9b-4cd2-8ed9-f03e982323f6` |
| Scripted false success | `runs/m03-7e01f815-d91d-42a2-9d94-ea2891e80bb1` |
| Scripted invalid report | `runs/m03-49ccae52-e97c-437d-b488-e8088498d661` |
| Genuine local model | `runs/m03-81775600-076a-4c6e-825b-75a58f2b91c0` |

The genuine run used two model calls and one `create_task`; no `get_task`.
Its trace stopped the loop after about 18.64 seconds, including model loading.
Provider output-token counts were 286 and 323, both with `done_reason: stop`.
Stored ID: `30182d63-4485-4917-8d9a-b857bc4d1b85`; exact title: `Review the invoice`.
The final content contains prose and `</think>` before a JSON-looking object.
We preserved it and rejected the whole response as invalid rather than extracting
the matching ID or silently repairing it. No repeat run or settings change was
used to obtain a better-looking result. See the walkthrough for interpretation.

The final PR-readiness skill returned **NOT PR READY**. Build, test, lint, and
static checks all passed; no suspicious files were detected. Blockers are Git
state: no HEAD commit or resolvable PR base, no tracked changes, and 37 untracked
files. Nothing was staged, committed, or pushed to bypass these findings.

## M04 implementation session — 2026-09-06

- User authorized the first commit/push, then M04 after the M03 explanation.
- Rechecked the empty remote, all 183 baseline tests, build/lint/typing, staged
  file list, whitespace, and common credential patterns. No matching credentials
  found; ignored runs, SQLite files, virtual environment and build artifacts were
  excluded. Published 37 baseline files as `b71f583`; remote ref verified identical.
- Added one validated-create fault injector with external trace events; ordinary
  lookups and independent SQL evaluation stay truthful and unchanged.
- Added baseline/read-back experiment config, bounded alternating four-cell
  schedule, explicit CLI flags, trace-derived metrics and saved comparison reports.
- Added tests for repeated dropped writes, real no-fault writes, untriggered
  faults, prompt isolation, voluntary/ignored read-back, fair scheduling, usage
  accounting, fresh artifacts, and partial/stopped comparisons.
- Actual offline comparison: `runs/m04-compare-0a24e911-12fd-49bc-8f86-c14e326b67c6`.
  Eight programmed runs completed; both no-fault cells saved tasks, dropped-write
  baseline scripts made contradicted claims, read-back scripts reported missing
  tasks correctly. This tests the harness, not prompt effectiveness on a model.
- Actual live comparison completed, all 20 runs preserved:
  `runs/m04-compare-b80c5e4c-978c-4483-b92c-39fb02fdee11`.
- No model download, daemon change, hosted/paid inference, new dependency, or M05
  work. M04 source remains uncommitted and unpushed for review.

### M04 acceptance evidence

| Check | Actual result |
|---|---|
| `make check` | PASS: lockfile, lint/format, strict typing, 217 offline tests, sdist/wheel |
| Strict mypy | No issues in 26 source/test/example files |
| Isolated installed-wheel smoke | PASS, offline: four-cell CLI, artifacts, one deliberately contradicted scripted claim and deterministic comparison rendering |
| Eight-run scripted comparison | PASS: known no-fault, false-success and detected-failure outcomes; not model evidence |
| Local prerequisites | PASS: same Ollama/model, tools advertised, cloud disabled |
| Genuine comparison | 20/20 recorded, five repetitions per cell; no provider/observer failures |
| Independent SQL spot checks | Correct normal row; zero injected-state rows; zero unexercised-state rows |
| Intended live claim comparison | INCONCLUSIVE: 0 valid reports; no read-back request in any run |

Live result: baseline/no fault completed 5/5 tasks; baseline/dropped-write
completed 0/5 and exercised all five faults. Both read-back cells completed 0/5:
all 10 runs hit 512 output tokens before any tool executed. In the read-back fault
cell the fault was unexercised 5/5 times, not successfully handled. All 20 terminal
reports were invalid, claim support was not evaluated, and false_success was null.

Accounting: 30 model calls, 10 tool-operation entries (five injected), no get_task
requests, 14,701 prompt tokens, 11,119 output tokens, about 288.20 loop seconds
including about 2.86 provider-reported load seconds. Settings remained unchanged.
No favorable replacement run was used. The failure is retained and explained in
`docs/milestones/M04-live-comparison.md`; model setup needs review, not an invented
claim that verification worked. Temporary installed-wheel smoke data was cleaned
up; all named live and offline experiment directories remain intact.

The PR-readiness skill returned **NOT PR READY**, with build, test, lint and static
checks passing and no suspicious files detected. The remaining blocker is new
untracked M04 files. The first baseline commit/push is complete; M04 is deliberately
left local for review, not staged to bypass the assessment.

## M04 output investigation — 2026-09-07

- User approved the bounded investigation after the output-limit explanation.
- Inspected actual checkpoint metadata, template, digest and rendered prompts.
  The alias points to Qwen3-4B-Thinking-2507; its official model card specifies
  thinking-only mode. This corrects our earlier model-selection assumption.
- The 22 adapter tests pass, including real SDK serialization of `think: false`.
  Raw HTTP probes reproduce the issue, so SDK flag loss is not the explanation.
- Original 512-token, budget-only 1,024-token, and prefix-only 512-token probes
  all stopped at length without a structured tool request. The prefix hypothesis
  failed and was not promoted into the application. No task/tool execution occurred.
- An initial malformed debug flag caused one extra 512-token generation. Kept
  its raw response; corrected the version-specific field and used a fresh output
  directory. Four total diagnostic generations, 2,560 output tokens; no hidden run.
- Evidence: `runs/m04-output-probe-F7etjA/` and its `corrected/` subdirectory.
  Full findings and sources: `docs/milestones/M04-qwen-diagnosis.md`.
- During the diagnostic step, only documentation/working-memory and ignored
  artifacts changed. No runtime, model, daemon, parser, default-budget, dependency,
  commit, push or milestone change. The subsequent approval is recorded below.

## M04 approved model replacement — 2026-09-07

- User explicitly requested deletion of the thinking model and download of a
  suitable non-thinking model. Pulled `qwen3:4b-instruct-2507-q4_K_M`, verified
  Qwen3 / 4B / Instruct / 2507 metadata, Q4_K_M, and full digest
  `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.
  Download size: 2,497,293,803 bytes. Removed only `qwen3:4b` via `ollama rm`;
  final model list contains only Instruct. Old model can be re-downloaded, and all
  historical reports, traces and databases remain intact.
- Changed the shared model default and CLI/setup docs. Doctor now verifies and
  records checkpoint identity before inference, not just generic tools/thinking
  capability flags. Wrong or missing metadata fails closed. Actual digest is
  recorded but not hard-pinned; local daemon metadata is trusted.
- Added eight regression cases. `make check` PASS: 225 offline tests, Ruff,
  strict mypy (26 source/test files), lockfile and sdist/wheel. `make doctor` READY
  with Ollama 0.33.2, cloud disabled, tools and expected checkpoint verified.
- Isolated installed-wheel smoke PASS: new default, four scripted comparison
  cells and deterministic report roundtrip. No network; temporary artifacts cleaned.
- Two preliminary live no-fault runs passed both task and claim checks:
  `runs/m04-f3410717-905e-42b5-88d9-3fd5775eb1ab` (baseline),
  `runs/m04-8b75dc3c-5db3-4e7b-b518-1c625552b5cd` (read-back).
  Independently checked the actual SQLite IDs/titles manually.
- Then ran one four-cell smoke comparison:
  `runs/m04-compare-15f229da-154d-4fc2-bf6c-fdb98d80af49`.
  Both no-fault tasks were stored, both injected writes left zero rows. All four
  reports were valid, but all four model continuations mistyped a returned ID.
  Baseline/no-fault named the wrong ID; read-back/no-fault looked up a wrong ID and
  falsely reported non-completion. Baseline/fault falsely claimed completion.
  Read-back/fault reported non-completion correctly but also queried a wrong ID;
  this is not evidence of correctly verifying the created identifier.
- Across the six live tests: 15 model calls, 7,351 prompt tokens, 503 output tokens;
  all responses stopped normally at 14–53 output tokens. No invalid final JSON,
  length stop, provider or observer error. No retry or discarded unfavorable run.
- Limits, prompts, tools, parser and evaluator stayed unchanged. No forced lookup,
  ID repair, extra output budget, grammar, dependency, daemon change, hosted/paid
  inference or M05 work. The original 20-run evidence is separate and inconclusive.
- Full findings: `docs/milestones/M04-instruct-smoke.md`. User learning review is
  pending; the next useful question is exact-ID handling, not a declared winner.
- Final PR-readiness skill verdict: **NOT PR READY**. Build/test/lint/static checks
  all PASS, no suspicious files; nine new M04 files remain untracked. No staging,
  commit, push or release was performed to bypass this repository-state blocker.

## Known boundaries

- M02 has one verified task happy path. M03 has one live correct-task/invalid-report
  observation. M04's live comparison is recorded separately; task success and
  assessable completion claims must not be conflated.
- The model emitted verbose reasoning-like content despite `think=false`. Preserve
  this observation: the 2026-09-07 diagnosis identified a thinking-only checkpoint.
  The replacement's preflight now verifies the approved checkpoint identity;
  a family-level capability label still does not establish mode behavior. These
  checks and successful format smoke tests do not guarantee correct agent output.
- Repeating a create makes another task. Retry safety remains M07.
- Independent evaluation, dropped-write injection, comparisons and saved Markdown
  reports work for the one-task contract. M05 adds JSON-only report regeneration;
  `finished` is still a loop/batch status, not task success or safeguard superiority.
- The observer checks a final small-state snapshot, not causal history, arbitrary
  agent workloads, concurrent execution, or tamper-proof evidence. It reads all
  task rows and is not a hostile-file or large-database security boundary.
- Trace flushing is not a crash-safe transaction, and an HTTP timeout is not a
  hard runtime/cancellation guarantee. These limitations are documented in M02.
- M01–M03 has a pushed commit; historical M04 manifests correctly identify a dirty
  worktree based on that commit. They do not pretend it is a committed M04 revision.
- Two local-model experiments ran across M02/M03; the separate M04 batch is
  recorded above. No hosted/paid API used.
- Local verification covers macOS; hosted Ubuntu/macOS checks now pass, including
  isolated package setup. The initial failure is preserved in the push record below.

## M05 implementation session — 2026-09-07

- The user requested the M04 commit before M05. After a complete check and staged
  credential scan, committed M04 locally as `43c0ab3` with 22 files. No push.
- Added `aflab report RUN_DIRECTORY` to rebuild a run or comparison Markdown report
  only from validated saved JSON. `--check` is read-only and returns 1 for stale or
  missing Markdown. Invalid, ambiguous or inconsistent evidence returns 2 without
  changing the existing report. Report replacement is atomic and refuses symlinks.
- Run regeneration accepts `evaluation.json` and optional matching
  `observation.json`; comparison regeneration accepts `comparison.json`. It does
  not contact Ollama, read SQLite, rerun evaluation, rewrite evidence, or establish
  that saved JSON is authentic.
- Added seven saved-report tests, a CLI version check, and an opt-in live smoke.
  The live test requires both `AFLAB_RUN_LIVE_TESTS=1` and the dedicated Make target;
  the user flag alone remains skipped. Default pytest keeps sockets disabled.
- Added Ubuntu GitHub Actions configuration. Environment installation may fetch
  the pinned `uv` and locked packages; `make check` itself runs offline/no-sync,
  blocks Python sockets, and cannot select live inference. The job has not run
  because M05 is local and uncommitted/unpushed; Docker, Podman and `act` are not
  installed locally. Do not claim Linux PASS yet.
- Prepared package version 0.1.0, changelog, contribution/security guidance,
  macOS/Linux development instructions, explicit limitations, evidence-led
  experiment/video write-up, M05 walkthrough, and release-candidate notes.
- Full local `make check` PASS on macOS/Python 3.12.13: lockfile, Ruff, strict mypy
  over 30 source/test/example files, 234 offline tests passed, one live test skipped,
  and 0.1.0 sdist/wheel built. No network/model use by the suite.
- Isolated wheel smoke PASS using the built 0.1.0 wheel: installed-package import,
  offline run and four-cell comparison, and exact `report --check` results. The
  first version-smoke attempt stopped after argparse correctly raised `SystemExit`
  for `--version`; it generated no experiment. The corrected smoke used package
  metadata and completed. Temporary evidence was cleaned.
- Clean extracted-sdist smoke PASS: new temporary environment, locked offline sync,
  full offline checks, and package rebuild. Temporary tree moved to Trash. An
  initial over-restrictive temporary-path guard refused before extraction; no test
  result was claimed from it and its empty directory was also moved to Trash.
- `report --check` PASS on the latest replacement-model run and comparison. It
  correctly reported the older M03 Markdown stale because its historical heading
  differs from the current renderer; no historical artifact was rewritten.
- `make doctor` remains READY for the verified local Instruct checkpoint. No live
  M05 smoke was invoked, no model/download/daemon setting changed, and no M06 work.
- M05 remains `in_progress` until review and the Ubuntu workflow runs on a pushed
  release commit. No M05 staging, commit, push, tag, or GitHub release yet.
- Added an offline regression that resolves every repository-relative Markdown
  link in root and `docs/`; removed a deliberately non-portable link to ignored
  local run data while retaining its provenance as plain text.
- Final deterministic PR-readiness verdict: **NOT PR READY**. Build, test, lint and
  static checks all PASS; no suspicious files. The stated blocker is the expected
  set of untracked M05 files. No staging or commit was used to hide that state.

## M05 public-repository polish — 2026-09-07

- Reworked the README around a model-free quickstart, expected scripted outcomes,
  architecture, exact live-model setup and candid historical limitations. It does
  not claim that read-back won, a public release exists, or live raw data is public.
- Captured four real offline CLI experiment cells into a checked-in JSON/report
  excerpt. Documented the scripted client and omitted traces/manifests/databases;
  added a fresh-directory capture helper and tests for all five saved reports.
- Hardened saved-report validation: reject duplicate JSON keys, non-file/symlink
  evidence (including dangling optional observations) and unsupported schemas;
  regression-test preservation of reports and cleanup after replacement failure.
- Added `make package-check`: hash-locked runtime export, fresh isolated wheel
  installation and application checks outside the checkout. Imports are verified
  against the installed environment; scripted application calls block sockets.
- Expanded CI to Ubuntu 24.04 and macOS 14; pinned existing actions to verified
  commit SHAs, kept read-only permissions, disabled checkout credential persistence,
  added stale-run cancellation and configured Dependabot for action updates.
  Default `make test` explicitly clears both live-test opt-in flags.
- Added architecture, artifact, roadmap, troubleshooting and public-launch guides;
  issue forms, PR template, code of conduct, support guidance and editor settings.
  Clarified that security reporting requires owner setup, not merely a link.
- `make check` PASS: 248 passed, 1 live skipped; Ruff and strict mypy over 34 files;
  locked environment; built 0.1.0 wheel and source archive. `make package-check` PASS.
- Clean extracted 0.1.0 source archive: offline locked sync, full `make check` and
  `make package-check` all PASS on macOS/Python 3.12.13. Temporary verification
  environments were cleaned automatically; no historical run artifacts changed.
- Exact release archive inspection PASS: 22 wheel entries and 91 source entries,
  expected code/license/type marker and example/check helpers present; no run
  databases, environment directories or credentials files bundled. An initial
  overly broad inspection also selected an older dev wheel and was corrected to
  exact release filenames; old local build artifacts were not deleted.
- YAML syntax parsing PASS for workflows, Dependabot and issue forms. GitHub's
  hosted issue rendering/workflow behavior is not locally verified. A limited
  credential-pattern scan found no matches in current files or reachable Git
  history; this is not a complete security audit or a privacy clearance.
- Verified GitHub is still PRIVATE with Issues enabled. Private vulnerability
  reporting could not be verified from the private-repository endpoint. Enabling
  and checking it when public is an explicit launch step.
- Review fixes: gave example helpers an explicit test import path; normalized
  macOS temporary-directory symlinks in installed-package identity checks. Both
  failures were in the new verification setup and passed after correction.
- M05 stays `in_progress`: user review and hosted CI remain. No staging, commit,
  push, visibility change, tag/release, live inference, model/daemon change or M06.
- Final PR-readiness assessment: **NOT PR READY**. Build, tests, lint and static
  checks PASS; no suspicious files detected. The sole reported blocker is the
  intended new files remaining untracked. They were not staged without permission.

## M05 authorized commit and push — 2026-09-07

- User explicitly requested committing and pushing the pending changes and
  suggestions for the repository About text and topics. Metadata suggestions do
  not authorize a visibility change, tag or release.
- Reviewed the staged M05 changes and confirmed `origin/main` still points to
  `b71f583`; the push will also include the existing local M04 commit `43c0ab3`.
- Fresh `make check` PASS: 248 offline tests passed, one live test skipped,
  lockfile, Ruff, strict mypy over 34 files, and 0.1.0 wheel/source build.
  `make package-check` PASS with a fresh isolated installed environment.
- Staged whitespace checks and a limited credential/artifact-pattern scan PASS;
  ignored local runs, databases and environments are excluded.
- Deterministic analyzer verdict: **PR READY**. Build, tests, lint and static
  checks PASS; no suspicious files or blockers detected.
- M05 remains `in_progress`: hosted CI and the separate learning checkpoint
  remain pending. Commit/push authorization does not establish learning completion.

- Committed M05 as `de73f82` and pushed it together with M04. Remote ref was
  verified as `de73f823b42f85aa4e562f2cb97ede3dc119e0f7`.
- Hosted run `34083484567`: Ubuntu 24.04 and macOS 14 both passed `make check`,
  then failed `make package-check` because offline requirements resolution lacked
  cached package-index metadata. Existing local caches had masked this assumption.
- Corrected isolated package setup to use `uv sync --locked --offline --no-dev
  --no-install-project` against its own temporary environment, then install the
  built wheel. Dependency versions, application behavior and offline checks stay
  unchanged. Hosted verification of this correction is pending.
- Separate Dependabot run `34083489248` failed with "Github Dependabot job token
  is not set". This is an unresolved service-side job issue; no token/settings
  changes were attempted.
- Correction committed and pushed as `6354745`. Fresh local `make check` and
  `make package-check` PASS; 248 tests passed and one live test skipped. The
  deterministic analyzer again returned **PR READY**, all four checks passing
  and no suspicious files or blockers.
- Hosted run `34083659223` on `6354745`: Ubuntu 24.04 and macOS 14 both PASS,
  including isolated wheel installation and scripted report checks. GitHub also
  reported a non-failing Node 20 action deprecation warning; dependency maintenance
  remains follow-up work alongside the separate Dependabot service error.
- M05 remains `in_progress` only for its separate learning/review checkpoint.
  No new model evidence, visibility change, release/tag or M06 work was added.

## M05 public-launch preparation — 2026-09-07

- User merged Dependabot PRs #2 (`actions/setup-python` 7.0.0) and #1
  (`actions/checkout` 7.0.1). Both remain pinned to their reviewed full SHAs;
  `persist-credentials` stays disabled and workflow permissions stay read-only.
- No open pull requests remain. In the first post-merge `main` run `34086130000`,
  Ubuntu passed and macOS remained queued for runner capacity. The launch-prep push
  supersedes that run through the configured concurrency group; its intended-commit
  Ubuntu/macOS matrix must pass before the visibility change.
- Restrict branch-push CI to `main`; pull requests still run the same Ubuntu 24.04
  and macOS 14 matrix. This removes duplicate push/PR runs without weakening the
  required checks.
- Updated the release checklist to reflect completed hosted CI and commit/push,
  while keeping tag and GitHub release publication explicitly unapproved.
- GitHub About text and nine repository topics are configured. Issues are enabled;
  README, MIT license, issue form and PR template are present through the API.
- A limited current-tree and reachable-history scan found no credential patterns,
  model weights, databases or raw run artifacts. Existing history does contain the
  maintainer commit email and documented `/Users/dhasharma/...` paths. These are
  privacy metadata, not credentials; history rewriting would invalidate recorded
  commit references and requires an explicit decision before visibility changes.
- Private vulnerability reporting and branch rules cannot be configured on this
  private repository under the current plan. Both are immediate post-public steps.
- Technical launch preparation does not complete the separate M05 learning review.
- Launch-prep commit `a641f80` was pushed and hosted run `34086434727` passed on
  Ubuntu 24.04 and macOS 14, including isolated wheel installation. The earlier
  queued run was cancelled by the intended concurrency policy. The repository is
  clean and has no open pull requests; visibility remains private pending the
  explicit history-privacy decision above.

## M05 public repository launch — 2026-09-07

- User explicitly accepted exposure of the existing commit email and recorded
  local paths, preserving historical commit identifiers and experiment provenance.
- Changed `dharmendrathinks/agent-fault-lab` from private to public. No tag,
  GitHub release, package publication or M06 work was performed.
- Enabled private vulnerability reporting; the API reports `enabled: true` and
  the public advisory route returns HTTP 200.
- Protected `main` with strict required checks `offline checks (ubuntu-24.04)` and
  `offline checks (macos-14)`, both bound to GitHub Actions. Force pushes and branch
  deletion are disabled, and review conversations must be resolved. Admins are not
  enforced so the sole maintainer retains an emergency bypass.
- Enabled dependency vulnerability alerts, Dependabot security updates, secret
  scanning and secret-scanning push protection.
- GitHub then opened one moderate alert for pytest temporary-directory handling in
  the development lock (`pytest<9.0.3`). Raised the declared range to
  `pytest>=9.0.3,<10` and locked pytest 9.1.1. This changes test tooling only;
  runtime dependencies are unchanged. Fresh `make check` PASS with 248 tests and
  one live test skipped; `make package-check` PASS.
- Committed and pushed the pytest update as `89e9743`. Hosted run `34090765739`
  passed on Ubuntu 24.04 and macOS 14, and GitHub marked Dependabot alert #1
  `fixed` without dismissal. The default branch has no open dependency alert.
- Public HTTP checks returned 200 for the repository, raw README, issue chooser and
  private-advisory form. MIT license, About text, nine topics and Issues are visible
  through the public API. No open PRs, tags or releases exist.
- The in-app browser was unavailable, so README diagram/layout and issue-form UI
  rendering were not visually inspected. This is the only remaining launch UI
  check; public accessibility and configuration were verified independently.
- M05 remains `in_progress` solely for the separate user learning checkpoint.

## M05 first release — 2026-09-07

- User explicitly requested "yeah release now", authorizing the release metadata
  commit/push, annotated `v0.1.0` tag, and GitHub release with wheel, source archive,
  and checksums. PyPI publication is outside this release.
- Updated README status, dated the changelog, and finalized release notes. The
  package version was already 0.1.0; runtime code and dependencies are unchanged.
- Fresh `make check` PASS: 248 offline tests passed, one live test skipped;
  lockfile, Ruff, strict mypy and 0.1.0 package build passed. `make package-check`
  PASS in an isolated installed environment. PR Ready analyzer: **PR READY**;
  build, test, lint and static checks passed, with no suspicious files or blockers.
- Release commit `30ba7461df9762a79623c501134d24a2098accc9` was pushed. Hosted run
  `34091647210` passed on Ubuntu 24.04 and macOS 14, including installed-wheel
  checks, before tag creation and publication.
- Rebuilt the final artifacts from the clean release commit. All 91 source archive
  entries match tracked files (plus package metadata); all 22 wheel entries have
  expected code, metadata, license and type marker. The exact wheel passed a
  fresh isolated installation and scripted CLI/report check.
- Created and pushed annotated tag `v0.1.0`; verified its remote peeled commit is
  `30ba7461df9762a79623c501134d24a2098accc9`. Published the normal latest GitHub
  release with curated notes, the 0.1.0 wheel, source archive and `SHA256SUMS`.
- Asset SHA-256 values: wheel
  `d410a8f9ae7508fb1de8dd843f570615141f4e02e7b1c74c66087c77d48163e3`;
  source archive
  `1fa859aa2a613e27629d032a0114bcbe3f2a2624f9efc470571092b2808dfe8d`.
- Anonymous public API and all three asset downloads verified. Downloaded bytes
  match the local release assets; `shasum -a 256 -c SHA256SUMS` passes for both
  packages. The release is published, marked latest, and is not a prerelease.
- M05 remains `in_progress` for its separate learning checkpoint. Release
  authorization does not claim the checkpoint was completed or authorize M06.
- User asked whether the learning plan belongs in the public repository. Reviewed
  `PLAN.md`: the learning path fits the lab's purpose; retained previously accepted
  personal paths and historical decisions. Added public-reader context separating
  planning assumptions from release commitments, corrected the stale scope summary,
  and updated the public roadmap's candidate label. This is a post-release docs
  clarification; the published tag and package assets remain at `30ba746`.

## Phase 2 detailed planning — 2026-09-07

- User requested a detailed M06–M10 plan, selected focused live checks, full agent
  conversation recovery, and executor-owned operation IDs for retry protection.
  They then requested implementation and specifically expanded documentation in
  `PLAN.md`. This step records the plan; no M06 runtime code is implemented yet.
- Expanded Phase 2 directly in the design authority with shared boundaries, CLI
  commands, artifact compatibility, milestone experiments, implementation steps,
  offline cases, live matrices, review gates, and v0.2 candidate requirements.
- Recorded M08's attempt/deadline/backoff limits, M09's durable state, locking and
  crash boundaries, and M10's saved-evidence diagnostics and independent review.
- Explicitly separated Phase 2 execution-policy treatments from the historical
  M04 prompt-only comparison. No prior experiment is reinterpreted.
- The 20 planned live runs are bounded milestone smoke checks, not measurements
  already obtained or an instruction to invoke all milestones together.
- Documentation verification: `make check` PASS with 248 offline tests passed,
  one live test skipped, lockfile, Ruff, strict mypy and package build passing.
  PR Ready analyzer: **PR READY**; build, test, lint and static checks passed,
  with no suspicious files or blockers. No live inference, staging, commit or push
  was performed in this documentation step.
- M06 is `planned`; M05 learning review stays pending. Next action is the M06
  implementation above, with no automatic M07 progression.

## M06 implementation and focused live smoke — 2026-09-07

- User requested starting Phase 2. Implemented M06 only, preserving the pending
  planning edits and historical evidence. M07–M10 remain planned.
- Added the optional executor boundary, required version 1 response envelope,
  syntax/schema/request validation, eleven finite cases, and raw-byte trace capture.
  Both policies validate arguments; valid bytes are preserved. Storage and the
  independent evaluator keep their existing behavior. No automatic retry was added.
- Added explicit offline/live reliability list/run/compare commands and versioned
  reports with invalid/absent claims, unknown outcomes, partial runs and unexercised
  faults. Legacy CLI and report readers pass their existing regressions.
- Added offline regressions for malformed responses, unchanged storage on invalid
  input, committed writes followed by rejected responses, false claims that pass
  response validation, partial failures, explicit mode selection, and regeneration
  from saved JSON without a database. Installed-wheel checks exercise M06 too.
- Verified the local checkpoint metadata and digest match the approved Instruct
  baseline. Ran exactly four planned local smoke runs: healthy and wrong-create-title
  under both policies. All four tasks were correctly stored; three final completion
  claims used wrong IDs, while validated wrong-title returned prose plus JSON and
  failed strict terminal validation. Eight model calls, four creates, no lookups.
- Both configured response faults activated. The validator detected the request
  mismatch after the correct write committed. No provider, evaluator or output-limit
  error occurred. No retry, output cleanup, model setting change or discarded run.
- Review found an inherited metric flag counted dropped writes only, despite
  correct separate response-fault counts. Reliability schema 2 fixes the generic
  flag and validates consistency; schema 1 readers preserve the original smoke.
  No original evidence was rewritten and no inference was repeated for the fix.
- Detailed provenance, exact wrong IDs, counts and limitations are in
  `docs/milestones/M06-live-smoke.md`. Raw artifacts remain ignored under `runs/`.
- Final `make check` PASS: 345 offline tests passed, one live test skipped,
  lockfile, Ruff, strict mypy over 39 source/test/example/script files, and package
  build. `make package-check` PASS with the M06 comparison installed outside the
  checkout. All six original schema 1 smoke reports still pass `report --check`.
- Final PR Ready analyzer verdict: **NOT PR READY**. Build, test, lint and static
  checks all PASS; no suspicious files. The sole blocker is seven intended new
  files remaining untracked. No staging was performed to bypass that state.
- M06 stays `in_progress` for separate review. No staging, commit, push, tag,
  package publication, new dependency, model download, daemon change or M07 work.

## M07 implementation and focused live smoke — 2026-09-07

- User requested `impl m7`, accepting M06 for progression. Implemented M07 only,
  preserving all earlier uncommitted changes. M05 learning review remains pending.
- Added explicit keyed task creation with exact argument matching, atomic task and
  operation-record writes, durable replay, conflict detection and database-lifetime
  retention. Ordinary task calls retain their old behavior and do not create a ledger.
- Added executor-owned operation IDs, per-attempt IDs, two-attempt bounded retries,
  and identical delivery errors for before-write failure and lost committed reply.
  Separate model calls get new IDs. Validation, storage and contract errors do not retry.
- Added three cases/three policies, default paired comparisons plus optional control,
  trace-derived attempt accounting and versioned reports. Independent SQL still
  grades task rows rather than trusting replay receipts. Recorded decisions in PLAN.md.
- Offline tests cover the nine cells, repeated/concurrent keys, exact inputs,
  different-argument conflicts, persistence, insert and commit rollback, missing
  databases, retry admission/exhaustion, partial evidence and report regeneration.
  Installed-wheel checks exercise all lost-reply policies outside the checkout.
- Verified the approved checkpoint metadata/digest with `make doctor`; ran exactly
  six planned local smoke runs. Lost-reply unprotected retry produced two rows;
  protected retry produced one row and one replay. Both before-write retries recovered
  one task. All six model claims copied task IDs incorrectly and were contradicted.
- Six runs: 12 model calls, 6 logical creates, 10 attempts, 4 retries, 8 storage
  entries, 1 replay, 4/4 configured faults exercised. No lookups, invalid/absent claims,
  provider/evaluator failures or output-limit stops. Five stored outcomes completed;
  the duplicate run did not satisfy exactly-one-task grading.
- See `docs/milestones/M07.md` and `docs/milestones/M07-live-smoke.md` for commands,
  exact ID mismatches, dirty source provenance and guarantee limits. All nine M07
  reports and all six historical M06 reports match saved JSON regeneration.
- Final `make check` PASS: 393 offline tests passed, one gated live test skipped,
  lockfile check, Ruff lint/format, strict mypy over 43 source/test/example/script
  files, and sdist/wheel build. The added real SQLite commit-lock regression passes.
  `make package-check` PASS, including installed M07 comparisons and child reports
  with socket construction blocked. No new dependencies or model downloads.
- Final PR Ready analyzer: **NOT PR READY**. Build, test, lint and static checks
  all PASS; no suspicious files or remaining risks reported. Its sole blocker is
  the 13 intended M06/M07 files remaining untracked. No staging to bypass the verdict.
- M07 learning checkpoint: explain the atomic ledger boundary, why identical titles
  do not establish shared intent, and why returning the original task does not fix
  a wrong terminal ID. Not marked fully complete before that review.
- Exact next action: review the walkthrough and preserved smoke, then authorize M08
  separately. No staging, commit, push, tag or publication performed in this step.

## M08–M10 implementation and Phase 2 candidate — 2026-09-07

- User authorized completing all remaining Phase 2 work after the M07 handoff,
  then said continue. M07 is accepted for progression; M08–M10 learning and M10's
  independent human diagnostic review remain separate. No Phase 3 implementation.
- M08: added one owned allowlisted subprocess per attempt, socket blocking inside
  each worker, transient retry admission, deadlines/backoff/operation budgets,
  finite late-result observation, terminate/grace/kill and confirmed-exit cleanup.
  All creates use the retained operation ledger. No evaluator snapshot or next
  attempt while an owned worker remains active.
- Offline M08 evidence covers once/twice/continuous transient failure, permanent
  failure, malformed/absent replies, before/after delays, ignored termination,
  KeyboardInterrupt cleanup, fake-time backoff and a real commit/cancel race. A
  race can leave zero or one task; tests assert atomicity instead of invented order.
- M09: added a separate transactional run journal for full conversation/provider
  turns, pending tool order/cursor, named scripts, operation IDs, attempts, remaining
  time, fault consumption, terminal result, evaluation and artifact-finalization
  state. Reservations commit before external actions. Unknown interrupted elapsed
  time charges the full reservation; exact downtime stays unknown.
- Added inherited Unix run ownership, immutable configuration and compatibility
  checks, saved-model digest verification, `aflab resume`, and the explicit
  `scripts/check_restart.py` crash controller. Legacy runs remain read-only and
  are refused for resume. No implicit migrations or remote fallback.
- M09 offline tests kill real processes at all six planned barriers. They also
  verify orphan lock retention, competing resume ownership, multi-tool order,
  operation/fault/budget persistence, lost model-response accounting, terminal
  response recovery, completed-run no-op, corrupt-state rejection and finalization
  after report-write failure. The standalone four-run controller passed offline.
- M10: added `aflab diagnose --format markdown|json`, standardized journal events,
  worker evidence references, last-checkpoint/resume explanations, saved evaluation
  and terminal support, plus explicit schema/timing/projection gaps. Diagnosis
  performs no fresh grading or tool/model calls. Golden tests cover event order,
  exact source references and unknown conclusions.
- Verified the existing local checkpoint/digest with `make doctor`. M08's six live
  runs recorded 12 model calls, six creates, seven attempts, one retry, four deadline
  expirations, two cancellations and six activated faults. Four tasks completed;
  two remained absent. Three wrong-ID completion claims and one false non-completion
  were contradicted; two non-completion claims were supported. No lookups or missing
  reports. No force-kill was needed live; its mechanism is covered offline.
- M09's four live runs recorded eight model calls, four creates and five attempts.
  All stored one task. Both explicit crash barriers were reached; after-commit
  resume charged one reservation and replayed once under the original operation ID.
  All four valid completion claims used wrong IDs and were contradicted. No lookups,
  provider/evaluator failures or output-limit stops. No additional M10 inference.
- M10 self-review diagnosed all ten M08/M09 children and ten historical M06/M07
  children. All reports still match saved JSON; local diagnostic exports accompany
  the new ignored bundles. Automated evidence is not an independent reviewer.
- Prepared local package `0.2.0rc1`; only the project's own version changed in
  `uv.lock`, with no new dependency. Added M08/M09/M10 walkthroughs, live evidence
  notes, artifact/architecture/limitation updates and the pending reviewer worksheet.
- Full `make check` PASS: 440 offline tests, one gated live test skipped, locked
  dependencies, lint/format, strict mypy over 57 source/test/example/script files,
  and candidate sdist/wheel build. Installed-wheel checks passed with process
  comparison, no-op resume and both diagnostic/report readers outside the checkout.
- Hosted Ubuntu/macOS CI is configured to discover these process tests, but has
  not run this uncommitted candidate. Local checks ran on macOS ARM64; no Linux
  result is claimed for these exact changes.
- Final PR Ready analyzer verdict: **NOT PR READY**. Build, test, lint and static
  checks all PASS; no suspicious files or remaining risks reported. Its sole
  blocker is 32 intended Phase 2 files remaining untracked. No staging to bypass
  that verdict. Final `make package-check` also PASS for the installed `0.2.0rc1`
  wheel, including process comparison, completed resume, reports and diagnosis.
- No staging, commit, push, tag, package publication, model download or daemon
  change in this implementation step. The candidate is local and unreleased.
- Exact next action: review the M08/M09 findings, obtain the M10 independent
  engineer's explanation from the bundle alone, record ambiguities/fixes, then
  decide separately whether to publish the candidate. M05 learning review stays open.

## Phase 2 release publication session — 2026-09-07

- User explicitly requested commit, push, release, README and related-file updates.
  Publication target is `v0.2.0rc1`, marked as a prerelease; stable `v0.1.0` is retained.
- Updated the README with candidate installation, Phase 2 commands and actual live
  limitations; added candidate release notes and aligned the changelog, public
  roadmap, milestone introduction, publication workflow and plan decision.
- M08/M09 learning checkpoints, M10 independent diagnostic review and the M05
  learning checkpoint remain open. No new inference or Phase 3 implementation.
- Release verification: `make check` PASS (440 offline tests, one gated live test
  skipped; lockfile, lint/format, strict typing and build passed). `make package-check`
  PASS for the installed candidate outside the checkout. Both archives contain the
  required code/license; the source archive includes the plan, progress, docs, tests
  and restart controller. No private runs, databases or environment files are bundled.
- Staged all 52 intended Phase 2/release files under the user's explicit request.
  `git diff --cached --check` PASS. Pattern inspection found only previously reviewed
  maintainer paths, no credential matches. PR Ready analyzer: **PR READY**; build,
  test, lint and static checks PASS, no suspicious files, blockers or remaining risks.
- Hosted CI and publication outcome will be recorded after they occur. Exact next
  release action: commit/push, wait for Ubuntu/macOS CI, then tag and publish verified
  artifacts. This release record does not assert the pending human reviews passed.

## Remaining roadmap

| Milestones | Status | Entry condition |
|---|---|---|
| M01: ordinary task workflow | complete | User reviewed the basics and explicitly authorized M02 |
| M02: first agent | complete | Explained; user explicitly authorized M03 |
| M03: independent evaluation | complete | Explained; user explicitly authorized M04 |
| M04: first fault comparison | complete | Original inconclusive batch and replacement smoke recorded; user reviewed summary and authorized M05 |
| M05: reproducible first release | in_progress | v0.1.0 published; local and hosted Ubuntu/macOS checks pass; separate learning review remains |
| M06: tool contracts and malformed data | complete | Technical evidence recorded; user explicitly authorized M07 after the handoff |
| M07: retry and duplicate-effect safety | complete | Technical/live evidence recorded; user authorized all remaining Phase 2 after the handoff |
| M08: delays, recovery and limits | in_progress | Technical implementation/checks and six live runs recorded; learning review pending |
| M09: crash and restart recovery | in_progress | Technical implementation/checks and four live runs recorded; learning review pending |
| M10: diagnostic traces | in_progress | Technical checks and saved-bundle self-review recorded; independent reviewer gate pending |
| M11–M13: boundaries and state | planned | Review prior experiment evidence and scope the phase |
| M14–M16: evaluation methodology and transfer | planned | Reusable experiments and reviewed evaluators exist |
| M17–M18: external reproduction and reuse | planned | A relevant external problem or collaborator is available |

See `PLAN.md` for all individual milestone definitions and gates.
