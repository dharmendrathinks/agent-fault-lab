"""Actual StateGraph orchestration; imports LangGraph only inside its pinned env."""

import importlib
from typing import TypedDict

from agent_fault_lab.boundaries import model_step, tool_step
from agent_fault_lab.boundary_records import BoundaryJournal
from agent_fault_lab.model import ModelClient


class GraphState(TypedDict):
    steps: int


def run_graph(journal: BoundaryJournal, client: ModelClient | None = None) -> None:
    graph_api = importlib.import_module("langgraph.graph")

    def route(state: GraphState) -> str:
        checkpoint = journal.state
        if checkpoint.status != "running":
            return "terminal"
        return "tools" if checkpoint.cursor < len(checkpoint.pending) else "model"

    def model(state: GraphState) -> GraphState:
        journal.save("runtime_node", runtime="langgraph", node="model")
        model_step(journal, client)
        return {"steps": state["steps"] + 1}

    def tools(state: GraphState) -> GraphState:
        journal.save("runtime_node", runtime="langgraph", node="tools")
        tool_step(journal)
        return {"steps": state["steps"] + 1}

    def terminal(state: GraphState) -> GraphState:
        journal.save("runtime_node", runtime="langgraph", node="terminal")
        return state

    builder = graph_api.StateGraph(GraphState)
    builder.add_node("model", model)
    builder.add_node("tools", tools)
    builder.add_node("terminal", terminal)
    destinations = {name: name for name in ("model", "tools", "terminal")}
    builder.add_conditional_edges(graph_api.START, route, destinations)
    builder.add_conditional_edges("model", route, destinations)
    builder.add_conditional_edges("tools", route, destinations)
    builder.add_edge("terminal", graph_api.END)
    # No retries, cache, checkpointer, tool parallelism, callbacks or hosted tracing.
    graph = builder.compile()
    graph.invoke({"steps": 0}, config={"recursion_limit": 32, "callbacks": []})
