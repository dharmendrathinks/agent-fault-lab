# M02 — First genuine local-agent run

Recorded on 2026-09-06. This is one happy-path smoke test, not a reliability benchmark.

## Question and expectation

Can the local model request our Python tool, receive its result, and report a
created task whose exact title and ID agree with independent SQLite inspection?

Expected: one task titled `Review the invoice`, stored before the model's final
response. No fault injector, read-back instruction, or scripted model is involved.

## What changed

The user approved local-only Ollama configuration and restart. We created the
previously absent `/Users/dhasharma/.ollama/server.json` with only:

```json
{"disable_ollama_cloud": true}
```

The restarted daemon confirmed cloud disabled. This follows the
[official local-only configuration](https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features).
This persistent setting disables Ollama cloud features for this local installation,
not just this project. To undo it deliberately, change the flag to false and
restart Ollama; Agent Fault Lab will then refuse live runs until local-only mode
is restored. The project never changes the setting automatically.

No application code, prompt, model choice, or generation limit changed for this run.

## What happened

Command: `uv run --offline --no-sync aflab run`.

| Observed step | Actual evidence |
|---|---|
| Model request 1 | Requested `create_task` with title `Review the invoice` |
| Python tool execution | Committed task ID `b35ccad5-6033-48fc-bcfe-8ea331b8bcc8` |
| Model request 2 | Received that result and reported the same title and ID |
| Independent SQL read | Exactly one row, with the expected title and reported ID |

There were two model calls and one tool execution. The model did not request
`get_task`; the separate read-only database check was performed outside the agent.

The trace recorded about 25.81 seconds for the loop, including model loading and
local metadata calls. Provider-reported output tokens were 354 and 495, with
`done_reason: stop` on both turns. Initial model load was about 3.10 seconds.
These are observations from one run, not performance promises.

## Evidence on this machine

All artifacts are retained, ignored by Git, under:

`runs/m02-42a3bce3-275d-4536-9c18-bb163083ab07/`

- `manifest.json`: local model digest, Ollama/package versions, request, settings.
- `trace.jsonl`: actual requests, results, usage, and timings; unedited content.
- `tasks.sqlite3`: real stored data.
- `result.json`: loop status and full final response, not an independent grade.

Reinspect without invoking the agent's tool:

```sh
sqlite3 -readonly runs/m02-42a3bce3-275d-4536-9c18-bb163083ab07/tasks.sqlite3 \
  'SELECT id, title FROM tasks;'
```

The manifest records qwen3:4b digest
`359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`,
Ollama 0.33.2, temperature 0, context 4096, maximum output 512 per response,
`stream=false`, and `think=false`. The source is an uncommitted worktree, so this
is not pinned to a published revision.

## Surprise and limits

Although we requested `think=false`, ordinary response content contained verbose
reasoning-like text and a closing `</think>` marker. The separate thinking field
was null. The raw response is preserved; we did not strip it or rerun to obtain
a tidier result. The second response used 495 of the 512-token output allowance.

This shows that the requested flag did not produce a clean, concise response in
this run. It does not establish the cause or what was internally computed. Review
this behavior before assuming the later terminal JSON contract will work unchanged.

The evidence supports one successful local tool-using workflow. It does not prove
repeatability, recovery, prompt-injection resistance, or trustworthy self-reporting
when a tool lies. Those experiments remain future milestones.

## Your learning checkpoint

The model chose the action. Python executed it. The model saw the returned result
and answered. A separate database read established what was actually stored.

Walk through those four responsibilities using the trace before moving to M03.
