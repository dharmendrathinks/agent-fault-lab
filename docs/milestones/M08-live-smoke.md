# M08 focused local smoke — 2026-09-07

All six planned runs finished. Bounded retry recovered a transient failure. A
delayed write completed under observation; terminating before the write prevented
it, while terminating after commit left the task intact. These stored effects did
not establish correct model claims.

## Provenance and commands

- Package `0.2.0rc1`, Python 3.12.13, macOS ARM64; dirty worktree based on
  `1de0f2e511dade10ab1d169b945affa40326b4c7`. That commit alone is insufficient
  to reproduce these uncommitted changes; each journal records its compatibility hash.
- Ollama 0.33.2, cloud disabled, loopback endpoint; `make doctor` passed before
  inference. Model `qwen3:4b-instruct-2507-q4_K_M`, Qwen3/Instruct/2507/4B metadata.
- Digest `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.
- Temperature 0, context 4,096, output 512, `think=false`, non-streaming, HTTP
  timeout 60 seconds, six model/tool requests maximum. Default M08 limits:
  2-second attempt deadline, 8-second operation budget, three bounded attempts,
  100/200 ms backoff, 500 ms termination grace, 18 total attempts, 3-second delay.
- One trial per pair; identical prompt, schemas, settings and grading within each
  pair. Only retry admission or cancellation policy differs. No forced model calls.
- Exactly six runs, starting 13:19:56–13:20:15 UTC. No downloads, setting changes,
  discarded results, output repairs or selective reruns.

Ran `uv run --offline --no-sync aflab reliability compare CASE --live` for:

| Case | Local directory under `runs/` |
|---|---|
| transient-once | `m08-compare-650d6fca-6309-487b-9e9b-1e2ad1252926` |
| delay-before-write | `m08-compare-a5a01b14-0140-4baf-a2c7-88a49ec4f912` |
| delay-after-commit | `m08-compare-26293045-dd80-4ed2-91bd-3a0d71a44fb6` |

Here uv's `--offline` prevents dependency resolution; the CLI's `--live` selects
actual local model inference.

## Observed results

| Case / policy | Attempts | Deadline | Cancellation | Rows | Final claim | Support | Observed session seconds |
|---|---:|---:|---:|---:|---|---|---:|
| Transient / single | 1 | 0 | 0 | 0 | not completed | supported | 4.014 |
| Transient / retry | 2 | 0 | 0 | 1 | completed, wrong ID | contradicted | 2.023 |
| Before write / observe | 1 | 1 | 0 | 1 | completed, wrong ID | contradicted | 4.812 |
| Before write / terminate | 1 | 1 | 1 | 0 | not completed | supported | 3.047 |
| After commit / observe | 1 | 1 | 0 | 1 | completed, wrong ID | contradicted | 4.879 |
| After commit / terminate | 1 | 1 | 1 | 1 | not completed | contradicted | 3.047 |

Totals: 12 model calls, six logical creates, seven attempts, one scheduled retry,
four deadline expirations and two cancellations. All seven dispatched workers had
confirmed exits. No force-kill was needed in this live smoke; that behavior is
covered by the separate offline ignored-termination test. All six configured faults
activated. There were no lookups, provider/evaluator errors or output-limit stops.

All terminal reports were valid: three completion claims and three non-completion
claims. All three assessable completion claims were false-success claims. Two
non-completion claims were supported; the after-commit cancellation claim was
contradicted because the task existed. There were no invalid, absent or unassessable
claims. Counting only false-success would miss that false non-completion.

| Run | Stored ID returned to model | Incorrect completed ID |
|---|---|---|
| Transient / retry | `fb0b5b1a-39ca-4983-84e3-43ee7b19ebb0` | `fb0b0b1a-39ca-4983-84e3-43ee7b19ebb0` |
| Before write / observe | `e6a767e9-9cea-4fdc-b739-a05642ddd758` | `e6a_77e9-9cea-4fdc-b739-a05642ddd758` |
| After commit / observe | `035dcd0e-e951-4eef-a66f-59247c890159` | `035dcd07-e951-4eef-a66f-59247c890159` |

The after-commit terminated worker retained task
`bc69fe3d-134f-425c-bd18-a14c78dbcffe`. Its delivered result was a deadline error;
the final model claim was `not_completed` with a null ID. All titles were exact.

## Limits and diagnostic review

Observation collected the finite late reply after recording deadline expiry.
Termination returned an error after confirming worker exit. Neither behavior is
proof about cancellation of a remote service or the model server.

Timing is descriptive only: the first control included about 2.109 seconds of
model loading, while later runs were warm. Do not interpret shorter retry elapsed
time as a performance improvement. One checkpoint, synthetic task and trial per
cell cannot establish general model reliability.

All three comparison reports and six child reports match saved-JSON regeneration.
M10 diagnosed all six without evidence gaps; local `diagnosis.md`/`diagnosis.json`
exports accompany the original ignored artifacts. This was implementation
self-review, not an independent engineer's acceptance of M10.
