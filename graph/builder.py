"""LangGraph graph builder for the notebook-first AutoWiSPA workflow."""

from __future__ import annotations
from langgraph.graph import StateGraph, END

from graph.state import AutoWiSPAState
from graph.nodes import (
    problem_analysis_node,
    knowledge_retrieval_node,
    model_formulation_node,
    solution_planning_node,
    notebook_generation_node,
    verification_node,
    simulation_node,
    report_generation_node,
)
from graph.edges import (
    route_after_problem_analysis,
    route_after_verification,
    route_after_simulation,
)


def build_autowisp_graph(config: dict = None):
    """Build and compile the simplified notebook-first AutoWiSPA workflow."""
    workflow = StateGraph(AutoWiSPAState)

    workflow.add_node("problem_analysis", problem_analysis_node)
    workflow.add_node("knowledge_retrieval", knowledge_retrieval_node)
    workflow.add_node("model_formulation", model_formulation_node)
    workflow.add_node("solution_planning", solution_planning_node)
    workflow.add_node("notebook_generation", notebook_generation_node)
    workflow.add_node("verification", verification_node)
    workflow.add_node("simulation", simulation_node)
    workflow.add_node("report_generation", report_generation_node)

    workflow.set_entry_point("problem_analysis")

    workflow.add_conditional_edges(
        "problem_analysis",
        route_after_problem_analysis,
        {
            "knowledge_retrieval": "knowledge_retrieval",
            "__end__": END,
        },
    )

    workflow.add_conditional_edges(
        "verification",
        route_after_verification,
        {
            "simulation": "simulation",
            "notebook_generation": "notebook_generation",
            "report_generation": "report_generation",
        },
    )

    workflow.add_conditional_edges(
        "simulation",
        route_after_simulation,
        {
            "notebook_generation": "notebook_generation",
            "report_generation": "report_generation",
        },
    )

    workflow.add_edge("knowledge_retrieval", "model_formulation")
    workflow.add_edge("model_formulation", "solution_planning")
    workflow.add_edge("solution_planning", "notebook_generation")
    workflow.add_edge("notebook_generation", "verification")
    workflow.add_edge("report_generation", END)

    return workflow.compile()
