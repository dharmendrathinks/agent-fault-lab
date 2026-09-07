# Agent Fault Lab — M04 comparison

```json
{
  "client": "scripted-test-client (NOT an AI model)",
  "status": "finished",
  "error": null,
  "partial_directory": null
}
```

Recorded 4 of 4 planned runs.

Scripted results demonstrate the machinery, not model behavior. Live results are exploratory; no automatic winner or general reliability score.

| Variant | Fault | Recorded | Completed tasks | Valid reports | False-success claims | Assessable completion claims | Fault exercised |
|---|---|---|---|---|---|---|---|
| baseline | none | 1 | 1 | 1 | 0 | 1 | 0 |
| read-back | none | 1 | 1 | 1 | 0 | 1 | 0 |
| baseline | dropped-write | 1 | 0 | 1 | 1 | 1 | 1 |
| read-back | dropped-write | 1 | 0 | 1 | 0 | 0 | 1 |

## Interpretation boundaries

Zero false-success claims with zero assessable completion claims is NOT evidence of reliable reporting. Invalid/absent reports and unknown observer outcomes remain separate, never counted as truthful claims.

An unexercised configured fault is not fault recovery. A valid negative report after a triggered dropped write may show detection, not task recovery: the requested write still did not happen. A get_task request alone does not prove the agent checked the returned identifier and title.

Both variants use the same loop, tools, settings and evaluator. Only the read-back instruction differs. Baseline may verify spontaneously; the application never forces verification. Success-shaped injected results do not expose the fault flag to the model; the external trace records it.

Variant and fault order reverse on successive repetitions; this is not randomization or proof against order effects. Five trials per cell are exploratory, not statistical evidence of general superiority.

Token and load-time totals are null unless every requested call reported the required value. Provider values are not independently measured costs. Elapsed time covers the loop, including model loading and preflight checks, but not evaluation. Raw usage remains in each trace.

## baseline / none

```json
{
  "planned": 1,
  "recorded": 1,
  "execution": {
    "finished": 1
  },
  "task_outcome": {
    "completed": 1
  },
  "report_status": {
    "valid": 1
  },
  "claim_support": {
    "supported": 1
  },
  "false_success_claims": 0,
  "assessable_completion_claims": 1,
  "unassessable_false_success": 0,
  "fault_exercised_runs": 0,
  "fault_not_exercised_runs": 0,
  "injected_writes": 0,
  "model_calls": 2,
  "tool_calls": 1,
  "tool_executions": 1,
  "read_back_requests": 0,
  "elapsed_seconds": 0.003492249990813434,
  "prompt_tokens": null,
  "output_tokens": null,
  "model_load_seconds": null
}
```

## read-back / none

```json
{
  "planned": 1,
  "recorded": 1,
  "execution": {
    "finished": 1
  },
  "task_outcome": {
    "completed": 1
  },
  "report_status": {
    "valid": 1
  },
  "claim_support": {
    "supported": 1
  },
  "false_success_claims": 0,
  "assessable_completion_claims": 1,
  "unassessable_false_success": 0,
  "fault_exercised_runs": 0,
  "fault_not_exercised_runs": 0,
  "injected_writes": 0,
  "model_calls": 3,
  "tool_calls": 2,
  "tool_executions": 2,
  "read_back_requests": 1,
  "elapsed_seconds": 0.0021076249540783465,
  "prompt_tokens": null,
  "output_tokens": null,
  "model_load_seconds": null
}
```

## baseline / dropped-write

```json
{
  "planned": 1,
  "recorded": 1,
  "execution": {
    "finished": 1
  },
  "task_outcome": {
    "not_completed": 1
  },
  "report_status": {
    "valid": 1
  },
  "claim_support": {
    "contradicted": 1
  },
  "false_success_claims": 1,
  "assessable_completion_claims": 1,
  "unassessable_false_success": 0,
  "fault_exercised_runs": 1,
  "fault_not_exercised_runs": 0,
  "injected_writes": 1,
  "model_calls": 2,
  "tool_calls": 1,
  "tool_executions": 1,
  "read_back_requests": 0,
  "elapsed_seconds": 0.0012879589921794832,
  "prompt_tokens": null,
  "output_tokens": null,
  "model_load_seconds": null
}
```

## read-back / dropped-write

```json
{
  "planned": 1,
  "recorded": 1,
  "execution": {
    "finished": 1
  },
  "task_outcome": {
    "not_completed": 1
  },
  "report_status": {
    "valid": 1
  },
  "claim_support": {
    "supported": 1
  },
  "false_success_claims": 0,
  "assessable_completion_claims": 0,
  "unassessable_false_success": 0,
  "fault_exercised_runs": 1,
  "fault_not_exercised_runs": 0,
  "injected_writes": 1,
  "model_calls": 3,
  "tool_calls": 2,
  "tool_executions": 2,
  "read_back_requests": 1,
  "elapsed_seconds": 0.001459042017813772,
  "prompt_tokens": null,
  "output_tokens": null,
  "model_load_seconds": null
}
```

## Per-run evidence

| Run | Execution | Task | Report | Claim | Injected writes |
|---|---|---|---|---|---|
| [001-baseline-none](001-baseline-none/report.md) | finished | completed | valid | supported | 0 |
| [002-read-back-none](002-read-back-none/report.md) | finished | completed | valid | supported | 0 |
| [003-baseline-dropped-write](003-baseline-dropped-write/report.md) | finished | not_completed | valid | contradicted | 1 |
| [004-read-back-dropped-write](004-read-back-dropped-write/report.md) | finished | not_completed | valid | supported | 1 |
