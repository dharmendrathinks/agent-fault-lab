# Agent Fault Lab progress

## Resume here

- Phase: 1 — Understand agents and demonstrate one reliability problem.
- Current milestone: **M04 — Reproduce one fault and compare one safeguard**.
- Status: **complete**.
- Technical verification: **passed**; 225 offline tests, Ruff lint/format, strict
  typing, lockfile, sdist/wheel build and isolated offline installed-wheel smoke.
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
- Exact next action: commit the reviewed M04 checkpoint, then implement only M05's
  reproducible v0.1 packaging. Preserve the wrong-ID evidence; no automatic reruns,
  ID correction, new model, or M06 reliability work.
- `make agent-demo` and the two negative examples remain scripted learning aids,
  not evidence about what a model does.
- Publication: M01–M03 baseline committed and pushed with explicit approval as
  `b71f5835558a490812f0df44b610d37e4cf49896` on `origin/main`. M04 changes are local.
- Next milestone: M05 explicitly authorized on 2026-09-07. All observed format and
  ID-copying failures stay in M04; no output stripping or safeguard-win claim.

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
  reports work for the one-task contract. A report-regeneration CLI remains later
  work. `finished` is a loop/batch status, not task success or safeguard superiority.
- The observer checks a final small-state snapshot, not causal history, arbitrary
  agent workloads, concurrent execution, or tamper-proof evidence. It reads all
  task rows and is not a hostile-file or large-database security boundary.
- Trace flushing is not a crash-safe transaction, and an HTTP timeout is not a
  hard runtime/cancellation guarantee. These limitations are documented in M02.
- M01–M03 has a public commit; current M04 manifests correctly identify a dirty
  worktree based on that commit. They do not pretend it is a committed M04 revision.
- Two local-model experiments ran across M02/M03; the separate M04 batch is
  recorded above. No hosted/paid API used.
- This verification covers the macOS development machine. Offline Linux CI is
  planned for M05 and has not been run or claimed here.

## Remaining roadmap

| Milestones | Status | Entry condition |
|---|---|---|
| M01: ordinary task workflow | complete | User reviewed the basics and explicitly authorized M02 |
| M02: first agent | complete | Explained; user explicitly authorized M03 |
| M03: independent evaluation | complete | Explained; user explicitly authorized M04 |
| M04: first fault comparison | complete | Original inconclusive batch and replacement smoke recorded; user reviewed summary and authorized M05 |
| M05: reproducible first release | planned | Explicitly authorized; begin only after committing the M04 checkpoint |
| M06–M10: execution reliability | planned | Review the first release and plan the next phase |
| M11–M13: boundaries and state | planned | Review prior experiment evidence and scope the phase |
| M14–M16: evaluation methodology and transfer | planned | Reusable experiments and reviewed evaluators exist |
| M17–M18: external reproduction and reuse | planned | A relevant external problem or collaborator is available |

See `PLAN.md` for all individual milestone definitions and gates.
