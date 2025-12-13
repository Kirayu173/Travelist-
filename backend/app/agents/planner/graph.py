from __future__ import annotations

from app.agents.planner.nodes import PlannerNodes
from app.agents.planner.state import PlannerState
from langgraph.graph import END, START, StateGraph


def build_planner_graph(nodes: PlannerNodes):
    """Assemble LangGraph for the planning pipeline (fast path)."""

    graph = StateGraph(PlannerState)
    graph.add_node("plan_input", nodes.plan_input_node)
    graph.add_node("planner_fast", nodes.planner_fast_node)
    graph.add_node("plan_validate", nodes.plan_validate_node)
    graph.add_node("plan_output", nodes.plan_output_node)

    graph.add_edge(START, "plan_input")
    graph.add_edge("plan_input", "planner_fast")
    graph.add_edge("planner_fast", "plan_validate")
    graph.add_edge("plan_validate", "plan_output")
    graph.add_edge("plan_output", END)
    return graph.compile()
