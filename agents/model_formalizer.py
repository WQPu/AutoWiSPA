"""
Model Formalizer Agent
Combines scenario definition, system modeling, and mathematical formulation
into one coherent LLM interaction.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


FORMALIZATION_SYSTEM_PROMPT = r"""You are a senior wireless signal processing theorist and simulation designer.

Your task is to transform a structured task specification into one unified formalization package that is directly useful for simulation, algorithm design, and reporting.

Return one strict JSON object with this structure:
{
  "scenario_spec": {
    "signal_type": "...",
    "core_parameters": {"...": "..."},
    "snr_range_db": ["task_defined_low", "task_defined_high"],
    "test_scenarios": [
      {"name": "...", "description": "...", "overrides": {"...": "..."}}
    ],
    "data_contract": {
      "inputs": ["..."],
      "expected_outputs": ["..."]
    },
    "generation_notes": "..."
  },
  "system_model_doc": "Markdown + LaTeX string",
  "math_formulation": {
    "problem_type": "...",
    "objective": {
      "type": "maximize|minimize|estimate|decide",
      "description": "...",
      "formula_latex": "..."
    },
    "variables": [
      {"symbol": "...", "name": "...", "domain": "...", "description": "..."}
    ],
    "constraints": [
      {"formula_latex": "...", "description": "...", "type": "equality|inequality|structural"}
    ],
    "key_formulas": [
      {"name": "...", "formula_latex": "...", "description": "..."}
    ],
    "assumptions": ["..."],
    "model_properties": {
      "convexity": "...",
      "closed_form": false,
      "iterative_required": true,
      "special_structure": "..."
    },
    "formulation_markdown": "Markdown + LaTeX string"
  },
  "algorithm_design": {
    "proposed_algorithm": {
      "name": "...",
      "type": "iterative|closed_form|decomposition|learning_based|subspace|spectral",
      "summary": "One-sentence description of the algorithm approach."
    },
    "algorithm_steps": [
      {
        "step": 1,
        "name": "...",
        "description": "What this step computes and why.",
        "formula_latex": "The core formula executed in this step (e.g., '\\mathbf{R}_y = \\frac{1}{N}\\sum_{n=1}^{N}\\mathbf{y}_n\\mathbf{y}_n^H')",
        "inputs": ["symbol or variable name"],
        "outputs": ["symbol or variable name"],
        "numpy_hint": "Brief hint on numpy/scipy implementation (e.g., 'np.cov or direct outer product accumulation')"
      }
    ],
    "baseline_algorithms": [
      {
        "name": "...",
        "summary": "One-sentence description.",
        "key_formula_latex": "The defining formula of the baseline.",
        "numpy_hint": "Brief implementation hint."
      }
    ],
    "convergence": {
      "criterion": "Convergence or stopping condition (e.g., 'max iterations or residual < epsilon'). Use null if non-iterative.",
      "typical_iterations": null,
      "formula_latex": "Stopping condition formula, or null."
    },
    "complexity": {
      "per_iteration": "Big-O per iteration (e.g., 'O(M^2 N)'), or per evaluation if non-iterative.",
      "dominant_operation": "The most expensive matrix/vector operation (e.g., 'eigendecomposition of M×M covariance matrix')."
    }
  },
  "formalization_summary": {
    "design_implications": ["..."],
    "evaluation_focus": ["..."],
    "implementation_risks": ["..."]
  }
}

Requirements:
1. scenario_spec, system_model_doc, math_formulation, and algorithm_design must be mutually consistent.
2. Use rigorous mathematical notation with clear symbol definitions.
3. test_scenarios should contain a task-appropriate set of meaningful cases.
4. data_contract must describe what the notebook's executable code should construct and evaluate.
5. Avoid fabricating default numbers. Use explicit values only when the task or evidence supports them; otherwise use null, empty lists, or a concise note.
6. The output must remain useful for a single notebook-based implementation workflow.
7. Keep the response compact, but do not enforce rigid counts for scenarios, formulas, variables, or assumptions. Include however many items are technically necessary for the task.
8. Keep descriptions terse. Each free-text field should be 1 sentence when possible.
9. system_model_doc and formulation_markdown must each be a short technical paragraph, not a multi-section document.
10. Do not include headings, bullet lists, or explanatory prose outside the required JSON fields.
11. CRITICAL — algorithm_design:
    a. algorithm_steps must be a COMPLETE ordered sequence of every computational step needed to go from raw input data to final output. Do not skip intermediate steps.
    b. Each step's formula_latex must be the EXACT formula that would be translated to code — not a high-level description. Include matrix dimensions, index ranges, and normalization constants.
    c. baseline_algorithms must include at least one classical/reference method with its defining formula, so the notebook can implement a fair comparison.
    d. numpy_hint should reference specific numpy/scipy functions when applicable (e.g., 'np.linalg.eigh', 'scipy.linalg.toeplitz').
    e. The algorithm_steps sequence must be detailed enough that a code generator can produce a working implementation without additional mathematical references.
12. CRITICAL — use task_spec input fields:
    a. task_spec.exploitable_structure (or task_spec.problem_understanding.exploitable_structure):
       If a mathematical structure is identified (sparsity, low-rank, Toeplitz, shift-invariance, etc.):
       - Set math_formulation.model_properties.special_structure to that structure.
       - Choose algorithm_design.proposed_algorithm.type and algorithm_steps to directly exploit it
         (e.g., sparsity → OMP/LASSO steps; Toeplitz → Vandermonde decomposition; subspace → eigendecomposition).
       - Add the structure as a design_implication in formalization_summary.
    b. task_spec.performance_targets.theoretical_bound:
       If a theoretical bound is named (CRB, channel capacity, matched-filter bound, etc.):
       - Include it in formalization_summary.evaluation_focus as a benchmark goal.
       - Add it as a baseline_algorithms entry (name = bound name, key_formula_latex = bound formula,
         numpy_hint = 'analytical formula — compute and plot as reference') so the notebook
         can overlay the bound on the performance curves.
"""


class ModelFormalizerAgent:
    """Generate one coherent formalization package in a single LLM call."""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or LLMClient()

    def _max_tokens(self, node_name: str, fallback: Optional[int] = None) -> Optional[int]:
        resolver = getattr(self.llm, "get_max_tokens", None)
        if callable(resolver):
            value = resolver(node_name, fallback)
            return value if isinstance(value, int) or value is None else fallback
        return fallback

    def formalize(
        self,
        task_spec: dict,
        retrieved_knowledge: Optional[dict] = None,
    ) -> dict:
        knowledge_summary = self._build_knowledge_summary(retrieved_knowledge or {})
        messages = [
            {"role": "system", "content": FORMALIZATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"## Task Specification\n```json\n{json.dumps(task_spec, ensure_ascii=False, indent=2)}\n```\n\n"
                    f"## Knowledge Summary\n{knowledge_summary}\n\n"
                    "Produce the unified formalization package as a strict JSON object. Keep it concise without dropping technically necessary content."
                ),
            },
        ]
        response = self.llm.chat(
            messages,
            max_tokens=self._max_tokens("model_formulation", 4000),
            node_name="model_formulation",
        )
        return self._compact_formalization(self._parse_response(response))

    @staticmethod
    def _build_knowledge_summary(retrieved_knowledge: dict) -> str:
        papers = retrieved_knowledge.get("relevant_papers") or []
        lines = []
        if papers:
            lines.append("Relevant papers:")
            for idx, paper in enumerate(papers, start=1):
                lines.append(
                    f"- [{idx}] {paper.get('title', '')} ({paper.get('year', '')}, {paper.get('source', '')})"
                )
        insights = (retrieved_knowledge.get("design_insights") or "").strip()
        if insights:
            lines.append("\nRetrieved design insights:")
            lines.append(insights)
        algorithms = retrieved_knowledge.get("relevant_algorithms") or []
        if algorithms:
            lines.append(
                "\nRelevant algorithm families: "
                + ", ".join(
                    item if isinstance(item, str) else (item or {}).get("name", "")
                    for item in algorithms if item
                )
            )
        return "\n".join(lines) if lines else "(No external knowledge available)"

    @staticmethod
    def _normalize_text(value: object) -> str:
        return str(value or "").strip()

    @classmethod
    def _compact_formalization(cls, formalization: dict) -> dict:
        scenario_spec = formalization.get("scenario_spec") or {}
        math_formulation = formalization.get("math_formulation") or {}
        summary = formalization.get("formalization_summary") or {}

        compact_scenarios = []
        for item in (scenario_spec.get("test_scenarios") or []):
            compact_scenarios.append(
                {
                    "name": cls._normalize_text(item.get("name", "")),
                    "description": cls._normalize_text(item.get("description", "")),
                    "overrides": item.get("overrides") or {},
                }
            )

        compact_variables = []
        for item in (math_formulation.get("variables") or []):
            compact_variables.append(
                {
                    "symbol": cls._normalize_text(item.get("symbol", "")),
                    "name": cls._normalize_text(item.get("name", "")),
                    "domain": cls._normalize_text(item.get("domain", "")),
                    "description": cls._normalize_text(item.get("description", "")),
                }
            )

        compact_constraints = []
        for item in (math_formulation.get("constraints") or []):
            compact_constraints.append(
                {
                    "formula_latex": cls._normalize_text(item.get("formula_latex", "")),
                    "description": cls._normalize_text(item.get("description", "")),
                    "type": cls._normalize_text(item.get("type", "")),
                }
            )

        compact_formulas = []
        for item in (math_formulation.get("key_formulas") or []):
            compact_formulas.append(
                {
                    "name": cls._normalize_text(item.get("name", "")),
                    "formula_latex": cls._normalize_text(item.get("formula_latex", "")),
                    "description": cls._normalize_text(item.get("description", "")),
                }
            )

        return {
            "scenario_spec": {
                "signal_type": cls._normalize_text(scenario_spec.get("signal_type", "unknown")),
                "core_parameters": dict(scenario_spec.get("core_parameters") or {}),
                "snr_range_db": scenario_spec.get("snr_range_db") or [],
                "test_scenarios": compact_scenarios,
                "data_contract": {
                    "inputs": list((scenario_spec.get("data_contract") or {}).get("inputs") or []),
                    "expected_outputs": list((scenario_spec.get("data_contract") or {}).get("expected_outputs") or []),
                },
                "generation_notes": cls._normalize_text(scenario_spec.get("generation_notes", "")),
            },
            "system_model_doc": cls._normalize_text(formalization.get("system_model_doc", "")),
            "math_formulation": {
                "problem_type": cls._normalize_text(math_formulation.get("problem_type", "unknown")),
                "objective": {
                    "type": cls._normalize_text((math_formulation.get("objective") or {}).get("type", "unknown")),
                    "description": cls._normalize_text((math_formulation.get("objective") or {}).get("description", "")),
                    "formula_latex": cls._normalize_text((math_formulation.get("objective") or {}).get("formula_latex", "")),
                },
                "variables": compact_variables,
                "constraints": compact_constraints,
                "key_formulas": compact_formulas,
                "assumptions": [
                    cls._normalize_text(item)
                    for item in (math_formulation.get("assumptions") or [])
                ],
                "model_properties": {
                    "convexity": cls._normalize_text((math_formulation.get("model_properties") or {}).get("convexity", "unknown")),
                    "closed_form": bool((math_formulation.get("model_properties") or {}).get("closed_form", False)),
                    "iterative_required": bool((math_formulation.get("model_properties") or {}).get("iterative_required", True)),
                    "special_structure": cls._normalize_text((math_formulation.get("model_properties") or {}).get("special_structure", "")),
                },
                "formulation_markdown": cls._normalize_text(math_formulation.get("formulation_markdown", "")),
            },
            "formalization_summary": {
                "design_implications": [
                    cls._normalize_text(item)
                    for item in (summary.get("design_implications") or [])
                ],
                "evaluation_focus": [
                    cls._normalize_text(item)
                    for item in (summary.get("evaluation_focus") or [])
                ],
                "implementation_risks": [
                    cls._normalize_text(item)
                    for item in (summary.get("implementation_risks") or [])
                ],
            },
            "algorithm_design": cls._compact_algorithm_design(formalization.get("algorithm_design") or {}),
        }

    @classmethod
    def _compact_algorithm_design(cls, algo_design: dict) -> dict:
        """Compact and normalize the algorithm_design section."""
        proposed = algo_design.get("proposed_algorithm") or {}
        compact_proposed = {
            "name": cls._normalize_text(proposed.get("name", "unknown")),
            "type": cls._normalize_text(proposed.get("type", "unknown")),
            "summary": cls._normalize_text(proposed.get("summary", "")),
        }

        compact_steps = []
        for item in (algo_design.get("algorithm_steps") or []):
            if not isinstance(item, dict):
                continue
            compact_steps.append({
                "step": item.get("step", len(compact_steps) + 1),
                "name": cls._normalize_text(item.get("name", "")),
                "description": cls._normalize_text(item.get("description", "")),
                "formula_latex": cls._normalize_text(item.get("formula_latex", "")),
                "inputs": list(item.get("inputs") or []),
                "outputs": list(item.get("outputs") or []),
                "numpy_hint": cls._normalize_text(item.get("numpy_hint", "")),
            })

        compact_baselines = []
        for item in (algo_design.get("baseline_algorithms") or []):
            if not isinstance(item, dict):
                continue
            compact_baselines.append({
                "name": cls._normalize_text(item.get("name", "")),
                "summary": cls._normalize_text(item.get("summary", "")),
                "key_formula_latex": cls._normalize_text(item.get("key_formula_latex", "")),
                "numpy_hint": cls._normalize_text(item.get("numpy_hint", "")),
            })

        convergence = algo_design.get("convergence") or {}
        compact_convergence = {
            "criterion": cls._normalize_text(convergence.get("criterion", "")),
            "typical_iterations": convergence.get("typical_iterations"),
            "formula_latex": cls._normalize_text(convergence.get("formula_latex", "")),
        }

        complexity = algo_design.get("complexity") or {}
        compact_complexity = {
            "per_iteration": cls._normalize_text(complexity.get("per_iteration", "")),
            "dominant_operation": cls._normalize_text(complexity.get("dominant_operation", "")),
        }

        return {
            "proposed_algorithm": compact_proposed,
            "algorithm_steps": compact_steps,
            "baseline_algorithms": compact_baselines,
            "convergence": compact_convergence,
            "complexity": compact_complexity,
        }

    @staticmethod
    def _repair_json(text: str) -> str:
        """Fix common LLM JSON error: unquoted LaTeX formula values.

        LLMs sometimes emit:  "formula_latex": \\\\mathbf{x} \\\\sim ..., "next": ...
        instead of:           "formula_latex": "\\\\mathbf{x} \\\\sim ...", "next": ...

        Only bare values that begin with ``\\\\`` (JSON-escaped LaTeX backslash) are
        targeted, so valid JSON primitives (strings, numbers, booleans, objects,
        arrays) are never touched.  The terminator is ``, "next_key"`` so that ``}``
        characters inside LaTeX groups (e.g. ``\\\\mathbf{n}``) are not confused with
        the JSON object closing brace.
        """

        def _quote_value(m: re.Match) -> str:
            key = m.group(1)
            val = m.group(2).rstrip()
            val_escaped = val.replace('"', '\\"')
            return f'"{key}": "{val_escaped}"'

        # Terminator: only ", "next_key" (a JSON comma + quoted-key sequence).
        # This avoids matching } inside LaTeX groups like \mathbf{n}.
        pattern = (
            r'"([a-zA-Z_][a-zA-Z0-9_]*)"'   # "key"
            r':\s*'
            r'(\\\\.*?)'                      # bare value — must start with \\
            r'(?=\s*,\s*"[a-zA-Z_])'         # end at , "next_key" only
        )
        return re.sub(pattern, _quote_value, text, flags=re.DOTALL)

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

        # Last resort: attempt JSON repair for unquoted string values (common with LaTeX)
        try:
            repaired = ModelFormalizerAgent._repair_json(stripped)
            parsed = json.loads(repaired)
            if isinstance(parsed, dict):
                logger.debug("[S3] JSON parsed after _repair_json fix")
                return parsed
        except json.JSONDecodeError:
            pass

        return None

    @staticmethod
    def _parse_response(response: str) -> dict:
        parsed = ModelFormalizerAgent._extract_json_dict(response)
        if isinstance(parsed, dict):
            return parsed

        logger.warning(
            "[S3] JSON extraction failed — falling back to empty formalization. "
            "Raw response head: %s",
            repr(response[:400]),
        )
        return {
            "scenario_spec": {"raw_response": response},
            "system_model_doc": response,
            "math_formulation": {
                "problem_type": "unknown",
                "objective": {"type": "unknown", "description": response, "formula_latex": ""},
                "variables": [],
                "constraints": [],
                "key_formulas": [],
                "assumptions": [],
                "model_properties": {
                    "convexity": "unknown",
                    "closed_form": False,
                    "iterative_required": True,
                    "special_structure": "",
                },
                "formulation_markdown": response,
            },
            "algorithm_design": {
                "proposed_algorithm": {"name": "unknown", "type": "unknown", "summary": ""},
                "algorithm_steps": [],
                "baseline_algorithms": [],
                "convergence": {"criterion": "", "typical_iterations": None, "formula_latex": ""},
                "complexity": {"per_iteration": "", "dominant_operation": ""},
            },
            "formalization_summary": {
                "design_implications": [],
                "evaluation_focus": [],
                "implementation_risks": ["Formalization parse fallback triggered"],
            },
        }