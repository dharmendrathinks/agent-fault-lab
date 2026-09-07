# Scripted dropped-write example

[Open the comparison report](report.md). Each row links to its individual report.

This is a captured **scripted test-client run**, not an Ollama run, model benchmark,
or evidence that a prompt improves real agents. The ordinary CLI executed four
cases against fresh SQLite databases on 2026-09-07. Programmed responses determine
which tools are requested and what completion claim is made.

The baseline falsely claims completion after a dropped write. The scripted
read-back case reports non-completion; it detects the failure but does not recover
the missing task. Real models need not follow either sequence.

## Verify or capture

From the repository root after the README setup:

```sh
uv run --offline --no-sync aflab report examples/evidence/dropped-write --check
make test
uv run --offline --no-sync python examples/capture_example.py --output runs/new-example
```

Tests check all five reports against their saved JSON. This verifies rendering
consistency, not authenticity or a rerun of the experiment.

The capture output directory must not exist. The script runs the public offline
comparison command in a temporary directory and copies the JSON/report excerpt
without editing results. IDs and elapsed times vary between captures. Rendering
the same saved JSON is deterministic; runs are not byte-identical.

## Included and omitted

Included: comparison JSON/Markdown and four evaluation/observation/Markdown pairs.
The observation includes execution results and accounting. Unknown model token
usage remains `null`, not a made-up zero.

Omitted: manifests, traces, raw result files and databases. This avoids machine
paths and environment metadata and keeps the sample small. It is a report excerpt,
**not a complete execution archive**. To query databases and inspect full traces,
run `aflab compare --offline` yourself. See the
[artifact guide](../../../docs/artifacts.md).
