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

## Check the distribution, not just the checkout

```sh
make package-check
```

This builds the wheel, syncs runtime dependencies directly from `uv.lock` into a
fresh temporary environment offline, and installs the built wheel there. It
checks installed-package identity outside the checkout, exercises the version
entry point, three scripted demos, the original comparison, M06/M07 comparisons,
an M08 process comparison, finalized-run resume, diagnosis and saved reports. Python socket
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

## Publish a release candidate

With explicit publication authorization, update the package version, lockfile,
changelog, README, release notes, roadmap and progress record together. Run
`make check` and `make package-check`, inspect both distribution archives, then
commit and push. Wait for both hosted CI jobs on the intended release commit.

Create an annotated version tag on that verified commit. Attach its wheel, source
archive and `SHA256SUMS` to the GitHub release; verify downloaded checksums and the
remote tag's commit. Mark candidates as prereleases and retain the previous stable
release as latest. Record the actual commit, CI run and publication outcome in
`PROGRESS.md`. Publication does not satisfy learning or independent-review gates.
This workflow does not publish to PyPI.
