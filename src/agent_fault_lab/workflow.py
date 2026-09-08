"""An ordinary create/read/check workflow, with no model or evaluator access."""

from agent_fault_lab.claims import TerminalClaim
from agent_fault_lab.contracts import validate_response
from agent_fault_lab.journal import strict_json
from agent_fault_lab.model import RunResult, ToolCall
from agent_fault_lab.tools import ToolExecutor, ToolResult
from agent_fault_lab.trace import Recorder

LABEL = "deterministic create/read/check workflow (zero model calls)"


def run_workflow(executor: ToolExecutor, title: str, recorder: Recorder) -> RunResult:
    recorder.emit("run_started", client=LABEL)
    calls = executions = 0

    def call(tool: ToolCall) -> ToolResult:
        nonlocal calls, executions
        calls += 1
        call_id = f"workflow-{calls}"
        recorder.emit(
            "tool_requested", call_id=call_id, call=tool.model_dump(mode="json")
        )
        delivery = executor.execute(tool, call_id)
        executions += int(delivery.executed)
        recorder.emit(
            "tool_returned",
            call_id=call_id,
            content=delivery.content,
            executed=delivery.executed,
        )
        raw = strict_json(delivery.content)
        if isinstance(raw, dict) and "schema_version" in raw:
            response = validate_response(delivery.content.encode(), tool)
            return ToolResult(
                ok=response.ok,
                value=response.value.model_dump(mode="json")
                if response.value
                else None,
                error=response.error.message if response.error else None,
                executed=delivery.executed,
            )
        return ToolResult.model_validate(raw)

    claim = TerminalClaim(status="unknown", task_id=None)
    try:
        created = call(ToolCall(name="create_task", arguments={"title": title}))
        value = created.value
        task_id = value.get("id") if isinstance(value, dict) else None
        if (
            created.ok
            and isinstance(value, dict)
            and isinstance(task_id, str)
            and task_id.strip()
            and value.get("title") == title
        ):
            read = call(ToolCall(name="get_task", arguments={"task_id": task_id}))
            if read.ok and isinstance(read.value, dict):
                if read.value.get("id") == task_id and read.value.get("title") == title:
                    claim = TerminalClaim(status="completed", task_id=task_id)
            elif read.ok and read.value is None:
                claim = TerminalClaim(status="not_completed", task_id=None)
    except ValueError as exc:
        recorder.emit("workflow_invalid_response", error=str(exc))
    result = RunResult(
        status="finished",
        final_content=claim.model_dump_json(),
        model_calls=0,
        tool_calls=calls,
        tool_executions=executions,
    )
    recorder.emit("run_stopped", result=result.model_dump(mode="json"))
    return result
