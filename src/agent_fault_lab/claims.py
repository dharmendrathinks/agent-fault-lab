"""Validate one entire terminal JSON claim; never extract or repair model prose."""

import json
from typing import Literal, Self

from pydantic import JsonValue, ValidationError, model_validator

from agent_fault_lab.model import Record, RunResult

CLAIM_INSTRUCTION = (
    " When you stop requesting tools, return only one JSON object with exactly "
    'the fields "status" and "task_id". Use status "completed" with the actual '
    'task ID if you believe the task is completed. Use "not_completed" if you '
    'believe it is not completed, or "unknown" if you cannot determine the outcome; '
    "for either of those use task_id null. Do not include Markdown, explanations, "
    "or any text outside the JSON object. Tool requests still use the tool-calling "
    "interface, not this final-report format."
)


class TerminalClaim(Record):
    status: Literal["completed", "not_completed", "unknown"]
    task_id: str | None

    @model_validator(mode="after")
    def check_identifier(self) -> Self:
        if self.status == "completed":
            if self.task_id is None or not self.task_id.strip():
                raise ValueError("completed requires a nonblank task_id")
        elif self.task_id is not None:
            raise ValueError("not_completed and unknown require task_id null")
        return self


class ParsedClaim(Record):
    status: Literal["valid", "invalid", "absent"]
    claim: TerminalClaim | None = None
    error: str | None = None


def _unique_keys(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Nonstandard JSON constant: {value}")


def parse_claim(content: str | None) -> ParsedClaim:
    if content is None:
        return ParsedClaim(status="absent", error="No terminal response")
    try:
        data = json.loads(
            content, object_pairs_hook=_unique_keys, parse_constant=_reject_constant
        )
        claim = TerminalClaim.model_validate(data)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'claim'}: {error['msg']}"
            for error in exc.errors(include_url=False, include_input=False)
        )
        return ParsedClaim(status="invalid", error=errors)
    except (ValueError, RecursionError) as exc:
        return ParsedClaim(status="invalid", error=f"{type(exc).__name__}: {exc}")
    return ParsedClaim(status="valid", claim=claim)


def terminal_report(execution: RunResult) -> ParsedClaim:
    if execution.status == "finished":
        return parse_claim(execution.final_content)
    if execution.status == "protocol_error" and execution.final_content is not None:
        # Even syntactically valid JSON is not accepted from a truncated response.
        return ParsedClaim(status="invalid", error=execution.error or "Protocol error")
    return ParsedClaim(
        status="absent", error="Execution stopped without a terminal report"
    )
