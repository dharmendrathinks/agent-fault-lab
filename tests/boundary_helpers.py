"""Explicit scanner double for offline machinery tests, never scanner evidence."""

import hashlib
from pathlib import Path
from typing import Literal

from agent_fault_lab.journal import atomic_json
from agent_fault_lab.scanner import ScanResult


class ScriptedScanner:
    def __init__(
        self, status: Literal["admitted", "blocked", "error"] = "admitted"
    ) -> None:
        self.status = status

    def scan(self, content: bytes, directory: Path) -> ScanResult:
        directory.mkdir()
        (directory / "SKILL.md").write_bytes(content)
        result = ScanResult(
            engine="SCRIPTED scanner double, NOT SkillSpector",
            commit="test fixture",
            version="test fixture",
            input_sha256=hashlib.sha256(content).hexdigest(),
            status=self.status,
            recommendation="SAFE" if self.status == "admitted" else "CAUTION",
            complete=self.status != "error",
            exit_code=0,
            elapsed_seconds=0,
            error="Scripted scanner error" if self.status == "error" else None,
        )
        atomic_json(directory / "scan.json", result.model_dump(mode="json"))
        return result
