# Changelog

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
