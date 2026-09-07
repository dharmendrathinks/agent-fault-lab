# Public roadmap

The aim is to reproduce agent failures and test whether safeguards help. Every
milestone needs a clear failure, an independent check and an honest result.

## Available in v0.1.0

- Bounded local tool-using agent and offline scripted client.
- Independently evaluated task store and strict terminal claims.
- Dropped-write fault and baseline/read-back comparison.
- Traces, accounting, saved evidence and reproducible reports.
- Offline tests, package checks and contribution documentation.

## Next, after first-release review

- M06: malformed tool results and response-contract handling.
- M07: retries, duplicate effects and idempotency.
- Subsequent execution milestones: timeout, interruption and recovery experiments.

## Later, with concrete experiments

Permissions and untrusted inputs; context and memory failures; stronger evaluation
methodology; then reproduction and reuse with external projects. These are planned
learning areas, not current capabilities or promised release dates.

See [PLAN.md](../PLAN.md) for the full staged plan and
[PROGRESS.md](../PROGRESS.md) for verified results and unresolved gates.

Useful contributions now: reproduce setup on a clean machine, improve an ambiguous
report, add an evaluation regression, or propose a real failure with synthetic
input and a clear expected outcome. Discuss adapters, frameworks and dashboards
before implementing them. See [CONTRIBUTING.md](../CONTRIBUTING.md).
