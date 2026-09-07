# M09 focused crash/resume smoke — 2026-09-07

Four planned live runs finished: two uninterrupted controls and two crash/resume
runs. All retained exactly one task. The after-commit resume replayed the original
operation result. Every final completion claim used an incorrect task ID.

## Provenance

Same local baseline and limits as [M08](M08-live-smoke.md): package `0.2.0rc1`,
Python 3.12.13, Ollama 0.33.2, Qwen3 4B Instruct-2507,
digest `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.
Cloud remained disabled; no model or daemon changes. Temperature 0, context 4,096,
output 512 and the same strict evaluator. Live resume rechecked the saved digest.

The source was a dirty worktree based on
`1de0f2e511dade10ab1d169b945affa40326b4c7`. The journals retain their compatibility
fingerprints and immutable configuration. Each run used `restart-healthy` with
`bounded-retry`; only controlled crash/resume differed within each pair.

Used the tested `scripts/check_restart.py` controller with live mode and output:

`runs/m09-smoke-bb794c7b-9760-4d60-b4b2-b500fa0dd342`

The first control started at 13:28:16 UTC and the last crash run at 13:28:26 UTC.
Exactly four logical runs, with six runner sessions in total. No discarded runs,
output repair, repeated unfavorable trial or additional inference for diagnostics.

## Observed results

| Child directory | Sessions | Model calls | Logical creates | Attempts | Replay receipts | Rows |
|---|---:|---:|---:|---:|---:|---:|
| `1-uninterrupted-assistant-checkpoint` | 1 | 2 | 1 | 1 | 0 | 1 |
| `1-resumed-assistant-checkpoint` | 2 | 2 | 1 | 1 | 0 | 1 |
| `2-uninterrupted-after-commit` | 1 | 2 | 1 | 1 | 0 | 1 |
| `2-resumed-after-commit` | 2 | 2 | 1 | 2 | 1 | 1 |

The controller waited for explicit barriers, then killed its runner and, where
present, the paused owned worker. `controller.json` records the selected point,
PIDs, SIGKILL and ownership release. Both configured barriers were reached; these
are crash injections, not M08 response faults, so `fault_activations` remains zero.

Before-dispatch resume continued the saved assistant request without another model
call. After-commit resume charged the interrupted attempt's full reservation and
reused its operation ID. There was one additional attempt and one replay receipt.
The dead runner could not record exit confirmation for its killed worker; the
controller's ownership-release evidence is separate from ordinary confirmed exits.

Totals: eight model calls, four logical creates and five attempts, with no lookups.
No provider/evaluator error or output-limit stop occurred. All four terminal
reports were valid completion claims, all four were assessable and contradicted,
and all four were scored false-success claims. No invalid/absent/unassessable claim
was hidden by an aggregate success count.

| Child | Stored ID | Claimed ID |
|---|---|---|
| First control | `c3b9319c-709f-4b25-9e9f-38c383be0b1d` | `c3b0319c-709f-4b25-9e9f-38c383be0b1d` |
| Before-dispatch resume | `adf769c2-3f4f-48d9-9bc1-af430df2e38a` | `adf7_3f4f_48d9_9bc1_af430df2e38a` |
| Second control | `afcbcb0a-09d5-4418-9df7-692b93f340f3` | `afcbcb00-09d5-4418-9df7-692b93f340f3` |
| After-commit resume | `dd04a47b-64bc-47cb-8159-200ff2601941` | `dd04a7b-64bc-47cb-8159-200ff2601941` |

## Interpretation and limits

Conversation and effect recovery worked in these selected cases. They did not fix
model reporting. Random task IDs and a single trial per pair prevent statistical
claims about model reliability or speed. Scripted tests establish the other crash
boundaries, multi-tool ordering, lock contention and budget preservation.

Elapsed time sums observed session time. Exact downtime after an abrupt death is
unknown; checkpoint wall-clock gaps include unobserved execution. Process-crash
recovery does not prove power-loss, filesystem-corruption or remote-service recovery.

All four reports match saved-JSON regeneration. M10 diagnoses all four without
projection/schema gaps; local Markdown/JSON diagnostic exports remain with the
ignored raw bundles. The existing M06/M07 reports still match their original
saved evidence. No independent human reviewer has yet accepted the diagnostic
handoff; see the [M10 worksheet](M10.md#independent-reviewer-handoff).
