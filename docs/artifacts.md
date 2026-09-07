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

## Rebuild versus rerun

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
