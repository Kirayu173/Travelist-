from __future__ import annotations

from app.ai.graph.nodes import AssistantNodes
from app.ai.graph.state import AssistantState
from langgraph.graph import END, START, StateGraph


def build_assistant_graph(nodes: AssistantNodes):
    """Assemble LangGraph for the assistant pipeline."""

    graph = StateGraph(AssistantState)
    graph.add_node("memory_read", nodes.memory_read_node)
    graph.add_node("assistant", nodes.assistant_node)
    graph.add_node("trip_query", nodes.trip_query_node)
    graph.add_node("response", nodes.response_formatter_node)

    graph.add_edge(START, "memory_read")
    graph.add_edge("memory_read", "assistant")

    def _route(state: AssistantState) -> str:
        return "trip_query" if state.intent == "trip_query" else "response"

    graph.add_conditional_edges(
        "assistant",
        _route,
        {
            "trip_query": "trip_query",
            "response": "response",
        },
    )
    graph.add_edge("trip_query", "response")
    graph.add_edge("response", END)
    return graph.compile()
