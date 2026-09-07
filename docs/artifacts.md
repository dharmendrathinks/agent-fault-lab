# Reading experiment artifacts

Generated outputs normally live under ignored `runs/`. A custom output directory
must be new. Review a run before uploading it.

| Single-run file | What it records |
|---|---|
| `manifest.json` | Configuration, environment and available source/model provenance |
| `trace.jsonl` | Events, model/tool requests and responses, injected faults and failures |
| `tasks.sqlite3` | Actual task state |
| `result.json` | Raw loop result, final content and stop reason |
| `evaluation.json` | Independent storage inspection and terminal-claim assessment |
| `observation.json` | Experiment configuration, evaluation and accounting |
| `report.md` | Human-readable evaluation and observation |

Comparisons add `comparison.json`, `comparison-trace.jsonl`, a root manifest and
report, plus numbered child directories. The aggregate JSON embeds recorded
observations. A missing cell is not a passing cell.

Saved evaluation, observation and comparison schemas are version 1. The evaluator
identifier is `m03-v1`; run manifests use schema 3. These identify different
contracts and need not match package versions. M04 report headings identify the
experiment that M05 packages.

M06 run manifests use schema 4. Its observations and comparisons use explicit
`reliability-run` and `reliability-comparison` artifact tags, each at schema 2;
legacy M04 readers remain available. M06 retains the same independent evaluation
schema and grader. Its `contracts` counts separate syntax, schema and request
errors from valid or unchecked responses and fault activations. The
[M06 walkthrough](milestones/M06.md) describes the envelope and injection cases.
The initial reliability schema 1 remains readable. Its inherited
`metrics.fault_exercised` counted dropped writes only; its contract counts record
response-fault activation correctly. Schema 2 corrects the generic flag without
rewriting the original smoke evidence.

M06 `response_captured` trace events contain base64-encoded original response
bytes. Contract assessment, fault metadata and execution accounting stay outside
the model-facing envelope. A contract rejection does not establish whether the
underlying write committed.

## Rebuild versus rerun

M07 uses `retry-run` and `retry-comparison` artifact discriminators with schema 1;
run manifests use version 5. Its `retry` counts separate accepted operations,
attempts, scheduled retries, storage entries, replays, delivery/contract errors
and fault activations. The old `metrics.tool_executions` remains a logical count.
Attempt IDs and operation IDs connect external events; commit-position and replay
metadata never enter the model response. The optional `task_operations` SQLite
table retains protected create receipts for the experiment database lifetime.
Evaluation uses the task table, not this ledger. See [M07](milestones/M07.md).

M08/M09 process manifests use schema 6. `execution-run` and `execution-comparison`
artifacts use schema 1. `journal.sqlite3` holds the authoritative full conversation
checkpoint and ordered events; `trace.jsonl` projects those events with run/session,
call/operation/attempt identifiers and local timing. `worker-*.jsonl` contains actual
child receipts, later imported with original source references. A crash can leave
unimported or partial bytes; diagnosis reports gaps rather than reconstructing them.

The inherited `run.lock` prevents overlapping owners. `barrier-*` and optional
`controller.json` files document explicitly requested crash tests. Legacy bundles
have no compatible journal and cannot be resumed. `aflab resume` changes only an
explicitly selected compatible run; `aflab diagnose` is read-only. Neither command
migrates old evidence. See [M09](milestones/M09.md) and [M10](milestones/M10.md).

`aflab report RUN_DIRECTORY --check` compares Markdown with a rendering of saved
JSON. Exit 0 means matching; 1 means missing/stale Markdown. Without `--check`, only
`report.md` is replaced, using a same-directory temporary file and atomic replace.
Unsupported schema values, duplicate JSON keys, invalid evidence, symlink inputs
and mismatched run observations fail without replacing the report.

Run reports read `evaluation.json` and optional matching `observation.json`.
Comparison reports read aggregate `comparison.json`, not child files. Regeneration
never reads SQLite or calls a model. It checks presentation consistency, **not
authenticity**. Editing JSON and regenerating Markdown can produce a matching but
false account. There are no signatures or guarantees against hostile filesystem
races. Not every cross-field semantic invariant is validated.

Commands return 2 for usage/provider/evaluator/harness errors and 130 for handled
interruptions. A recorded agent failure can return 0: the lab successfully captured
an unsuccessful experiment. Inspect the evaluation, not just the shell status.

## Sharing evidence

Review prompts, titles, responses, traces, absolute paths, model metadata and Git
provenance. Use synthetic data; never upload credentials, customer data or weights.
Keep originals locally and label public excerpts and omissions.

The [public example](../examples/evidence/dropped-write/README.md) contains scripted
JSON and reports only. Historical live runs remain local; their write-ups are
observations, not independently reproduced public benchmarks.
