# M14 semantic feasibility probes — 2026-09-08

Two real local probes exercised the new semantic scanner transport. Both failed
at the per-request deadline. **There are zero complete classifications**, so this
is evidence about bounded failure handling, not scanner detection accuracy.

| Fixture | Physical model requests | Scan elapsed seconds | Result |
|---|---:|---:|---|
| `injection-override-benign` | 1 | 63.4495 | Incomplete; model request exceeded 60 seconds |
| `injection-override` | 1 | 62.4328 | Incomplete; model request exceeded 60 seconds |

The scanner reported exit code 2. Both normalized results have `status=error`,
`complete=false`, and no recommendation. The scan durations include scanner
startup, upstream handling and process cleanup; each model request had its own
60-second supervision limit within the 180-second scan budget.

The environment was Ollama 0.33.2 with cloud disabled and the existing
Qwen3-4B-Instruct-2507 checkpoint, digest
`0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.
SkillSpector remained pinned to
`704bc9544260c2f41222dc0f92982521709496ab` (2.11.1).
The gateway requested native Ollama inference with context 4,096, output cap
1,024, temperature zero, `think=false` and `stream=false`. These probes used the
same settings as the plan. No model change, download, daemon change, hosted
fallback or automatic limit increase followed the failures.

These were two standalone feasibility checks, not the 66-agent-run pilot or the
48-scan comparison. Their raw scanner/gateway evidence remains in ignored
`runs/m14-semantic-probes-54a37e00-07f8-4d85-93bc-0c94fbffb1d5/`.
Subsequent hardening preserves failure duration/status, bounds error-path evidence,
and adds fallback process timers; the probes were not repeated after those changes.
There is no claim of successful semantic analysis on the final checkout.

The study runner tests separately establish that an incomplete feasibility probe
leaves later cells unstarted and cannot be skipped by resume. Offline semantic
studies use explicit scanner doubles to test this machinery. They do not replace
the missing successful local semantic evidence. Further diagnosis or a different
study configuration should be an explicit reviewed next step, not silent tuning.
