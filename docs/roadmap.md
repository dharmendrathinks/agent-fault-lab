# Public roadmap

The aim is to reproduce agent failures and test whether safeguards help. Every
milestone needs a clear failure, an independent check and an honest result.

## Available in v0.1.0

- Bounded local tool-using agent and offline scripted client.
- Independently evaluated task store and strict terminal claims.
- Dropped-write fault and baseline/read-back comparison.
- Traces, accounting, saved evidence and reproducible reports.
- Offline tests, package checks and contribution documentation.

## Added in v0.2.0

- [M06](milestones/M06.md): malformed tool results and response-contract handling.
- [M07](milestones/M07.md): retries, duplicate effects and operation-ID replay.
- [M08](milestones/M08.md): process supervision, deadlines and cancellation limits.
- [M09](milestones/M09.md): durable conversation state and crash/restart recovery.
- [M10](milestones/M10.md): read-only failure timelines from saved evidence.

The [release notes](releases/v0.2.0.md) describe the guarantees and live findings.
The maintainer confirmed the remaining Phase 2 reviews complete on 2026-09-07
and authorized stable publication. [PROGRESS.md](../PROGRESS.md) records technical
evidence, that confirmation and next actions.

## Added in v0.3.0

The [release notes](releases/v0.3.0.md) describe the implemented capabilities and
the evidence available at publication.

- [M11](milestones/M11.md): real static SkillSpector admission and operation-bound
  task approvals, with audit/enforce comparisons and explicit resume. Accepted for
  progression after the user's M11 discussion and continuation request.
- [M12](milestones/M12.md): implemented untrusted-content comparisons across skill,
  task and tool-response surfaces, with scanner and permission policies varied separately.
- [M13](milestones/M13.md): implemented stale requests, policy, approvals and memory,
  comparing cached context with authoritative refresh.

Local technical and real-scanner evidence is recorded in [PROGRESS.md](../PROGRESS.md).
M12/M13 learning reviews and separately opted-in live smoke remain follow-up work.
Publication does not mark these learning milestones fully complete. The
[static smoke note](milestones/Phase3-static-smoke.md) preserves scanner
misses and distinguishes programmed client behavior from model observations.

SkillSpector is a shared Phase 3 integration. Semantic scanner comparisons remain
M14. Technical checks and learning acceptance gate advancement between milestones.

## Later, with concrete experiments

Stronger evaluation methodology, then reproduction and reuse with external projects.
These are planned
learning areas, not current capabilities or promised release dates.

See [PLAN.md](../PLAN.md) for the full staged plan and
[PROGRESS.md](../PROGRESS.md) for verified results and unresolved gates.

Useful contributions now: reproduce setup on a clean machine, improve an ambiguous
report, add an evaluation regression, or propose a real failure with synthetic
input and a clear expected outcome. Discuss adapters, frameworks and dashboards
before implementing them. See [CONTRIBUTING.md](../CONTRIBUTING.md).
