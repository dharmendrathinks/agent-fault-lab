# Agent Fault Lab progress

## Resume here

- Phase: 1 — Understand agents and demonstrate one reliability problem.
- Current milestone: **M03 — Verify outcomes independently**.
- Status: **in_progress**.
- Technical verification: **passed**; 183 offline tests, lint, format, strict
  typing, lockfile, sdist/wheel build, and an isolated offline installed-wheel smoke.
- Live integration: **verified**. One genuine M03 qwen3:4b run saved the correct
  task but emitted prose around JSON. The checker reported completed task, invalid
  terminal report, and no scored claim. A separate manual SQL read confirmed storage.
  This is not an end-to-end passing structured agent response or a false-success run.
- Learning checkpoint: M01 and M02 accepted for progression by the user's explicit
  requests after explanations. M03 walkthrough pending; no formal quiz claimed.
- Exact next action: review `docs/milestones/M03.md` and the live `report.md` with
  the user. Explain why saved work and valid reporting are separate, and why the
  checker reads SQLite independently. Keep M03 in progress until learning review.
- `make agent-demo` and the two negative examples remain scripted learning aids,
  not evidence about what a model does.
- Next milestone: M04 only after review and explicit user direction. The live
  response-format issue must be reviewed before interpreting claim comparisons;
  do not automatically run the planned 20-trial experiment or strip model output.

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

## Known boundaries

- M02 has one verified task happy path. M03 has one live correct-task/invalid-report
  observation. No live M03 supported structured completion claim has been observed;
  repeated reliability and failure recovery have not been measured.
- The model emitted verbose reasoning-like content despite `think=false`. Preserve
  this observation when reviewing the baseline for future comparisons. Do not
  assume that a requested setting guarantees the observed output format.
- Repeating a create makes another task. Retry safety remains M07.
- Independent evaluation and saved Markdown reports work for the one-task contract.
  Fault scenarios, comparisons, and a report-regeneration CLI remain unimplemented.
  `finished` is a loop status, not task success.
- The observer checks a final small-state snapshot, not causal history, arbitrary
  agent workloads, concurrent execution, or tamper-proof evidence. It reads all
  task rows and is not a hostile-file or large-database security boundary.
- Trace flushing is not a crash-safe transaction, and an HTTP timeout is not a
  hard runtime/cancellation guarantee. These limitations are documented in M02.
- There is no Git commit identifier yet; source revision is an uncommitted worktree.
- Two local-model experiments have run across M02/M03; no hosted/paid API used.
- This verification covers the macOS development machine. Offline Linux CI is
  planned for M05 and has not been run or claimed here.

## Remaining roadmap

| Milestones | Status | Entry condition |
|---|---|---|
| M01: ordinary task workflow | complete | User reviewed the basics and explicitly authorized M02 |
| M02: first agent | complete | Explained; user explicitly authorized M03 |
| M03: independent evaluation | in_progress | Technical gate passed; user learning review pending |
| M04–M05: first fault comparison and release | planned | Review M03 and output-format issue; explicit authorization required |
| M06–M10: execution reliability | planned | Review the first release and plan the next phase |
| M11–M13: boundaries and state | planned | Review prior experiment evidence and scope the phase |
| M14–M16: evaluation methodology and transfer | planned | Reusable experiments and reviewed evaluators exist |
| M17–M18: external reproduction and reuse | planned | A relevant external problem or collaborator is available |

See `PLAN.md` for all individual milestone definitions and gates.
