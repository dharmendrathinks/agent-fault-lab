"""Adapter validation and owned subprocess tests, not real scanner acceptance."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import JsonValue

import agent_fault_lab.scanner as scanner_module
from agent_fault_lab.scanner import (
    BENIGN_SKILL,
    MAX_OUTPUT,
    VERSION,
    SkillSpector,
    invoke,
    normalize,
    read_skill,
)


def raw_report() -> dict[str, JsonValue]:
    return {
        "metadata": {
            "skillspector_version": VERSION,
            "llm_requested": False,
            "meta_analysis_applied": False,
            "inference_usage": [],
        },
        "analysis_completeness": {
            "is_complete": True,
            "status": "complete",
            "total_components": 1,
            "scanned_components": 1,
            "execution_successful": True,
            "coverage_percent": 100,
            "partially_inspected_files": 0,
            "entirely_uninspected_files": 0,
        },
        "risk_assessment": {"recommendation": "SAFE"},
        "issues": [],
        "execution_successful": True,
    }


@pytest.mark.parametrize(
    "recommendation,code",
    [
        ("SAFE", 0),
        ("CAUTION", 0),
        ("CAUTION", 1),
        ("DO_NOT_INSTALL", 1),
    ],
)
def test_valid_findings_are_not_execution_errors(
    recommendation: str, code: int
) -> None:
    raw = raw_report()
    raw["risk_assessment"] = {"recommendation": recommendation}
    assert normalize(json.dumps(raw), code) == (recommendation, True)


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("metadata", "skillspector_version", "changed"),
        ("metadata", "llm_requested", True),
        ("metadata", "llm_requested", 0),
        ("metadata", "meta_analysis_applied", True),
        ("metadata", "inference_usage", [{}]),
        ("analysis_completeness", "is_complete", False),
        ("analysis_completeness", "is_complete", 1),
        ("analysis_completeness", "status", "partial"),
        ("risk_assessment", "recommendation", "UNKNOWN"),
    ],
)
def test_degraded_or_changed_scan_fails_closed(
    section: str, key: str, value: JsonValue
) -> None:
    raw = raw_report()
    nested = raw[section]
    assert isinstance(nested, dict)
    nested[key] = value
    with pytest.raises(ValueError):
        normalize(json.dumps(raw), 0)


@pytest.mark.parametrize(
    "raw", ["[]", "null", "{}", "{", '{"a":1,"a":2}', '{"value":NaN}']
)
def test_malformed_scan_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize(raw, 0)


@pytest.mark.parametrize("code", [1, 2, -9])
def test_clean_report_cannot_hide_abnormal_exit(code: int) -> None:
    with pytest.raises(ValueError):
        normalize(json.dumps(raw_report()), code)


def test_skill_validation_preserves_exact_bytes(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    content = BENIGN_SKILL.encode() + b"\r\n  trailing  \r\n"
    path.write_bytes(content)
    assert read_skill(path) == content
    assert read_skill(tmp_path) == content
    (tmp_path / "script.py").write_text("raise AssertionError('never execute')")
    with pytest.raises(ValueError, match="only SKILL"):
        read_skill(tmp_path)
    link = tmp_path / "link.md"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="symlink"):
        read_skill(link)
    path.write_bytes(b"x" * (16 * 1024 + 1))
    with pytest.raises(ValueError, match="limit"):
        read_skill(path)


def test_missing_scanner_records_error_without_fallback(tmp_path: Path) -> None:
    result = SkillSpector(tmp_path / "absent-python").scan(
        BENIGN_SKILL.encode(), tmp_path / "scan"
    )
    assert result.status == "error" and not result.complete
    assert result.recommendation is None and result.error
    assert (tmp_path / "scan" / "scan.json").exists()


def executable(tmp_path: Path, code: str) -> Path:
    path = tmp_path / "fake-python"
    path.write_text(f"#!{sys.executable}\n{code}\n")
    path.chmod(0o700)
    return path


def test_timeout_reaps_owned_process(tmp_path: Path) -> None:
    python = executable(tmp_path, "import time\ntime.sleep(30)")
    started = time.monotonic()
    code, _, _, error = invoke(python, [], tmp_path, timeout=0.05)
    assert code < 0 and error == "Scanner deadline exceeded"
    assert time.monotonic() - started < 3


def test_descendant_cannot_hold_pipe_after_leader_exits(tmp_path: Path) -> None:
    python = executable(
        tmp_path,
        "import os,time\n"
        "if os.fork():\n    os._exit(0)\n"
        "time.sleep(0.5)\n"
        "open('late-effect', 'w').write('bad')\n",
    )
    _, _, _, error = invoke(python, [], tmp_path, timeout=0.05)
    assert error == "Scanner deadline exceeded"
    time.sleep(0.6)
    assert not (tmp_path / "late-effect").exists()


@pytest.mark.parametrize(
    ("snapshot", "exited"),
    [
        ("321 Z\n999 S\n", True),
        ("999 S\n", True),
        ("321 S\n", False),
        ("321 Z\n321 S\n", False),
        ("", False),
        ("unparseable\n", False),
    ],
)
def test_darwin_signal_permission_requires_no_live_group_members(
    monkeypatch: pytest.MonkeyPatch, snapshot: str, exited: bool
) -> None:
    monkeypatch.setattr(scanner_module, "platform", "darwin")
    monkeypatch.setattr(os, "killpg", Mock(side_effect=PermissionError("denied")))
    inspect = Mock(return_value=subprocess.CompletedProcess([], 0, snapshot, ""))
    monkeypatch.setattr(subprocess, "run", inspect)
    if exited:
        scanner_module._signal_group(321, signal.SIGKILL)
    else:
        with pytest.raises(PermissionError, match="denied"):
            scanner_module._signal_group(321, signal.SIGKILL)
    assert inspect.call_args.kwargs["timeout"] == 0.5


@pytest.mark.parametrize(
    "failure",
    [
        OSError("ps unavailable"),
        subprocess.CalledProcessError(1, "ps"),
        subprocess.TimeoutExpired("ps", 0.5),
    ],
)
def test_darwin_uninspectable_group_preserves_permission_error(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    monkeypatch.setattr(scanner_module, "platform", "darwin")
    monkeypatch.setattr(os, "killpg", Mock(side_effect=PermissionError("denied")))
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=failure))
    with pytest.raises(PermissionError, match="denied"):
        scanner_module._signal_group(321, signal.SIGTERM)


def test_other_platform_does_not_suppress_signal_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scanner_module, "platform", "linux")
    monkeypatch.setattr(os, "killpg", Mock(side_effect=PermissionError("denied")))
    inspect = Mock(side_effect=AssertionError("Darwin inspection must not run"))
    monkeypatch.setattr(subprocess, "run", inspect)
    with pytest.raises(PermissionError, match="denied"):
        scanner_module._signal_group(321, signal.SIGKILL)
    inspect.assert_not_called()


@pytest.mark.parametrize("destination", ["stdout", "report"])
def test_output_limit_is_bounded(tmp_path: Path, destination: str) -> None:
    code = (
        "import os\nwhile True: os.write(1, b'x'*65536)"
        if destination == "stdout"
        else "open('raw-report.json','wb').write(b'x'*(8*1024*1024))"
    )
    python = executable(tmp_path, code)
    _, stdout, stderr, error = invoke(python, [], tmp_path)
    report = tmp_path / "raw-report.json"
    size = report.stat().st_size if report.exists() else 0
    assert error and "exceeds 4 MiB" in error
    assert len(stdout) + len(stderr) + size <= MAX_OUTPUT


def test_child_environment_drops_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-secret")
    python = executable(tmp_path, "import os,json\nprint(json.dumps(dict(os.environ)))")
    code, out, _, error = invoke(python, [], tmp_path)
    assert code == 0 and error is None
    assert "OPENAI_API_KEY" not in json.loads(out)


def test_worker_blocks_python_sockets_before_scanner_import() -> None:
    # A child avoids changing the test process or its resource limits.
    script = (
        "import sys,socket\n"
        "from agent_fault_lab import scanner_worker as w\n"
        "class FakeDistribution:\n"
        "    version=w.VERSION\n"
        "    def read_text(self, name):\n"
        '        return \'{"vcs_info":{"commit_id":"\'+w.PIN+\'"}}\'\n'
        "w.distribution=lambda _: FakeDistribution()\n"
        "sys.argv=['worker','doctor']\n"
        "w.main()\n"
        "for call in [socket.socket, lambda: socket.create_connection(('127.0.0.1',1)),"
        "lambda: socket.getaddrinfo('example.invalid',80)]:\n"
        "    try: call()\n"
        "    except PermissionError: pass\n"
        "    else: raise AssertionError('network was allowed')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
        env=dict(os.environ),
    )
    assert completed.returncode == 0, completed.stderr
