# Development and verification

## Supported development baseline

- Python 3.12 (the package currently rejects other minor versions).
- `uv` with the committed `uv.lock`.
- macOS is the locally verified environment.
- Ubuntu 24.04 and macOS 14 are configured in GitHub Actions; both workflows must
  run successfully before a release is published. Hosted results are not implied
  by a local check.

On macOS or Linux:

```sh
git clone https://github.com/dharmendrathinks/agent-fault-lab.git
cd agent-fault-lab
uv sync --locked --all-groups
make check
uv run --offline --no-sync aflab demo --offline
```

The initial sync and CI setup may download locked Python packages. `make check`
then uses `--offline --no-sync`: it neither resolves new versions nor installs
missing dependencies. Pytest also disables Python sockets. This is reproducible
dependency behavior, not a complete operating-system network sandbox.

Both CI jobs perform online environment setup first, followed by the same offline
lock, lint, type, test, build and isolated wheel commands. They do not install or
start Ollama. `make test` resets both live opt-in flags to zero.

Phase 3 also requires `make scanner-setup` and `make scanner-check`. Setup installs
the independently locked SkillSpector environment. The check then runs actual static
scanning with scripted agents: M11 approval lifecycle, all eight M12 skill fixtures,
task/tool policy cells and both M13 context variants for every case. Both CI platforms
run this check. Default unit tests use labeled scanner doubles and remain independent
of scanner installation. Read the actual recommendations; scanner misses are findings,
not automatically harness failures.

Phase 4 adds `aflab evaluator audit --output DIR`, included in offline unit and
installed-wheel checks. It runs independent SQL fixtures against twelve disposable
grader mutations. `make runtime-setup` installs the separate pinned LangGraph
environment; after scanner setup, `make runtime-check` exercises the actual graph
with controlled model responses and sockets blocked. Both CI platforms run that
integration check. Root tests do not require LangGraph to be installed.

## Check the distribution, not just the checkout

```sh
make package-check
```

This builds the wheel, syncs runtime dependencies directly from `uv.lock` into a
fresh temporary environment offline, and installs the built wheel there. It
checks installed-package identity outside the checkout, exercises the version
entry point, three scripted demos, the original comparison, M06/M07 comparisons,
an M08 process comparison, M11 approvals, M12/M13 comparisons, finalized-run resume,
diagnosis, repeated-study execution, the evaluator audit and saved reports. It
also checks that missing runtime integration fails explicitly. Python socket
construction is blocked during the scripted application calls. Temporary files
are cleaned automatically. Initial dependency setup must have populated uv's cache.
Using the lock directly avoids requiring cached package-index metadata in addition
to the downloaded wheels; the source project is excluded from this sync.

The source checkout's tests also verify the checked-in scripted reports and local
Markdown links. They do not validate GitHub rendering or remote workflow execution.
See [public launch](public-launch.md) for those remaining checks.

## Optional local inference

Follow [M02 setup](milestones/M02.md#local-setup), then run:

```sh
make doctor
uv run --offline --no-sync aflab run
```

For the dedicated live pytest smoke, both actions are required:

```sh
AFLAB_RUN_LIVE_TESTS=1 make live-test
```

The user opt-in flag alone does not select the test: the Make target supplies a
second command-path guard and enables sockets only for `tests/test_live_ollama.py`.
It performs no pull, retry,
cloud fallback, or task-success assertion. Generated evidence stays temporary.

## Verify saved reports

```sh
uv run --offline --no-sync aflab report runs/YOUR-RUN --check
uv run --offline --no-sync aflab report runs/YOUR-RUN
```

`--check` changes nothing and returns 1 for a missing/stale `report.md`. Regeneration
validates either `evaluation.json` (plus matching `observation.json`, when present)
or `comparison.json`, then atomically replaces only the Markdown. It does not read
SQLite, rerun evaluation, contact a model, or rewrite raw evidence.

## Prepare a release

Keep local preparation separate from publication. Update the target package version,
lockfile, draft release notes, changelog, roadmap and progress record together.
Keep the README stable link and installation tag on the actually published release.
For Phase 3, follow the [v0.3.0 release gates](releases/v0.3.0.md#release-gates).

```sh
uv sync --locked --all-groups
make check
make package-check
make scanner-check
git diff --check
```

Inspect both distribution archives: the source must include the scanner's separate
lock/setup files and fixtures, while neither archive may contain local environments,
credentials, model weights or private run databases. Verify the extracted source
and an installed wheel outside the checkout. Generate `SHA256SUMS` from only the
target version's wheel and source archive, excluding old files retained in `dist/`.
Run PR Ready and record its actual verdict, including untracked-file findings.
Automated checks do not satisfy learning acceptance or opt in to live inference.

## Publish a stable release

After review/live-evidence gates are satisfied, or the maintainer authorizes a
release with specific follow-ups explicitly disclosed in PLAN.md, update the release-facing
README and changelog for the intended stable tag and recheck the final package.
Commit/push only when requested, then wait for both hosted CI jobs on the intended
release commit. For Phase 3, both platforms must also pass real-scanner acceptance.

With explicit publication authorization, create an annotated version tag on that
verified commit. Attach its wheel, source archive and `SHA256SUMS` to the GitHub
release; mark the stable release as latest with prerelease disabled. Verify
downloaded checksums and the remote tag's commit. Record the actual CI run and
publication outcome in
`PROGRESS.md`. Publication does not satisfy learning or independent-review gates.
This workflow does not publish to PyPI.

## Publish a release candidate

Use a candidate only when explicitly requested. Follow the same verification and
publication process, use a version such as `0.3.0rc1`, mark it as a prerelease and
retain the previous stable release as latest. Do not silently substitute a candidate
for a requested stable release.
