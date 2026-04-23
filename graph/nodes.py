"""LangGraph node functions for the notebook-first AutoWiSPA pipeline."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from graph.state import AutoWiSPAState
from utils.event_bus import Event, EventType, get_event_bus

logger = logging.getLogger(__name__)

PLAN_CORE_ROLES = [
    "title",
    "problem_setup",
    "modeling_summary",
    "imports_setup",
    "data_generation",
    "algorithm_core",
    "evaluation_logic",
    "execution",
]

PLAN_RECOMMENDED_ROLES = ["plotting", "result_notes"]

ROLE_CELL_TYPES = {
    "title": "markdown",
    "problem_setup": "markdown",
    "modeling_summary": "markdown",
    "result_notes": "markdown",
    "imports_setup": "code",
    "data_generation": "code",
    "algorithm_core": "code",
    "evaluation_logic": "code",
    "execution": "code",
    "plotting": "code",
}


_checkpoint_mgr = None


def _build_llm_client(state: dict, temperature: Optional[float] = None):
    from utils.llm_client import LLMClient

    config = state.get("config") or {}
    overrides = {}
    if temperature is not None:
        overrides["temperature"] = temperature
    return LLMClient.from_config(config, **overrides)


def _architect_temperature(state: dict, fallback: float = 0.4) -> float:
    llm_cfg = ((state.get("config") or {}).get("llm") or {})
    return float(llm_cfg.get("architect_temperature", llm_cfg.get("temperature", fallback)))


def set_checkpoint_dir(output_dir) -> None:
    """Called by main.py at the start of each run to activate checkpoint functionality."""
    global _checkpoint_mgr  # noqa: PLW0603
    from utils.checkpoint import CheckpointManager

    _checkpoint_mgr = CheckpointManager(Path(output_dir))


def _save_checkpoint(stage: str, state: dict) -> None:
    if _checkpoint_mgr is not None:
        _checkpoint_mgr.save(stage, state)


def _save_stage_artifact(filename: str, data: object) -> None:
    """Immediately write a stage output file to the experiment directory.

    Called right after a stage succeeds so the artifact is available even
    if the pipeline is interrupted before the final main.py write-out.
    """
    if _checkpoint_mgr is None:
        return
    try:
        path = _checkpoint_mgr.output_dir / filename
        if isinstance(data, (dict, list)):
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            path.write_text(str(data), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Artifact] Failed to save stage artifact %s: %s", filename, exc)


def _save_iteration_artifacts(
    attempt: int,
    notebook: dict | None,
    verification_results: dict | None = None,
    simulation_results: dict | None = None,
) -> None:
    """Persist notebook and debug outputs under experiments/<run>/iterations/<n>."""
    if _checkpoint_mgr is None:
        return
    try:
        out_dir = _checkpoint_mgr.output_dir / "iterations" / f"iter_{attempt:03d}"
        out_dir.mkdir(parents=True, exist_ok=True)
        if notebook:
            (out_dir / "simulation.ipynb").write_text(
                json.dumps(notebook, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if verification_results:
            (out_dir / "verification_results.json").write_text(
                json.dumps(verification_results, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if simulation_results:
            (out_dir / "simulation_results.json").write_text(
                json.dumps(simulation_results, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Artifact] Failed to save iteration artifacts: %s", exc)


def _notebook_code_snapshot(notebook: dict | None) -> dict[str, str]:
    if not isinstance(notebook, dict):
        return {}
    snapshot: dict[str, str] = {}
    for idx, cell in enumerate(notebook.get("cells") or [], start=1):
        if cell.get("cell_type") != "code":
            continue
        role = (cell.get("metadata") or {}).get("autowisp_role", f"cell_{idx}")
        snapshot[f"Cell {idx} · {role}"] = "".join(cell.get("source") or [])
    return snapshot


def collect_experiment_evidence(state: dict) -> str:
    """Collect real experiment data for report generation and review prompts."""
    parts: list[str] = []

    sim = state.get("simulation_results")
    if isinstance(sim, dict):
        parts.append("### Simulation Results")
        parts.append(f"- Status: {sim.get('status', 'unknown')}")
        if sim.get("execution_time") is not None:
            parts.append(f"- Execution time: {sim.get('execution_time')}s")
        perf_data = sim.get("performance_data") or {}
        if isinstance(perf_data, dict):
            parts.append(f"- Performance keys: {', '.join(list(perf_data.keys())[:8]) or 'none'}")
        if sim.get("error_log"):
            parts.append(f"- Error log: {str(sim.get('error_log'))[:800]}")

    verif = state.get("verification_results")
    if isinstance(verif, dict):
        parts.append("\n### Verification Results")
        parts.append(f"- Status: {verif.get('status', 'unknown')}")
        errors = verif.get("errors") or []
        warnings = verif.get("warnings") or []
        parts.append(f"- Errors: {len(errors)}")
        parts.append(f"- Warnings: {len(warnings)}")
        if errors:
            parts.append(f"- First error: {str(errors[0])[:500]}")

    return "\n".join(parts) if parts else "(No experiment data available)"


def _clip_text(value: object, limit: int = 180) -> str:
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _trace_entry(stage: str, title: str, summary_lines: list[str], payload: dict | None = None) -> dict:
    return {
        "stage": stage,
        "title": title,
        "summary_lines": summary_lines,
        "payload": payload or {},
    }


def _log_trace(stage: str, title: str, summary_lines: list[str]) -> None:
    body = "\n".join(f"  - {line}" for line in summary_lines if line)
    logger.info("[%s] %s\n%s", stage, title, body)


def _is_missing_value(value: object) -> bool:
    return value is None or value == ""


def _deep_merge_task_spec(base: dict, overlay: dict) -> dict:
    """Merge retrieval refinements into the existing task spec without dropping fields."""
    if not isinstance(base, dict):
        return dict(overlay) if isinstance(overlay, dict) else {}
    if not isinstance(overlay, dict):
        return dict(base)

    merged: dict = dict(base)
    for key, overlay_value in overlay.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(overlay_value, dict):
            merged[key] = _deep_merge_task_spec(base_value, overlay_value)
            continue
        if _is_missing_value(overlay_value):
            continue
        merged[key] = overlay_value
    return merged


def _preserve_task_intent(base_spec: dict, refined_spec: dict) -> dict:
    """Keep user-critical task intent when retrieval summaries drift toward generic metrics."""
    merged = _deep_merge_task_spec(base_spec, refined_spec)

    task_category = str((merged.get("task_category") or base_spec.get("task_category") or "")).lower()
    base_metric = str(((base_spec.get("performance_targets") or {}).get("primary_metric") or "")).strip()
    merged_perf = merged.get("performance_targets")
    if not isinstance(merged_perf, dict):
        merged_perf = {}
        merged["performance_targets"] = merged_perf

    merged_metric = str((merged_perf.get("primary_metric") or "")).strip()
    if "doa" in task_category or "aoa" in task_category or "angle" in task_category:
        base_metric_lower = base_metric.lower()
        merged_metric_lower = merged_metric.lower()
        if base_metric and (
            not merged_metric
            or merged_metric_lower in {"nmse", "mse"}
            or ("rmse" in base_metric_lower and "rmse" not in merged_metric_lower)
            or ("deg" in base_metric_lower and "deg" not in merged_metric_lower)
        ):
            merged_perf["primary_metric"] = base_metric

    return merged


def _apply_task_spec_defaults(task_spec: dict) -> dict:
    if not isinstance(task_spec, dict):
        return {}

    spec = dict(task_spec)
    if not spec.get("task_category"):
        spec["task_category"] = "wireless_signal_processing"

    system_model = spec.get("system_model")
    if not isinstance(system_model, dict):
        system_model = {}
        spec["system_model"] = system_model

    if not system_model.get("channel_model"):
        system_model["channel_model"] = "AWGN"
    if not system_model.get("waveform"):
        system_model["waveform"] = "single-carrier"
    perf = spec.get("performance_targets")
    if not isinstance(perf, dict):
        perf = {}
        spec["performance_targets"] = perf
    if not perf.get("primary_metric"):
        task_cat = str(spec.get("task_category", "")).lower()
        if "doa" in task_cat or "angle" in task_cat or "aoa" in task_cat:
            perf["primary_metric"] = "RMSE"
        elif "detect" in task_cat:
            perf["primary_metric"] = "Pd"
        elif "estimation" in task_cat or "channel" in task_cat:
            perf["primary_metric"] = "NMSE"
        elif "beamform" in task_cat or "precod" in task_cat:
            perf["primary_metric"] = "SINR"
        else:
            # Leave generic — LLM should determine the appropriate metric
            perf["primary_metric"] = "primary_metric"

    return spec


def _normalize_plan_role(raw_role: object) -> str:
    role = str(raw_role or "").strip().lower().replace("-", "_").replace(" ", "_")
    return "".join(ch for ch in role if ch.isalnum() or ch == "_")


def _default_role_cell_type(role: str) -> str:
    return ROLE_CELL_TYPES.get(role, "code")


def _default_variable_points(task_spec: dict) -> list[int]:
    # Derive operating points from task spec range (may be SNR or any other parameter)
    operating_range = ((task_spec.get("system_model") or {}).get("snr_range_db")
                       or (task_spec.get("system_model") or {}).get("operating_range"))
    if isinstance(operating_range, list) and len(operating_range) >= 2:
        start = int(operating_range[0])
        stop = int(operating_range[1])
        step = 5 if stop >= start else -5
        return list(range(start, stop + step, step))
    return [0, 1, 2, 3, 4]


def _normalize_solution_plan(task_spec: dict, solution_plan: dict | None) -> dict:
    normalized = dict(solution_plan or {})

    architecture = normalized.get("architecture")
    if not isinstance(architecture, dict):
        architecture = {}
    architecture.setdefault("name", "Notebook Solution")
    architecture.setdefault("strategy_label", architecture.get("name", "notebook_solution"))
    architecture.setdefault("summary", architecture.get("rationale") or "Single-path notebook execution plan")
    normalized["architecture"] = architecture

    algorithm_spec = normalized.get("algorithm_spec")
    if not isinstance(algorithm_spec, dict):
        algorithm_spec = {}
    algorithm_spec.setdefault("objective", (task_spec.get("task_description") or task_spec.get("task_category") or "Notebook study objective"))
    algorithm_spec.setdefault("inputs", [])
    algorithm_spec.setdefault("outputs", [])
    algorithm_spec.setdefault("pipeline", [])
    algorithm_spec.setdefault("core_assumptions", [])
    algorithm_spec.setdefault("implementation_constraints", [])
    algorithm_spec.setdefault("failure_modes", [])
    evaluation_contract = algorithm_spec.get("evaluation_contract")
    if not isinstance(evaluation_contract, dict):
        evaluation_contract = {}
    evaluation_contract.setdefault("required_result_keys", ["algorithm", "elapsed_sec", "performance_data", "report_assets"])
    evaluation_contract.setdefault("baseline_methods", [])
    algorithm_spec["evaluation_contract"] = evaluation_contract
    normalized["algorithm_spec"] = algorithm_spec

    evaluation_plan = normalized.get("evaluation_plan")
    if not isinstance(evaluation_plan, dict):
        evaluation_plan = {}
    primary_metric = (task_spec.get("performance_targets") or {}).get("primary_metric") or "primary_metric"
    primary_metrics = evaluation_plan.get("primary_metrics")
    if not isinstance(primary_metrics, list):
        primary_metrics = []
    if not primary_metrics:
        primary_metrics = [{"name": primary_metric, "description": f"Primary task metric {primary_metric}"}]
    baseline_methods = evaluation_plan.get("baseline_methods")
    if not isinstance(baseline_methods, list):
        baseline_methods = []
    if not baseline_methods:
        baseline_methods = [
            {"name": item, "description": f"Baseline comparison against {item}"}
            for item in (evaluation_contract.get("baseline_methods") or [])
            if item
        ]
    evaluation_plan.setdefault("independent_variable", None)
    raw_points = evaluation_plan.get("variable_points")
    evaluation_plan["variable_points"] = raw_points if isinstance(raw_points, list) and raw_points else _default_variable_points(task_spec)
    if not evaluation_plan.get("independent_variable"):
        # Determine label from task context: use "SNR (dB)" only when task explicitly
        # defines an SNR range; otherwise keep it generic.
        has_snr_range = bool((task_spec.get("system_model") or {}).get("snr_range_db"))
        evaluation_plan["independent_variable"] = "SNR (dB)" if has_snr_range else "Operating Point"
    evaluation_plan.setdefault("num_monte_carlo", 20)
    evaluation_plan["primary_metrics"] = primary_metrics
    evaluation_plan.setdefault("secondary_metrics", [])
    evaluation_plan["baseline_methods"] = baseline_methods
    evaluation_plan.setdefault("plots", [])
    evaluation_plan.setdefault("sensitivity_factors", [])
    evaluation_plan.setdefault("boundary_conditions", [])
    normalized["evaluation_plan"] = evaluation_plan

    notebook_plan = normalized.get("notebook_plan")
    if not isinstance(notebook_plan, list):
        notebook_plan = []
    role_map: dict[str, dict] = {}
    ordered_roles: list[str] = []
    for item in notebook_plan:
        if not isinstance(item, dict):
            continue
        role = _normalize_plan_role(item.get("role"))
        if not role:
            continue
        normalized_item = dict(item)
        normalized_item["role"] = role
        normalized_item["cell_type"] = normalized_item.get("cell_type") or _default_role_cell_type(role)
        must_include = normalized_item.get("must_include")
        if not isinstance(must_include, list):
            must_include = []
        normalized_item["must_include"] = [str(entry) for entry in must_include if str(entry).strip()]
        if role not in role_map:
            ordered_roles.append(role)
        role_map[role] = normalized_item

    for role in [*PLAN_CORE_ROLES, *PLAN_RECOMMENDED_ROLES]:
        if role not in role_map:
            role_map[role] = {
                "role": role,
                "cell_type": _default_role_cell_type(role),
                "purpose": "Auto-filled notebook contract requirement",
                "must_include": [],
            }
            ordered_roles.append(role)

    normalized["notebook_plan"] = [role_map[role] for role in ordered_roles]
    normalized["execution_contract"] = {
        "primary_metric": primary_metrics[0].get("name") or primary_metric,
        "baseline_methods": [
            (item or {}).get("name")
            for item in baseline_methods
            if isinstance(item, dict) and (item or {}).get("name")
        ],
        "independent_variable": evaluation_plan.get("independent_variable") or "Operating Point",
        "variable_points": evaluation_plan.get("variable_points") or [],
        "num_monte_carlo": evaluation_plan.get("num_monte_carlo"),
        "required_roles": [item.get("role") for item in normalized["notebook_plan"] if item.get("role")],
        "required_result_keys": evaluation_contract.get("required_result_keys") or ["algorithm", "elapsed_sec", "performance_data", "report_assets"],
        "comparison_required": bool(baseline_methods),
        "algorithm_steps": [
            {
                "name": (step or {}).get("name"),
                "formula_latex": (step or {}).get("formula_latex", ""),
            }
            for step in (algorithm_spec.get("pipeline") or [])
            if isinstance(step, dict) and (step or {}).get("name")
        ],
        "implementation_constraints": [
            str(item)
            for item in (algorithm_spec.get("implementation_constraints") or [])
            if str(item).strip()
        ],
    }
    return normalized


def _review_requires_repair(review: dict) -> bool:
    if not isinstance(review, dict):
        return False
    health = review.get("result_health") or {}
    return (
        health.get("execution_success") is False
        or health.get("metrics_trustworthy") is False
        or health.get("figures_complete") is False
    )


def _build_repair_context(state: dict) -> dict:
    verification_results = state.get("verification_results") or {}
    simulation_results = state.get("simulation_results") or {}
    review_feedback = state.get("review_feedback") or {}

    issues: list[str] = []
    source = "fresh_generation"
    if verification_results.get("status") == "error":
        source = "verification"
        issues.extend(str(item) for item in (verification_results.get("errors") or []) if str(item).strip())
        issues.extend(str(item) for item in (verification_results.get("repair_guidance") or []) if str(item).strip())
    elif simulation_results.get("status") == "error":
        source = "simulation"
        for item in [simulation_results.get("stage"), simulation_results.get("error"), simulation_results.get("error_log")]:
            if str(item or "").strip():
                issues.append(str(item))
    elif _review_requires_repair(review_feedback):
        source = "result_review"
        issues.extend(str(item) for item in (review_feedback.get("technical_risks") or []) if str(item).strip())
        issues.extend(
            str(item)
            for item in (((review_feedback.get("result_health") or {}).get("main_concerns") or []))
            if str(item).strip()
        )
        issues.extend(str(item) for item in (review_feedback.get("actionable_notes") or []) if str(item).strip())

    return {
        "source": source,
        "repair_required": bool(state.get("notebook")) and bool(issues),
        "verification_status": verification_results.get("status"),
        "simulation_status": simulation_results.get("status"),
        "review_status": (review_feedback.get("result_health") or {}),
        "issues": issues[:12],
    }


def _normalize_clarification_questions(agent, questions: list[str] | None, missing_fields: list[str]) -> list[str]:
    normalized = [q.strip() for q in (questions or []) if isinstance(q, str) and q.strip()]
    if normalized:
        return normalized[:2]
    if hasattr(agent, "build_clarification_questions"):
        fallback = agent.build_clarification_questions(missing_fields)
        fallback = [q.strip() for q in fallback if isinstance(q, str) and q.strip()]
        if fallback:
            return fallback[:2]
    if missing_fields:
        return ["Please provide the missing required information: " + ", ".join(missing_fields[:3])]
    return ["Please clarify the task type and primary performance metric so the system can continue."]


def problem_analysis_node(state: AutoWiSPAState) -> dict:
    from agents.problem_analyzer import ProblemAnalyzerAgent

    bus = get_event_bus()
    bus.emit_node_start("problem_analysis", {"query": state["user_query"][:200]})
    agent = ProblemAnalyzerAgent(llm=_build_llm_client(state))

    result = agent.analyze(
        user_query=state["user_query"],
        conversation_history=state.get("conversation_history") or [],
    )

    if result.get("status") == "complete":
        task_spec = _apply_task_spec_defaults(result.get("task_spec") or {})
        is_complete, missing = agent.check_completeness(task_spec)
        summary_lines = [
            f"Task type: {task_spec.get('task_category', 'unknown')}",
            f"Waveform: {(task_spec.get('system_model') or {}).get('waveform', 'unknown')}",
            f"Primary metric: {(task_spec.get('performance_targets') or {}).get('primary_metric', 'unknown')}",
            f"Spec complete: {is_complete}",
        ]
        _log_trace("S1", "Problem analysis result", summary_lines)

        if not is_complete:
            questions = _normalize_clarification_questions(agent, [], missing)
            out = {
                "task_spec": task_spec,
                "task_spec_complete": False,
                "clarification_questions": questions,
                "execution_trace": [_trace_entry("S1", "Problem analysis pending clarification", summary_lines, {"questions": questions})],
                "current_phase": "awaiting_user_input",
            }
            bus.emit_node_end("problem_analysis", {"summary": "\n".join(summary_lines)})
            return out

        hitl_timeout = float((((state.get("config") or {}).get("web") or {}).get("hitl_timeout", 10)))
        bus.emit_log("problem_analysis", f"Waiting up to {int(hitl_timeout)}s for human review before auto-continue")
        hitl = bus.wait_for_human(
            node="problem_analysis",
            prompt='Please review the parsed task spec. Click "Approve" if correct, or provide revision comments.',
            context={"task_spec": task_spec, "summary": summary_lines},
            timeout=hitl_timeout,
        )
        if hitl["action"] == "revise" and hitl["feedback"]:
            revised = agent.analyze(
                user_query=state["user_query"],
                conversation_history=[
                    *(state.get("conversation_history") or []),
                    {"role": "user", "content": hitl["feedback"]},
                ],
            )
            task_spec = _apply_task_spec_defaults((revised.get("task_spec") or task_spec))

        out = {
            "task_spec": task_spec,
            "task_spec_complete": True,
            "clarification_questions": [],
            "execution_trace": [_trace_entry("S1", "Problem analysis result", summary_lines, task_spec)],
            "current_phase": "knowledge_retrieval",
        }
        _save_checkpoint("problem_analysis", {**state, **out})
        _save_stage_artifact("task_spec.json", task_spec)
        bus.emit_node_end("problem_analysis", {"summary": "\n".join(summary_lines)})
        return out

    partial_spec = _apply_task_spec_defaults(result.get("partial_spec") or {})
    is_complete, missing = agent.check_completeness(partial_spec)
    if is_complete:
        out = {
            "task_spec": partial_spec,
            "task_spec_complete": True,
            "clarification_questions": [],
            "execution_trace": [_trace_entry("S1", "Problem analysis result", ["Spec completed by defaults"], partial_spec)],
            "current_phase": "knowledge_retrieval",
        }
        _save_checkpoint("problem_analysis", {**state, **out})
        _save_stage_artifact("task_spec.json", partial_spec)
        bus.emit_node_end("problem_analysis", {"summary": "Spec completed by defaults"})
        return out

    questions = _normalize_clarification_questions(agent, result.get("questions"), missing)
    summary_lines = [
        f"Spec incomplete, pending questions: {len(questions)}",
        f"Missing fields: {', '.join(missing) or 'unknown'}",
    ]
    out = {
        "task_spec": partial_spec,
        "task_spec_complete": False,
        "clarification_questions": questions,
        "execution_trace": [_trace_entry("S1", "Problem analysis pending clarification", summary_lines, {"questions": questions})],
        "current_phase": "awaiting_user_input",
    }
    bus.emit_node_end("problem_analysis", {"summary": "\n".join(summary_lines)})
    return out


def knowledge_retrieval_node(state: AutoWiSPAState) -> dict:
    from agents.knowledge_retriever import KnowledgeRetrieverAgent
    from agents.problem_analyzer import ProblemAnalyzerAgent

    bus = get_event_bus()
    bus.emit_node_start("knowledge_retrieval")

    cfg = state.get("config") or {}
    kb_cfg = cfg.get("knowledge_base") or {}
    top_k_papers = int(kb_cfg.get("top_k_papers", 5))
    top_k_algorithms = int(kb_cfg.get("top_k_algorithms", 5))
    top_k_templates = int(kb_cfg.get("top_k_templates", 3))
    online_sources = kb_cfg.get("online_sources") or ["ieee_crossref", "semantic_scholar", "crossref", "arxiv"]

    retriever = KnowledgeRetrieverAgent(
        llm=_build_llm_client(state),
        online_sources=online_sources,
        config=kb_cfg,
    )
    knowledge = retriever.retrieve(
        task_spec=state["task_spec"],
        top_k_papers=top_k_papers,
        top_k_algorithms=top_k_algorithms,
        top_k_templates=top_k_templates,
    )
    base_spec = state["task_spec"] or {}
    refined_spec = ProblemAnalyzerAgent(llm=_build_llm_client(state)).refine_with_knowledge(base_spec, knowledge)
    refined_spec = _preserve_task_intent(base_spec, refined_spec)
    refined_spec = _apply_task_spec_defaults(refined_spec)

    papers = knowledge.get("relevant_papers") or []
    summary_lines = [
        f"Search query: {knowledge.get('paper_search_query', '')}",
        f"Papers found: {len(papers)}",
        f"Refined task metric: {(refined_spec.get('performance_targets') or {}).get('primary_metric', 'unknown')}",
        f"Refined waveform: {(refined_spec.get('system_model') or {}).get('waveform', 'unknown')}",
    ]
    _log_trace("S2", "Knowledge retrieval and refinement", summary_lines)

    out = {
        "retrieved_knowledge": knowledge,
        "task_spec": refined_spec,
        "execution_trace": [_trace_entry("S2", "Knowledge retrieval and refinement", summary_lines, {"knowledge": knowledge, "task_spec": refined_spec})],
        "current_phase": "model_formulation",
    }
    _save_checkpoint("knowledge_retrieval", {**state, **out})
    _save_stage_artifact("retrieved_knowledge.json", knowledge)
    _save_stage_artifact("task_spec.json", refined_spec)
    bus.emit_node_end("knowledge_retrieval", {"summary": "\n".join(summary_lines), "papers": papers, "paper_search_query": knowledge.get("paper_search_query", "")})
    return out


def model_formulation_node(state: AutoWiSPAState) -> dict:
    from agents.model_formalizer import ModelFormalizerAgent

    bus = get_event_bus()
    bus.emit_node_start("model_formulation")

    agent = ModelFormalizerAgent(llm=_build_llm_client(state))
    formalization = agent.formalize(
        task_spec=state["task_spec"],
        retrieved_knowledge=state.get("retrieved_knowledge") or {},
    )

    scenario_spec = formalization.get("scenario_spec") or {}
    math_formulation = formalization.get("math_formulation") or {}
    algorithm_design = formalization.get("algorithm_design") or {}
    summary_lines = [
        f"Signal type: {scenario_spec.get('signal_type', 'unknown')}",
        f"Scenario count: {len(scenario_spec.get('test_scenarios', []))}",
        f"Problem type: {math_formulation.get('problem_type', 'unknown')}",
        f"Key formulas: {len(math_formulation.get('key_formulas', []))}",
        f"Algorithm: {(algorithm_design.get('proposed_algorithm') or {}).get('name', 'unknown')}",
        f"Algorithm steps: {len(algorithm_design.get('algorithm_steps', []))}",
        f"Baselines: {len(algorithm_design.get('baseline_algorithms', []))}",
    ]
    _log_trace("S3", "Unified model formalization", summary_lines)

    out = {
        "problem_formalization": formalization,
        "execution_trace": [_trace_entry("S3", "Unified model formalization", summary_lines, formalization)],
        "current_phase": "solution_planning",
    }
    _save_checkpoint("model_formulation", {**state, **out})
    _save_stage_artifact("problem_formalization.json", formalization)
    bus.emit_node_end("model_formulation", {"summary": "\n".join(summary_lines)})
    return out


def solution_planning_node(state: AutoWiSPAState) -> dict:
    from agents.solution_designer import SolutionDesignerAgent

    bus = get_event_bus()
    bus.emit_node_start("solution_planning")

    agent = SolutionDesignerAgent(llm=_build_llm_client(state, temperature=_architect_temperature(state)))
    solution_plan = agent.design(
        task_spec=state["task_spec"],
        retrieved_knowledge=state.get("retrieved_knowledge") or {},
        formalization=state.get("problem_formalization") or {},
    )
    solution_plan = _normalize_solution_plan(state.get("task_spec") or {}, solution_plan)

    architecture = solution_plan.get("architecture") or {}
    notebook_plan = solution_plan.get("notebook_plan") or []
    evaluation_plan = solution_plan.get("evaluation_plan") or {}
    summary_lines = [
        f"Architecture: {architecture.get('name', 'unknown')}",
        f"Strategy: {architecture.get('strategy_label', 'unknown')}",
        f"Notebook cells planned: {len(notebook_plan)}",
        f"Primary metrics: {', '.join(item.get('name', '') for item in evaluation_plan.get('primary_metrics', [])[:4]) or 'none'}",
    ]
    _log_trace("S4", "Solution planning", summary_lines)

    out = {
        "solution_plan": solution_plan,
        "execution_trace": [_trace_entry("S4", "Solution planning", summary_lines, solution_plan)],
        "current_phase": "notebook_generation",
    }
    _save_checkpoint("solution_planning", {**state, **out})
    _save_stage_artifact("solution_plan.json", solution_plan)
    _save_stage_artifact("notebook_plan.json", solution_plan.get("notebook_plan") or [])
    bus.emit_node_end("solution_planning", {"summary": "\n".join(summary_lines)})
    return out


def notebook_generation_node(state: AutoWiSPAState) -> dict:
    from agents.notebook_generator import NotebookGenerator

    bus = get_event_bus()
    bus.emit_node_start("notebook_generation")

    agent = NotebookGenerator(llm=_build_llm_client(state), repair_llm=_build_llm_client(state))
    repair_context = _build_repair_context(state)
    repair_feedback = "\n".join(repair_context.get("issues") or [])

    existing_notebook = state.get("notebook")
    if existing_notebook and repair_feedback:
        notebook = agent.repair(
            notebook=existing_notebook,
            task_spec=state.get("task_spec") or {},
            solution_plan=state.get("solution_plan") or {},
            error_message=repair_feedback,
            repair_context=repair_context,
            formalization=state.get("problem_formalization") or {},
        )
        generation_mode = f"repair:{repair_context.get('source', 'unknown')}"
    else:
        notebook = agent.generate(
            task_spec=state.get("task_spec") or {},
            retrieved_knowledge=state.get("retrieved_knowledge") or {},
            formalization=state.get("problem_formalization") or {},
            solution_plan=state.get("solution_plan") or {},
        )
        generation_mode = "fresh"

    notebook_summary = agent.summarize_notebook(notebook)
    attempt = int(state.get("verification_retry_count", 0)) + int(state.get("simulation_retry_count", 0))
    summary_lines = [
        f"Generation mode: {generation_mode}",
        f"Notebook cells: {len(notebook.get('cells', []))}",
        f"Code cells: {notebook_summary.get('code_cells', 0)}",
        f"Markdown cells: {notebook_summary.get('markdown_cells', 0)}",
    ]
    _log_trace("S5", "Notebook generation", summary_lines)

    out = {
        "notebook": notebook,
        "notebook_validated": False,
        "verification_results": None,
        "simulation_results": None,
        "review_feedback": None,
        "execution_trace": [_trace_entry("S5", "Notebook generation", summary_lines, notebook_summary)],
        "current_phase": "verification",
    }
    _save_iteration_artifacts(attempt=attempt, notebook=notebook)
    _save_checkpoint("notebook_generation", {**state, **out})
    _save_stage_artifact("simulation.ipynb", notebook)
    bus.emit(Event(type=EventType.CODE_UPDATE, node="notebook_generation", data={"notebook": notebook, "code_package": _notebook_code_snapshot(notebook)}))
    bus.emit_node_end("notebook_generation", {"summary": "\n".join(summary_lines)})
    return out


def verification_node(state: AutoWiSPAState) -> dict:
    from agents.verifier import VerificationAgent

    bus = get_event_bus()
    bus.emit_node_start("verification")

    agent = VerificationAgent(config=(state.get("config") or {}).get("agents", {}))
    results = agent.verify_notebook(
        notebook=state.get("notebook") or {},
        task_spec=state.get("task_spec") or {},
        solution_plan=state.get("solution_plan") or {},
    )

    retry_count = int(state.get("verification_retry_count", 0))
    max_retries = int(state.get("max_verification_retries", 3))
    errors = results.get("errors") or []
    warnings = results.get("warnings") or []

    if results.get("status") == "error":
        retry_count += 1
        exceeded = retry_count >= max_retries
        summary_lines = [
            "Status: error",
            f"Errors: {len(errors)}",
            f"Warnings: {len(warnings)}",
            f"First error: {_clip_text(errors[0], 180) if errors else 'none'}",
        ]
        _log_trace("S6", "Notebook verification", summary_lines)
        out = {
            "verification_results": results,
            "verification_retry_count": retry_count,
            "notebook_validated": False,
            "execution_trace": [_trace_entry("S6", "Notebook verification", summary_lines, results)],
            "current_phase": "report_generation" if exceeded else "notebook_generation",
            "termination_reason": f"Verification retries reached limit ({max_retries})" if exceeded else None,
        }
        _save_iteration_artifacts(
            attempt=retry_count + int(state.get("simulation_retry_count", 0)),
            notebook=state.get("notebook"),
            verification_results=results,
        )
        bus.emit_node_end("verification", {"summary": "\n".join(summary_lines)})
        return out

    summary_lines = [
        "Status: passed",
        f"Warnings: {len(warnings)}",
        f"Required roles: {', '.join(results.get('required_roles', [])) or 'none'}",
    ]
    _log_trace("S6", "Notebook verification", summary_lines)
    out = {
        "verification_results": results,
        "verification_retry_count": 0,
        "notebook_validated": True,
        "execution_trace": [_trace_entry("S6", "Notebook verification", summary_lines, results)],
        "current_phase": "simulation",
    }
    _save_checkpoint("verification", {**state, **out})
    _save_stage_artifact("verification_results.json", results)
    bus.emit_node_end("verification", {"summary": "\n".join(summary_lines)})
    return out


def simulation_node(state: AutoWiSPAState) -> dict:
    from agents.simulator import SimulatorAgent

    bus = get_event_bus()
    bus.emit_node_start("simulation")

    agent = SimulatorAgent(config=(state.get("config") or {}).get("simulation", {}))
    results = agent.execute(
        notebook=state.get("notebook") or {},
        task_spec=state.get("task_spec") or {},
        solution_plan=state.get("solution_plan") or {},
    )

    retry_count = int(state.get("simulation_retry_count", 0))
    max_retries = int(state.get("max_simulation_retries", 1))

    if results.get("status") == "error":
        retry_count += 1
        exceeded = retry_count >= max_retries
        summary_lines = [
            "Status: error",
            f"Stage: {results.get('stage', 'execution')}",
            f"Error: {_clip_text(results.get('error_log') or results.get('error') or '', 220)}",
        ]
        _log_trace("S7", "Notebook simulation", summary_lines)
        out = {
            "simulation_results": results,
            "simulation_retry_count": retry_count,
            "execution_trace": [_trace_entry("S7", "Notebook simulation", summary_lines, results)],
            "current_phase": "report_generation" if exceeded else "notebook_generation",
            "termination_reason": f"Simulation retries reached limit ({max_retries})" if exceeded else None,
        }
        _save_iteration_artifacts(
            attempt=int(state.get("verification_retry_count", 0)) + retry_count,
            notebook=state.get("notebook"),
            simulation_results=results,
        )
        bus.emit_node_end("simulation", {"summary": "\n".join(summary_lines)})
        return out

    perf_data = results.get("performance_data") or {}
    summary_lines = [
        f"Status: {results.get('status', 'success')}",
        f"Execution time: {results.get('execution_time', 'N/A')}s",
        f"Performance fields: {', '.join(list(perf_data.keys())[:8]) or 'none'}",
    ]
    _log_trace("S7", "Notebook simulation", summary_lines)
    out = {
        "simulation_results": results,
        "simulation_retry_count": 0,
        "execution_trace": [_trace_entry("S7", "Notebook simulation", summary_lines, results)],
        "current_phase": "report_generation",
    }
    _save_checkpoint("simulation", {**state, **out})
    _save_stage_artifact("simulation_results.json", results)
    bus.emit(Event(type=EventType.PERF_UPDATE, node="simulation", data={"performance_data": perf_data, "execution_time": results.get("execution_time"), "iteration": 1, "eval_level": "notebook"}))
    bus.emit_node_end("simulation", {"summary": "\n".join(summary_lines)})
    return out


def report_generation_node(state: AutoWiSPAState) -> dict:
    from agents.reporter import ReporterAgent

    bus = get_event_bus()
    bus.emit_node_start("report_generation")

    agent = ReporterAgent(llm=_build_llm_client(state))
    report_output_dir = str(_checkpoint_mgr.output_dir) if _checkpoint_mgr is not None else None
    try:
        report, review = agent.generate_with_review(
            task_spec=state.get("task_spec") or {},
            retrieved_knowledge=state.get("retrieved_knowledge") or {},
            formalization=state.get("problem_formalization") or {},
            solution_plan=state.get("solution_plan") or {},
            notebook=state.get("notebook") or {},
            verification_results=state.get("verification_results") or {},
            simulation_results=state.get("simulation_results") or {},
            experiment_evidence=collect_experiment_evidence(state),
            output_dir=report_output_dir,
        )
    except Exception as exc:
        _log_trace("S8", "Report generation FAILED", [f"Error: {exc}"])
        report = (
            "# Report Generation Failed\n\n"
            f"> **Error:** {exc}\n\n"
            "The simulation completed successfully. Please inspect the notebook and simulation artifacts for results.\n"
        )
        review = {"overall_score": 0, "passed": False, "issues": [str(exc)]}

    try:
        final_notebook = agent.enrich_notebook(
            notebook=state.get("notebook") or {},
            verification_results=state.get("verification_results") or {},
            simulation_results=state.get("simulation_results") or {},
            output_dir=report_output_dir,
        )
    except Exception as exc:
        _log_trace("S8", "Notebook enrichment FAILED", [f"Error: {exc}"])
        final_notebook = state.get("notebook") or {}

    report_lines = report.splitlines()
    summary_lines = [
        f"Report lines: {len(report_lines)}",
        f"Report preview: {_clip_text(' '.join(report_lines[:5]), 180)}",
        f"Review score: {review.get('overall_score', 'N/A')}",
    ]
    _log_trace("S8", "Report generation", summary_lines)

    out = {
        "final_report": report,
        "final_notebook": final_notebook,
        "review_feedback": review,
        "execution_trace": [_trace_entry("S8", "Report generation", summary_lines, {"report_preview": report_lines[:20]})],
        "current_phase": "result_review",
    }
    _save_checkpoint("report_generation", {**state, **out})
    _save_stage_artifact("report.md", report)
    _save_stage_artifact("simulation.ipynb", final_notebook)
    _save_stage_artifact("review_feedback.json", review)
    bus.emit_node_end("report_generation", {"summary": "\n".join(summary_lines)})
    return out