# Architecture and code map

The agent's view is separate from the evaluator's evidence. There is one task
environment, not a plugin system or general agent framework.

| Responsibility | Implementation | Boundary |
|---|---|---|
| Task persistence | [tasks.py](../src/agent_fault_lab/tasks.py) | Validate input; commit before reporting success |
| Model-facing tools | [tools.py](../src/agent_fault_lab/tools.py) | Allowlisted calls with validated arguments |
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
fix. Discuss new faults and providers first. M05 adds packaging, not treatments.
