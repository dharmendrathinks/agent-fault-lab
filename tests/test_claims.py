"""A valid JSON object is not automatically a true statement about a task."""

import json

import pytest

from agent_fault_lab.claims import TerminalClaim, parse_claim, terminal_report
from agent_fault_lab.model import ExecutionStatus, RunResult


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            '{"status":"completed","task_id":"task-1"}',
            TerminalClaim(status="completed", task_id="task-1"),
        ),
        (
            '{"status":"not_completed","task_id":null}',
            TerminalClaim(status="not_completed", task_id=None),
        ),
        (
            '{"status":"unknown","task_id":null}',
            TerminalClaim(status="unknown", task_id=None),
        ),
        (
            ' \n {"task_id":"  exact-id  ","status":"completed"}\t',
            TerminalClaim(status="completed", task_id="  exact-id  "),
        ),
    ],
)
def test_valid_claims_preserve_values(content: str, expected: TerminalClaim) -> None:
    parsed = parse_claim(content)
    assert (
        parsed.status == "valid" and parsed.claim == expected and parsed.error is None
    )


@pytest.mark.parametrize(
    "content",
    [
        "",
        " \t\n",
        "Done!",
        "null",
        "true",
        "123",
        '"a string"',
        "[]",
        "{}",
        '{"status":"completed"}',
        '{"task_id":"task-1"}',
        '{"status":"success","task_id":"task-1"}',
        '{"status":"Completed","task_id":"task-1"}',
        '{"status":true,"task_id":"task-1"}',
        '{"status":"completed","task_id":null}',
        '{"status":"completed","task_id":""}',
        '{"status":"completed","task_id":"  \\n"}',
        '{"status":"completed","task_id":123}',
        '{"status":"completed","task_id":true}',
        '{"status":"completed","task_id":["task-1"]}',
        '{"status":"completed","task_id":"task-1","explanation":"done"}',
        '{"status":"not_completed","task_id":"task-1"}',
        '{"status":"unknown","task_id":"task-1"}',
        '{"status":"unknown","task_id":null,}',
        '{"status":"unknown","task_id":NaN}',
        '{"status":"unknown","task_id":Infinity}',
        '{"status":"completed","task_id":"task-1","status":"unknown"}',
        '{"status":"completed","task_id":"first","task_id":"second"}',
        '```json\n{"status":"unknown","task_id":null}\n```',
        'Here is my answer: {"status":"completed","task_id":"task-1"}',
        '{"status":"completed","task_id":"task-1"} Done.',
        '{"status":"completed","task_id":"task-1"}{"status":"unknown","task_id":null}',
        '<think>reasoning</think>\n{"status":"completed","task_id":"task-1"}',
        '</think>\n{"status":"completed","task_id":"task-1"}',
    ],
)
def test_bad_reports_are_rejected_without_extraction(content: str) -> None:
    parsed = parse_claim(content)
    assert parsed.status == "invalid" and parsed.claim is None and parsed.error


def test_absent_is_not_a_false_claim() -> None:
    assert parse_claim(None).status == "absent"


def test_claim_ids_are_not_silently_rewritten_or_uuid_validated() -> None:
    task_id = "  परीक्षण\n' OR 1=1 --  "
    parsed = parse_claim(json.dumps({"status": "completed", "task_id": task_id}))
    assert parsed.claim and parsed.claim.task_id == task_id


def test_deeply_nested_invalid_json_does_not_crash_evaluation() -> None:
    assert parse_claim("[" * 2000 + "]" * 2000).status == "invalid"


@pytest.mark.parametrize("status", ["provider_error", "model_limit", "tool_limit"])
def test_partial_content_is_not_a_terminal_claim(status: ExecutionStatus) -> None:
    execution = RunResult(
        status=status,
        final_content='{"status":"completed","task_id":"untrusted-partial"}',
        model_calls=1,
        tool_calls=0,
        tool_executions=0,
    )
    assert terminal_report(execution).status == "absent"


def test_truncated_json_is_invalid_even_if_parseable() -> None:
    execution = RunResult(
        status="protocol_error",
        final_content='{"status":"completed","task_id":"task-1"}',
        model_calls=1,
        tool_calls=0,
        tool_executions=0,
        error="Model response hit its output limit",
    )
    report = terminal_report(execution)
    assert report.status == "invalid" and report.claim is None
    assert report.error == execution.error
