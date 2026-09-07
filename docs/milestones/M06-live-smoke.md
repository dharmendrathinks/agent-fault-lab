# M06 — Focused local response-contract smoke, 2026-09-07

Four live runs were recorded after offline and installed-wheel checks. Each run
saved exactly one correct task. Three terminal completion claims named incorrect
IDs; the fourth response violated the terminal JSON contract. This smoke does
not establish a safeguard winner.

## Provenance and method

- Checkpoint: `qwen3:4b-instruct-2507-q4_K_M`, Ollama 0.33.2.
- Installed digest:
  `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.
- Doctor and model responses identified Qwen3 / 4B / Instruct / 2507, tools
  supported, and cloud disabled. The digest matches the approved M04 replacement.
- The existing baseline prompt, tools, evaluator, temperature 0, 4,096-token
  context, 512 output-token limit, six-call budgets, and `think=false` remained.
- Each condition ran pass-through then validated, once per policy. No randomization
  or counterbalanced repetition is claimed for this one-trial smoke.
- Manifests record source commit `1de0f2e511dade10ab1d169b945affa40326b4c7`
  with `dirty: true`; M06 was local and uncommitted. This is not a tagged M06 build.
- No model download, daemon change, paid/hosted inference, automatic retry,
  forced read-back, ID repair, terminal-output cleanup, or extra run was performed.

Local ignored evidence directories:

- Healthy: `runs/m06-compare-b19dbf61-9675-4632-a660-b019269fdf65`.
- Wrong create title: `runs/m06-compare-404a378e-ff3a-4483-a4f6-ac2805e1939a`.

Each includes its paired manifest, aggregate JSON/report, comparison trace, and
child runs with raw responses, independent evaluation and SQLite state. This
write-up describes local evidence; the raw artifacts are not committed or claimed
to have been independently reproduced by another person.

## Observations

| Condition | Policy | Correct stored tasks | Contract result | Terminal report | Claim support |
|---|---|---:|---|---|---|
| Healthy | pass-through | 1 | Unchecked | Valid completion JSON | Contradicted: wrong ID |
| Healthy | validated | 1 | Valid response | Valid completion JSON | Contradicted: wrong ID |
| Wrong create title | pass-through | 1 | Unchecked; fault activated | Valid completion JSON | Contradicted: wrong ID |
| Wrong create title | validated | 1 | Request mismatch rejected; fault activated | Invalid: prose followed by JSON | Not evaluated |

Each run made two model requests and one create call. No run requested `get_task`.
The stored title was exactly `Review the invoice` in all four databases.

Examples of exact ID-copying errors:

| Stored task ID | Reported task ID |
|---|---|
| `b489a253-4f36-43a0-b110-1b7afc116d1d` | `b48_253-4f36-43a0-b110-1b7afc116d1d` |
| `a10bf5e6-59ce-40ba-8a5c-608b31c833ba` | `a10bf_5e6-59ce-40ba-8a5c-608b31c833ba` |
| `be2c8030-ff7d-4244-abf5-9855a84f1e78` | `be2c8_30-ff7d-4244-abf5-9855a84f1e78` |

In the validated altered-title run, the executor returned an `invalid_result`
request-validation error after the write committed. The model responded with
prose saying it could not create the task, followed by a JSON non-completion
object. The strict terminal parser rejected the whole response. It did not extract
the JSON or turn that invalid report into an assessable claim.

Across all four runs, the adapter reported 3,484 prompt tokens and 271 output
tokens over eight model calls. Recorded loop elapsed time totaled approximately
9.505 seconds, including approximately 1.831 seconds of provider-reported model
loading. These timings are exploratory and not a performance comparison. There
were no provider errors, output-limit stops, or evaluator errors.

## Accounting correction and artifact preservation

The initial smoke used M06 reliability schema 1. Its `contracts.fault_activations`
correctly recorded the two response injections, but the inherited
`metrics.fault_exercised` flag still counted only dropped writes and was false in
those runs. This was a reporting defect; use the contract counts and injection
events to interpret the original smoke.

The implementation now writes reliability schema 2, where the generic flag covers
every activated fault and a validation invariant checks its consistency. Readers
retain schema 1 support. Original observations and reports were preserved; no
inference was repeated to replace these results. Offline regressions verify the
corrected accounting and backward readability.

## What the evidence supports

The validator detected the injected request inconsistency. It did not prevent a
correct write, repair the model's final report, establish successful recovery, or
ensure correct ID copying. Healthy response validation also left terminal ID
errors untouched.

Three of three assessable completion claims were contradicted. The remaining run
had no assessable terminal claim. Its zero scored false-success count is not
evidence of reliable reporting. The stored task outcome and the claim outcome
must remain separate.

The [M06 walkthrough](M06.md) explains the contract boundaries. Review these
results before proceeding to M07's retry and duplicate-effect experiments.
