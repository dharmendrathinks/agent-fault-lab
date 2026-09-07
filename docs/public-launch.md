# Public-launch checklist

This is a maintainer checklist, not an automated publication workflow. Making the
repository public does not push local commits or create a release. The user owns
those decisions. Local test results are recorded in [PROGRESS.md](../PROGRESS.md).

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
- Optional description: “A local-first lab for reproducing AI-agent failures and
  checking outcomes independently.” Suggested topics: `ai-agents`, `fault-injection`,
  `evaluation`, `reliability`, `ollama`, `python`.

Actions have read-only repository permissions and full-SHA pins; PR workflows do
not receive publication secrets. This follows
[GitHub's secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use).
Setup downloads pinned tools and locked dependencies; inference is not part of CI.

## Release only after review

Complete the [v0.1 checklist](releases/v0.1.0.md). Tag and publish only after explicit
approval and successful CI. Review package metadata before any package-index
publication; the quickstart currently supports source installation and makes no
claim of a PyPI release. A public repository does not require publishing to PyPI.
