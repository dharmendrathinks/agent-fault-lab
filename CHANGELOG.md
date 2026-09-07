# Changelog

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
