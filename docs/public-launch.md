# Public-launch checklist

This is a maintainer checklist, not an automated publication workflow. Making the
repository public does not push local commits or create a release. The user owns
those decisions. Local test results are recorded in [PROGRESS.md](../PROGRESS.md).

Launch status: the repository was made public on 2026-09-07. Private vulnerability
reporting, secret scanning, push protection, Dependabot security updates, and
strict Ubuntu/macOS status checks on `main` are enabled. Public HTTP access to the
repository, README, issue chooser, and advisory form was verified; final visual
rendering inspection remains a maintainer browser check.

## Before pushing

- Review `git status`, the complete diff and the intended commit history. Include
  the new source, tests, docs, CI and scripted example; do not omit untracked files.
- Run `make check`, `make package-check` and `git diff --check`.
- Inspect distributable contents for unwanted files. Check for credentials,
  personal paths and unreviewed raw data in both proposed files and Git history.
  Automated pattern scans are not a complete security review.
- Confirm the MIT license covers original code; do not bundle model weights or
  third-party material without its required license.
- Read the README as a newcomer and review the scripted sample and live-result
  limitations. Do not claim a released version, CI pass or public dataset that
  does not exist.

## GitHub setup and verification

- Explicitly approve the local commit and push. Do not rewrite historical commits
  just to remove a local path without a separate review.
- Run the configured Ubuntu 24.04 and macOS 14 workflows on the intended commit.
  Local macOS success does not establish hosted CI or Linux success.
- When making the repository public, immediately enable **private vulnerability
  reporting** in Settings → Security → Advanced Security, then check the reporting
  button as a visitor. GitHub requires explicit owner/admin setup for a public
  repository. See [GitHub's instructions](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).
- Verify issue forms, PR template, README links and the diagram on GitHub. Hosted
  rendering and issue-form acceptance have not been established by local tests.
- Consider requiring the actual observed CI check names before merges, and review
  Dependabot action updates rather than auto-merging them.
- Configured description: “A Python lab for reproducing AI agent failures,
  injecting tool faults, and independently evaluating outcomes.” Configured topics:
  `agent-reliability`, `ai-agents`, `fault-injection`, `llm-evaluation`, `ollama`,
  `python`, `reproducible-research`, `sqlite`, and `tool-calling`.

Actions have read-only repository permissions and full-SHA pins; PR workflows do
not receive publication secrets. This follows
[GitHub's secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use).
Setup downloads pinned tools and locked dependencies; inference is not part of CI.

## Release only after review

Follow the [release workflow](development.md#publish-a-release-candidate) and review
the [v0.2.0rc1 notes](releases/v0.2.0rc1.md); the
[v0.1 checklist](releases/v0.1.0.md) records the original release. Tag and publish only after explicit
approval and successful CI. Review package metadata before any package-index
publication; the quickstart currently supports source installation and makes no
claim of a PyPI release. A public repository does not require publishing to PyPI.
