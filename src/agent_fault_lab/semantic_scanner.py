"""M14 semantic profile; v2 evidence wraps the shared v1 admission projection."""

import hashlib
import json
import time
from pathlib import Path
from typing import Literal

import httpx
from pydantic import JsonValue

from agent_fault_lab.journal import atomic_json, regular, strict_json
from agent_fault_lab.model import DEFAULT_MODEL
from agent_fault_lab.ollama_adapter import LOCAL_HOST, OllamaClient
from agent_fault_lab.scanner import (
    MAX_INPUT,
    MAX_OUTPUT,
    PIN,
    VERSION,
    ScanFinding,
    ScanResult,
    SkillSpector,
    findings,
    invoke,
    normalize,
)
from agent_fault_lab.semantic_gateway import Gateway


def bound_evidence(directory: Path) -> bool:
    """Cap error paths too, reserving room for the final status/identity records."""
    candidates = [
        directory / name
        for name in ("raw-report.json", "stdout.txt", "stderr.txt", "gateway.json")
    ]
    budget = MAX_OUTPUT - 65536
    truncated = False
    # Preserve the gateway's smaller bounded account before scanner diagnostics.
    for path in reversed(candidates):
        if not path.exists():
            continue
        regular(path)
        size = path.stat().st_size
        if size > budget:
            with path.open("r+b") as stream:
                stream.truncate(budget)
            size = budget
            truncated = True
        budget -= size
    return truncated


def normalize_semantic(raw: str, code: int, requests: int) -> str:
    value = strict_json(raw)
    if not isinstance(value, dict) or not isinstance(value.get("metadata"), dict):
        raise ValueError("Missing semantic metadata")
    metadata = value["metadata"]
    assert isinstance(metadata, dict)
    attempted, succeeded = (
        metadata.get("llm_calls_attempted"),
        metadata.get("llm_calls_succeeded"),
    )
    if (
        metadata.get("llm_requested") is not True
        or metadata.get("llm_available") is not True
        or metadata.get("llm_degraded", False) is not False
        or requests < 1
        or type(attempted) is not int
        or type(succeeded) is not int
        or attempted < 1
        or attempted != succeeded
        or attempted > requests
        or type(metadata.get("meta_analysis_applied")) is not bool
        or not isinstance(metadata.get("inference_usage"), list)
    ):
        raise ValueError("Semantic analyzers did not establish complete execution")
    # Reuse only static profile's common coverage/risk validation. The original
    # raw report and semantic mode facts remain untouched in saved evidence.
    metadata["llm_requested"] = False
    metadata["meta_analysis_applied"] = False
    metadata["inference_usage"] = []
    recommendation, _ = normalize(json.dumps(value), code)
    return recommendation


class SemanticSkillSpector(SkillSpector):
    def scan(self, content: bytes, directory: Path) -> ScanResult:
        directory.mkdir()
        snapshot = directory / "SKILL.md"
        snapshot.write_bytes(content)
        started = time.monotonic()
        status: Literal["admitted", "blocked", "error"] = "error"
        error = None
        code = None
        recommendation = None
        raw_digest = None
        parsed_findings: tuple[ScanFinding, ...] = ()
        gateway = Gateway(directory, started + 180)
        identity: dict[str, JsonValue] = {}
        try:
            if len(content) > MAX_INPUT or not content.decode().strip():
                raise ValueError("Invalid skill size or encoding")
            identity = dict(self.doctor(directory))
            info = OllamaClient().inspect()
            if not info.ready:
                raise ValueError(
                    "Semantic preflight failed: " + "; ".join(info.problems)
                )
            with httpx.Client(
                trust_env=False, follow_redirects=False, timeout=5
            ) as client:
                response = client.post(
                    LOCAL_HOST + "/api/show", json={"model": DEFAULT_MODEL}
                )
                response.raise_for_status()
                details = response.json()
            metadata = details.get("model_info", {})
            context = metadata.get("qwen3.context_length")
            if type(context) is not int or context < 4096:
                raise ValueError(
                    "Checkpoint does not establish the requested context capacity"
                )
            identity.update(
                {
                    "provider": info.model_dump(mode="json"),
                    "checkpoint_context_capacity": context,
                    "effective_context_tokens": 4096,
                    "max_output_tokens": 1024,
                }
            )
            registry = directory / "model-registry.json"
            # JSON is valid YAML; use upstream's documented registry override.
            atomic_json(
                registry,
                {
                    "models": {
                        DEFAULT_MODEL: {
                            "context_length": 4096,
                            "max_output_tokens": 1024,
                        }
                    }
                },
            )
            with gateway:
                code, stdout, stderr, failure = invoke(
                    self.python,
                    [
                        str(snapshot.absolute()),
                        str((directory / "raw-report.json").absolute()),
                        gateway.base_url,
                        DEFAULT_MODEL,
                        str(registry.absolute()),
                    ],
                    directory,
                    timeout=max(0.0, 180 - (time.monotonic() - started)),
                )
                (directory / "stdout.txt").write_bytes(stdout)
                (directory / "stderr.txt").write_bytes(stderr)
                if failure or gateway.error:
                    raise ValueError(failure or gateway.error)
            raw = directory / "raw-report.json"
            regular(raw)
            total = sum(
                p.stat().st_size
                for p in directory.iterdir()
                if p.is_file() and p != snapshot
            )
            if total > MAX_OUTPUT:
                # Preserve a bounded prefix as incomplete evidence, never admit it.
                with raw.open("r+b") as stream:
                    stream.truncate(max(0, raw.stat().st_size - (total - MAX_OUTPUT)))
                raise ValueError(
                    "Combined semantic evidence exceeds 4 MiB; report truncated"
                )
            recommendation = normalize_semantic(raw.read_text(), code, gateway.requests)
            parsed = strict_json(raw.read_text())
            assert isinstance(parsed, dict)
            parsed_findings = findings(parsed.get("issues"))
            raw_digest = hashlib.sha256(raw.read_bytes()).hexdigest()
            if snapshot.read_bytes() != content:
                raise ValueError("Semantic scan input snapshot changed")
            status = "admitted" if recommendation == "SAFE" else "blocked"
        except (OSError, ValueError, httpx.HTTPError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        if bound_evidence(directory):
            status = "error"
            error = (
                "Combined semantic evidence exceeded 4 MiB; bounded prefixes retained"
            )
            recommendation = raw_digest = None
            parsed_findings = ()
        result = ScanResult(
            engine="SkillSpector static-plus-semantic",
            commit=PIN,
            version=VERSION,
            input_sha256=hashlib.sha256(content).hexdigest(),
            status=status,
            recommendation=recommendation,
            complete=status != "error",
            exit_code=code,
            elapsed_seconds=time.monotonic() - started,
            error=(
                error[:4096] + " [truncated]" if error and len(error) > 4096 else error
            ),
            raw_sha256=raw_digest,
            findings=parsed_findings,
        )
        if (
            len(result.model_dump_json().encode()) * 2
            + len(json.dumps(identity).encode())
            > 60000
        ):
            result = result.model_copy(
                update={
                    "status": "error",
                    "complete": False,
                    "recommendation": None,
                    "findings": (),
                    "error": "Normalized scan evidence exceeds reserved space",
                }
            )
        atomic_json(
            directory / "semantic-scan.json",
            {
                "schema_version": 2,
                "artifact": "semantic-scan",
                "profile": "static-plus-semantic",
                "identity": identity,
                "requests": gateway.requests,
                "admission": result.model_dump(mode="json"),
                "limits": {
                    "scan_seconds": 180,
                    "physical_requests": 12,
                    "request_seconds": 60,
                    "output_tokens": 1024,
                },
            },
        )
        atomic_json(directory / "scan.json", result.model_dump(mode="json"))
        return result
