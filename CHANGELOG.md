# Changelog

## 0.3.0 — 2026-09-07

- Added M11 static SkillSpector integration in a separately pinned environment,
  strict content admission, bounded scanner execution and retained raw evidence.
- Added operation-bound approvals, explicit approve/reject/resume commands, atomic
  grant consumption and task receipts, and independent authorization evaluation.
- Added scripted permission comparisons, boundary reports/diagnosis, restart and
  rollback regressions, installed-wheel coverage and real-scanner CI checks.
- Added M12's four attack/benign pairs on skill, task and tool surfaces, crossed
  scanner/permission policies and independent delivery, seed and effect accounting.
- Added M13's stale title/policy/approval, poisoned notes and shortened history
  cases, with cached/authoritative-refresh comparisons, read-only request-state tools,
  rescan provenance and durable restart behavior.
- Recorded real static-scanner misses in bounded scripted integration evidence.
  M11 is accepted for progression; M12/M13 learning reviews and separately opted-in
  Phase 3 live smoke remain pending; the maintainer authorized stable publication
  with those limits disclosed.
- Updated 0.3.0 package metadata and [release notes](docs/releases/v0.3.0.md).
  The version change also changes the resume fingerprint: resume older runs with
  their original checkout/environment; saved reports and diagnostics remain readable.

## 0.2.0 — 2026-09-07

- Promoted the reviewed Phase 2 candidate to a stable release after the maintainer
  confirmed review completion and authorized publication.
- Updated package metadata, installation instructions, roadmap and review records.
  Runtime behavior and locked dependency versions are unchanged from v0.2.0rc1.
- Preserved candidate artifacts and live findings. The package version participates
  in the resume fingerprint: use the original candidate environment to resume its
  runs. Saved-report and diagnostic readers remain available in the stable release.

## 0.2.0rc1 — 2026-09-07 (prerelease)

- Added M06 response-contract experiments: strict versioned envelopes, raw response
  capture, syntax/schema/request checks, and paired pass-through/validated policies.
- Added explicit offline/live `aflab reliability` commands and regenerable reports
  that keep contract failures separate from independently inspected task outcomes.
- Added M07 before-write/lost-reply experiments, bounded retries, and atomic
  operation-ID deduplication with persisted replay results and conflict detection.
- Added attempt accounting, independent duplicate-effect evaluation, regenerable
  retry reports, and installed-wheel/offline regressions.
- Added M08 process supervision, transient recovery, deadlines, observed late results,
  terminate/kill cleanup and separate effect accounting with offline worker sockets.
- Added M09 durable conversation checkpoints, inherited run ownership, persistent
  budgets, protected crash recovery and resumable artifact finalization.
- Added M10 read-only Markdown/JSON diagnosis with journal ordering, evidence
  references and explicit projection/schema/timing gaps. Preserved all prior readers.
- Recorded bounded M06–M09 live smoke findings, including wrong-ID completion
  claims and false non-completion; no general model-reliability improvement claimed.
- Published as a candidate for review: M08/M09 learning checkpoints and M10's
  independent diagnostic review remain pending. v0.1.0 remains the stable release.

## 0.1.0 — 2026-09-07

- Added a bounded tool-using agent and local-only Ollama adapter.
- Added independent SQLite evaluation and strict structured terminal claims.
- Added dropped-write fault injection and a four-cell safeguard comparison.
- Preserved inconclusive and unfavorable live evidence, including checkpoint,
  truncation, and task-ID copying failures.
- Added deterministic report regeneration, offline checks, opt-in live testing,
  Ubuntu/macOS CI configuration, and first-release documentation.
- Added a captured scripted example with regeneration checks, isolated wheel
  verification, architecture/artifact guides and community contribution templates.
- Reject duplicate JSON keys, symlink/non-file evidence and unsupported schemas
  during saved-report regeneration; preserve reports on validation/replacement errors.
- Updated the development lock to pytest 9.1.1 after GitHub identified vulnerable
  temporary-directory handling in the previous test-runner version.
