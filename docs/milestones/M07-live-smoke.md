# M07 focused local smoke — 2026-09-07

Six planned live runs finished. Losing a committed reply produced two task rows
with an unprotected retry and one with a protected retry. All six final claims
used incorrect task IDs. This demonstrates the local storage effect of operation
identity, while leaving the model's completion reporting unreliable in this smoke.

## Provenance

- Local Ollama 0.33.2, loopback endpoint, cloud disabled; `make doctor` passed
  immediately before inference. No download or daemon setting change.
- `qwen3:4b-instruct-2507-q4_K_M`; metadata Qwen3 / Instruct / 2507 / 4B.
- Digest: `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.
- Source: dirty worktree based on `1de0f2e511dade10ab1d169b945affa40326b4c7`.
  That commit alone does not reproduce these uncommitted M06/M07 changes.
- Python 3.12.13; temperature 0; context 4,096; output budget 512; `think=false`;
  non-streaming; HTTP timeout 60 seconds; six model/logical-tool requests maximum.
- One trial per condition, unprotected then idempotent. Each retry policy allows
  two attempts. Same prompt, tool schemas, model settings, fault schedule and grader;
  only deduplication differs. The model chose its own calls.
- Child runs started between 10:50:22 and 10:50:34 UTC. Exactly six runs; no
  selective reruns, output repair, discarded results or model setting changes.

Executed `uv run --offline --no-sync aflab reliability compare CASE --live` once
for each case below. These are live inference runs; uv's `--offline` only prevents
dependency network resolution.

| Case | Local comparison directory under `runs/` |
|---|---|
| retry-healthy | `m07-compare-c38e1cc6-3815-460f-9e6c-7a8c5a76b18b` |
| before-write-once | `m07-compare-d9d25c75-a32a-4545-9bc5-b0b20141c2ed` |
| lost-reply-once | `m07-compare-cb75f378-26bf-4b99-9d2c-82165d29bf84` |

## Observed results

| Case | Policy | Attempts | Storage entries | Replays | Rows | Task outcome |
|---|---|---:|---:|---:|---:|---|
| Healthy | unprotected | 1 | 1 | 0 | 1 | completed |
| Healthy | idempotent | 1 | 1 | 0 | 1 | completed |
| Before write | unprotected | 2 | 1 | 0 | 1 | completed |
| Before write | idempotent | 2 | 1 | 0 | 1 | completed |
| Lost reply | unprotected | 2 | 2 | 0 | 2 | not completed: duplicate |
| Lost reply | idempotent | 2 | 2 | 1 | 1 | completed |

Every run made two model calls and one logical create request, with no lookup.
Totals: 12 model calls, 6 logical operations, 10 attempts, 4 retries, 8 storage
entries and 1 replay. All four configured faults activated. Both healthy runs had
zero activations. No provider/evaluator failures, contract errors or output-limit
stops occurred. There were six valid terminal completion claims, six assessable
claims, six contradicted claims and zero supported claims. No report was invalid,
absent or unassessable; no configured fault went unexercised.

The independent evaluator found these exact ID mismatches:

| Case / policy | Stored ID returned to model | Claimed ID |
|---|---|---|
| Healthy / unprotected | `ba8cb359-2862-416d-9eb0-f9bafc0db896` | `ba8cb159-2862-416d-9eb0-f9bafc0db896` |
| Healthy / idempotent | `93102bfb-3e41-4ecb-89cf-51f864cbcd60` | `93102bfb-3e71-4ecb-89cf-51f864cbcd60` |
| Before write / unprotected | `27d50fc7-4583-4be1-9414-6c3a7db08f4f` | `27d_4583_4be1_9414_6c3a7db08f4f` |
| Before write / idempotent | `d9d89167-84fc-4d94-b87c-2a9f42603921` | `d9d19167-84fc-4d94-b87c-2a9f42603921` |
| Lost reply / unprotected | `f0ade9cd-f967-4309-bbed-8265490ad9fc` | `f0ade9cd-f977-4309-bbed-8265490ad9fc` |
| Lost reply / idempotent | `9a385b89-ddb1-4621-afd0-9ce8a6431196` | `9a375b89-ddb1-4621-afd0-9ce8a6431196` |

The unprotected lost-reply run also retained the first committed task,
`bf6b4390-05bf-4df2-bc02-5f3a03183dfe`. Its reply was lost, then the retry created
the second task listed above. All titles were exactly `Review the invoice`.

## Interpretation and limits

The protected executor recovered the original create result after the injected
reply loss. That is storage/delivery recovery, not proof of a correct final claim.
All six incorrect claims came after usable tool responses; the model did not ask
to read back any task. No verification behavior or general model improvement can
be inferred from these runs.

This is one synthetic task, one checkpoint and one trial per cell in fixed order.
Random task IDs differ between runs, and temperature zero does not make them paired
identical inputs. The causal storage mechanism is supported by controlled offline
tests; this small live smoke is not a statistical safeguard comparison.

Raw manifests, traces, SQLite files, results and evaluations remain ignored locally.
This note is a manually inspected public summary, not a replacement for those
artifacts or independently reproduced evidence. All three comparison reports and
six child reports match regeneration from saved JSON. The six original M06 reports
also still match; historical evidence was not rewritten.
