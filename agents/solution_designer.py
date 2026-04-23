"""
Solution Designer Agent
Combines architecture design, executable specification, evaluation planning,
and notebook cell planning into one coherent LLM interaction.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from utils.llm_client import LLMClient


CORE_NOTEBOOK_ROLES = [
    "title",
    "problem_setup",
    "modeling_summary",
    "imports_setup",
    "data_generation",
    "algorithm_core",
    "evaluation_logic",
    "execution",
]

RECOMMENDED_NOTEBOOK_ROLES = [
    "plotting",
    "result_notes",
]


SOLUTION_DESIGNER_PROMPT = r"""You are a senior wireless algorithm designer and notebook-oriented implementation planner.

Given the task specification, formalized system/mathematical model, and retrieved knowledge, design one coherent solution package that is immediately ready for notebook generation.

CRITICAL — You MUST reference the mathematical formulas from the formalization (especially math_formulation and algorithm_design) and incorporate them into your solution design. Every pipeline step must have a concrete formula_latex that maps directly to the formalization.

Return one strict JSON object with this structure:
{
  "architecture": {
    "name": "...",
    "strategy_label": "...",
    "summary": "...",
    "rationale": "...",
    "algorithm_structure": "...",
    "pseudocode": "A multi-line pseudocode string with numbered steps. Each step must reference formulas from the formalization (e.g., Step 3: compute $\\mathbf{R}_y = ...$ via sample covariance).",
    "estimated_complexity": "O(...)",
    "confidence": 0.0,
    "potential_weakness": "..."
  },
  "algorithm_spec": {
    "objective": "...",
    "inputs": [{"name": "...", "shape": "...", "dtype": "...", "description": "..."}],
    "outputs": [{"name": "...", "shape": "...", "dtype": "...", "description": "..."}],
    "pipeline": [
      {
        "step": 1,
        "name": "...",
        "purpose": "...",
        "formula_latex": "The exact mathematical formula for this step (e.g., '\\mathbf{R}_y = \\frac{1}{N}\\sum_{n=1}^{N}\\mathbf{y}_n\\mathbf{y}_n^H')",
        "implementation_hint": "Specific numpy/scipy function to use (e.g., 'np.cov or outer product accumulation')"
      }
    ],
    "core_assumptions": ["..."],
    "implementation_constraints": ["..."],
    "failure_modes": ["..."],
    "evaluation_contract": {
      "primary_metrics": ["..."],
      "baseline_methods": ["..."],
      "required_result_keys": ["algorithm", "elapsed_sec", "performance_data"]
    }
  },
  "evaluation_plan": {
    "independent_variable": "<task_defined_axis_or_null>",
    "variable_points": ["<task_defined_points>"],
    "num_monte_carlo": null,
    "primary_metrics": [{"name": "...", "formula_latex": "...", "description": "..."}],
    "secondary_metrics": [{"name": "...", "description": "..."}],
    "baseline_methods": [{"name": "...", "description": "...", "key_formula_latex": "...", "implementation_hint": "..."}],
    "sensitivity_factors": [
      {
        "factor": "Name of the factor to vary (e.g., 'Number of snapshots', 'Number of sources', 'Array elements')",
        "values": ["list of test values"],
        "description": "Why varying this factor matters for evaluation."
      }
    ],
    "plots": [
      {
        "title": "...",
        "x_axis": "...",
        "y_axis": "...",
        "curves": ["proposed", "baseline1", "..."],
        "scale": "linear|semilogy|semilogx",
        "description": "What this plot demonstrates."
      }
    ],
    "boundary_conditions": [{"name": "...", "description": "...", "expected_behavior": "..."}]
  },
  "notebook_plan": [
    {"role": "title", "cell_type": "markdown", "purpose": "...", "must_include": ["..."]},
    {"role": "setup", "cell_type": "code", "purpose": "...", "must_include": ["..."]}
  ]
}

Requirements:
1. Produce exactly one solution path, not multiple candidates.
2. The notebook_plan must be directly executable as a single notebook workflow.
3. All implementation should live inside notebook cells. Do not assume external Python modules.
4. notebook_plan must include these core roles:
    title, problem_setup, modeling_summary, imports_setup, data_generation, algorithm_core,
    evaluation_logic, execution.
5. Add plotting and result_notes when they help communicate evidence, but do not force them for every task.
6. evaluation_plan and algorithm_spec must be consistent with the formalized math model.
7. Keep the plan practical and implementation-oriented.
8. evaluation_plan.independent_variable and variable_points MUST reflect the actual task axis. Only use "SNR (dB)" if the task involves SNR sweeps. For other tasks use appropriate axes.
9. The evaluation_logic notebook cell MUST be designed as a sweep function that loops over every value in variable_points, computing the metric at each point independently. Never design it to compute once and replicate.
10. If baseline_methods are specified, each must be implemented and evaluated in the same sweep loop alongside the proposed algorithm.
11. CRITICAL — Mathematical formula consistency:
    a. Every step in algorithm_spec.pipeline MUST include formula_latex copied or derived from the formalization's math_formulation or algorithm_design.
    b. Every baseline in evaluation_plan.baseline_methods MUST include key_formula_latex.
    c. Every primary_metric MUST include formula_latex (e.g., 'RMSE = \sqrt{\frac{1}{K}\sum_{k=1}^{K}(\hat{\theta}_k - \theta_k)^2}').
    d. The pseudocode in architecture must reference the same formulas from the pipeline steps.
12. CRITICAL — Multi-factor evaluation:
    a. sensitivity_factors must list 2-4 key factors beyond the primary independent_variable that affect algorithm performance (e.g., number of snapshots, number of sources, SNR, array size).
    b. Each factor should have concrete test values appropriate for the task.
    c. The evaluation_logic cell should be designed to support sweeping over these factors too, producing separate comparison plots for each factor.
13. CRITICAL — Rich plot design:
    a. Plan at least 3 plots: (i) primary metric vs independent variable, (ii) one sensitivity factor comparison, (iii) spatial spectrum or intermediate result visualization if applicable.
    b. Each plot entry must specify x_axis, y_axis, curves, and scale.
"""


class SolutionDesignerAgent:
    """Design one integrated solution package for notebook-first execution."""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or LLMClient(temperature=0.4)

    def _max_tokens(self, node_name: str, fallback: Optional[int] = None) -> Optional[int]:
        resolver = getattr(self.llm, "get_max_tokens", None)
        if callable(resolver):
            value = resolver(node_name, fallback)
            return value if isinstance(value, int) or value is None else fallback
        return fallback

    def design(
        self,
        task_spec: dict,
        retrieved_knowledge: dict,
        formalization: dict,
    ) -> dict:
        # Extract algorithm_design formulas for emphasis
        algo_design_block = self._build_algorithm_design_reference(formalization)

        messages = [
            {"role": "system", "content": SOLUTION_DESIGNER_PROMPT},
            {
                "role": "user",
                "content": (
                    f"## Task Specification\n```json\n{json.dumps(task_spec, ensure_ascii=False, indent=2)}\n```\n\n"
                    f"## Retrieved Knowledge\n```json\n{json.dumps(self._compact_knowledge(retrieved_knowledge), ensure_ascii=False, indent=2)}\n```\n\n"
                    f"## Formalization\n```json\n{json.dumps(self._compact_formalization(formalization), ensure_ascii=False, indent=2)}\n```\n\n"
                    + algo_design_block
                    + "IMPORTANT: Your algorithm_spec.pipeline steps MUST map 1:1 to the algorithm_steps above. "
                    "Copy the formula_latex from each step into your pipeline. "
                    "Your baseline_methods MUST include key_formula_latex from the baseline_algorithms above.\n\n"
                    "Return one strict JSON solution package."
                ),
            },
        ]
        response = self.llm.chat(
            messages,
            max_tokens=self._max_tokens("solution_planning"),
            node_name="solution_planning",
        )
        return self._parse_response(response)

    @staticmethod
    def _build_algorithm_design_reference(formalization: dict) -> str:
        """Extract algorithm_design from formalization into a readable reference block."""
        algo = formalization.get("algorithm_design") or {}
        if not algo.get("algorithm_steps"):
            # Fallback to key_formulas from math_formulation
            math = formalization.get("math_formulation") or {}
            formulas = math.get("key_formulas") or []
            if not formulas:
                return ""
            lines = ["## Key Mathematical Formulas (from formalization)\n"]
            for f in formulas:
                lines.append(f"- **{f.get('name', '')}**: ${f.get('formula_latex', '')}$ — {f.get('description', '')}")
            return "\n".join(lines) + "\n\n"

        proposed = algo.get("proposed_algorithm") or {}
        lines = [
            f"## Algorithm Design Reference (from formalization)",
            f"**Proposed**: {proposed.get('name', 'unknown')} ({proposed.get('type', '')}) — {proposed.get('summary', '')}",
            "",
            "### Algorithm Steps (your pipeline MUST follow these):",
        ]
        for step in algo["algorithm_steps"]:
            if not isinstance(step, dict):
                continue
            lines.append(
                f"  Step {step.get('step', '?')}: **{step.get('name', '')}**\n"
                f"    Formula: ${step.get('formula_latex', '')}$\n"
                f"    Inputs: {', '.join(step.get('inputs') or [])}\n"
                f"    Outputs: {', '.join(step.get('outputs') or [])}\n"
                f"    numpy hint: `{step.get('numpy_hint', '')}`"
            )

        baselines = algo.get("baseline_algorithms") or []
        if baselines:
            lines.append("\n### Baseline Algorithms (must include in evaluation):")
            for bl in baselines:
                if not isinstance(bl, dict):
                    continue
                lines.append(
                    f"  - **{bl.get('name', '')}**: ${bl.get('key_formula_latex', '')}$\n"
                    f"    {bl.get('summary', '')} — hint: `{bl.get('numpy_hint', '')}`"
                )

        convergence = algo.get("convergence") or {}
        if convergence.get("criterion"):
            lines.append(f"\n### Convergence: {convergence['criterion']}")

        complexity = algo.get("complexity") or {}
        if complexity.get("per_iteration"):
            lines.append(f"### Complexity: {complexity['per_iteration']}")

        return "\n".join(lines) + "\n\n"

    @staticmethod
    def _compact_formalization(formalization: dict) -> dict:
        """Compact formalization for prompt injection.

        algorithm_design is already extracted via _build_algorithm_design_reference,
        so only scenario_spec + math_formulation are included here.
        """
        scenario = formalization.get("scenario_spec") or {}
        math_f = formalization.get("math_formulation") or {}
        summary = formalization.get("formalization_summary") or {}
        return {
            # Full system model doc — no truncation, critical for formula fidelity
            "system_model_doc": str(formalization.get("system_model_doc") or ""),
            "scenario_spec": {
                "signal_type": scenario.get("signal_type", ""),
                "core_parameters": scenario.get("core_parameters") or {},
                "snr_range_db": scenario.get("snr_range_db") or [],
                "test_scenarios": scenario.get("test_scenarios") or [],
                "data_contract": scenario.get("data_contract") or {},
                "generation_notes": scenario.get("generation_notes", ""),
            },
            "math_formulation": {
                "problem_type": math_f.get("problem_type", ""),
                "objective": math_f.get("objective") or {},
                "variables": math_f.get("variables") or [],
                "key_formulas": math_f.get("key_formulas") or [],
                "assumptions": math_f.get("assumptions") or [],
                "constraints": math_f.get("constraints") or [],
                "model_properties": math_f.get("model_properties") or {},
                "formulation_markdown": math_f.get("formulation_markdown", ""),
            },
            "formalization_summary": {
                "design_implications": summary.get("design_implications") or [],
                "evaluation_focus": summary.get("evaluation_focus") or [],
                "implementation_risks": summary.get("implementation_risks") or [],
            },
            # NOTE: algorithm_design extracted separately via _build_algorithm_design_reference
        }

    @staticmethod
    def _compact_knowledge(knowledge: dict) -> dict:
        return {
            "relevant_papers": [
                {
                    "title": item.get("title"),
                    "year": item.get("year"),
                    "source": item.get("source"),
                }
                for item in (knowledge.get("relevant_papers") or [])
            ],
            "relevant_algorithms": [
                item if isinstance(item, str) else (item or {}).get("name", "")
                for item in (knowledge.get("relevant_algorithms") or [])
                if item
            ],
            "design_insights": (knowledge.get("design_insights") or ""),
        }

    @staticmethod
    def _extract_json_dict(response: str) -> Optional[dict]:
        stripped = (response or "").strip()
        if not stripped:
            return None

        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        fence_matches = re.findall(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL)
        for candidate in fence_matches:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

        decoder = json.JSONDecoder()
        start = stripped.find("{")
        while start != -1:
            try:
                parsed, _ = decoder.raw_decode(stripped[start:])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
            start = stripped.find("{", start + 1)

        return None

    @staticmethod
    def _parse_response(response: str) -> dict:
        parsed = SolutionDesignerAgent._extract_json_dict(response)
        if isinstance(parsed, dict):
            return parsed

        return {
            "architecture": {
                "name": "Fallback Notebook Solution",
                "strategy_label": "fallback",
                "summary": response,
                "rationale": "Response parsing fell back to raw text.",
                "algorithm_structure": "",
                "pseudocode": "",
                "estimated_complexity": "Unknown",
                "confidence": 0.1,
                "potential_weakness": "LLM response did not follow strict JSON.",
            },
            "algorithm_spec": {
                "objective": response,
                "inputs": [],
                "outputs": [],
                "pipeline": [],
                "core_assumptions": [],
                "implementation_constraints": [],
                "failure_modes": ["Fallback parse triggered"],
                "evaluation_contract": {
                    "primary_metrics": [],
                    "baseline_methods": [],
                    "required_result_keys": ["algorithm", "elapsed_sec", "performance_data"],
                },
            },
            "evaluation_plan": {
                "independent_variable": None,
                "variable_points": [],
                "num_monte_carlo": None,
                "primary_metrics": [],
                "secondary_metrics": [],
                "baseline_methods": [],
                "plots": [],
                "boundary_conditions": [],
            },
            "notebook_plan": [
                *[
                    {"role": role, "cell_type": "markdown" if role in {"title", "problem_setup", "modeling_summary"} else "code", "purpose": "Fallback notebook structure", "must_include": []}
                    for role in CORE_NOTEBOOK_ROLES
                ],
                *[
                    {"role": role, "cell_type": "markdown" if role == "result_notes" else "code", "purpose": "Recommended fallback notebook structure", "must_include": []}
                    for role in RECOMMENDED_NOTEBOOK_ROLES
                ],
            ],
        }