# Agent Fault Lab

Build agents. Reproduce failures. Test the fixes.

An open-source learning lab for investigating agent reliability through small,
reproducible experiments. This is not yet an agent framework or a reliability
benchmark. **M04 adds a controlled dropped-write fault and a four-cell comparison
of baseline versus read-back instructions.** The independent SQLite checker keeps
task outcomes separate from the agent's claims. Saved traces and reports expose
invalid replies, unexercised faults, and unfavorable results.
See [PROGRESS.md](PROGRESS.md) for verified live results
and any remaining setup or learning gates.

The current local baseline is **`qwen3:4b-instruct-2507-q4_K_M`**, an explicitly
named non-thinking checkpoint. It replaces the ambiguous `qwen3:4b` alias that
resolved to Thinking-2507. The original unsuccessful comparison is preserved in
the [setup diagnosis](docs/milestones/M04-qwen-diagnosis.md); selecting a suitable
checkpoint does not guarantee correct tool calls or reports.
The [replacement smoke tests](docs/milestones/M04-instruct-smoke.md) produced valid
JSON but also exposed task-ID copying errors; those failures remain in the evidence.

Repository: [dharmendrathinks/agent-fault-lab](https://github.com/dharmendrathinks/agent-fault-lab).

## Setup

Install Python 3.12 and [uv](https://docs.astral.sh/uv/), then run from this project:

```sh
uv sync --locked
make check
make demo
make agent-demo
```

The first sync may download Python packages, including Ollama, HTTPX, and Pydantic.
The task store itself still uses only the standard library. After setup, checks
and both demonstrations run offline. Default tests block Python socket creation
with `pytest-socket`; this is a test guard, not an operating-system network sandbox.

No running Ollama daemon, model download, API key, or paid service is required for
the tests or scripted demo. The real agent explicitly uses local Ollama. Codex is
only a development assistant, not the model executing inside the lab.

## Try independent evaluation

```sh
make agent-demo  # scripted requests, real task writes; NOT an AI experiment
uv run --offline --no-sync aflab demo --offline --case false-success
uv run --offline --no-sync aflab demo --offline --case invalid-report
make doctor      # local metadata checks only; no download or inference
```

The scripted demo saves a fresh directory under `runs/`. Inspect `trace.jsonl` to
follow the model request, tool request, real tool result, and final response.
`tasks.sqlite3` contains the actual data. The manifest labels the client, settings,
and source revision; `result.json` describes how the loop stopped. Afterward, a
separate read-only SQLite connection checks the actual rows. `evaluation.json`
and `report.md` record the result without asking another model to judge it.

**`finished` means the model stopped requesting tools, not that its task succeeded.**
The scripted responses are programmed and cannot demonstrate what a real model
would do. The false-success example deliberately makes a completion claim without
calling any tool; it is not yet a dropped-write fault experiment.

| Scripted case | Task outcome | Terminal report | Claim support |
|---|---|---|---|
| `happy-path` (default) | completed | valid | supported |
| `false-success` | not_completed | valid | contradicted |
| `invalid-report` | completed | invalid | not_evaluated |

The terminal contract is one complete JSON object, for example
`{"status":"completed","task_id":"the-actual-id"}`. Non-completion and uncertainty
use `not_completed` or `unknown`, with `task_id: null`. No prose or JSON extraction
is allowed. Invalid replies do not erase a successful write, and an unreadable
database means **unknown**, not an empty database or a failed task.

See [the M03 walkthrough](docs/milestones/M03.md) for the full grading rules,
relevant files, and a genuine local run that saved the task but failed this
strict response-format contract.

## Compare one safeguard against one fault

```sh
uv run --offline --no-sync aflab compare --offline --trials 1
```

This runs four **scripted** examples on fresh databases: baseline/no fault,
read-back/no fault, baseline/dropped write, and read-back/dropped write. Under the
fault, every validated create returns a plausible ID without saving a row; read
operations stay truthful. Only the external trace records the injection flag.
Scripted verification behavior is programmed, not evidence that a prompt helps AI.

For a genuine comparison, omit the application's `--offline` flag explicitly:

```sh
uv run --offline --no-sync aflab compare --trials 5
```

Five repetitions per cell means 20 local runs, executed one at a time. The default
is one repetition (four runs); the maximum is five. Variant and fault order reverse
on alternate repetitions. Provider or evaluator errors stop the remaining batch;
invalid reports and task failures stay in the results. Ctrl-C preserves partial
evidence. Existing output directories are never overwritten.

Open the comparison directory's `report.md`. It links each run and records task
outcomes, claim/report counts, exercised faults, calls, tokens, elapsed time, and
provider-reported model loading separately. Missing usage remains `null`, not zero.
A missing task detected by read-back is **detection, not recovery**.

See [M04's walkthrough](docs/milestones/M04.md) before interpreting a result.
Zero scored false-success claims with no assessable completion claims does not
demonstrate reliable reporting. Historical failures remain available for review.

## Run the local model

For one live run, first follow [M02 local setup](docs/milestones/M02.md#local-setup)
and confirm `make doctor` is ready, then explicitly run:

```sh
uv run --offline --no-sync aflab run
uv run --offline --no-sync aflab run --variant read-back --fault dropped-write
```

Here `uv --offline` disables Python package downloads; it does **not** disable the
application's explicit request to local Ollama. `aflab demo --offline` and
`aflab compare --offline` use the scripted client. There is no automatic
substitution between the two clients. Check prerequisites before either live command.

The live runner uses `qwen3:4b-instruct-2507-q4_K_M`, non-streaming output,
`think=false`, temperature 0, 4,096 context tokens, 512 output tokens per response,
and a 60-second HTTP timeout. It permits up to six model requests and six processed tool calls.
Rejected calls also consume the tool budget. It never downloads a model, retries
a model request, changes daemon settings, or falls back to a cloud model.

`aflab doctor` checks the running daemon's local-only status, model digest,
advertised tool capability, and checkpoint identity (Qwen3, 4B, Instruct, 2507).
Missing or mismatched checkpoint metadata refuses live runs. This is a guard for
the approved baseline, not a universal model-compatibility test. The actual digest
and identity are recorded; the digest is not hard-pinned or an attestation of the
daemon. Changing model families requires an explicit baseline review.
Run directories are never overwritten; `--output` must name a new directory with
an existing parent. Saved reports and `compare` are available now; the `report`
regeneration command remains later work. Exit code 0 means an experiment
was recorded, not that the task or report passed. Provider, evaluator, and harness
errors return 2; keyboard interruption returns 130.

## What works now

```python
from pathlib import Path

from agent_fault_lab import TaskStore

store = TaskStore(Path("tasks.sqlite3"))
created = store.create_task("Review the invoice")
saved = store.get_task(created.id)
assert saved == created
assert store.get_task("unknown-task-id") is None
```

This example creates a persistent SQLite file in the current directory. For a
temporary demonstration that cleans up its own data, use `make demo` instead.

The store requires a file path with an existing parent directory. Opening an
existing database preserves its contents; a fresh experiment needs a fresh file.
Each operation opens and closes its own connection. In-memory SQLite and concurrent
agent execution are not part of this milestone.

| Operation | Contract |
|---|---|
| `create_task(title)` | Return a `Task(id, title)` only after committing the insert |
| `get_task(task_id)` | Read from storage; return `None` when the identifier is absent |
| Invalid input | Non-strings raise `TypeError`; blank strings raise `ValueError` |
| Storage error | Raise the SQLite error; do not report success |

Whitespace-only titles are rejected, but meaningful surrounding whitespace,
newlines, punctuation, and Unicode are preserved exactly. Titles are bound as SQL
parameters, not interpolated into SQL statements.

Calling `create_task` twice creates two distinct tasks, even with the same title.
Retry safety is intentionally deferred to M07. An immutable returned `Task` is a
snapshot, not proof that every future implementation or fault scenario saved it.

## Learning checkpoints

Read [the M01 walkthrough](docs/milestones/M01.md), then run `make demo`.
The example shows both the function result and a separate SQL read of stored data.
Try explaining these three things before moving on:

1. What changes on disk when `create_task` completes?
2. Why does the function return after leaving the transaction block?
3. Why is `None` for an unknown ID different from a database error?

For M02, read [the agent walkthrough](docs/milestones/M02.md). The model asks for
an action; our application validates and performs it. The model then receives
the result and decides whether to request another action or respond.

For M03, read [the independent-checker walkthrough](docs/milestones/M03.md).
Explain why a task can be completed while its final claim is wrong or malformed,
and why the checker does not call the agent's `get_task` tool.

For M04, read [the fault-comparison walkthrough](docs/milestones/M04.md). Explain
how to distinguish a triggered fault, detected failure, recovered task, and invalid
report. The model is not forced to verify by application code.

These tests establish application behavior, **not general AI reliability**.

## Development checks

```sh
make test       # storage, loop, evaluator, reports, CLI, adapter; sockets disabled
make lint       # Ruff lint and formatting check
make typecheck  # strict mypy, including tests and examples
make build     # build sdist and wheel without downloading dependencies
make check     # lockfile check plus all of the above
```

Check commands do not install missing dependencies: rerun `uv sync --locked` if
setup is incomplete. Generated databases, build outputs, caches, and environments
are ignored by Git. The MIT license covers original project code.

## Roadmap and handoff

- [PLAN.md](PLAN.md): full design and all 18 milestone definitions.
- [PROGRESS.md](PROGRESS.md): current milestone, evidence, learning checkpoint,
  and the exact next action.
- [AGENTS.md](AGENTS.md): working rules for Codex and future contributors.

The M01–M03 baseline was published with explicit user approval. M04 is the current
local milestone; no automatic advancement to M05 or release publication is included.
