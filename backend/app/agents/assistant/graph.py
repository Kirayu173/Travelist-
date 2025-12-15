from __future__ import annotations

from app.agents.assistant.nodes import AssistantNodes
from app.agents.assistant.state import AssistantState
from langgraph.graph import END, START, StateGraph


def build_assistant_graph(nodes: AssistantNodes):
    """Assemble LangGraph for the assistant pipeline."""

    graph = StateGraph(AssistantState)
    graph.add_node("memory_read", nodes.memory_read_node)
    graph.add_node("assistant", nodes.assistant_node)
    graph.add_node("poi", nodes.poi_node)
    graph.add_node("trip_query", nodes.trip_query_node)
    graph.add_node("tool_select", nodes.tool_select_node)
    graph.add_node("tool_execute", nodes.tool_execute_node)
    graph.add_node("response", nodes.response_formatter_node)

    graph.add_edge(START, "memory_read")
    graph.add_edge("memory_read", "assistant")
    graph.add_edge("assistant", "poi")
    graph.add_edge("poi", "trip_query")
    graph.add_edge("trip_query", "tool_select")
    graph.add_edge("tool_select", "tool_execute")
    graph.add_edge("tool_execute", "response")
    graph.add_edge("response", END)
    return graph.compile()
