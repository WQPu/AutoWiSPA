"""AutoWiSPA global state definition for the notebook-first pipeline."""

from __future__ import annotations

import operator
from typing import Annotated, List, Optional

from typing_extensions import TypedDict


class AutoWiSPAState(TypedDict):
    """Shared state passed across the simplified AutoWiSPA pipeline."""

    user_query: str
    conversation_history: Annotated[List[dict], operator.add]

    task_spec: Optional[dict]
    task_spec_complete: bool
    clarification_questions: Optional[List[str]]

    retrieved_knowledge: Optional[dict]
    problem_formalization: Optional[dict]
    solution_plan: Optional[dict]

    notebook: Optional[dict]
    notebook_validated: bool

    verification_results: Optional[dict]
    simulation_results: Optional[dict]
    review_feedback: Optional[dict]

    verification_retry_count: int
    simulation_retry_count: int
    review_retry_count: int
    max_verification_retries: int
    max_simulation_retries: int
    max_review_retries: int

    execution_trace: Annotated[List[dict], operator.add]

    final_report: Optional[str]
    final_notebook: Optional[dict]

    current_phase: str
    should_terminate: bool
    termination_reason: Optional[str]
    error_state: Optional[str]
    config: Optional[dict]
