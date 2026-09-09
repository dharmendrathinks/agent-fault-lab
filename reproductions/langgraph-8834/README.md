# LangGraph #8834: router failure followed by resume

This standalone reduction tests a public report by **roli-lpci (Rolando Bosch)**:
[issue #8834](https://github.com/langchain-ai/langgraph/issues/8834). The issue
references upstream commit `81bf17b23123e4ef8b9d5f49fa09a0122fc2edd1`. We execute
the PyPI release **LangGraph 1.2.11**, with **langgraph-checkpoint-sqlite 3.1.1**
and this directory's complete lock. We do not claim to execute an upstream Git
checkout or verify the source-level fix proposed in the comments.

The original report disclosed AI assistance. This code is an independently written
reduction of the reported sequence, with a task-writing sink and evidence protocol;
the finding is credited to that report. Original lab code is MIT licensed; the
framework is installed separately under its own license. No upstream code is vendored.
On 2026-09-08 the issue remained open, with another contributor reporting a prepared
fix and tests. No upstream communication was submitted by this project.

## Run without Agent Fault Lab

Copy this directory to a clean location. It needs Python 3.12 and uv, but no lab
package, Ollama, API key or model. Initial setup downloads locked Python packages.

```sh
uv sync --locked
.venv/bin/python -I reproduce.py doctor
printf 'resume\n' | .venv/bin/python -I reproduce.py both \
  --backend memory --condition healthy --directory runs/healthy --thread-id healthy-1
printf 'resume\n' | .venv/bin/python -I reproduce.py both \
  --backend memory --condition router-failure --directory runs/router --thread-id router-1
```

Each command needs a fresh output directory. `both` emits the initial observation,
waits for `resume` on stdin, and emits the resumed observation. For a restart:

```sh
.venv/bin/python -I reproduce.py initial --backend sqlite \
  --condition router-failure --directory runs/restart --thread-id restart-1
.venv/bin/python -I reproduce.py resume --backend sqlite \
  --condition router-failure --directory runs/restart --thread-id restart-1
```

Use the **same directory, condition, backend and thread ID** for resume. This is
restart after an exception, not a killed process. The lab controller fixes these
inputs. Node-failure is the additional control: substitute `node-failure`.
Injection is limited to the initial phase, so a fresh process cannot accidentally
inject the failure again during resume. No automatic retries are installed.

The graph is `START → work → conditional router → sink → END`. Work returns
`value=1`; the sink commits one task and returns `value=2`. A node fault occurs
before the work update; a router fault occurs after it. Calls and fault activation
are written to `events.jsonl`; `initial.json` and `resume.json` contain returns,
exceptions, snapshots, pending tasks and per-invocation call counts.

Inspect actual task storage separately. With the SQLite CLI installed:

```sh
sqlite3 -readonly runs/router/tasks.sqlite3 'SELECT id, title FROM tasks;'
```

An empty result is a missing task even when resume returns normally. A normal
control must have exactly one row titled `Review the invoice.` with a usable ID.
The lab controller uses its own read-only Python SQL evaluator, including an
inspection between invocations; this script never imports that evaluator.

Python socket construction is blocked before framework imports; tracing is off.
The script has a 30-second alarm. This is a bounded trusted-code reproduction,
not an OS sandbox, model benchmark or general recovery guarantee. Standalone
output is raw evidence; the lab wrapper adds strict grading and saved reports.
