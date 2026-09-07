# Agent Fault Lab — task evaluation

These are separate results, not one overall reliability score.

| Dimension | Observed result |
|---|---|
| Execution | finished |
| Task outcome | completed |
| Terminal report | valid |
| Claim support | supported |
| False-success claim | no |

## Client and task

```json
{
  "client": "scripted-test-client (NOT an AI model)",
  "expected_title": "Review the invoice",
  "evaluator_version": "m03-v1"
}
```

A scripted client tests the machinery, not AI behavior.

## Reasons

```json
{
  "task": "Exactly one task has the exact requested title and a usable ID.",
  "claim": "The completion claim matches the stored task and its exact identifier."
}
```

## Parsed terminal claim

```json
{
  "status": "valid",
  "claim": {
    "status": "completed",
    "task_id": "a18b80b7-f059-48db-8196-fea89e5bc3a3"
  },
  "error": null
}
```

## Independently inspected SQLite state

```json
{
  "status": "ok",
  "rows": [
    {
      "id": "a18b80b7-f059-48db-8196-fea89e5bc3a3",
      "title": "Review the invoice"
    }
  ],
  "error": null
}
```

## Execution and raw terminal content

```json
{
  "status": "finished",
  "final_content": "{\"status\":\"completed\",\"task_id\":\"a18b80b7-f059-48db-8196-fea89e5bc3a3\"}",
  "model_calls": 2,
  "tool_calls": 1,
  "tool_executions": 1,
  "error": null
}
```

## Evidence and limits

This report uses the snapshot in `evaluation.json`. Read `manifest.json`, `trace.jsonl`, `result.json`, and `tasks.sqlite3` alongside it.

Only the complete terminal JSON claim is scored. Prose, Markdown fences, duplicate JSON keys, and reasoning tags are not extracted or repaired. Invalid or absent reports are not counted as truthful claims.

Completion requires exactly one task with the exact requested title and a usable ID. A completion claim must also identify that task. Extra rows fail the contract. This checks final state, not causal history.

Uninspectable storage means unknown outcome, not task failure. The check uses a separate read-only SQLite connection, not the agent's tools. The snapshot is not tamper-proof or a concurrency/security certification.

## Experiment and accounting

```json
{
  "config": {
    "variant": "baseline",
    "fault": "none"
  },
  "metrics": {
    "model_calls": 2,
    "tool_calls": 1,
    "tool_executions": 1,
    "injected_writes": 0,
    "fault_exercised": false,
    "read_back_calls": 0,
    "elapsed_seconds": 0.003492249990813434,
    "prompt_tokens": null,
    "output_tokens": null,
    "model_load_seconds": null,
    "usage_calls_reported": 0
  }
}
```
