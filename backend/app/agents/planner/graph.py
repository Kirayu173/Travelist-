from __future__ import annotations

from app.agents.planner.nodes import PlannerNodes
from app.agents.planner.state import PlannerState
from langgraph.graph import END, START, StateGraph


def build_planner_graph(nodes: PlannerNodes):
    """Assemble LangGraph for the planning pipeline (fast/deep)."""

    graph = StateGraph(PlannerState)
    graph.add_node("plan_input", nodes.plan_input_node)
    graph.add_node("planner_fast", nodes.planner_fast_node)
    graph.add_node("planner_deep", nodes.planner_deep_node)
    graph.add_node("plan_validate", nodes.plan_validate_node)
    graph.add_node("plan_validate_global", nodes.plan_validate_global_node)
    graph.add_node("plan_output", nodes.plan_output_node)

    graph.add_edge(START, "plan_input")

    def _route_mode(state: PlannerState) -> str:
        return "planner_deep" if state.mode == "deep" else "planner_fast"

    graph.add_conditional_edges("plan_input", _route_mode)
    graph.add_edge("planner_fast", "plan_validate")
    graph.add_edge("planner_deep", "plan_validate_global")
    graph.add_edge("plan_validate", "plan_output")
    graph.add_edge("plan_validate_global", "plan_output")
    graph.add_edge("plan_output", END)
    return graph.compile()
