"""LangGraph routing functions for the notebook-first AutoWiSPA pipeline."""

from __future__ import annotations
from graph.state import AutoWiSPAState


def route_after_problem_analysis(state: AutoWiSPAState) -> str:
    """If the task spec is complete, continue; otherwise wait for user input."""
    if state.get("task_spec_complete"):
        return "knowledge_retrieval"
    return "__end__"


def route_after_simulation(state: AutoWiSPAState) -> str:
    """Route simulation failures back to notebook repair until retry limit is reached."""
    results = state.get("simulation_results", {})
    if results.get("status") == "error":
        retry_count = int(state.get("simulation_retry_count", 0))
        max_retries = int(state.get("max_simulation_retries", 1))
        if retry_count < max_retries:
            return "notebook_generation"
        return "report_generation"
    return "report_generation"


def route_after_verification(state: AutoWiSPAState) -> str:
    """Route verification failures back to notebook repair until retry limit is reached."""
    results = state.get("verification_results", {})
    if results.get("status") == "passed":
        return "simulation"

    retry_count = int(state.get("verification_retry_count", 0))
    max_retries = int(state.get("max_verification_retries", 3))
    if retry_count < max_retries:
        return "notebook_generation"
    return "report_generation"
