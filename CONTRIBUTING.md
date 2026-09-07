# Contributing to Agent Fault Lab

Contributions should make a failure more reproducible, an evaluation more
trustworthy, or the evidence easier to inspect. Please do not add a provider,
framework, fault, or compatibility layer without first explaining the concrete
experiment it enables.

## Local setup

Use Python 3.12 and `uv`:

Fork the repository, clone your fork and create a focused branch before editing.

```sh
uv sync --locked --all-groups
make check
```

`make check` runs with dependency fetching disabled. Tests block Python sockets,
so the default suite needs no Ollama daemon, model, account, or credential.

## A useful change

1. State the failure or contract being tested.
2. Add a small regression that fails for the relevant reason.
3. Keep the task environment, model loop, fault injector, and independent
   evaluator separate.
4. Preserve unfavorable outcomes and distinguish scripted fixtures from live-model
   evidence.
5. Update the relevant walkthrough and limitation.

Use synthetic data only. Never commit secrets, private prompts, customer data,
model weights, generated run databases, or unreviewed live traces. Routine outputs
belong under ignored `runs/`.

## Checks

```sh
make lint
make typecheck
make test
make build
make check
make package-check
```

For M11 scanner/approval changes, also run `make scanner-setup` once (downloads the
separately locked scanner) and `make scanner-check`. The latter runs real static
SkillSpector and scripted agent/approval checks without model inference. Both CI
platforms require it. Core `make check` stays independent of scanner installation.

A local-model smoke is separate and deliberately inconvenient to trigger:

```sh
make doctor
AFLAB_RUN_LIVE_TESTS=1 make live-test
```

It never pulls a model and is not a release gate for ordinary contributions.
Model behavior is an observation, not a deterministic unit-test expectation.

Before proposing a change, ensure `git diff --check` is clean and describe which
claims the evidence supports—and which it does not. See
[development](docs/development.md), [known limitations](docs/known-limitations.md),
and [security guidance](SECURITY.md).

Use `examples/capture_example.py` to capture the public scripted example in a
new directory and review the diff before replacing evidence. Keep its
scripted label and list of omissions. Do not hand-edit outcomes to make tests pass.

AI-assisted contributions are welcome when you understand and verify the change.
Contributions are provided under this project's [MIT license](LICENSE); only submit
work you are entitled to contribute. Follow the [code of conduct](CODE_OF_CONDUCT.md).
