"""Exercise the real pinned graph with sockets blocked and controlled model turns."""

import importlib
import json
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_fault_lab.boundaries import run_boundary
from agent_fault_lab.boundary_records import BoundaryConfig, BoundaryJournal
from agent_fault_lab.langgraph_runtime import run_graph
from agent_fault_lab.model import ModelTurn, ProviderError, ToolCall
from agent_fault_lab.runtime_records import RUNTIME_CASES, runtime_config
from agent_fault_lab.scanner import SkillSpector
from agent_fault_lab.scanner_worker import OfflineSocket
from agent_fault_lab.scripted import ScriptedClient
from agent_fault_lab.study_child import OfflineStudyScanner


def check() -> None:
    importlib.import_module("langgraph.graph")
    socket.socket = OfflineSocket  # type: ignore[misc]
    with tempfile.TemporaryDirectory(prefix="aflab-graph-contracts-") as temporary:
        root = Path(temporary)
        for case in RUNTIME_CASES:
            config = runtime_config(case, "offline")
            native = run_boundary(
                root / (case + "-native"), config, scanner=SkillSpector()
            )
            with patch(
                "agent_fault_lab.boundaries.advance",
                side_effect=AssertionError("Native loop forbidden"),
            ):
                graph = run_boundary(
                    root / (case + "-graph"),
                    config,
                    scanner=SkillSpector(),
                    driver=run_graph,
                )
            assert native.status == graph.status == "finished", (case, graph.error)
            for field in (
                "task_outcome",
                "claim_support",
                "model_calls",
                "tool_calls",
                "tool_executions",
            ):
                assert getattr(native, field) == getattr(graph, field), (case, field)
            assert native.authorization.status == graph.authorization.status == "held"
            assert native.report.status == graph.report.status == "valid"
            if graph.context:
                assert (
                    graph.context.seeded_preserved
                    and graph.context.boundary_violations == 0
                )
            events = BoundaryJournal.events(
                root / (case + "-graph") / "boundary.sqlite3"
            )
            nodes = [e.data["node"] for e in events if e.kind == "runtime_node"]
            assert nodes[-1] == "terminal" and "model" in nodes and "tools" in nodes
            print(f"PASS matched real graph / {case}", flush=True)

        examples = {
            "malformed-claim": (
                [ModelTurn(content="```json\n{}\n```")],
                "finished",
                "invalid",
                0,
            ),
            "truncated-claim": (
                [
                    ModelTurn(
                        content='{"status":"unknown","task_id":null}',
                        finish_reason="length",
                    )
                ],
                "protocol_error",
                "invalid",
                0,
            ),
            "malformed-tool": (
                [
                    ModelTurn(
                        tool_calls=(
                            ToolCall(name="create_task", arguments={"title": 17}),
                        )
                    ),
                    ModelTurn(content='{"status":"not_completed","task_id":null}'),
                ],
                "finished",
                "valid",
                1,
            ),
            "tool-budget": (
                [
                    ModelTurn(
                        tool_calls=tuple(
                            ToolCall(name="unknown", arguments={}) for _ in range(7)
                        )
                    )
                ],
                "tool_limit",
                "absent",
                6,
            ),
            "model-budget": (
                [
                    ModelTurn(tool_calls=(ToolCall(name="unknown", arguments={}),))
                    for _ in range(6)
                ],
                "model_limit",
                "absent",
                6,
            ),
        }
        for name, (turns, status, report, calls) in examples.items():
            with patch(
                "agent_fault_lab.boundaries.advance",
                side_effect=AssertionError("Native loop forbidden"),
            ):
                result = run_boundary(
                    root / name,
                    BoundaryConfig(case="approved"),
                    scanner=OfflineStudyScanner(),
                    client=ScriptedClient(turns),
                    driver=run_graph,
                )
            assert result.execution and result.execution.status == status, (
                name,
                result.error,
            )
            assert result.report.status == report and result.tool_calls == calls, name
            assert result.state.rows == (), name
            print(f"PASS real graph / {name}", flush=True)

        def failed(messages: object) -> ModelTurn:
            raise ProviderError("Controlled local provider failure")

        result = run_boundary(
            root / "provider-error",
            BoundaryConfig(case="approved"),
            scanner=OfflineStudyScanner(),
            client=ScriptedClient([failed]),
            driver=run_graph,
        )
        assert result.execution and result.execution.status == "provider_error"
        assert result.report.status == "absent" and result.state.rows == ()
        print("PASS real graph / provider error", flush=True)
        print(
            json.dumps(
                {
                    "matched_cases": 4,
                    "protocol_and_budget_cases": 6,
                    "network": "blocked",
                }
            )
        )


if __name__ == "__main__":
    check()
