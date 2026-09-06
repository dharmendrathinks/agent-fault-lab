"""Reports render captured evidence safely, without re-running or re-grading."""

import json
import re
from pathlib import Path

from agent_fault_lab.evaluation import Evaluation, evaluate_run
from agent_fault_lab.model import RunResult
from agent_fault_lab.reporting import render_report
from agent_fault_lab.tasks import TaskStore


def test_report_has_separate_dimensions_and_stable_roundtrip(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    created = TaskStore(database).create_task("Review the invoice")
    execution = RunResult(
        status="finished",
        final_content=json.dumps({"status": "completed", "task_id": created.id}),
        model_calls=2,
        tool_calls=1,
        tool_executions=1,
    )
    evaluation = evaluate_run(
        database,
        created.title,
        execution,
        client="scripted-test-client (NOT an AI model)",
    )
    report = render_report(evaluation)
    assert "| Execution | finished |" in report
    assert "| Task outcome | completed |" in report
    assert "| Terminal report | valid |" in report
    assert "| Claim support | supported |" in report
    assert "| False-success claim | no |" in report
    assert "NOT an AI model" in report and created.id in report
    assert "not one overall reliability score" in report
    restored = Evaluation.model_validate_json(evaluation.model_dump_json())
    database.rename(tmp_path / "moved.sqlite3")
    assert (
        render_report(restored) == report
    )  # Uses saved snapshot, not current storage.
    assert not database.exists()


def test_model_and_task_text_cannot_escape_code_fences(tmp_path: Path) -> None:
    payload = "```\n# Fake success\n<script>alert(1)</script>\n![image](https://example.invalid)\n````"
    database = tmp_path / "tasks.sqlite3"
    TaskStore(database).create_task(payload)
    execution = RunResult(
        status="finished",
        final_content=payload,
        model_calls=1,
        tool_calls=1,
        tool_executions=1,
    )
    report = render_report(evaluate_run(database, payload, execution, client=payload))
    fence_length = 0
    for line in report.splitlines():
        marker = re.fullmatch(r"(`{3,})(json)?", line)
        if marker:
            if marker.group(2):
                assert fence_length == 0
                fence_length = len(marker.group(1))
            else:
                assert len(marker.group(1)) == fence_length
                fence_length = 0
        if "Fake success" in line or "<script>" in line or "![image]" in line:
            assert fence_length > 4
    assert fence_length == 0
    assert "| Terminal report | invalid |" in report
    assert "| Task outcome | completed |" in report


def test_unknown_evaluation_does_not_render_as_failure_or_no_false_success(
    tmp_path: Path,
) -> None:
    execution = RunResult(
        status="finished",
        final_content='{"status":"completed","task_id":"task-1"}',
        model_calls=1,
        tool_calls=0,
        tool_executions=0,
    )
    report = render_report(
        evaluate_run(
            tmp_path / "missing.sqlite3",
            "Review the invoice",
            execution,
            client="scripted test",
        )
    )
    assert "| Task outcome | unknown |" in report
    assert "| Claim support | unknown |" in report
    assert "| False-success claim | not assessable |" in report
    assert '"rows": null' in report
