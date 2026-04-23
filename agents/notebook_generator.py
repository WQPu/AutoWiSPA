"""Notebook-first generator for the simplified AutoWiSPA pipeline."""

from __future__ import annotations

import ast
import json
import logging
import re
from pathlib import Path
from typing import Optional

from utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

SECTION_RE = re.compile(
    r"^#\s*={5,}\s*(MARKDOWN|CODE):\s*(.+?)\s*={5,}\s*$",
    re.MULTILINE,
)

CORE_REQUIRED_ROLES = [
    "title",
    "problem_setup",
    "modeling_summary",
    "imports_setup",
    "data_generation",
    "algorithm_core",
    "evaluation_logic",
    "execution",
    "plotting",
    "result_notes",
]

MARKDOWN_ROLES = {
    "title",
    "problem_setup",
    "modeling_summary",
    "result_notes",
}

CODE_ROLES = {
    "imports_setup",
    "data_generation",
    "algorithm_core",
    "evaluation_logic",
    "execution",
    "plotting",
}


NOTEBOOK_SYSTEM_PROMPT = r"""You are a senior wireless signal processing researcher building a single executable Jupyter notebook.

Return notebook content using only these section markers:

# ========== MARKDOWN: <role> ==========
<markdown body>

# ========== CODE: <role> ==========
<python code>

═══════════════════════════════════════════════
PART A — STRUCTURE AND FORMAT
═══════════════════════════════════════════════
1. All implementation must live inside notebook cells. Keep everything self-contained — no external modules.
2. Use only one coherent solution path matching the provided solution plan.
3. Required roles (in order): title, problem_setup, modeling_summary, imports_setup, data_generation,
   algorithm_core, evaluation_logic, execution, plotting, result_notes.
4. Between each pair of consecutive code cells, insert a brief narrative markdown cell (role: <prev_role>_narrative)
   that: (a) states what the next block computes, (b) lists key inputs/outputs, (c) shows key inline equations $...$.
5. The execution cell must assign a dict named RESULTS with keys: algorithm, elapsed_sec, performance_data, report_assets.
6. performance_data must be JSON-serializable. Preferred nested format:
   {"metric_curve": {"x": [...], "proposed": [...], "baseline_name": [...], "x_label": "SNR (dB)"}}
7. report_assets must contain: problem_summary, solution_summary, evaluation_summary, tables (list), figures (list).
8. Avoid: input(), plt.show(), bare except, eval(), exec(), subprocess, os.system.
9. Use numpy/scipy/matplotlib. Use scipy.linalg, scipy.signal, scipy.optimize for standard algorithms.
10. Return full notebook content, not prose about the notebook.
11. Use KaTeX-ready math: inline $...$, block $$...$$ on separate lines. No \(...\) or \[...\].

═══════════════════════════════════════════════
PART B — EVALUATION SWEEP (MANDATORY)
═══════════════════════════════════════════════
12. evaluation_logic MUST define run_evaluation(eval_config) that:
    a. Reads the operating-point list from eval_config (e.g. "snr_points", "variable_points").
    b. Loops over EVERY operating point, computing ALL methods independently at each point.
    c. Returns performance_data with per-point arrays.
    FORBIDDEN: computing a metric once and appending it N times to fill the array.
    FORBIDDEN: using a single dataset without re-generating data at each operating point.
13. data_generation MUST accept the operating condition as a parameter (e.g. snr_db, num_snapshots).
14. Set np.random.seed(42) at the top of execution cell. Define all hyperparameters as named variables.

═══════════════════════════════════════════════
PART C — BASELINE IMPLEMENTATION (MANDATORY)
═══════════════════════════════════════════════
15. Every baseline listed in the Implementation Contract MUST be:
    a. Fully implemented in algorithm_core (never just referenced by name or left as a stub).
    b. Called inside the SAME sweep loop as the proposed method.
    c. Exported as its own named curve in performance_data (e.g. "music", "esprit", "ls").
    FAILURE TO IMPLEMENT ANY BASELINE = notebook review FAILURE.

═══════════════════════════════════════════════
PART D — ALGORITHM CORRECTNESS PRINCIPLES
═══════════════════════════════════════════════
Apply ALL of the following principles to every algorithm you implement, including baselines.

[D1] Noise and SNR
- Complex AWGN with total power σ²: noise = (σ/√2) * (randn(N) + 1j*randn(N))
  NOT: noise = σ * (randn(N) + 1j*randn(N))  ← 2× power error
- Recompute σ from signal power at EACH operating point inside the sweep loop.
- Verify: as SNR increases, performance must improve. If it does not, noise generation is wrong.

[D2] Subspace Methods (MUSIC, ESPRIT, Root-MUSIC, SOMP, etc.)
- Use numpy.linalg.eigh (NOT eig) for Hermitian matrices — returns real eigenvalues in ASCENDING order.
- Signal subspace   = eigvecs[:, -num_sources:]       ← LAST num_sources columns
- Noise subspace    = eigvecs[:, :-num_sources]        ← FIRST (N - num_sources) columns
  WRONG: eigvecs[:, :-num_rx]   → empty for N×N matrix, all MUSIC spectra become identical
  WRONG: eigvecs[:, :-1]        → wrong count
- Spatial smoothing subarray_size must satisfy: num_sources+1 ≤ subarray_size ≤ num_rx - num_sources
- After computing the noise subspace, verify shape: assert E_n.shape == (num_rx, num_rx - num_sources)
- MUSIC spectrum denominator: 1 / real(a^H @ E_n @ E_n^H @ a). If denominator ≈ 0 for all angles → subspace bug.

[D3] Iterative / Optimization Algorithms (ADMM, gradient descent, EM, MM, etc.)
- MUST loop until convergence criterion OR max_iter, whichever comes first.
- Convergence check: norm(x_new - x_old) / (norm(x_old) + 1e-12) < tol
- Regularization parameters (λ, μ, ρ) must scale with the problem: e.g. λ = 0.1 * max(|A^T b|)
- Track and export objective values per iteration for plotting (convergence curve).

[D4] Probability and Statistics
- BER/SER: num_errors / total_bits. Ensure ≥100 errors are observed (increase trials if BER < 1e-4).
- Sample covariance requires num_snapshots >> num_sources. If num_snapshots < num_rx, use diagonal loading.
- Always average metrics (RMSE, BER) over multiple independent Monte Carlo trials.

[D5] Array Signal Processing
- Steering vector: a(θ) = exp(-j·2π·d/λ·[0,1,...,N-1]·sin(θ)), θ in radians.
- Verify steering matrix shape: (num_rx, num_sources) before y = A @ s + n.
- For coherent sources, rank of signal covariance drops — apply spatial smoothing before subspace methods.

[D6] Beamforming
- Apply beamforming weights as: output = w.conj().T @ y  (NOT w.T — complex conjugate required).
- Normalize weights: ||w|| = 1 or w^H a(θ₀) = 1 for consistent power comparison.
- Verify null placement: |w^H a(θ_null)| ≈ 0.

[D7] Detection and Hypothesis Testing
- Threshold for CFAR/energy detection MUST be recomputed at each noise level from current σ.
  WRONG: using a fixed threshold η across all SNR points.
- Pd and Pfa must be estimated from Monte Carlo trials, not assumed analytically.

[D8] Channel and Signal Models
- OFDM: add cyclic prefix BEFORE channel convolution, remove AFTER. Missing CP removal → ISI.
- Rayleigh fading: normalize channel taps so E[||h||²] = 1 to keep SNR definition consistent.
- Matched filter: verify the sample offset is correct — off-by-one errors degrade SNR.

[D9] Curve Sanity Check (MANDATORY — add this code before writing to performance_data)
For EVERY method's result array, add these guards inside the sweep:
    assert len(result_array) == len(operating_points), f"{method_name}: result length mismatch"
    if len(set(round(v, 8) for v in result_array)) == 1:
        print(f"WARNING: {method_name} produced constant results across all operating points — likely implementation bug.")
Metric physical range checks:
    RMSE (degrees): 0 to 180  |  BER/SER: 0 to 0.5  |  Capacity: > 0  |  Pd/Pfa: 0 to 1

[D10] Variable Naming and Reproducibility
- Never reuse metric variable names between methods (e.g. use rmse_proposed, rmse_music — NOT rmse for both).
- Define ALL hyperparameters (SNR range, num_trials, etc.) as named constants at the top of evaluation_logic.
- np.random.seed(42) at execution cell top.

═══════════════════════════════════════════════
PART E — FORMULA-DRIVEN IMPLEMENTATION
═══════════════════════════════════════════════
16. The Algorithm Design block in the user prompt contains step-by-step formulas.
    algorithm_core MUST implement each step with a comment citing the formula name and LaTeX.
    Use the same variable naming convention as the formulas (R_y, A_theta, E_n, etc.).
17. Baseline algorithms must follow their key_formula_latex exactly.
18. modeling_summary markdown cell MUST list all key formulas using $...$ notation.

═══════════════════════════════════════════════
PART F — RICH EVALUATION AND OUTPUT
═══════════════════════════════════════════════
19. Beyond the primary sweep, evaluate sensitivity to at least ONE secondary factor (snapshots, sources, array size).
    Store in performance_data: {"snapshot_sensitivity": {"x": [...], "proposed": [...], ...}}
20. plotting cell MUST produce ≥3 figures:
    Fig 1: primary metric vs operating variable (all methods).
    Fig 2: sensitivity analysis (secondary factor).
    Fig 3: algorithm-specific visualization (spectrum, beampattern, convergence, constellation).
    Save each with fig.savefig('filename.png', dpi=150, bbox_inches='tight'). Add to report_assets figures.
21. result_notes MUST include a Markdown comparison table across all methods and key operating points.
22. plotting cell: use semilogy for lower-is-better metrics (BER, NMSE, RMSE, SER, PFA); linear for higher-is-better.
"""


REPAIR_SYSTEM_PROMPT = r"""You repair AutoWiSPA notebook cells.

Return the FULL repaired notebook using the same section marker format:
# ========== MARKDOWN: <role> ==========
# ========== CODE: <role> ==========

Requirements:
1. Repair root causes, not symptoms. Preserve roles, baselines, metric names, and result keys.
2. The execution cell must still assign RESULTS with keys: algorithm, elapsed_sec, performance_data, report_assets.
3. Keep all code notebook-local.
4. Return the entire repaired notebook.

───────────────────────────────────────────────
DIAGNOSIS CHECKLIST — check ALL before repairing
───────────────────────────────────────────────
[R1] CONSTANT / FLAT-LINE RESULTS (any method):
  A method that returns identical values across ALL operating points is broken. Diagnose by type:
  - Subspace (MUSIC, ESPRIT): noise subspace sliced with wrong index.
      WRONG:   eigvecs[:, :-num_rx]       → empty slice for N×N matrix
      WRONG:   eigvecs[:, :-1]            → wrong dimension
      CORRECT: eigvecs[:, :-num_sources]  → first (N - num_sources) columns (eigh returns ascending order)
    Add: assert E_n.shape == (num_rx, num_rx - num_sources), "subspace shape wrong"
  - Iterative methods: result computed outside the sweep loop, or max_iter=0.
  - Detection methods: threshold computed once at a fixed SNR and reused for all SNR points.
  - Any method: check for the pattern `result = compute_once()` followed by `result_list = [result] * N`.
  Fix: add `if len(set(round(v,8) for v in vals)) == 1: print(f"WARNING: {name} constant")` after each sweep.

[R2] NOISE / SNR BUG:
  Performance not improving with SNR → noise generation wrong.
  CORRECT complex AWGN (total power σ²): noise = (σ/√2) * (randn(N) + 1j*randn(N))
  WRONG:                                  noise = σ * (randn(N) + 1j*randn(N))   ← 2× power, 3 dB offset
  Also: σ must be recomputed from signal_power at EACH SNR point inside the sweep loop.

[R3] MISSING SWEEP:
  Evaluation not looping over operating points. Add a loop over eval_config operating-point list.
  Each iteration must re-generate data at the current operating condition, not reuse a single dataset.

[R4] MISSING / STUB BASELINES:
  Required baselines not implemented or returning zeros/NaN. Implement each baseline fully inside the sweep loop.
  Each must export its own named curve (e.g. performance_data["metric"]["music"] = rmse_music_list).

[R5] CONVERGENCE BUG (iterative algorithms):
  Algorithm runs to max_iter every time with no progress check.
  Add: if np.linalg.norm(x_new - x_old) / (np.linalg.norm(x_old) + 1e-12) < tol: break
  Regularization parameters must scale with data: λ = 0.1 * np.max(np.abs(A.T @ b))

[R6] VARIABLE NAME COLLISION:
  Metric variable (e.g. `rmse`) reused between methods inside the loop.
  Rename to: rmse_proposed, rmse_music, rmse_esprit — never a shared name.

[R7] PHYSICAL RANGE VIOLATION:
  After the sweep, add guards before writing to performance_data:
  - RMSE degrees: 0 to 180  |  BER: 0 to 0.5  |  Capacity: > 0  |  Pd/Pfa: 0 to 1
  If a value is out of range, print a warning and clip or flag the result.

[R8] MATRIX DIMENSION / SHAPE MISMATCH:
  Verify: steering matrix shape = (num_rx, num_sources); covariance shape = (num_rx, num_rx).
  For spatial smoothing: assert subarray_size >= num_sources + 1.
  For ESPRIT: rotational invariance matrices must come from signal subspace rows.
"""


class NotebookGenerator:
    """Generate and repair a single runnable notebook artifact."""

    def __init__(self, llm: Optional[LLMClient] = None, repair_llm: Optional[LLMClient] = None):
        self.llm = llm or LLMClient()
        self.repair_llm = repair_llm or self.llm

    def _max_tokens(self, client: LLMClient, node_name: str, fallback: Optional[int] = None) -> Optional[int]:
        resolver = getattr(client, "get_max_tokens", None)
        if callable(resolver):
            value = resolver(node_name, fallback)
            return value if isinstance(value, int) or value is None else fallback
        return fallback

    def generate(
        self,
        task_spec: dict,
        retrieved_knowledge: Optional[dict] = None,
        formalization: Optional[dict] = None,
        solution_plan: Optional[dict] = None,
    ) -> dict:
        prompt = self._build_generation_prompt(
            task_spec=task_spec or {},
            retrieved_knowledge=retrieved_knowledge or {},
            formalization=formalization or {},
            solution_plan=solution_plan or {},
        )
        response = self.llm.chat(
            [
                {"role": "system", "content": NOTEBOOK_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=self._max_tokens(self.llm, "notebook_generation"),
            node_name="notebook_generation",
        )
        return self._finalize_notebook(
            self._response_to_notebook(response, task_spec or {}, solution_plan or {}, formalization or {}),
            task_spec or {},
            solution_plan or {},
            formalization or {},
            allow_repair=True,
        )

    def repair(
        self,
        notebook: dict,
        task_spec: dict,
        solution_plan: dict,
        error_message: str,
        repair_context: Optional[dict] = None,
        formalization: Optional[dict] = None,
    ) -> dict:
        prompt = self._build_repair_prompt(
            notebook,
            task_spec or {},
            solution_plan or {},
            error_message,
            repair_context or {},
            formalization or {},
        )
        response = self.repair_llm.chat(
            [
                {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=self._max_tokens(self.repair_llm, "notebook_repair"),
            node_name="notebook_repair",
        )
        candidate = self._response_to_notebook(response, task_spec or {}, solution_plan or {}, formalization or {})
        return self._finalize_notebook(candidate or notebook, task_spec or {}, solution_plan or {}, formalization or {}, allow_repair=False)

    def summarize_notebook(self, notebook: dict) -> dict:
        cells = notebook.get("cells") or []
        roles = []
        code_roles = []
        markdown_roles = []
        for cell in cells:
            role = (cell.get("metadata") or {}).get("autowisp_role", "unlabeled")
            roles.append(role)
            if cell.get("cell_type") == "code":
                code_roles.append(role)
            else:
                markdown_roles.append(role)
        return {
            "cells": len(cells),
            "code_cells": len(code_roles),
            "markdown_cells": len(markdown_roles),
            "roles": roles,
            "code_roles": code_roles,
            "markdown_roles": markdown_roles,
        }

    @staticmethod
    def extract_code_cells(notebook: dict) -> list[dict]:
        cells = []
        for index, cell in enumerate(notebook.get("cells") or [], start=1):
            if cell.get("cell_type") != "code":
                continue
            cells.append(
                {
                    "index": index,
                    "role": (cell.get("metadata") or {}).get("autowisp_role", f"code_{index}"),
                    "source": "".join(cell.get("source") or []),
                }
            )
        return cells

    @staticmethod
    def save_notebook(notebook: dict, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(notebook, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_generation_prompt(
        self,
        task_spec: dict,
        retrieved_knowledge: dict,
        formalization: dict,
        solution_plan: dict,
    ) -> str:
        knowledge_summary = self._compact_knowledge(retrieved_knowledge)
        execution_contract = self._build_execution_contract(task_spec, solution_plan)

        # Explicit baseline obligation block — makes the constraint impossible to overlook
        baselines = [b for b in (execution_contract.get("baseline_methods") or []) if b]
        baseline_block = ""
        if baselines:
            baseline_block = (
                "## Baseline Implementation Obligations\n"
                "The following baselines MUST each be fully implemented (not just referenced by name) "
                "and produce an independent per-point curve in `performance_data`:\n"
                + "\n".join(f"- `{b}`" for b in baselines)
                + "\n\n"
            )

        # Explicit algorithm steps block — from formalization's algorithm_design
        algo_design = formalization.get("algorithm_design") or {}
        algo_steps = algo_design.get("algorithm_steps") or []
        algo_baselines = algo_design.get("baseline_algorithms") or []

        # Build detailed algorithm design block with formulas
        algo_design_block = ""
        if algo_steps:
            proposed = algo_design.get("proposed_algorithm") or {}
            lines = [
                f"## Algorithm Design: {proposed.get('name', 'Proposed Method')}",
                f"Type: {proposed.get('type', 'unknown')} — {proposed.get('summary', '')}",
                "",
                "### Step-by-step implementation (each step must appear in algorithm_core):",
            ]
            for step in algo_steps:
                s = step if isinstance(step, dict) else {}
                lines.append(
                    f"**Step {s.get('step', '?')}: {s.get('name', '')}**\n"
                    f"  - Description: {s.get('description', '')}\n"
                    f"  - Formula: ${s.get('formula_latex', '')}$\n"
                    f"  - Inputs: {', '.join(s.get('inputs') or [])}\n"
                    f"  - Outputs: {', '.join(s.get('outputs') or [])}\n"
                    f"  - numpy/scipy hint: `{s.get('numpy_hint', '')}`"
                )
            convergence = algo_design.get("convergence") or {}
            if convergence.get("criterion"):
                lines.append(f"\n### Convergence: {convergence['criterion']}")
                if convergence.get("formula_latex"):
                    lines.append(f"  ${convergence['formula_latex']}$")
            complexity = algo_design.get("complexity") or {}
            if complexity.get("per_iteration"):
                lines.append(f"\n### Complexity: {complexity['per_iteration']} — dominant: {complexity.get('dominant_operation', '')}")
            algo_design_block = "\n".join(lines) + "\n\n"

        # Baseline algorithms from formalization
        if algo_baselines:
            baseline_formula_lines = ["## Baseline Algorithm Formulas (must be fully implemented):"]
            for bl in algo_baselines:
                if not isinstance(bl, dict):
                    continue
                baseline_formula_lines.append(
                    f"- **{bl.get('name', '')}**: {bl.get('summary', '')}\n"
                    f"  Formula: ${bl.get('key_formula_latex', '')}$\n"
                    f"  numpy/scipy hint: `{bl.get('numpy_hint', '')}`"
                )
            algo_design_block += "\n".join(baseline_formula_lines) + "\n\n"

        # Fallback: use execution_contract algorithm_steps if no formalization steps
        alg_steps = [s for s in (execution_contract.get("algorithm_steps") or []) if s]
        steps_block = ""
        if not algo_steps and alg_steps:
            step_lines = []
            for i, s in enumerate(alg_steps):
                if isinstance(s, dict):
                    formula = s.get("formula_latex", "")
                    label = f"{i + 1}. {s.get('name', str(s))}"
                    if formula:
                        label += f" — ${formula}$"
                    step_lines.append(label)
                else:
                    step_lines.append(f"{i + 1}. {s}")
            steps_block = (
                "## Required Algorithm Steps (implement in algorithm_core)\n"
                + "\n".join(step_lines)
                + "\n\n"
            )

        # Extract sensitivity factors from solution_plan
        sensitivity_factors = (solution_plan.get("evaluation_plan") or {}).get("sensitivity_factors") or []
        sensitivity_block = ""
        if sensitivity_factors:
            sf_lines = ["## Sensitivity Factors (must evaluate at least one beyond primary sweep):"]
            for sf in sensitivity_factors:
                if not isinstance(sf, dict):
                    continue
                sf_lines.append(
                    f"- **{sf.get('factor', '')}**: test values = {sf.get('values', [])}\n"
                    f"  Reason: {sf.get('description', '')}"
                )
            sensitivity_block = "\n".join(sf_lines) + "\n\n"

        # Extract plot plan from solution_plan
        plot_plan = (solution_plan.get("evaluation_plan") or {}).get("plots") or []
        plot_block = ""
        if plot_plan:
            pl_lines = ["## Required Plots (generate ALL of these):"]
            for i, pl in enumerate(plot_plan, 1):
                if not isinstance(pl, dict):
                    continue
                pl_lines.append(
                    f"{i}. **{pl.get('title', f'Plot {i}')}**: "
                    f"x={pl.get('x_axis', '?')}, y={pl.get('y_axis', '?')}, "
                    f"curves={pl.get('curves', [])}, scale={pl.get('scale', 'linear')}\n"
                    f"   Purpose: {pl.get('description', '')}"
                )
            plot_block = "\n".join(pl_lines) + "\n\n"

        return (
            f"## Task Specification\n```json\n{json.dumps(task_spec, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Formalization\n```json\n{json.dumps(formalization, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Implementation Contract\n```json\n{json.dumps(execution_contract, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Knowledge Summary\n{knowledge_summary}\n\n"
            + algo_design_block
            + baseline_block
            + steps_block
            + sensitivity_block
            + plot_block
            + "## Notebook Writing Policy\n"
            "Follow the system prompt rules exactly. Key reminders:\n"
            "- Treat the implementation contract as binding: roles, metric names, baselines, result keys.\n"
            "- Keep everything executable in one notebook. No external files.\n"
            "- SWEEP: evaluation function MUST loop over every operating point, re-generating data each time.\n"
            "- BASELINES: every baseline in the contract must be fully implemented and produce its own curve.\n"
            "- CORRECTNESS [D2]: noise subspace = eigvecs[:, :-num_sources] (eigh ascending order). "
            "Verify shape before computing MUSIC/ESPRIT. Add assert E_n.shape == (num_rx, num_rx - num_sources).\n"
            "- CORRECTNESS [D1]: complex AWGN = (σ/√2)*(randn+j*randn). Recompute σ at each SNR point.\n"
            "- CORRECTNESS [D9]: add constant-result guards for every method before writing to performance_data.\n"
            "- FORMULA: every step in Algorithm Design must appear in algorithm_core with a formula-citing comment.\n"
            "- SENSITIVITY: evaluate at least ONE secondary factor beyond the primary sweep.\n"
            "- PLOTS: ≥3 figures (primary comparison + sensitivity + algorithm-specific). Save each with savefig.\n"
            "- RESULT TABLE: result_notes must include a Markdown comparison table.\n\n"
            "Generate the full notebook now."
        )

    def _build_repair_prompt(
        self,
        notebook: dict,
        task_spec: dict,
        solution_plan: dict,
        error_message: str,
        repair_context: dict,
        formalization: Optional[dict] = None,
    ) -> str:
        execution_contract = self._build_execution_contract(task_spec, solution_plan)
        repair_context = self._normalize_repair_context(repair_context)

        # Inject algorithm design block from formalization so the repair LLM can see exact formulas
        algo_repair_block = ""
        algo_design = (formalization or {}).get("algorithm_design") or {}
        algo_steps = algo_design.get("algorithm_steps") or []
        if algo_steps:
            proposed = algo_design.get("proposed_algorithm") or {}
            lines = [
                f"## Algorithm Design: {proposed.get('name', 'Proposed Algorithm')}",
                "### Step formulas (repair must preserve these):",
            ]
            for s in algo_steps:
                if not isinstance(s, dict):
                    continue
                lines.append(
                    f"Step {s.get('step', '?')}: **{s.get('name', '')}** — "
                    f"${s.get('formula_latex', '')}$"
                )
            for bl in (algo_design.get("baseline_algorithms") or []):
                if not isinstance(bl, dict):
                    continue
                lines.append(
                    f"Baseline **{bl.get('name', '')}**: "
                    f"${bl.get('key_formula_latex', '')}$"
                )
            algo_repair_block = "\n".join(lines) + "\n\n"

        return (
            f"## Task Specification\n```json\n{json.dumps(task_spec, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Solution Plan\n```json\n{json.dumps(solution_plan, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Implementation Contract\n```json\n{json.dumps(execution_contract, ensure_ascii=False, indent=2)}\n```\n\n"
            + algo_repair_block
            + f"## Repair Context\n```json\n{json.dumps(repair_context, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Current Notebook\n{self._serialize_notebook_for_prompt(notebook)}\n\n"
            f"## Error Feedback\n{error_message}\n\n"
            "Repair the notebook and return the full notebook content. Keep the implementation contract intact and fix the root causes behind the reported failures."
        )

    def _response_to_notebook(self, response: str, task_spec: dict, solution_plan: dict, formalization: dict) -> dict:
        sections = self._parse_sections(response)
        if not sections:
            logger.warning("[NotebookGenerator] Failed to parse notebook sections, using fallback notebook")
            return self._build_fallback_notebook(task_spec, solution_plan, formalization)
        return self._assemble_notebook(sections, task_spec, solution_plan)

    def _parse_sections(self, response: str) -> list[tuple[str, str, str]]:
        response = self._strip_outer_fence(response)
        matches = list(SECTION_RE.finditer(response))
        if not matches:
            return []
        sections: list[tuple[str, str, str]] = []
        for index, match in enumerate(matches):
            kind = match.group(1).lower()
            role = self._normalize_role(match.group(2).strip())
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(response)
            content = response[start:end].strip()
            if not content:
                continue
            if kind == "code":
                content = self._strip_code_fence(content)
            sections.append((kind, role, content))
        return sections

    def _assemble_notebook(self, sections: list[tuple[str, str, str]], task_spec: dict, solution_plan: dict) -> dict:
        execution_contract = self._build_execution_contract(task_spec, solution_plan)
        cells = []
        for kind, role, content in sections:
            kind = self._expected_cell_type(role) or kind
            if kind == "markdown":
                cells.append(self._make_markdown_cell(self._normalize_math_markdown(content), role))
            else:
                cells.append(self._make_code_cell(content, role))
        return {
            "metadata": {
                "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                "language_info": {"name": "python", "version": "3.10"},
                "autowisp": {
                    "task_category": task_spec.get("task_category", "wireless_signal_processing"),
                    "architecture_name": ((solution_plan.get("architecture") or {}).get("name") or "Notebook Solution"),
                    "notebook_roles": [role for _, role, _ in sections],
                    "execution_contract": execution_contract,
                },
            },
            "nbformat": 4,
            "nbformat_minor": 5,
            "cells": cells,
        }

    def _finalize_notebook(
        self,
        notebook: dict,
        task_spec: dict,
        solution_plan: dict,
        formalization: dict,
        allow_repair: bool,
    ) -> dict:
        notebook = self._normalize_role_cell_types(notebook)
        notebook = self._ensure_required_roles(notebook, task_spec, solution_plan, formalization)
        notebook = self._ensure_results_contract(notebook, task_spec, solution_plan)
        notebook.setdefault("metadata", {}).setdefault("autowisp", {})["execution_contract"] = self._build_execution_contract(
            task_spec,
            solution_plan,
        )
        notebook = self._sanitize_code_cells(notebook)
        syntax_errors = self._find_syntax_errors(notebook)
        if syntax_errors and allow_repair:
            notebook = self._repair_syntax_errors(notebook, syntax_errors, task_spec, solution_plan)
            notebook = self._normalize_role_cell_types(notebook)
            notebook = self._ensure_results_contract(notebook, task_spec, solution_plan)
            notebook = self._sanitize_code_cells(notebook)
        return notebook

    def _normalize_role_cell_types(self, notebook: dict) -> dict:
        cells = list(notebook.get("cells") or [])
        changed = False
        for cell in cells:
            role = (cell.get("metadata") or {}).get("autowisp_role", "")
            expected = self._expected_cell_type(role)
            if not expected or cell.get("cell_type") == expected:
                continue

            source = "".join(cell.get("source") or [])
            cell["cell_type"] = expected
            cell.setdefault("metadata", {})["autowisp_role"] = role
            if expected == "code":
                cell["source"] = self._strip_code_fence(source).splitlines(keepends=True)
                cell["execution_count"] = None
                cell["outputs"] = []
            else:
                cell["source"] = self._normalize_math_markdown(source).splitlines(keepends=True)
                cell.pop("execution_count", None)
                cell.pop("outputs", None)
            changed = True

        if changed:
            notebook["cells"] = cells
        return notebook

    def _sanitize_code_cells(self, notebook: dict) -> dict:
        cells = list(notebook.get("cells") or [])
        changed = False
        for cell in cells:
            if cell.get("cell_type") != "code":
                continue
            source = "".join(cell.get("source") or [])
            try:
                ast.parse(source)
                continue
            except SyntaxError:
                sanitized = self._comment_narrative_lines(source)
                if sanitized == source:
                    continue
                try:
                    ast.parse(sanitized)
                except SyntaxError:
                    continue
                cell["source"] = sanitized.splitlines(keepends=True)
                changed = True

        if changed:
            notebook["cells"] = cells
        return notebook

    @staticmethod
    def _comment_narrative_lines(source: str) -> str:
        sanitized_lines: list[str] = []
        python_prefixes = (
            "#",
            "def ",
            "class ",
            "import ",
            "from ",
            "for ",
            "while ",
            "if ",
            "elif ",
            "else:",
            "try:",
            "except",
            "finally:",
            "with ",
            "return ",
            "raise ",
            "assert ",
            "yield ",
            "pass",
            "break",
            "continue",
            "global ",
            "nonlocal ",
            "del ",
            "@",
        )

        for line in source.splitlines(keepends=True):
            stripped = line.strip()
            if not stripped:
                sanitized_lines.append(line)
                continue
            if stripped.startswith(python_prefixes):
                sanitized_lines.append(line)
                continue
            if any(token in stripped for token in ("=", "(", ")", "[", "]", "{", "}")):
                sanitized_lines.append(line)
                continue
            if stripped.startswith(("```", "-", "*")) or re.match(r"^\d+\.", stripped):
                sanitized_lines.append(f"# {stripped}\n")
                continue
            if re.match(r"^[A-Za-z][A-Za-z0-9_\-\s\.,:;>$\\]+$", stripped):
                sanitized_lines.append(f"# {stripped}\n")
                continue
            sanitized_lines.append(line)

        return "".join(sanitized_lines)

    def _ensure_results_contract(self, notebook: dict, task_spec: dict, solution_plan: dict) -> dict:
        cells = list(notebook.get("cells") or [])
        evaluation_index = self._find_role_index(cells, "evaluation_logic")
        execution_index = self._find_role_index(cells, "execution")
        if evaluation_index is None or execution_index is None:
            return notebook

        metric_name = self._primary_metric_name(task_spec, solution_plan)
        evaluation_cell = cells[evaluation_index]
        execution_cell = cells[execution_index]
        evaluation_source = "".join(evaluation_cell.get("source") or [])
        execution_source = "".join(execution_cell.get("source") or [])

        if "AUTO-WISP RESULTS HELPER" not in evaluation_source:
            evaluation_source = evaluation_source.rstrip() + "\n\n" + self._results_helper_code(metric_name) + "\n"
            evaluation_cell["source"] = evaluation_source.splitlines(keepends=True)

        if "AUTO-WISP EXECUTION CONTRACT" not in execution_source:
            execution_source = execution_source.rstrip() + "\n\n" + self._execution_contract_code(metric_name) + "\n"
            execution_cell["source"] = execution_source.splitlines(keepends=True)

        notebook["cells"] = cells
        return notebook

    @staticmethod
    def _find_role_index(cells: list[dict], role: str) -> Optional[int]:
        for index, cell in enumerate(cells):
            if (cell.get("metadata") or {}).get("autowisp_role") == role:
                return index
        return None

    @staticmethod
    def _results_helper_code(metric_name: str) -> str:
        metric_label = metric_name or "primary_metric"
        return (
            "# AUTO-WISP RESULTS HELPER\n"
            "def _autowisp_normalize_results(candidate):\n"
            "    if candidate is None:\n"
            "        candidate = {}\n"
            "    if not isinstance(candidate, dict):\n"
            "        candidate = {'performance_data': {'raw_results': candidate}}\n"
            "    performance_data = candidate.get('performance_data')\n"
            "    if not isinstance(performance_data, dict):\n"
            "        for key in ('metrics', 'results', 'evaluation_results', 'raw_results'):\n"
            "            value = candidate.get(key)\n"
            "            if isinstance(value, dict):\n"
            "                performance_data = value\n"
            "                break\n"
            "    if not isinstance(performance_data, dict):\n"
            "        performance_data = {'raw_results': performance_data if performance_data is not None else {}}\n"
            "    report_assets = candidate.get('report_assets')\n"
            "    if not isinstance(report_assets, dict):\n"
            "        report_assets = {}\n"
            "    report_assets.setdefault('problem_summary', 'Recovered from notebook auto-debug path.')\n"
            "    report_assets.setdefault('solution_summary', 'Execution contract was normalized to ensure RESULTS generation.')\n"
            f"    report_assets.setdefault('evaluation_summary', 'Primary metric exported as {metric_label}.')\n"
            "    performance_data = _autowisp_to_builtin(performance_data)\n"
            "    tables = report_assets.get('tables')\n"
            "    if not isinstance(tables, list) or not tables:\n"
            "        tables = _autowisp_build_tables(performance_data)\n"
            "    report_assets['tables'] = tables\n"
            "    figures = report_assets.get('figures') or report_assets.get('figures_metadata') or []\n"
            "    if not isinstance(figures, list):\n"
            "        figures = []\n"
            "    if not figures:\n"
            "        figures = _autowisp_build_figures(performance_data)\n"
            "    report_assets['figures'] = figures\n"
            "    report_assets['figures_metadata'] = figures\n"
            "    candidate['algorithm'] = candidate.get('algorithm') or 'Notebook Auto-Debug'\n"
            "    candidate['elapsed_sec'] = float(candidate.get('elapsed_sec') or 0.0)\n"
            "    candidate['performance_data'] = performance_data\n"
            "    candidate['report_assets'] = report_assets\n"
            "    return candidate\n\n"
            "def _autowisp_to_builtin(value):\n"
            "    if value is None or isinstance(value, (str, int, float, bool)):\n"
            "        return value\n"
            "    if isinstance(value, dict):\n"
            "        return {str(k): _autowisp_to_builtin(v) for k, v in value.items()}\n"
            "    if isinstance(value, (list, tuple, set)):\n"
            "        return [_autowisp_to_builtin(v) for v in value]\n"
            "    if hasattr(value, 'tolist'):\n"
            "        return _autowisp_to_builtin(value.tolist())\n"
            "    if hasattr(value, 'item'):\n"
            "        try:\n"
            "            return value.item()\n"
            "        except Exception:\n"
            "            pass\n"
            "    return str(value)\n\n"
            "def _autowisp_curve_specs(perf_data):\n"
            "    if not isinstance(perf_data, dict):\n"
            "        return []\n"
            "    _x_keys = ('x', 'variable_points', 'operating_points', 'snr', 'snr_points', 'snr_db')\n"
            "    top_x = None\n"
            "    for key in _x_keys:\n"
            "        value = perf_data.get(key)\n"
            "        if isinstance(value, list) and len(value) >= 2:\n"
            "            top_x = value\n"
            "            break\n"
            "    specs = []\n"
            "    for metric_name, payload in perf_data.items():\n"
            "        if not isinstance(payload, dict):\n"
            "            continue\n"
            "        x_values = None\n"
            "        for key in _x_keys:\n"
            "            value = payload.get(key)\n"
            "            if isinstance(value, list) and len(value) >= 2:\n"
            "                x_values = value\n"
            "                break\n"
            "        if x_values is None:\n"
            "            x_values = top_x\n"
            "        if not isinstance(x_values, list) or len(x_values) < 2:\n"
            "            continue\n"
            "        _skip_keys = set(_x_keys) | {'x_label', 'xlabel', 'ylabel', 'title'}\n"
            "        series = {}\n"
            "        for series_name, series_values in payload.items():\n"
            "            if series_name in _skip_keys:\n"
            "                continue\n"
            "            if isinstance(series_values, list) and len(series_values) == len(x_values):\n"
            "                series[str(series_name)] = series_values\n"
            "        if series:\n"
            "            specs.append({\n"
            "                'metric': str(metric_name),\n"
            "                'x': x_values,\n"
            "                'x_label': payload.get('x_label') or payload.get('xlabel') or 'Operating Point',\n"
            "                'series': series,\n"
            "            })\n"
            "    return specs\n\n"
            "def _autowisp_build_tables(perf_data):\n"
            "    tables = []\n"
            "    for spec in _autowisp_curve_specs(perf_data):\n"
            "        columns = [spec['x_label']] + [name.replace('_', ' ').title() for name in spec['series'].keys()]\n"
            "        rows = []\n"
            "        for idx, x_value in enumerate(spec['x']):\n"
            "            rows.append([x_value] + [values[idx] for values in spec['series'].values()])\n"
            "        tables.append({\n"
            "            'title': spec['metric'].replace('_', ' ').title(),\n"
            "            'columns': columns,\n"
            "            'rows': rows,\n"
            "        })\n"
            "    return tables\n\n"
            "def _autowisp_build_figures(perf_data):\n"
            "    figures = []\n"
            "    for spec in _autowisp_curve_specs(perf_data):\n"
            "        figures.append({\n"
            "            'title': spec['metric'].replace('_', ' ').title(),\n"
            "            'xlabel': spec['x_label'],\n"
            "            'ylabel': spec['metric'].replace('_', ' '),\n"
            "            'x': spec['x'],\n"
            "            'series': spec['series'],\n"
            "        })\n"
            "    return figures\n\n"
            "if 'run_experiment' not in globals():\n"
            "    def run_experiment(eval_config=None):\n"
            "        eval_config = dict(eval_config or globals().get('EVAL_CONFIG') or {})\n"
            "        existing_runner = globals().get('run_evaluation')\n"
            "        if callable(existing_runner):\n"
            "            return _autowisp_normalize_results(existing_runner(eval_config))\n"
            "        existing_results = globals().get('RESULTS')\n"
            "        if isinstance(existing_results, dict):\n"
            "            return _autowisp_normalize_results(existing_results)\n"
            "        for key in ('performance_data', 'metrics', 'results', 'evaluation_results'):\n"
            "            value = globals().get(key)\n"
            "            if isinstance(value, dict):\n"
            "                return _autowisp_normalize_results({'performance_data': value})\n"
            "        raise RuntimeError('Notebook auto-debug could not infer performance_data for RESULTS generation')\n"
        )

    @staticmethod
    def _execution_contract_code(metric_name: str) -> str:
        return (
            "# AUTO-WISP EXECUTION CONTRACT\n"
            "if not isinstance(globals().get('EVAL_CONFIG'), dict):\n"
            "    EVAL_CONFIG = {}\n"
            "if not isinstance(globals().get('RESULTS'), dict):\n"
            "    RESULTS = run_experiment(globals().get('EVAL_CONFIG', {}))\n"
            "RESULTS = _autowisp_normalize_results(RESULTS)\n"
            f"RESULTS.setdefault('notes', {{}})['primary_metric'] = {metric_name!r}\n"
        )

    def _ensure_required_roles(self, notebook: dict, task_spec: dict, solution_plan: dict, formalization: dict) -> dict:
        cells = list(notebook.get("cells") or [])
        if not cells:
            return self._build_fallback_notebook(task_spec, solution_plan, formalization)
        existing = {(cell.get("cell_type"), (cell.get("metadata") or {}).get("autowisp_role")) for cell in cells}
        fallback = self._build_fallback_notebook(task_spec, solution_plan, formalization)
        for cell in fallback.get("cells") or []:
            key = (cell.get("cell_type"), (cell.get("metadata") or {}).get("autowisp_role"))
            if key not in existing and (cell.get("metadata") or {}).get("autowisp_role") in self._required_roles(solution_plan):
                cells.append(cell)
        notebook["cells"] = cells
        notebook.setdefault("metadata", {}).setdefault("autowisp", {})["notebook_roles"] = [
            (cell.get("metadata") or {}).get("autowisp_role", "unlabeled") for cell in cells
        ]
        return notebook

    def _repair_syntax_errors(self, notebook: dict, syntax_errors: list[dict], task_spec: dict, solution_plan: dict) -> dict:
        repaired = json.loads(json.dumps(notebook))
        for error in syntax_errors:
            cell = repaired["cells"][error["index"]]
            source = "".join(cell.get("source") or [])
            messages = [
                {
                    "role": "system",
                    "content": "Fix the Python syntax error and return only the repaired code cell source.",
                },
                {
                    "role": "user",
                    "content": (
                        f"Task spec:\n```json\n{json.dumps(task_spec, ensure_ascii=False, indent=2)}\n```\n\n"
                        f"Solution plan:\n```json\n{json.dumps(solution_plan, ensure_ascii=False, indent=2)}\n```\n\n"
                        f"Cell role: {error['role']}\n"
                        f"Syntax error: {error['message']}\n\n"
                        f"Current code:\n```python\n{source}\n```"
                    ),
                },
            ]
            candidate = self._strip_code_fence(
                self.repair_llm.chat(
                    messages,
                    max_tokens=self._max_tokens(self.repair_llm, "notebook_repair"),
                    node_name="notebook_repair",
                )
            )
            try:
                ast.parse(candidate)
            except SyntaxError:
                continue
            cell["source"] = candidate.splitlines(keepends=True)
        return repaired

    def _find_syntax_errors(self, notebook: dict) -> list[dict]:
        errors = []
        for index, cell in enumerate(notebook.get("cells") or []):
            if cell.get("cell_type") != "code":
                continue
            source = "".join(cell.get("source") or [])
            try:
                ast.parse(source)
            except SyntaxError as exc:
                errors.append(
                    {
                        "index": index,
                        "role": (cell.get("metadata") or {}).get("autowisp_role", f"code_{index + 1}"),
                        "message": str(exc),
                    }
                )
        return errors

    def _build_fallback_notebook(self, task_spec: dict, solution_plan: dict, formalization: dict) -> dict:
        architecture = solution_plan.get("architecture") or {}
        evaluation_plan = solution_plan.get("evaluation_plan") or {}
        task_name = task_spec.get("task_category", "Wireless Signal Processing Study")
        strategy = architecture.get("strategy_label") or architecture.get("name") or "Structured notebook baseline"
        variable_points = evaluation_plan.get("variable_points") or self._default_variable_points(task_spec)
        axis_label = self._independent_variable_label(solution_plan)
        num_trials = self._default_num_trials(solution_plan)
        metric_name = self._primary_metric_name(task_spec, solution_plan)
        formal_summary = (formalization.get("system_model_doc") or formalization.get("math_formulation", {}).get("formulation_markdown") or "").strip()
        if not formal_summary:
            formal_summary = (
                "## Modeling Summary\n\n"
                "We study a reproducible wireless signal processing benchmark in which an estimator recovers a latent target from noisy observations across a configurable operating axis.\n\n"
                "The synthetic observation model is\n\n"
                "$$\n"
                "y = x + n, \\quad n \\sim \\mathcal{N}(0, \\sigma_n^2).\n"
                "$$\n\n"
                "The evaluation focuses on how the estimation error changes across the configured operating points."
            )

        sections = [
            ("markdown", "title", f"# {task_name}\n\nThis notebook implements the **{strategy}** solution as a single executable workflow."),
            ("markdown", "problem_setup", self._fallback_problem_setup_markdown(task_spec, axis_label, variable_points, num_trials)),
            ("markdown", "modeling_summary", self._normalize_math_markdown(formal_summary)),
            ("code", "imports_setup", self._fallback_imports_code()),
            ("code", "data_generation", self._fallback_data_generation_code()),
            ("code", "algorithm_core", self._fallback_algorithm_code()),
            ("code", "evaluation_logic", self._fallback_evaluation_code(metric_name, axis_label, num_trials)),
            ("code", "execution", self._fallback_execution_code(variable_points, axis_label, num_trials, metric_name)),
            ("code", "plotting", self._fallback_plotting_code(metric_name)),
            ("markdown", "result_notes", self._fallback_result_notes_markdown(metric_name)),
        ]
        return self._assemble_notebook(sections, task_spec, solution_plan)

    @staticmethod
    def _fallback_problem_setup_markdown(task_spec: dict, axis_label: str, variable_points: list, num_trials: Optional[int]) -> str:
        system_model = task_spec.get("system_model") or {}
        primary_metric = (task_spec.get("performance_targets") or {}).get("primary_metric") or "primary_metric"
        configuration_lines = [
            f"- Evaluation axis: {axis_label}",
            f"- Operating points: {variable_points or 'task-defined at runtime'}",
        ]
        if num_trials is not None:
            configuration_lines.append(f"- Monte Carlo trials: {num_trials}")
        configuration_lines.append("- Notebook artifact flow: problem summary -> executable experiment -> report assets")
        return (
            "## Problem Setup\n\n"
            f"We consider the **{task_spec.get('task_category', 'unknown')}** task under a notebook-first experimental workflow. "
            f"The working waveform assumption is **{system_model.get('waveform', 'unknown')}**, "
            f"and the reference channel or propagation setting is **{system_model.get('channel_model', 'unknown')}**.\n\n"
            "### Objective\n\n"
            f"Estimate or recover the task-dependent latent quantity while tracking the primary metric **{primary_metric}** across the configured evaluation protocol.\n\n"
            "### Evaluation Configuration\n\n"
            + "\n".join(configuration_lines)
            + "\n"
        )

    @staticmethod
    def _fallback_imports_code() -> str:
        return (
            "import json\n"
            "import math\n"
            "import random\n"
            "import statistics\n"
            "import time\n"
        )

    @staticmethod
    def _fallback_data_generation_code() -> str:
        return (
            "def generate_dataset(config):\n"
            "    operating_value = float(config.get('operating_value', 0.0))\n"
            "    trial = int(config.get('trial', 0))\n"
            "    rng = random.Random(1000 + trial * 37 + int((operating_value + 60) * 10))\n"
            "    signal_strength = 1.0\n"
            "    noise_scale = 1.0 / (1.0 + abs(operating_value))\n"
            "    target = math.sin((trial + 1) * 0.13) + 0.25 * math.cos(operating_value * 0.1)\n"
            "    observation = target + rng.gauss(0.0, noise_scale)\n"
            "    auxiliary = target + rng.gauss(0.0, noise_scale * 1.2)\n"
            "    return {\n"
            "        'operating_value': operating_value,\n"
            "        'trial': trial,\n"
            "        'signal_strength': signal_strength,\n"
            "        'noise_scale': noise_scale,\n"
            "        'target': target,\n"
            "        'observation': observation,\n"
            "        'auxiliary': auxiliary,\n"
            "    }\n"
        )

    @staticmethod
    def _fallback_algorithm_code() -> str:
        return (
            "def proposed_estimator(sample):\n"
            "    blend = 0.78 * sample['observation'] + 0.22 * sample['auxiliary']\n"
            "    regularizer = 0.05 * sample['noise_scale']\n"
            "    return blend / (1.0 + regularizer)\n\n"
            "def baseline_estimator(sample):\n"
            "    return sample['observation']\n"
        )

    @staticmethod
    def _fallback_evaluation_code(metric_name: str, axis_label: str, num_trials: Optional[int]) -> str:
        trial_line = (
            f"    num_trials = int(eval_config.get('num_trials', eval_config.get('num_monte_carlo', {num_trials})))\n"
            if num_trials is not None
            else "    num_trials = int(eval_config.get('num_trials', eval_config.get('num_monte_carlo', 1)))\n"
        )
        return (
            "def run_experiment(eval_config=None):\n"
            "    eval_config = dict(eval_config or {})\n"
            "    variable_points = list(eval_config.get('variable_points', [0, 1, 2, 3, 4]))\n"
            + trial_line +
            f"    axis_label = str(eval_config.get('independent_variable') or {axis_label!r})\n"
            "    started_at = time.time()\n"
            "    proposed_curve = []\n"
            "    baseline_curve = []\n"
            "    for operating_value in variable_points:\n"
            "        proposed_errors = []\n"
            "        baseline_errors = []\n"
            "        for trial in range(num_trials):\n"
            "            sample = generate_dataset({'operating_value': operating_value, 'trial': trial})\n"
            "            proposed_value = proposed_estimator(sample)\n"
            "            baseline_value = baseline_estimator(sample)\n"
            "            proposed_errors.append((proposed_value - sample['target']) ** 2)\n"
            "            baseline_errors.append((baseline_value - sample['target']) ** 2)\n"
            "        proposed_metric = math.sqrt(statistics.fmean(proposed_errors))\n"
            "        baseline_metric = math.sqrt(statistics.fmean(baseline_errors))\n"
            "        proposed_curve.append(round(proposed_metric, 6))\n"
            "        baseline_curve.append(round(baseline_metric, 6))\n"
            f"    metric_key = '{metric_name}_curve'\n"
            "    summary_rows = [\n"
            "        ['Proposed', round(statistics.fmean(proposed_curve), 6), round(min(proposed_curve), 6)],\n"
            "        ['Baseline', round(statistics.fmean(baseline_curve), 6), round(min(baseline_curve), 6)],\n"
            "    ]\n"
            "    report_assets = {\n"
            "        'problem_summary': 'Recover a latent target from noisy observations over task-defined operating points using a reproducible synthetic experiment.',\n"
            "        'solution_summary': 'Use a lightweight shrinkage-style estimator that blends the direct observation and an auxiliary statistic with regularization.',\n"
            "        'evaluation_summary': 'Compare the proposed estimator against a direct linear baseline across the configured operating grid.',\n"
            "        'figures': [\n"
            "            {\n"
            "                'title': 'Primary Metric Comparison',\n"
            "                'xlabel': axis_label,\n"
            f"                'ylabel': '{metric_name}',\n"
            "                'x': variable_points,\n"
            "                'series': {'proposed': proposed_curve, 'baseline_linear': baseline_curve},\n"
            "            }\n"
            "        ],\n"
            "        'tables': [\n"
            "            {\n"
            "                'title': 'Aggregate Performance Summary',\n"
            f"                'columns': ['Method', 'Mean {metric_name}', 'Best {metric_name}'],\n"
            "                'rows': summary_rows,\n"
            "            }\n"
            "        ],\n"
            "        'key_findings': [\n"
            "            'The proposed curve should stay below the baseline when regularization is effective.',\n"
            "            'Low-SNR and high-SNR regimes are both retained in the exported table for the report.',\n"
            "        ],\n"
            "    }\n"
            "    return {\n"
            "        'algorithm': 'Structured Notebook Baseline',\n"
            "        'elapsed_sec': round(time.time() - started_at, 4),\n"
            "        'performance_data': {\n"
            "            metric_key: {\n"
            "                'x': variable_points,\n"
            "                'x_label': axis_label,\n"
            "                'proposed': proposed_curve,\n"
            "                'baseline_linear': baseline_curve,\n"
            "            }\n"
            "        },\n"
            "        'report_assets': report_assets,\n"
            "    }\n"
        )

    @staticmethod
    def _fallback_execution_code(variable_points: list, axis_label: str, num_trials: Optional[int], metric_name: str) -> str:
        eval_config = {
            "variable_points": list(variable_points),
            "independent_variable": axis_label,
        }
        if num_trials is not None:
            eval_config["num_trials"] = int(num_trials)
        return (
            f"EVAL_CONFIG = {json.dumps(eval_config, ensure_ascii=False)}\n"
            "RESULTS = run_experiment(EVAL_CONFIG)\n"
            "RESULTS.setdefault('notes', {})['primary_metric'] = " + repr(metric_name) + "\n"
            "RESULTS.setdefault('report_assets', {}).setdefault('tables', [])\n"
            "print(json.dumps({'algorithm': RESULTS.get('algorithm'), 'metrics': list((RESULTS.get('performance_data') or {}).keys())}, ensure_ascii=False))\n"
        )

    @staticmethod
    def _fallback_result_notes_markdown(metric_name: str) -> str:
        return (
            "## Result Notes\n\n"
            "The execution cell stores a structured `RESULTS` dictionary containing:\n\n"
            "- `performance_data` for figure generation\n"
            "- `report_assets.problem_summary` and `report_assets.solution_summary` for report drafting\n"
            "- `report_assets.tables` for direct Markdown table rendering\n\n"
            f"All equations should stay KaTeX-ready, and the final report should discuss {metric_name} using only exported evidence."
        )

    @staticmethod
    def _fallback_plotting_code(metric_name: str) -> str:
        return (
            "PLOT_ARTIFACTS = []\n"
            "try:\n"
            "    import matplotlib.pyplot as plt\n"
            "    from IPython.display import Markdown, display\n"
            "    perf_data = (RESULTS.get('performance_data') or {}).get(" + repr(f"{metric_name}_curve") + ", {})\n"
            "    x = perf_data.get('x', [])\n"
            "    proposed = perf_data.get('proposed', [])\n"
            "    baseline = perf_data.get('baseline_linear', [])\n"
            "    x_label = perf_data.get('x_label', 'Operating Point')\n"
            "    if x and proposed and baseline:\n"
            "        delta = [round(b - p, 6) for p, b in zip(proposed, baseline)]\n"
            "        fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))\n"
            "        axes[0].plot(x, proposed, marker='o', linewidth=2.2, label='Proposed')\n"
            "        axes[0].plot(x, baseline, marker='s', linewidth=1.8, label='Baseline')\n"
            "        axes[0].set_xlabel(x_label)\n"
            "        axes[0].set_ylabel(" + repr(metric_name) + ")\n"
            "        axes[0].set_title('Primary Metric Comparison')\n"
            "        axes[0].grid(True, alpha=0.3)\n"
            "        axes[0].legend()\n"
            "        axes[1].plot(x, delta, marker='^', color='tab:green', linewidth=2.0)\n"
            "        axes[1].axhline(0.0, color='black', linewidth=1.0, alpha=0.4)\n"
            "        axes[1].set_xlabel(x_label)\n"
            "        axes[1].set_ylabel('Baseline - Proposed')\n"
            "        axes[1].set_title('Relative Gain Over Baseline')\n"
            "        axes[1].grid(True, alpha=0.3)\n"
            "        fig.tight_layout()\n"
            "        display(fig)\n"
            "        plt.close(fig)\n"
            "        display(Markdown('### Quick Summary\\n\\n' + '\\n'.join([\n"
            "            f'- Best proposed {" + repr(metric_name) + "}: {min(proposed):.6f}',\n"
            "            f'- Best baseline {" + repr(metric_name) + "}: {min(baseline):.6f}',\n"
            "            f'- Mean gain (baseline - proposed): {sum(delta) / len(delta):.6f}',\n"
            "        ])))\n"
            "        PLOT_ARTIFACTS.append({'figure': 'primary_metric_comparison', 'x': x, 'delta': delta})\n"
            "except Exception as exc:\n"
            "    PLOT_ARTIFACTS.append({'plotting_error': str(exc)})\n"
        )

    def _required_roles(self, solution_plan: dict) -> list[str]:
        notebook_plan = solution_plan.get("notebook_plan") or []
        roles = []
        for item in notebook_plan:
            role = self._normalize_role((item or {}).get("role", ""))
            if role:
                roles.append(role)
        if not roles:
            roles = list(CORE_REQUIRED_ROLES)
        for role in CORE_REQUIRED_ROLES:
            if role not in roles:
                roles.append(role)
        return roles

    @staticmethod
    def _expected_cell_type(role: str) -> Optional[str]:
        if role in CODE_ROLES:
            return "code"
        if role in MARKDOWN_ROLES:
            return "markdown"
        return None

    @staticmethod
    def _primary_metric_name(task_spec: dict, solution_plan: dict) -> str:
        primary_metric = ((task_spec.get("performance_targets") or {}).get("primary_metric") or "primary_metric")
        primary_metrics = (solution_plan.get("evaluation_plan") or {}).get("primary_metrics") or []
        if primary_metrics:
            metric_name = (primary_metrics[0] or {}).get("name")
            if metric_name:
                primary_metric = metric_name
        return re.sub(r"[^A-Za-z0-9]+", "_", primary_metric).strip("_") or "primary_metric"

    @staticmethod
    def _default_variable_points(task_spec: dict) -> list[int]:
        # Try operating range from task spec (may be SNR range or other parameter range)
        operating_range = (task_spec.get("system_model") or {}).get("snr_range_db") or (task_spec.get("system_model") or {}).get("operating_range")
        if isinstance(operating_range, list) and len(operating_range) >= 2:
            start = int(operating_range[0])
            stop = int(operating_range[1])
            step = 5 if stop >= start else -5
            return list(range(start, stop + step, step))
        return [0, 1, 2, 3, 4]

    @staticmethod
    def _independent_variable_label(solution_plan: dict) -> str:
        evaluation_plan = solution_plan.get("evaluation_plan") or {}
        label = str(evaluation_plan.get("independent_variable") or "").strip()
        return label or "Operating Point"

    @staticmethod
    def _default_num_trials(solution_plan: dict) -> Optional[int]:
        evaluation_plan = solution_plan.get("evaluation_plan") or {}
        raw_value = evaluation_plan.get("num_monte_carlo")
        if raw_value in (None, ""):
            return None
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _compact_formalization(formalization: dict) -> dict:
        """Return a compact subset of formalization for prompt injection.

        Strips algorithm_design (extracted separately in algo_design_block) and
        trims lengthy text fields to keep the prompt concise.
        """
        scenario = formalization.get("scenario_spec") or {}
        math_f = formalization.get("math_formulation") or {}
        system_doc = str(formalization.get("system_model_doc") or "")
        return {
            "system_model_doc": system_doc[:600] + ("..." if len(system_doc) > 600 else ""),
            "scenario_spec": {
                "signal_type": scenario.get("signal_type", ""),
                "core_parameters": scenario.get("core_parameters") or {},
                "snr_range_db": scenario.get("snr_range_db") or [],
                "data_contract": scenario.get("data_contract") or {},
                "generation_notes": str(scenario.get("generation_notes") or "")[:400],
            },
            "math_formulation": {
                "problem_type": math_f.get("problem_type", ""),
                "objective": math_f.get("objective") or {},
                "key_formulas": math_f.get("key_formulas") or [],
                "assumptions": math_f.get("assumptions") or [],
            },
            # NOTE: algorithm_design is extracted in detail via the Algorithm Design block below
        }

    @staticmethod
    def _compact_knowledge(retrieved_knowledge: dict) -> str:
        papers = retrieved_knowledge.get("relevant_papers") or []
        lines = []
        for item in papers[:8]:
            lines.append(f"- {item.get('title', 'Unknown title')} ({item.get('year', 'n/a')})")

        # Include algorithm names and descriptions — critical for baseline selection
        algorithms = retrieved_knowledge.get("relevant_algorithms") or []
        if algorithms:
            lines.append("\nRelevant algorithms (implement those listed in the contract as baselines):")
            for item in algorithms[:6]:
                if isinstance(item, dict):
                    name = (item.get("name") or "").strip()
                    desc = (item.get("description") or item.get("summary") or "").strip()[:200]
                    lines.append(f"- {name}" + (f": {desc}" if desc else ""))
                elif isinstance(item, str):
                    lines.append(f"- {item}")

        insights = (retrieved_knowledge.get("design_insights") or "").strip()
        if insights:
            lines.append("\nDesign insights:")
            lines.append(insights[:2400])
        if len(papers) > 8:
            lines.append(f"\n... {len(papers) - 8} more references omitted for brevity.")
        return "\n".join(lines) if lines else "(No retrieved knowledge summary available)"

    @staticmethod
    def _build_execution_contract(task_spec: dict, solution_plan: dict) -> dict:
        contract = dict(solution_plan.get("execution_contract") or {})
        evaluation_plan = solution_plan.get("evaluation_plan") or {}
        algorithm_spec = solution_plan.get("algorithm_spec") or {}
        eval_contract = algorithm_spec.get("evaluation_contract") or {}

        primary_metric = contract.get("primary_metric") or ((task_spec.get("performance_targets") or {}).get("primary_metric") or "primary_metric")
        baseline_methods = contract.get("baseline_methods") or []
        if not baseline_methods:
            baseline_methods = [
                (item or {}).get("name")
                for item in (evaluation_plan.get("baseline_methods") or [])
                if isinstance(item, dict) and (item or {}).get("name")
            ]
        if not baseline_methods:
            baseline_methods = [item for item in (eval_contract.get("baseline_methods") or []) if item]

        required_roles = contract.get("required_roles") or [
            (item or {}).get("role")
            for item in (solution_plan.get("notebook_plan") or [])
            if isinstance(item, dict) and (item or {}).get("role")
        ]
        if not required_roles:
            required_roles = list(CORE_REQUIRED_ROLES)

        contract.update(
            {
                "primary_metric": primary_metric,
                "baseline_methods": baseline_methods,
                "independent_variable": contract.get("independent_variable") or evaluation_plan.get("independent_variable") or "Operating Point",
                "variable_points": contract.get("variable_points") or evaluation_plan.get("variable_points") or [],
                "num_monte_carlo": contract.get("num_monte_carlo") or evaluation_plan.get("num_monte_carlo"),
                "required_roles": required_roles,
                "required_result_keys": contract.get("required_result_keys") or eval_contract.get("required_result_keys") or [
                    "algorithm",
                    "elapsed_sec",
                    "performance_data",
                    "report_assets",
                ],
                "comparison_required": bool(baseline_methods),
                "algorithm_steps": contract.get("algorithm_steps") or [
                    {
                        "name": (step or {}).get("name"),
                        "formula_latex": (step or {}).get("formula_latex", ""),
                    }
                    for step in (algorithm_spec.get("pipeline") or [])
                    if isinstance(step, dict) and (step or {}).get("name")
                ],
            }
        )
        return contract

    @staticmethod
    def _normalize_repair_context(repair_context: dict) -> dict:
        if not isinstance(repair_context, dict):
            return {"source": "unknown", "issues": []}
        normalized = dict(repair_context)
        issues = normalized.get("issues") or []
        normalized["issues"] = [str(item) for item in issues if str(item).strip()][:12]
        return normalized

    @staticmethod
    def _normalize_math_markdown(text: str) -> str:
        normalized = text.replace("\\[", "$$\n").replace("\\]", "\n$$")
        normalized = normalized.replace("\\(", "$ ").replace("\\)", " $")
        normalized = re.sub(r"(?m)^\$\$(.+?)\$\$$", r"$$\n\1\n$$", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    @staticmethod
    def _serialize_notebook_for_prompt(notebook: dict) -> str:
        blocks = []
        for cell in notebook.get("cells") or []:
            role = (cell.get("metadata") or {}).get("autowisp_role", "unlabeled")
            kind = cell.get("cell_type", "unknown").upper()
            body = "".join(cell.get("source") or [])
            blocks.append(f"# ========== {kind}: {role} ==========\n{body.strip()}")
        return "\n\n".join(blocks)

    @staticmethod
    def _make_markdown_cell(source: str, role: str) -> dict:
        return {
            "cell_type": "markdown",
            "metadata": {"autowisp_role": role},
            "source": source.splitlines(keepends=True),
        }

    @staticmethod
    def _make_code_cell(source: str, role: str) -> dict:
        return {
            "cell_type": "code",
            "metadata": {"autowisp_role": role},
            "source": source.splitlines(keepends=True),
            "execution_count": None,
            "outputs": [],
        }

    @staticmethod
    def _normalize_role(raw_role: str) -> str:
        role = raw_role.strip().lower().replace("-", "_").replace(" ", "_")
        return re.sub(r"[^a-z0-9_]+", "", role)

    @staticmethod
    def _strip_outer_fence(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 2:
                return "\n".join(lines[1:-1]).strip()
        return text

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 2 and lines[-1].strip() == "```":
                return "\n".join(lines[1:-1]).strip()
        return stripped