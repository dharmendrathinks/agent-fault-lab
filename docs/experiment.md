# What happened when an agent trusted a successful tool response?

## Question

If `create_task` returns a plausible success object but silently drops the write,
does instructing an agent to read the task back reduce unsupported completion
claims?

## Experiment

The same agent loop, tools, limits, local model settings, and independent evaluator
run in four cells: baseline/read-back crossed with normal/dropped-write behavior.
The fault changes only the validated create implementation. It returns a fresh ID
and exact title without inserting a row. `get_task` and the evaluator remain
truthful. The read-back variant receives one additional instruction; application
code never forces the lookup.

The independent evaluator opens SQLite read-only and grades stored outcome,
terminal-report validity, and claim support separately. A successful loop is not
automatically a completed task.

## Results—failures included

The original five-trial-per-cell batch was scientifically inconclusive: the
`qwen3:4b` alias resolved to Thinking-2507, all reports were invalid, and all ten
read-back runs exhausted 512 output tokens before using a tool. This revealed a
model-selection and measurement failure, not a result for or against read-back.

After explicit replacement with Qwen3-4B-Instruct-2507, two preliminary no-fault
runs succeeded. A one-trial-per-cell smoke then produced valid JSON and exercised
both faults—but the model copied the returned task ID incorrectly in all four
cells. Read-back under the fault ended with a supported non-completion claim, yet
it had looked up a mistyped ID. Therefore it did not prove that the returned ID
was correctly verified.

## Useful lesson

Reliability is not just “did the model call a verification tool?” The arguments
must preserve exact state, the response must support the decision, the final claim
must match independent reality, and the experimental setup itself must be valid.
Agent Fault Lab records those as different facts so one green-looking event cannot
hide the others.

This is an evidence-led case study, not proof that a prompt safeguard generally
works. Exact counts, settings, failures, and limits are in the
[M04 reports](milestones/M04.md). The next reliability milestone is intentionally
not included in v0.1.

## Reusable video structure

1. Show the success-shaped response and empty database.
2. Ask whether read-back catches it.
3. Reveal why the first experiment was invalid: wrong checkpoint and truncation.
4. Rerun with the explicit non-thinking checkpoint.
5. Show the copied-ID mismatch from authentic trace pixels.
6. End with the independent evaluator's distinction: tool call, actual state, and
   supported claim are separate.

Use genuine terminal output and saved report excerpts. Do not manufacture a
safeguard win or hide the first failed experiment.
