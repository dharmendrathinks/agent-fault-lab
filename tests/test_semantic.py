"""Socket-free transport contracts; these are not semantic model results."""

import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import JsonValue
from test_scanner import raw_report

import agent_fault_lab.semantic_gateway as module
from agent_fault_lab.model import DEFAULT_MODEL
from agent_fault_lab.scanner import MAX_OUTPUT, normalize
from agent_fault_lab.semantic_gateway import Gateway, completion, native_request
from agent_fault_lab.semantic_scanner import bound_evidence, normalize_semantic


def request(**changes: JsonValue) -> bytes:
    value: dict[str, JsonValue] = {
        "model": DEFAULT_MODEL,
        "messages": [{"role": "user", "content": "inspect"}],
        "max_completion_tokens": 9999,
        "temperature": 0.9,
    }
    value.update(changes)
    return json.dumps(value).encode()


def response(**changes: JsonValue) -> bytes:
    value: dict[str, JsonValue] = {
        "done": True,
        "done_reason": "stop",
        "message": {"role": "assistant", "content": '{"safe":true}'},
        "prompt_eval_count": 12,
        "eval_count": 8,
    }
    value.update(changes)
    return json.dumps(value).encode()


def test_gateway_applies_explicit_native_settings() -> None:
    native = native_request(request())
    assert native["options"] == {
        "temperature": 0.0,
        "num_ctx": 4096,
        "num_predict": 1024,
    }
    assert native["think"] is native["stream"] is False
    assert native["model"] == DEFAULT_MODEL


@pytest.mark.parametrize(
    "changes",
    [
        {"model": "other"},
        {"stream": True},
        {"max_completion_tokens": -1},
        {"tool_choice": "required"},
        {"messages": []},
        {"endpoint": "https://example.com"},
        {"messages": [{"role": "tool", "content": "unmatched"}]},
        {"response_format": {"type": "unknown"}},
    ],
)
def test_gateway_rejects_unsupported_requests(changes: dict[str, JsonValue]) -> None:
    with pytest.raises(ValueError):
        native_request(request(**changes))


def test_gateway_preserves_requested_json_schema() -> None:
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"safe": {"type": "boolean"}},
    }
    native = native_request(
        request(
            response_format={"type": "json_schema", "json_schema": {"schema": schema}}
        )
    )
    assert native["format"] == schema


@pytest.mark.parametrize(
    "changes",
    [
        {"done": False},
        {"done_reason": "length"},
        {"message": {"content": 5}},
        {"message": {"content": "valid", "thinking": "unexpected"}},
        {
            "message": {
                "content": "",
                "tool_calls": [{"function": {"name": "x", "arguments": "bad"}}],
            }
        },
    ],
)
def test_gateway_does_not_repair_incomplete_model_output(
    changes: dict[str, JsonValue],
) -> None:
    with pytest.raises(ValueError):
        completion(response(**changes))


def test_response_usage_is_observed_or_absent() -> None:
    value = completion(response())
    assert value["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }
    assert "usage" not in completion(response(eval_count=None))


def test_request_cap_counts_physical_requests_and_rejects_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = Mock()
    process.communicate.return_value = (response(), b"")
    process.returncode = 0
    launch = Mock(return_value=process)
    monkeypatch.setattr("agent_fault_lab.semantic_gateway.subprocess.Popen", launch)
    monkeypatch.setattr(module, "stop", Mock())
    gateway = Gateway(tmp_path, time.monotonic() + 180)
    for _ in range(12):
        gateway.exchange(gateway.path, request())
    assert launch.call_count == 12
    with pytest.raises(ValueError, match="limit"):
        gateway.exchange(gateway.path, request())
    assert launch.call_count == 12
    saved = json.loads((tmp_path / "gateway.json").read_text())
    assert saved["requests"] == 12
    assert len(saved["records"]) == 12
    assert process.communicate.call_args.kwargs["timeout"] <= 60
    with pytest.raises(ValueError, match="endpoint"):
        gateway.exchange("/api/pull", request())


def test_expired_gateway_never_starts_a_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launch = Mock(side_effect=AssertionError("must not launch"))
    monkeypatch.setattr("agent_fault_lab.semantic_gateway.subprocess.Popen", launch)
    gateway = Gateway(tmp_path, time.monotonic() - 1)
    with pytest.raises(ValueError, match="limit"):
        gateway.exchange(gateway.path, request())
    assert gateway.requests == 0


def test_gateway_caps_serialized_evidence(tmp_path: Path) -> None:
    gateway = Gateway(tmp_path, time.monotonic() + 180)
    gateway.records.append({"oversized": "x" * MAX_OUTPUT})
    gateway.persist()
    assert gateway.error and "truncated" in gateway.error
    assert (tmp_path / "gateway.json").stat().st_size < MAX_OUTPUT // 2


def test_error_evidence_has_a_combined_cap(tmp_path: Path) -> None:
    for name in ("gateway.json", "raw-report.json", "stdout.txt", "stderr.txt"):
        (tmp_path / name).write_bytes(b"x" * MAX_OUTPUT)
    assert bound_evidence(tmp_path)
    assert sum(path.stat().st_size for path in tmp_path.iterdir()) <= MAX_OUTPUT - 65536


def test_request_timeout_is_counted_and_cleanup_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = Mock()
    process.communicate.side_effect = subprocess.TimeoutExpired("local request", 60)
    launch = Mock(return_value=process)
    cleanup = Mock()
    monkeypatch.setattr("agent_fault_lab.semantic_gateway.subprocess.Popen", launch)
    monkeypatch.setattr(module, "stop", cleanup)
    gateway = Gateway(tmp_path, time.monotonic() + 180)
    with pytest.raises(ValueError, match="TimeoutExpired"):
        gateway.exchange(gateway.path, request())
    cleanup.assert_called_once_with(process)
    assert gateway.requests == 1
    assert gateway.records[0]["status"] == "failed"
    with pytest.raises(ValueError):
        gateway.exchange(gateway.path, request())
    assert launch.call_count == 1


def semantic_report() -> dict[str, JsonValue]:
    value = raw_report()
    metadata = value["metadata"]
    assert isinstance(metadata, dict)
    metadata.update(
        {
            "llm_requested": True,
            "llm_available": True,
            "llm_calls_attempted": 3,
            "llm_calls_succeeded": 3,
        }
    )
    return value


def test_semantic_metadata_is_required_and_legacy_static_reader_unchanged() -> None:
    raw = json.dumps(semantic_report())
    assert normalize_semantic(raw, 0, 3) == "SAFE"
    with pytest.raises(ValueError, match="static-only"):
        normalize(raw, 0)
    with pytest.raises(ValueError):
        normalize_semantic(json.dumps(raw_report()), 0, 0)


@pytest.mark.parametrize(
    "key,value",
    [
        ("llm_available", False),
        ("llm_calls_succeeded", 2),
        ("llm_degraded", True),
        ("llm_calls_attempted", 0),
        ("inference_usage", None),
    ],
)
def test_partial_semantic_evidence_cannot_admit(key: str, value: JsonValue) -> None:
    raw = semantic_report()
    metadata = raw["metadata"]
    assert isinstance(metadata, dict)
    metadata[key] = value
    with pytest.raises(ValueError):
        normalize_semantic(json.dumps(raw), 0, 3)


def test_worker_blocks_other_hosts_ports_and_dns_without_connecting() -> None:
    worker = Path(module.__file__).with_name("scanner_worker.py")
    script = """
import runpy, socket, sys
runpy.run_path(sys.argv[1])["gateway_network"](34567)
try:
    socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
except PermissionError:
    pass
else:
    raise AssertionError("Unexpected datagram socket")
for address in [("example.com", 443), ("127.0.0.1", 11434)]:
    with socket.socket() as client:
        try:
            client.connect(address)
        except PermissionError:
            pass
        else:
            raise AssertionError("Unexpected connection")
try:
    socket.getaddrinfo("example.com", 443)
except PermissionError:
    pass
else:
    raise AssertionError("Unexpected DNS lookup")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(worker)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
