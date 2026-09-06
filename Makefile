.PHONY: check lockcheck test lint typecheck build demo agent-demo doctor

UV ?= uv
RUN = $(UV) run --offline --no-sync

check: lockcheck lint typecheck test build

lockcheck:
	$(UV) lock --check --offline

test:
	$(RUN) pytest

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

typecheck:
	$(RUN) mypy

build:
	$(UV) build --offline --no-build-isolation

demo:
	$(RUN) python examples/task_workflow.py

agent-demo:
	$(RUN) aflab demo --offline

doctor:
	$(RUN) aflab doctor
