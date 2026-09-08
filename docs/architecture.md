# Architecture and code map

The agent's view is separate from the evaluator's evidence. There is one task
environment, not a plugin system or general agent framework.

| Responsibility | Implementation | Boundary |
|---|---|---|
| Task persistence | [tasks.py](../src/agent_fault_lab/tasks.py) | Validate input; commit before reporting success |
| Model-facing tools | [tools.py](../src/agent_fault_lab/tools.py) | Allowlisted calls with validated arguments |
| M06 response contracts | [contracts.py](../src/agent_fault_lab/contracts.py) | Strict response syntax, schema and request consistency; no storage proof |
| M06 execution policy | [reliability.py](../src/agent_fault_lab/reliability.py) | Raw response faults and pass-through/validated delivery; argument checks in both policies |
| M06 evidence | [reliability_reports.py](../src/agent_fault_lab/reliability_reports.py) | Contract counts separate from independent task and claim grades |
| Bounded execution | [agent.py](../src/agent_fault_lab/agent.py) | Preserve call order, raw output, limits and partial evidence |
| Local provider | [ollama_adapter.py](../src/agent_fault_lab/ollama_adapter.py) | Fixed loopback endpoint and explicit model preflight |
| Scripted client | [scripted.py](../src/agent_fault_lab/scripted.py) | Exercise machinery without claiming model behavior |
| Controlled fault | [faults.py](../src/agent_fault_lab/faults.py) | Skip a write while returning success-shaped data |
| Independent observer | [evaluation.py](../src/agent_fault_lab/evaluation.py) | Own read-only SQL path; never grade through the faulty tool |
| Claim validation | [claims.py](../src/agent_fault_lab/claims.py) | Reject invalid final JSON; never repair the answer |
| Accounting | [experiments.py](../src/agent_fault_lab/experiments.py) | Trace-derived counts; missing usage is unknown |
| Aggregation | [comparison.py](../src/agent_fault_lab/comparison.py) | Include invalid claims, partial runs and unexercised faults |
| Presentation | [reporting.py](../src/agent_fault_lab/reporting.py), [saved_reports.py](../src/agent_fault_lab/saved_reports.py) | Render saved evidence without new inference or SQL inspection |
| Commands | [cli.py](../src/agent_fault_lab/cli.py) | Fresh directories, preflight, capture and exit status |

## Four separate questions

1. Did the loop finish, reach a limit, or encounter an error?
2. Is exactly the requested task present in independently inspected storage?
3. Is the final response a valid terminal claim?
4. Does the stored evidence support that claim, including the exact task ID?

A finished loop is not a completed task. Valid JSON is not necessarily a true
claim. Uninspectable storage is unknown, not an invented failure.

Read-back adds an instruction, not forced execution. Both variants share tools,
model settings, limits and grading. Fault metadata stays outside model-facing
results. A lookup request alone does not establish correct verification.

The observer checks a final snapshot, not causal history. HTTP timeouts are not
hard process cancellation. The lab is not a sandbox. Report validation does not
authenticate data, recompute grades or check every cross-field business invariant.
See [artifacts](artifacts.md) and [limitations](known-limitations.md).

For a contribution, start with a reproducible failure and regression. Identify
which component owns the contract; keep evaluation independent of the proposed
fix. Discuss new faults and providers first. M06 adds response delivery policies;
the legacy M04 prompt comparison keeps its existing behavior. M07's
[retry executor](../src/agent_fault_lab/retries.py) assigns operation IDs and makes
at most two attempts. Its protected storage method commits a task and operation
record atomically; separate model calls retain distinct identities. The evaluator
still reads only actual task state through its own connection. See the
[M07 walkthrough](milestones/M07.md).

M08–M10 use [supervision.py](../src/agent_fault_lab/supervision.py) and the allowlisted
[worker.py](../src/agent_fault_lab/worker.py) for owned process attempts.
[durable_run.py](../src/agent_fault_lab/durable_run.py) saves a sequential conversation
through [journal.py](../src/agent_fault_lab/journal.py), reserving budgets before
external actions. Task and run databases remain separate. The operation ledger
reconciles uncertain task writes, while an inherited OS lock prevents overlapping
resume. [diagnostics.py](../src/agent_fault_lab/diagnostics.py) reads saved artifacts
and never invokes the evaluator for fresh grading. Existing v0.1/M06/M07 loops and
report readers remain available without implicit migration.

M11 adds a separate boundary experiment family. [scanner.py](../src/agent_fault_lab/scanner.py)
owns static SkillSpector admission through a pinned external environment;
[permissions.py](../src/agent_fault_lab/permissions.py) owns proposals, grants and
atomic task effects. Neither scanner findings nor an executor allow/deny flag
establish authorization in the independent
[boundary evaluator](../src/agent_fault_lab/boundary_evaluation.py), which joins
actual tasks with grant and receipt evidence through its own read-only SQL.
[boundaries.py](../src/agent_fault_lab/boundaries.py) persists conversations and
approval waits in `boundary.sqlite3`. [Boundary reports](../src/agent_fault_lab/boundary_reports.py)
keep scan status, authorization, actual outcome and claim support separate.
The [M11 walkthrough](milestones/M11.md) defines the experiment and its limits.

[context_cases.py](../src/agent_fault_lab/context_cases.py) defines the M12/M13
synthetic corpus and external ground truth. [context_runtime.py](../src/agent_fault_lab/context_runtime.py)
prepares reference snapshots, delivers scanned content, records supplied/shortened
history and obtains authoritative request state. The existing bounded loop owns
execution and durable checkpoints. [context_evaluation.py](../src/agent_fault_lab/context_evaluation.py)
grades independent task rows against seeded state and current request scope; it
does not import the executor or obtain task outcomes through model tools.

M12 varies scanner and permission enforcement independently. M13 varies only
runner refresh of current request state, keeping the read-only state tool available
to either variant. The synthetic approval controller is scoped to the current
requested title and remaining task; it never represents a human decision.

## Phase 4 development interfaces

`study_records.py` freezes a schedule and fingerprints; `studies.py` supervises
sequential child processes and preserves partial evidence. `study_reports.py`
renders saved scenario counts and conditional intervals. The ordinary workflow
uses the same tool responses and cannot inspect evaluator SQL.

`audit_corpus.py` creates contract-authored SQL fixtures. `evaluator_audit.py`
copies the package into a temporary directory per evaluator variant, applies one
declared mutation and invokes a separate offline worker. Production sources and
historical grades are never modified by the audit.

`boundaries.py` exposes one model step and one tool step used by its native loop
and by `langgraph_runtime.py`. LangGraph owns conditional graph edges; it does not
call the native loop. `runtimes.py` launches both transfer variants in the same
separate locked environment. Runtime records wrap independent boundary grades
without extending the tools or exposing evaluator metadata to the model.
