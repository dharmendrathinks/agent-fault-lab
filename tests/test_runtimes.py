"""Root tests need no LangGraph dependency; actual graph tests run in runtime-check."""

import json
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import JsonValue

from agent_fault_lab import runtimes
from agent_fault_lab.boundaries import resume_boundary
from agent_fault_lab.runtime_records import RUNTIME_CASES, runtime_config
from agent_fault_lab.study_records import plan


@pytest.mark.parametrize("change", ["version", "source", "dependency"])
def test_doctor_rejects_environment_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from agent_fault_lab.study_records import fingerprint

    project = tmp_path / "integrations/langgraph"
    (project / ".venv/bin").mkdir(parents=True)
    (project / ".venv/bin/python").touch()
    (project / "uv.lock").write_text(
        '[[package]]\nname="langgraph"\nversion="1.2.11"\n'
    )
    identity = {
        "langgraph": "old" if change == "version" else "1.2.11",
        "python": "3.12",
        "source_sha256": "wrong"
        if change == "source"
        else fingerprint()["source_sha256"],
        "dependencies": {"langgraph": "old" if change == "dependency" else "1.2.11"},
    }
    monkeypatch.setattr(runtimes, "integration", lambda: project)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=json.dumps(identity)),
    )
    with pytest.raises(ValueError, match="differ"):
        runtimes.doctor()


def test_runtime_forwards_owned_study_lock_and_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_fault_lab.audit_corpus import Reference, seed
    from agent_fault_lab.boundary_evaluation import evaluate
    from agent_fault_lab.boundary_records import BoundaryState
    from agent_fault_lab.runtime_records import RuntimeResult

    fixture = tmp_path / "fixture"
    state = seed(Reference("fixture", kind="boundary"), fixture)
    assert isinstance(state, BoundaryState)
    identity: dict[str, JsonValue] = {"langgraph": "1.2.11"}
    result = RuntimeResult(
        runtime="native",
        identity=identity,
        evaluation=evaluate(fixture, state),
        elapsed_seconds=0.0,
        nodes=(),
    )
    output = tmp_path / "runtime"
    captured: dict[str, Any] = {}

    def spawn(command: list[str], **kwargs: Any) -> Any:
        captured.update(kwargs, command=command)
        output.mkdir()
        (output / "runtime.json").write_text(result.model_dump_json())

        def communicate(*, timeout: float) -> tuple[bytes, bytes]:
            captured["timeout"] = timeout
            return b"", b""

        return SimpleNamespace(returncode=0, communicate=communicate)

    monkeypatch.setattr(runtimes, "doctor", lambda: identity)
    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(signal, "getitimer", lambda timer: (12.0, 0.0))
    with (tmp_path / "owned.lock").open("wb") as lock:
        assert (
            runtimes.run_runtime(
                "native", "approved", "offline", output, study_lock=lock.fileno()
            )
            == result
        )
        assert captured["pass_fds"] == (lock.fileno(),)
    assert captured["command"][-1] == "12.0" and captured["timeout"] == 17.0
    assert "start_new_session" not in captured


def test_runtime_study_refuses_missing_environment_before_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_fault_lab.studies import run

    monkeypatch.setattr(runtimes, "integration", lambda: tmp_path)
    with pytest.raises(ValueError, match="runtime-setup"):
        run(plan("runtime"), tmp_path / "study", "offline")
    assert not (tmp_path / "study").exists()


def test_runtime_design_is_matched_and_complete() -> None:
    design = plan("runtime")
    assert len(design.slots) == 24
    assert design.runtime == "matched"
    assert {s.policy for s in design.slots} == {"native", "langgraph"}
    for case in RUNTIME_CASES:
        assert sum(s.case == case for s in design.slots) == 6
        config = runtime_config(case, "offline")
        assert config.permission_policy == config.scan_policy == "enforce"
    assert runtime_config("injection-override", "offline").surface == "tool"
    assert runtime_config("memory-stale-title", "offline").context_policy == "refresh"


def test_missing_runtime_is_explicit_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtimes, "integration", lambda: tmp_path)
    with pytest.raises(ValueError, match="runtime-setup"):
        runtimes.run_runtime("langgraph", "approved", "offline", tmp_path / "run")
    assert not (tmp_path / "run").exists()


def test_runtime_cannot_resume_as_native(tmp_path: Path) -> None:
    (tmp_path / "runtime-manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="unsupported"):
        resume_boundary(tmp_path, mode="offline")


@pytest.mark.parametrize(
    "case", ["manual", "replay", "missing", "injection-override-benign"]
)
def test_future_runtime_cases_are_not_silently_admitted(case: str) -> None:
    with pytest.raises(ValueError, match="four frozen"):
        runtime_config(case, "offline")
