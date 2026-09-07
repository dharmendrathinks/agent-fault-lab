# Public roadmap

The aim is to reproduce agent failures and test whether safeguards help. Every
milestone needs a clear failure, an independent check and an honest result.

## Available in v0.1.0

- Bounded local tool-using agent and offline scripted client.
- Independently evaluated task store and strict terminal claims.
- Dropped-write fault and baseline/read-back comparison.
- Traces, accounting, saved evidence and reproducible reports.
- Offline tests, package checks and contribution documentation.

## Added in v0.2.0rc1 (prerelease)

- [M06](milestones/M06.md): malformed tool results and response-contract handling.
- [M07](milestones/M07.md): retries, duplicate effects and operation-ID replay.
- [M08](milestones/M08.md): process supervision, deadlines and cancellation limits.
- [M09](milestones/M09.md): durable conversation state and crash/restart recovery.
- [M10](milestones/M10.md): read-only failure timelines from saved evidence.

The [candidate release notes](releases/v0.2.0rc1.md) describe the guarantees and
live findings. M06/M07 were accepted for progression. M08/M09 learning checkpoints
and M10's independent diagnostic review remain pending; publication does not close
these gates. [PROGRESS.md](../PROGRESS.md) records technical evidence and next actions.

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
