# Pinned static SkillSpector environment

This is a required integration for M11 boundary experiments. It stays separate
from the core package and default offline tests because its dependency graph
includes scanner frameworks and model clients. Those model clients are not used
by this phase.

Upstream: [NVIDIA SkillSpector at the pinned revision](https://github.com/NVIDIA/SkillSpector/tree/704bc9544260c2f41222dc0f92982521709496ab).
The locked Git commit is `704bc9544260c2f41222dc0f92982521709496ab`, declared
version `2.11.1`. Both are verified from installed distribution metadata before
the scanner is imported. `uv.lock` is independent of the root lockfile.

From the repository root:

```sh
make scanner-setup
uv run --offline --no-sync aflab scanner doctor
make scanner-check
```

Setup fetches the locked dependencies. Checks then run the real static scanner
without model inference. The same check is configured in Ubuntu and macOS CI.
Core `make check` uses explicitly labeled doubles for scanner-dependent unit
tests; it does not need this environment installed.

Use `aflab scanner scan FILE.md --output NEW_DIRECTORY` for a standalone scan.
The supported input is one UTF-8 Markdown file, at most 16 KiB, or a directory
containing only `SKILL.md`. Archives, repositories, executable skills and transitive
dependencies are outside this milestone. The fixtures are inert text; never run
the commands in the suspicious fixture.

The adapter uses an isolated Python subprocess, an allowlisted environment,
`--no-llm`, no suppression baseline, no transitive fetching and Python socket
blocking before scanner imports. It records raw findings and warnings. This is
not an operating-system sandbox or a security guarantee against malicious Python
packages. The pinned scanner is trusted software; the skill is untrusted text.
Any unavailable required analysis is an error, including incomplete coverage.

`scanner-check` retains actual results under ignored `runs/scanner-check-UUID`.
It checks benign admission, the observed suspicious-fixture block, missing-grant
audit/enforcement and the manual CLI lifecycle with a scripted agent. It also runs
26 M12/M13 context experiments, retaining corpus classification results in
`runs/context-check-UUID/summary.json`. Its scripted
operator decisions are test automation, not a human learning review.

For an installed lab wheel or a different working directory, pass the absolute
environment interpreter using `scanner --python` on its doctor/scan subcommand,
or `boundaries run/compare --scanner-python`. Install this environment from the
checkout; the wheel does not bundle the external scanner or its dependencies.

Read the [M11 walkthrough](../../docs/milestones/M11.md) for approval semantics,
failure cases, evidence and limitations.
