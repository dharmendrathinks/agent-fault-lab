.PHONY: check lockcheck test lint typecheck build package-check demo agent-demo doctor live-test
.PHONY: scanner-setup scanner-check

UV ?= uv
RUN = $(UV) run --offline --no-sync

check: lockcheck lint typecheck test build

lockcheck:
	$(UV) lock --check --offline

test:
	AFLAB_RUN_LIVE_TESTS=0 AFLAB_LIVE_TEST_COMMAND=0 $(RUN) pytest

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

typecheck:
	$(RUN) mypy

build:
	$(UV) build --offline --no-build-isolation

package-check: build
	$(RUN) python scripts/check_distribution.py

scanner-setup:
	$(UV) sync --project integrations/skillspector --locked

scanner-check:
	$(UV) lock --project integrations/skillspector --check --offline
	$(RUN) python scripts/check_scanner.py
	$(RUN) python scripts/check_context.py

demo:
	$(RUN) python examples/task_workflow.py

agent-demo:
	$(RUN) aflab demo --offline

doctor:
	$(RUN) aflab doctor

live-test:
	@test "$$AFLAB_RUN_LIVE_TESTS" = "1" || (echo "Refused: set AFLAB_RUN_LIVE_TESTS=1 explicitly" >&2; exit 2)
	AFLAB_LIVE_TEST_COMMAND=1 $(RUN) pytest --enable-socket -m live tests/test_live_ollama.py
