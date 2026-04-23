"""Notebook-first report generation for AutoWiSPA."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


REPORTER_SYSTEM_PROMPT = """You are an expert technical writer producing a rigorous, detailed research-style report for a notebook-based wireless signal processing study.

Write thorough, evidence-grounded Markdown with these sections (in order):
1. Abstract
2. System Model and Mathematical Formulation
3. Algorithm Design
4. Experimental Setup
5. Results and Discussion
6. Performance Analysis and Assessment
7. Reliability and Limitations
8. Conclusion

**General Writing Standards:**
- Each section must be substantive. Aim for at least 3-5 full paragraphs (not bullet-heavy summaries) per major section.
- Explain every formula in prose: state what it represents, define each symbol, and connect it to the physical or algorithmic meaning before or after the equation block.
- Use an academic but accessible tone. Avoid terse one-liners — expand into full sentences explaining the reasoning.
- Use KaTeX-ready equations with only $...$ and $$...$$ delimiters.

**Section-Specific Requirements:**

**1. Abstract (200-300 words)**
   - State the problem, proposed approach, key evaluation setup, and main quantitative finding in one coherent paragraph.

**2. System Model and Mathematical Formulation (detailed)**
   - Open with 1-2 paragraphs describing the physical scenario and signal environment in prose.
   - Present the signal/observation model equation(s) with full $$...$$ blocks; explain each term.
   - Include a variable table (| Symbol | Domain | Description |) for all variables provided.
   - Dedicate a separate paragraph to the optimization objective: describe what is being minimized/maximized, why, and under what constraints.
   - Present ALL key formulas with a bold label, $$...$$ equation block, and a ≥2-sentence explanation of its role.
   - List all modeling assumptions as a numbered list with a brief justification for each.
   - Do NOT collapse mathematical modeling into one sentence when objective functions, constraints, or metric formulas are provided.

**3. Algorithm Design (detailed)**
   - Write a 2-3 paragraph overview of the algorithmic strategy and motivation.
   - Present algorithm steps as a numbered "Stepwise Algorithm Procedure" with the EXACT formula from each step in $$...$$ blocks. After each formula, write ≥1 sentence explaining what is computed and why.
   - Include a "Baseline Algorithms" subsection: for each baseline, give a 2-3 sentence description and key formula.
   - Include "Convergence and Complexity" subsection if data is available. Explain what drives complexity.
   - Include "Failure Modes and Practical Considerations" subsection if risks are available.

**4. Experimental Setup (complete)**
   - Describe simulation parameters in detail (array size, sources, SNR range, Monte Carlo trials, etc.).
   - Justify parameter choices where possible (e.g., why this SNR range, why this array size).
   - Explain what metrics are used and how they are computed.

**5. Results and Discussion (data-driven)**
   - Embed ALL provided figure references as Markdown images with descriptive captions (include figure number, what is plotted, key takeaway).
   - Reproduce ALL data tables directly in Markdown table format.
   - Write at least one dedicated paragraph per method discussing its performance curve shape and behavior.
   - Provide numbered Key Observations with quantitative specifics (cite exact metric values from the tables).
   - If sensitivity analysis results are available, discuss them in a dedicated "Sensitivity Analysis" subsection.
   - Connect observations to theoretical expectations (e.g., compare to CRB, expected asymptotic behavior).

**6. Performance Analysis and Assessment (mandatory, thorough)**
   a. **Result Validity Check** (≥1 paragraph): Assess physical reasonableness of all numerical results. Explicitly flag anomalies (performance not improving with SNR, flat-line metrics, negative values where positive expected, suspiciously identical curves, etc.). Conclude whether results are trustworthy.
   b. **Comparative Assessment**: Provide a structured Markdown table — Method | Best Case | Worst Case | Average | Trend | Ranking — for all methods. Write ≥1 paragraph interpreting the rankings.
   c. **Theoretical Consistency** (≥1 paragraph): Compare observed trends against expected theoretical behavior. Cite specific theoretical properties (CRB, array gain, statistical efficiency).
   d. **Strengths and Weaknesses**: For EACH evaluated method, give 2 strengths and 2 weaknesses based on the data.
   e. **Overall Verdict** (≥3 sentences): State whether the proposed method meets its design goals, under what SNR/conditions it is preferred, and whether it exhibits the expected algorithmic behavior.

**7. Reliability and Limitations**
   - Write as one continuous prose block (2-3 paragraphs) or a flat bullet list. No sub-headings.

**8. Conclusion (substantive)**
   - Summarize 3 key contributions as bullet points, each with a ≥1 sentence explanation.
   - State the main quantitative finding with exact numbers.
   - Suggest 3 concrete future work directions with brief rationale for each.

**Formatting Rules:**
- Do NOT add a References, Bibliography, or Appendix section.
- Use horizontal rules (---) to separate major sections.
- Use > blockquote for key findings or anomaly flags.
- Use **bold** for metric names and method names in tables and discussions.
- Use $...$ inline and $$...$$ display for all math.

---

After the full Markdown report, output the following delimiter on its own line:

===REVIEW_JSON===

Then immediately output a strict JSON review object (no markdown fences, no extra text) with this schema:
{
  "overall_score": <float 0-10>,
  "confidence": <float 0-1>,
  "summary": "<2-3 sentence overall assessment>",
  "technical_strengths": ["<strength 1>", "..."],
  "technical_risks": ["<risk 1>", "..."],
  "report_quality": {
    "clarity": "high|medium|low",
    "mathematical_rigor": "high|medium|low",
    "evidence_support": "high|medium|low",
    "presentation_completeness": "high|medium|low"
  },
  "result_health": {
    "execution_success": true|false,
    "metrics_trustworthy": true|false,
    "figures_complete": true|false,
    "main_concerns": ["<concern 1>", "..."]
  },
  "actionable_notes": ["<note 1>", "..."]
}
"""


class ReporterAgent:
    """Generate a research-style report from the notebook-first pipeline outputs."""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or LLMClient()

    def _max_tokens(self, node_name: str, fallback: Optional[int] = None) -> Optional[int]:
        resolver = getattr(self.llm, "get_max_tokens", None)
        if callable(resolver):
            value = resolver(node_name, fallback)
            return value if isinstance(value, int) or value is None else fallback
        return fallback

    def generate(
        self,
        task_spec: dict,
        retrieved_knowledge: dict,
        formalization: dict,
        solution_plan: dict,
        notebook: dict,
        verification_results: dict,
        simulation_results: dict,
        experiment_evidence: str = "",
        output_dir: Optional[str] = None,
    ) -> str:
        report_assets = self._extract_report_assets(simulation_results)
        figure_refs = self._generate_figures(simulation_results, report_assets, output_dir) if output_dir else ""
        notebook_summary = self._summarize_notebook(notebook)
        notebook_narrative = self._extract_notebook_narrative(notebook)
        notebook_code_summary = self._extract_notebook_code_summary(notebook)
        modeling_details = self._build_math_modeling_details(formalization, notebook_narrative)
        algorithm_details = self._build_algorithm_design_details(solution_plan, formalization, notebook_narrative)
        rendered_tables = self._render_tables(report_assets.get("tables") or []) or self._build_metric_tables(simulation_results)
        evaluation_notes = self._build_evaluation_notes(verification_results, simulation_results, report_assets)
        compact_sim = self._compact_simulation_results(simulation_results)
        compact_assets = self._compact_report_assets(report_assets)
        prompt = (
            f"## Task Specification\n```json\n{json.dumps(task_spec, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Retrieved Knowledge\n```json\n{json.dumps(self._compact_knowledge(retrieved_knowledge), ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Formalization\n```json\n{json.dumps(formalization, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Solution Plan\n```json\n{json.dumps(solution_plan, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Mathematical Modeling Details (MUST integrate into 'System Model and Mathematical Formulation' section)\n{modeling_details}\n\n"
            f"## Algorithm Design Details (MUST integrate into 'Algorithm Design' section)\n{algorithm_details}\n\n"
            f"## Notebook Summary\n{notebook_summary}\n\n"
            f"## Notebook Code Summary (key algorithm cells)\n{notebook_code_summary}\n\n"
            f"## Notebook-Derived Problem Narrative\n{notebook_narrative.get('problem_setup', '(Missing problem setup narrative)')}\n\n"
            f"## Notebook-Derived Solution Narrative\n{notebook_narrative.get('modeling_summary', '(Missing modeling summary narrative)')}\n\n"
            f"## Notebook-Derived Result Notes\n{notebook_narrative.get('result_notes', '(Missing result notes narrative)')}\n\n"
            f"## Verification Results\n```json\n{json.dumps(verification_results, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Simulation Results\n```json\n{json.dumps(compact_sim, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Extracted Report Assets\n```json\n{json.dumps(compact_assets, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Rendered Tables\n{rendered_tables or '(No tables available)'}\n\n"
            f"## Concise Evaluation Notes (MUST use in 'Performance Analysis and Assessment' section)\n{evaluation_notes}\n\n"
            f"## Experiment Evidence\n{experiment_evidence or '(No additional evidence block supplied)'}\n\n"
            f"## Figure References (MUST embed in Results section)\n{figure_refs or '(No figures generated)'}\n\n"

            "Generate the full Markdown report now.\n"
            "IMPORTANT REMINDERS:\n"
            "- Include ALL 8 sections: Abstract, System Model, Algorithm Design, Experimental Setup, "
            "Results and Discussion, Performance Analysis and Assessment, Reliability and Limitations, Conclusion.\n"
            "- Write in DETAIL. Each major section must have at least 3-5 substantive paragraphs — "
            "do NOT collapse analysis into terse bullet lists.\n"
            "- Every formula must be accompanied by a ≥1 sentence prose explanation after the equation block.\n"
            "- The 'Performance Analysis and Assessment' section is MANDATORY with all five subsections (a-e). "
            "Use the Evaluation Notes and rendered tables to make it concrete and quantitative.\n"
            "- Embed ALL figure references in the Results section with full captions.\n"
            "- Do NOT add any Appendix sections.\n"
            "- Use --- between major sections.\n"
            "- Use > blockquote for key findings and anomaly warnings.\n"
        )

        report = self.llm.chat(
            [
                {"role": "system", "content": REPORTER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=self._max_tokens("report_generation"),
            node_name="report_generation",
        )
        footer = self._build_footer(task_spec, verification_results, simulation_results)
        normalized_report = self._normalize_reliability_section(
            self._normalize_math_markdown(self._strip_outer_markdown_fence(report)).strip()
        )
        normalized_report = self._strip_appendices(normalized_report)
        normalized_report = self._ensure_inline_details(normalized_report, modeling_details, algorithm_details)
        return normalized_report + "\n\n" + footer

    def generate_with_review(
        self,
        task_spec: dict,
        retrieved_knowledge: dict,
        formalization: dict,
        solution_plan: dict,
        notebook: dict,
        verification_results: dict,
        simulation_results: dict,
        experiment_evidence: str = "",
        output_dir: Optional[str] = None,
    ) -> tuple[str, dict]:
        """Generate the full report AND a structured review in a single LLM call.

        Returns:
            (report_str, review_dict) — the normalized Markdown report and the
            parsed review JSON object (same schema as ResultReviewerAgent).
        """
        report_assets = self._extract_report_assets(simulation_results)
        figure_refs = self._generate_figures(simulation_results, report_assets, output_dir) if output_dir else ""
        notebook_summary = self._summarize_notebook(notebook)
        notebook_narrative = self._extract_notebook_narrative(notebook)
        notebook_code_summary = self._extract_notebook_code_summary(notebook)
        modeling_details = self._build_math_modeling_details(formalization, notebook_narrative)
        algorithm_details = self._build_algorithm_design_details(solution_plan, formalization, notebook_narrative)
        rendered_tables = self._render_tables(report_assets.get("tables") or []) or self._build_metric_tables(simulation_results)
        evaluation_notes = self._build_evaluation_notes(verification_results, simulation_results, report_assets)
        compact_sim = self._compact_simulation_results(simulation_results)
        compact_assets = self._compact_report_assets(report_assets)
        prompt = (
            f"## Task Specification\n```json\n{json.dumps(task_spec, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Retrieved Knowledge\n```json\n{json.dumps(self._compact_knowledge(retrieved_knowledge), ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Formalization\n```json\n{json.dumps(formalization, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Solution Plan\n```json\n{json.dumps(solution_plan, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Mathematical Modeling Details (MUST integrate into 'System Model and Mathematical Formulation' section)\n{modeling_details}\n\n"
            f"## Algorithm Design Details (MUST integrate into 'Algorithm Design' section)\n{algorithm_details}\n\n"
            f"## Notebook Summary\n{notebook_summary}\n\n"
            f"## Notebook Code Summary (key algorithm cells)\n{notebook_code_summary}\n\n"
            f"## Notebook-Derived Problem Narrative\n{notebook_narrative.get('problem_setup', '(Missing problem setup narrative)')}\n\n"
            f"## Notebook-Derived Solution Narrative\n{notebook_narrative.get('modeling_summary', '(Missing modeling summary narrative)')}\n\n"
            f"## Notebook-Derived Result Notes\n{notebook_narrative.get('result_notes', '(Missing result notes narrative)')}\n\n"
            f"## Verification Results\n```json\n{json.dumps(verification_results, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Simulation Results\n```json\n{json.dumps(compact_sim, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Extracted Report Assets\n```json\n{json.dumps(compact_assets, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## Rendered Tables\n{rendered_tables or '(No tables available)'}\n\n"
            f"## Concise Evaluation Notes (MUST use in 'Performance Analysis and Assessment' section)\n{evaluation_notes}\n\n"
            f"## Experiment Evidence\n{experiment_evidence or '(No additional evidence block supplied)'}\n\n"
            f"## Figure References (MUST embed in Results section)\n{figure_refs or '(No figures generated)'}\n\n"
            "Generate the full Markdown report now, then output ===REVIEW_JSON=== and the review JSON.\n"
            "IMPORTANT REMINDERS:\n"
            "- Include ALL 8 sections: Abstract, System Model, Algorithm Design, Experimental Setup, "
            "Results and Discussion, Performance Analysis and Assessment, Reliability and Limitations, Conclusion.\n"
            "- Write in DETAIL. Each major section must have at least 3-5 substantive paragraphs — "
            "do NOT collapse analysis into terse bullet lists.\n"
            "- Every formula must be accompanied by a ≥1 sentence prose explanation after the equation block.\n"
            "- The 'Performance Analysis and Assessment' section is MANDATORY with all five subsections (a-e). "
            "Use the Evaluation Notes and rendered tables to make it concrete and quantitative.\n"
            "- Embed ALL figure references in the Results section with full captions.\n"
            "- Do NOT add any Appendix sections.\n"
            "- Use --- between major sections.\n"
            "- Use > blockquote for key findings and anomaly warnings.\n"
            "- After the report, output ===REVIEW_JSON=== on its own line, then the strict JSON review object.\n"
        )

        try:
            raw_response = self.llm.chat(
                [
                    {"role": "system", "content": REPORTER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=self._max_tokens("report_generation"),
                node_name="report_generation",
            )
        except Exception as e:
            err_str = str(e)
            if "too long" in err_str.lower() or "message_too_long" in err_str.lower() or "user_message_too_long" in err_str.lower():
                # Prompt exceeded LLM context limit — build a minimal fallback report
                raw_response = self._build_fallback_report(task_spec, rendered_tables, evaluation_notes) + "\n\n===REVIEW_JSON===\n{\"overall_score\": 3, \"passed\": false, \"issues\": [\"Report generation failed: prompt too long\"]}"
            else:
                raise

        report_text, review_raw = self._split_report_and_review(raw_response)
        footer = self._build_footer(task_spec, verification_results, simulation_results)
        normalized_report = self._normalize_reliability_section(
            self._normalize_math_markdown(self._strip_outer_markdown_fence(report_text)).strip()
        )
        normalized_report = self._strip_appendices(normalized_report)
        normalized_report = self._ensure_inline_details(normalized_report, modeling_details, algorithm_details)
        final_report = normalized_report + "\n\n" + footer

        review_dict = self._parse_review_json(review_raw)
        return final_report, review_dict

    @staticmethod
    def _split_report_and_review(raw_response: str) -> tuple[str, str]:
        """Split the combined LLM response into (report_text, review_json_text)."""
        delimiter = "===REVIEW_JSON==="
        if delimiter in raw_response:
            parts = raw_response.split(delimiter, 1)
            return parts[0].strip(), parts[1].strip()
        # Fallback: the whole response is the report, no review present
        return raw_response.strip(), ""

    @staticmethod
    def _parse_review_json(review_raw: str) -> dict:
        """Parse the review JSON block, returning a fallback dict on failure."""
        _default = {
            "overall_score": 5.0,
            "confidence": 0.3,
            "summary": "Review JSON was not produced or could not be parsed.",
            "technical_strengths": [],
            "technical_risks": ["Review extraction failed"],
            "report_quality": {
                "clarity": "medium",
                "mathematical_rigor": "medium",
                "evidence_support": "medium",
                "presentation_completeness": "medium",
            },
            "result_health": {
                "execution_success": True,
                "metrics_trustworthy": True,
                "figures_complete": False,
                "main_concerns": [],
            },
            "actionable_notes": [],
        }
        if not review_raw:
            return _default
        # Strip code fences if present
        stripped = review_raw.strip()
        fence_match = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", stripped, re.IGNORECASE)
        if fence_match:
            stripped = fence_match.group(1).strip()
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        # Try to extract first JSON object
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
        logger.warning("[Reporter] Could not parse review JSON from combined response")
        return _default

    def enrich_notebook(
        self,
        notebook: dict,
        verification_results: dict,
        simulation_results: dict,
        output_dir: Optional[str] = None,
    ) -> dict:
        enriched = json.loads(json.dumps(notebook or {"cells": []}))
        cells = list(enriched.get("cells") or [])
        appendix_roles = {"autowisp_results_summary", "autowisp_results_tables", "autowisp_results_figures"}
        cells = [
            cell for cell in cells
            if (cell.get("metadata") or {}).get("autowisp_role") not in appendix_roles
        ]

        report_assets = self._extract_report_assets(simulation_results)
        rendered_tables = self._render_tables(report_assets.get("tables") or []) or self._build_metric_tables(simulation_results)
        figure_refs = self._figure_refs_from_dir(output_dir)
        evaluation_notes = self._build_evaluation_notes(verification_results, simulation_results, report_assets)
        raw_results = simulation_results.get("raw_results") or {}
        algorithm_name = raw_results.get("algorithm") or simulation_results.get("algorithm") or "unknown"
        elapsed = raw_results.get("elapsed_sec") or simulation_results.get("elapsed_sec") or simulation_results.get("execution_time")

        summary_lines = [
            "## AutoWiSPA Simulation Outputs",
            "",
            f"- Algorithm: {algorithm_name}",
            f"- Verification status: {verification_results.get('status', 'unknown')}",
            f"- Simulation status: {simulation_results.get('status', 'unknown')}",
        ]
        if elapsed is not None:
            summary_lines.append(f"- Execution time: {elapsed}")
        if report_assets.get("evaluation_summary"):
            summary_lines.extend(["", "### Evaluation Summary", "", str(report_assets.get("evaluation_summary"))])
        if evaluation_notes:
            summary_lines.extend(["", "### Validation Notes", "", evaluation_notes])
        cells.append(self._make_markdown_cell("\n".join(summary_lines), "autowisp_results_summary"))

        if rendered_tables:
            cells.append(
                self._make_markdown_cell(
                    "## Quantitative Tables\n\n" + rendered_tables,
                    "autowisp_results_tables",
                )
            )

        if figure_refs:
            cells.append(
                self._make_markdown_cell(
                    "## Figures and Comparison Plots\n\n" + figure_refs,
                    "autowisp_results_figures",
                )
            )

        enriched["cells"] = cells
        return enriched

    def _generate_figures(self, simulation_results: dict, report_assets: dict, output_dir: str) -> str:
        perf_data = simulation_results.get("performance_data") or {}
        raw_results = simulation_results.get("raw_results") or {}
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import numpy as np
        except ImportError:
            logger.warning("[Reporter] matplotlib not available, skipping figures")
            return ""

        figure_dir = Path(output_dir) / "figures"
        figure_dir.mkdir(parents=True, exist_ok=True)
        refs: list[str] = []
        figure_index = 1

        # Phase 1: render structured figure specs from report_assets
        for figure_spec in report_assets.get("figures") or []:
            figure_index = self._render_figure_spec(figure_spec, figure_dir, figure_index)

        # Phase 2: render from structured performance_data
        for metric_key, x_data, methods, x_label in self._iter_plot_specs(perf_data):
            fig, ax = plt.subplots(figsize=(7.5, 4.8))
            for idx, (method_name, method_values) in enumerate(methods.items()):
                ax.plot(
                    x_data,
                    method_values,
                    marker=["o", "s", "^", "d", "v"][idx % 5],
                    linewidth=2.2 if "proposed" in method_name.lower() else 1.6,
                    label=method_name.replace("_", " ").title(),
                )
            ax.set_xlabel(x_label)
            ax.set_ylabel(metric_key.replace("_", " "))
            ax.set_title(metric_key.replace("_", " ").title())
            ax.grid(True, alpha=0.3)
            ax.legend()
            fig.tight_layout()
            file_name = f"perf_curve_{figure_index}.png"
            fig.savefig(figure_dir / file_name, dpi=150, bbox_inches="tight")
            plt.close(fig)
            figure_index += 1

        # Phase 3: fallback — auto-detect metric arrays in raw_results
        if not list(figure_dir.glob("*.png")) and isinstance(raw_results, dict):
            x_axis = None
            x_axis_label = "Operating Point"
            for x_key in self._X_AXIS_KEYS:
                candidate = raw_results.get(x_key)
                if isinstance(candidate, list) and len(candidate) >= 2:
                    x_axis = [float(v) for v in candidate]
                    x_axis_label = str(raw_results.get("x_label") or raw_results.get("xlabel") or x_key.replace("_", " ").title())
                    break
            if x_axis is not None:
                metric_groups: dict[str, dict[str, list[float]]] = {}
                for key, values in raw_results.items():
                    if not isinstance(values, list) or len(values) != len(x_axis):
                        continue
                    if not all(isinstance(v, (int, float)) for v in values):
                        continue
                    # Group by metric prefix: ber_zf -> "ber", nmse_proposed -> "nmse"
                    parts = key.split("_", 1)
                    metric_prefix = parts[0].lower()
                    if metric_prefix in self._METRIC_PREFIXES:
                        method_label = parts[1] if len(parts) > 1 else key
                        metric_groups.setdefault(metric_prefix, {})[method_label] = [float(v) for v in values]

                for metric_name, methods in metric_groups.items():
                    if not methods:
                        continue
                    fig, ax = plt.subplots(figsize=(9, 6))
                    use_semilogy = metric_name in self._LOG_METRICS
                    markers = ["o", "s", "^", "d", "v", "p", "h"]
                    linestyles = ["-", "-", "--", "-.", ":", "-", "--"]
                    for idx, (method_label, y_values) in enumerate(methods.items()):
                        plot_y = [v if v > 0 else float("nan") for v in y_values] if use_semilogy else y_values
                        plot_fn = ax.semilogy if use_semilogy else ax.plot
                        plot_fn(
                            x_axis,
                            plot_y,
                            marker=markers[idx % len(markers)],
                            linestyle=linestyles[idx % len(linestyles)],
                            linewidth=2,
                            markersize=7,
                            label=method_label.replace("_", " ").upper(),
                        )
                    ax.set_xlabel(x_axis_label, fontsize=13)
                    ax.set_ylabel(metric_name.upper(), fontsize=13)
                    ax.set_title(f"{metric_name.upper()} vs {x_axis_label}", fontsize=13)
                    ax.legend(fontsize=11)
                    ax.grid(True, which="both", ls="--", alpha=0.5)
                    fig.tight_layout()
                    safe_label = re.sub(r'[^a-z0-9]+', '_', x_axis_label.lower()).strip('_')
                    file_name = f"{metric_name}_vs_{safe_label}.png"
                    fig.savefig(figure_dir / file_name, dpi=150, bbox_inches="tight")
                    plt.close(fig)
                    figure_index += 1

        # Collect all generated figure files as references
        for pattern in ("*.png", "*.jpg", "*.jpeg"):
            for image_path in sorted(figure_dir.glob(pattern)):
                caption = image_path.stem.replace("_", " ").title()
                refs.append(f"![{caption}](figures/{image_path.name})")
        return "\n\n".join(refs)

    @staticmethod
    def _figure_refs_from_dir(output_dir: Optional[str]) -> str:
        if not output_dir:
            return ""
        figure_dir = Path(output_dir) / "figures"
        if not figure_dir.exists():
            return ""
        refs: list[str] = []
        for pattern in ("*.png", "*.jpg", "*.jpeg"):
            for image_path in sorted(figure_dir.glob(pattern)):
                refs.append(f"![{image_path.stem.replace('_', ' ').title()}](figures/{image_path.name})")
        return "\n\n".join(refs)

    @staticmethod
    def _render_figure_spec(figure_spec: dict, figure_dir: Path, figure_index: int) -> int:
        if not isinstance(figure_spec, dict):
            return figure_index
        x_values = None
        for xk in ReporterAgent._X_AXIS_KEYS:
            x_values = figure_spec.get(xk)
            if isinstance(x_values, list) and len(x_values) >= 2:
                break
        else:
            x_values = None
        series = figure_spec.get("series") or figure_spec.get("curves") or {}
        if not isinstance(x_values, list) or len(x_values) < 2 or not isinstance(series, dict):
            return figure_index
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            return figure_index
        fig, ax = plt.subplots(figsize=(7.5, 4.8))
        for idx, (label, y_values) in enumerate(series.items()):
            if not isinstance(y_values, list) or len(y_values) != len(x_values):
                continue
            ax.plot(
                x_values,
                y_values,
                marker=["o", "s", "^", "d", "v"][idx % 5],
                linewidth=2.0,
                label=str(label).replace("_", " ").title(),
            )
        if not ax.lines:
            plt.close(fig)
            return figure_index
        ax.set_xlabel(str(figure_spec.get("xlabel") or "Operating Point"))
        ax.set_ylabel(str(figure_spec.get("ylabel") or figure_spec.get("metric") or "Value"))
        ax.set_title(str(figure_spec.get("title") or f"Figure {figure_index}"))
        ax.grid(True, alpha=0.3)
        ax.legend()
        fig.tight_layout()
        file_name = f"asset_curve_{figure_index}.png"
        fig.savefig(figure_dir / file_name, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return figure_index + 1

    @staticmethod
    def _compact_knowledge(retrieved_knowledge: dict) -> dict:
        papers_out = []
        for item in (retrieved_knowledge.get("relevant_papers") or []):
            abstract = str(item.get("abstract") or item.get("abstract_snippet") or "").strip()
            entry: dict = {
                "title": item.get("title"),
                "year": item.get("year"),
                "source": item.get("source"),
            }
            if abstract:
                entry["abstract"] = abstract[:300] + ("..." if len(abstract) > 300 else "")
            citations = item.get("citation_count")
            if citations is not None:
                entry["citations"] = citations
            papers_out.append(entry)

        alg_out = []
        for item in (retrieved_knowledge.get("relevant_algorithms") or []):
            if isinstance(item, dict):
                alg_entry: dict = {"name": item.get("name", "")}
                desc = str(item.get("description") or item.get("summary") or "").strip()
                if desc:
                    alg_entry["description"] = desc[:300] + ("..." if len(desc) > 300 else "")
                alg_out.append(alg_entry)
            elif isinstance(item, str):
                alg_out.append({"name": item})

        baseline_perf = retrieved_knowledge.get("baseline_performance") or {}
        code_templates = retrieved_knowledge.get("code_templates") or []
        template_hints = []
        for t in (code_templates if isinstance(code_templates, list) else [])[:3]:
            if isinstance(t, dict):
                hint = str(t.get("name") or t.get("description") or t.get("template_name") or "").strip()[:120]
                if hint:
                    template_hints.append(hint)

        result = {
            "relevant_papers": papers_out,
            "design_insights": (retrieved_knowledge.get("design_insights") or ""),
            "relevant_algorithms": alg_out,
        }
        if baseline_perf:
            result["baseline_performance"] = baseline_perf
        if template_hints:
            result["code_template_hints"] = template_hints
        return result

    @staticmethod
    def _compact_simulation_results(simulation_results: dict, max_array_len: int = 20) -> dict:
        """Truncate large array fields in simulation_results to reduce prompt size."""
        if not isinstance(simulation_results, dict):
            return simulation_results

        def _trim(value):
            if isinstance(value, list) and len(value) > max_array_len:
                return value[:max_array_len] + [f"... ({len(value) - max_array_len} more items truncated)"]
            if isinstance(value, dict):
                return {k: _trim(v) for k, v in value.items()}
            return value

        compact = {}
        for key, val in simulation_results.items():
            if key == "performance_data" and isinstance(val, dict):
                pd_compact = {}
                for pk, pv in val.items():
                    if pk in ("estimate_cloud_sigma3",):
                        # drop heavy scatter point arrays entirely
                        if isinstance(pv, dict):
                            pd_compact[pk] = {k2: (v2[:30] if isinstance(v2, list) and len(v2) > 30 else v2)
                                               for k2, v2 in pv.items()}
                        else:
                            pd_compact[pk] = pv
                    elif pk in ("cdf_sigma3",) and isinstance(pv, dict):
                        # keep only first 30 CDF points per method
                        pv_c = {}
                        for mname, mval in pv.items():
                            if isinstance(mval, dict):
                                pv_c[mname] = {k2: (v2[:30] if isinstance(v2, list) and len(v2) > 30 else v2)
                                               for k2, v2 in mval.items()}
                            else:
                                pv_c[mname] = mval
                        pd_compact[pk] = pv_c
                    elif pk == "per_point_stats" and isinstance(pv, list) and len(pv) > 5:
                        # keep at most 5 representative points
                        pd_compact[pk] = pv[:5] + [{"note": f"{len(pv) - 5} more points truncated"}]
                    else:
                        pd_compact[pk] = _trim(pv)
                compact[key] = pd_compact
            else:
                compact[key] = _trim(val)
        return compact

    @staticmethod
    def _compact_report_assets(report_assets: dict, max_rows: int = 10) -> dict:
        """Truncate large table rows in report_assets to reduce prompt size."""
        if not isinstance(report_assets, dict):
            return report_assets
        compact = dict(report_assets)
        tables = compact.get("tables")
        if isinstance(tables, list):
            compact_tables = []
            for table in tables:
                if not isinstance(table, dict):
                    compact_tables.append(table)
                    continue
                rows = table.get("rows")
                if isinstance(rows, list) and len(rows) > max_rows:
                    table = dict(table)
                    table["rows"] = rows[:max_rows]
                    table["_rows_truncated"] = f"{len(rows) - max_rows} rows omitted"
                compact_tables.append(table)
            compact["tables"] = compact_tables
        return compact

    @staticmethod
    def _build_fallback_report(task_spec: dict, rendered_tables: str, evaluation_notes: str) -> str:
        """Build a minimal fallback report when the full LLM call fails (e.g. prompt too long)."""
        title = str((task_spec.get("title") or task_spec.get("problem") or "Simulation Study")).strip()
        return (
            f"# {title}\n\n"
            "> **Note:** Full report generation was skipped because the context exceeded the model's message length limit. "
            "Key numeric results are preserved below.\n\n"
            "---\n\n"
            "## Abstract\n\nReport auto-generation encountered a message-too-long error. "
            "The simulation completed successfully and key results are shown in the tables below.\n\n"
            "---\n\n"
            "## Results Summary\n\n"
            f"{rendered_tables or '(No tables available)'}\n\n"
            "---\n\n"
            "## Evaluation Notes\n\n"
            f"{evaluation_notes or '(No evaluation notes)'}\n\n"
            "---\n\n"
            "## Conclusion\n\nPlease refer to the simulation notebook and figures for detailed analysis.\n"
        )

    @staticmethod
    def _summarize_notebook(notebook: dict) -> str:
        lines = []
        cells = notebook.get("cells") or []
        lines.append(f"Notebook cells: {len(cells)}")
        for index, cell in enumerate(cells, start=1):
            role = (cell.get("metadata") or {}).get("autowisp_role", "unlabeled")
            lines.append(f"- Cell {index}: {cell.get('cell_type', 'unknown')} / {role}")
        return "\n".join(lines)

    @staticmethod
    def _extract_notebook_narrative(notebook: dict) -> dict[str, str]:
        narrative: dict[str, str] = {}
        for cell in notebook.get("cells") or []:
            if cell.get("cell_type") != "markdown":
                continue
            role = (cell.get("metadata") or {}).get("autowisp_role", "unlabeled")
            text = "".join(cell.get("source") or []).strip()
            if text:
                narrative[role] = f"{narrative.get(role, '')}\n\n{text}".strip() if role in narrative else text
        return narrative

    @staticmethod
    def _extract_notebook_code_summary(notebook: dict) -> str:
        """Extract key code cells (algorithm_core, evaluation, baseline) as a readable summary.

        Limits each cell to 60 lines so the prompt stays bounded, but provides enough
        implementation detail for the LLM to write accurate Algorithm Design and
        Experimental Setup sections.
        """
        KEY_ROLES = {
            "algorithm_core": "Proposed Algorithm Implementation",
            "evaluation": "Evaluation / Sweep Loop",
            "results": "Results Collection",
            "baseline": "Baseline Implementation",
            "imports": "Imports and Setup",
        }
        lines: list[str] = []
        for cell in notebook.get("cells") or []:
            if cell.get("cell_type") != "code":
                continue
            role = (cell.get("metadata") or {}).get("autowisp_role", "")
            if role not in KEY_ROLES:
                continue
            source_lines = "".join(cell.get("source") or []).splitlines()
            truncated = source_lines[:60]
            tail_note = f"\n... ({len(source_lines) - 60} more lines)" if len(source_lines) > 60 else ""
            label = KEY_ROLES[role]
            lines.append(f"### [{label}] (role: {role})")
            lines.append("```python")
            lines.extend(truncated)
            if tail_note:
                lines.append(tail_note)
            lines.append("```")
            lines.append("")
        return "\n".join(lines).strip() or "(No key algorithm code cells extracted)"

    @staticmethod
    def _extract_report_assets(simulation_results: dict) -> dict:
        raw_results = simulation_results.get("raw_results") or {}
        if isinstance(raw_results, dict):
            assets = raw_results.get("report_assets")
            if isinstance(assets, dict):
                return assets
        return {}

    @staticmethod
    def _render_tables(tables: list[dict]) -> str:
        rendered: list[str] = []
        for table in tables:
            if not isinstance(table, dict):
                continue
            title = str(table.get("title") or "Table").strip()
            columns = [str(item) for item in (table.get("columns") or [])]
            rows = table.get("rows") or []
            if not columns or not rows:
                continue
            rendered.append(f"### {title}")
            rendered.append("| " + " | ".join(columns) + " |")
            rendered.append("| " + " | ".join(["---"] * len(columns)) + " |")
            for row in rows:
                cells = [str(item) for item in row]
                rendered.append("| " + " | ".join(cells) + " |")
            rendered.append("")
        return "\n".join(rendered).strip()

    def _build_metric_tables(self, simulation_results: dict) -> str:
        perf_data = simulation_results.get("performance_data") or {}
        raw_results = simulation_results.get("raw_results") or {}
        rendered: list[str] = []

        # Structured performance_data tables
        for metric_key, x_data, methods, x_label in self._iter_plot_specs(perf_data):
            rendered.append(f"### {metric_key.replace('_', ' ').title()}")
            columns = [x_label] + [name.replace("_", " ").title() for name in methods.keys()]
            rendered.append("| " + " | ".join(columns) + " |")
            rendered.append("| " + " | ".join(["---"] * len(columns)) + " |")
            for idx, x_value in enumerate(x_data):
                row = [str(x_value)] + [str(values[idx]) for values in methods.values()]
                rendered.append("| " + " | ".join(row) + " |")
            rendered.append("")

        # Fallback: build tables from raw_results direct arrays
        if not rendered and isinstance(raw_results, dict):
            x_axis = None
            x_axis_label = "Operating Point"
            for x_key in self._X_AXIS_KEYS:
                candidate = raw_results.get(x_key)
                if isinstance(candidate, list) and len(candidate) >= 2:
                    x_axis = candidate
                    x_axis_label = str(raw_results.get("x_label") or raw_results.get("xlabel") or x_key.replace("_", " ").title())
                    break
            if x_axis is not None:
                metric_groups: dict[str, dict[str, list]] = {}
                for key, values in raw_results.items():
                    if not isinstance(values, list) or len(values) != len(x_axis):
                        continue
                    if not all(isinstance(v, (int, float)) for v in values):
                        continue
                    parts = key.split("_", 1)
                    prefix = parts[0].lower()
                    if prefix in self._METRIC_PREFIXES:
                        method_label = parts[1] if len(parts) > 1 else key
                        metric_groups.setdefault(prefix, {})[method_label] = values
                for metric_name, methods in metric_groups.items():
                    rendered.append(f"### {metric_name.upper()} Performance")
                    columns = [x_axis_label] + [m.replace("_", " ").upper() for m in methods.keys()]
                    rendered.append("| " + " | ".join(columns) + " |")
                    rendered.append("| " + " | ".join(["---"] * len(columns)) + " |")
                    for idx, x_val in enumerate(x_axis):
                        row = [str(x_val)] + [f"{values[idx]:.4g}" for values in methods.values()]
                        rendered.append("| " + " | ".join(row) + " |")
                    rendered.append("")

        return "\n".join(rendered).strip()

    @staticmethod
    def _build_math_modeling_details(formalization: dict, notebook_narrative: dict[str, str]) -> str:
        math_formulation = formalization.get("math_formulation") or {}
        lines: list[str] = []

        system_model_doc = str(formalization.get("system_model_doc") or "").strip()
        if system_model_doc:
            lines.extend(["### System Model", system_model_doc, ""])

        objective = math_formulation.get("objective") or {}
        objective_desc = str(objective.get("description") or "").strip()
        objective_formula = str(objective.get("formula_latex") or "").strip()
        if objective_desc or objective_formula:
            lines.append("### Objective")
            if objective_desc:
                lines.append(objective_desc)
            if objective_formula:
                lines.append(ReporterAgent._latex_block(objective_formula))
            lines.append("")

        variables = math_formulation.get("variables") or []
        if variables:
            lines.append("### Variables")
            for item in variables:
                symbol = str((item or {}).get("symbol") or "").strip()
                name = str((item or {}).get("name") or "variable").strip()
                description = str((item or {}).get("description") or "").strip()
                domain = str((item or {}).get("domain") or "").strip()
                variable_line = f"- {name}"
                if symbol:
                    variable_line += f" with symbol ${symbol}$"
                if domain:
                    variable_line += f", domain ${domain}$"
                if description:
                    variable_line += f": {description}"
                lines.append(variable_line)
            lines.append("")

        constraints = math_formulation.get("constraints") or []
        if constraints:
            lines.append("### Constraints")
            for item in constraints:
                description = str((item or {}).get("description") or "").strip()
                formula = str((item or {}).get("formula_latex") or "").strip()
                if description:
                    lines.append(f"- {description}")
                if formula:
                    lines.append(ReporterAgent._latex_block(formula))
            lines.append("")

        key_formulas = math_formulation.get("key_formulas") or []
        if key_formulas:
            lines.append("### Key Formulas")
            for item in key_formulas:
                name = str((item or {}).get("name") or "Formula").strip()
                description = str((item or {}).get("description") or "").strip()
                formula = str((item or {}).get("formula_latex") or "").strip()
                lines.append(f"- {name}: {description}".rstrip())
                if formula:
                    lines.append(ReporterAgent._latex_block(formula))
            lines.append("")

        assumptions = math_formulation.get("assumptions") or []
        if assumptions:
            lines.append("### Modeling Assumptions")
            for item in assumptions:
                lines.append(f"- {item}")
            lines.append("")

        notebook_modeling = str(notebook_narrative.get("modeling_summary") or "").strip()
        if notebook_modeling:
            lines.extend(["### Notebook Modeling Narrative", notebook_modeling, ""])

        return "\n".join(line for line in lines if line is not None).strip() or "(No detailed mathematical modeling block available.)"

    @staticmethod
    def _build_algorithm_design_details(solution_plan: dict, formalization: dict, notebook_narrative: dict[str, str]) -> str:
        architecture = solution_plan.get("architecture") or {}
        algorithm_spec = solution_plan.get("algorithm_spec") or {}
        evaluation_plan = solution_plan.get("evaluation_plan") or {}
        summary = formalization.get("formalization_summary") or {}
        algo_design = formalization.get("algorithm_design") or {}
        lines: list[str] = []

        overview_parts = [
            str(architecture.get("summary") or "").strip(),
            str(architecture.get("algorithm_structure") or "").strip(),
            str(architecture.get("rationale") or "").strip(),
        ]
        overview_parts = [part for part in overview_parts if part]
        if overview_parts:
            lines.extend(["### Algorithm Overview", "\n\n".join(overview_parts), ""])

        # Proposed algorithm info from formalization
        proposed = algo_design.get("proposed_algorithm") or {}
        if proposed.get("name"):
            lines.append(f"**Proposed Method**: {proposed['name']} ({proposed.get('type', 'unknown')}) — {proposed.get('summary', '')}")
            lines.append("")

        pseudocode = str(architecture.get("pseudocode") or "").strip()
        if pseudocode:
            lines.extend(["### Pseudocode", pseudocode, ""])

        # Prefer formalization algorithm_steps over solution_plan pipeline
        algo_steps = algo_design.get("algorithm_steps") or []
        if algo_steps:
            lines.append("### Stepwise Algorithm Procedure (with Formulas)")
            for step in algo_steps:
                if not isinstance(step, dict):
                    continue
                step_num = step.get("step", "?")
                name = str(step.get("name", "")).strip()
                desc = str(step.get("description", "")).strip()
                formula = str(step.get("formula_latex", "")).strip()
                inputs = step.get("inputs") or []
                outputs = step.get("outputs") or []
                numpy_hint = str(step.get("numpy_hint", "")).strip()
                lines.append(f"{step_num}. **{name}**: {desc}")
                if formula:
                    lines.append(ReporterAgent._latex_block(formula))
                io_parts = []
                if inputs:
                    io_parts.append(f"Inputs: {', '.join(f'${v}$' for v in inputs)}")
                if outputs:
                    io_parts.append(f"Outputs: {', '.join(f'${v}$' for v in outputs)}")
                if numpy_hint:
                    io_parts.append(f"Implementation: `{numpy_hint}`")
                if io_parts:
                    lines.append("   " + " | ".join(io_parts))
            lines.append("")
        else:
            # Fallback to solution_plan pipeline
            pipeline = algorithm_spec.get("pipeline") or []
            if pipeline:
                lines.append("### Stepwise Design")
                for step in pipeline:
                    step_id = (step or {}).get("step")
                    name = str((step or {}).get("name") or "Step").strip()
                    purpose = str((step or {}).get("purpose") or "").strip()
                    hint = str((step or {}).get("implementation_hint") or "").strip()
                    formula = str((step or {}).get("formula_latex") or "").strip()
                    prefix = f"{step_id}. {name}" if step_id is not None else name
                    detail = f"{prefix}: {purpose}".rstrip(": ")
                    if hint:
                        detail += f" Implementation hint: {hint}"
                    lines.append(f"- {detail}")
                    if formula:
                        lines.append(ReporterAgent._latex_block(formula))
                lines.append("")

        # Baseline algorithms from formalization
        baselines = algo_design.get("baseline_algorithms") or []
        if baselines:
            lines.append("### Baseline Algorithms")
            for bl in baselines:
                if not isinstance(bl, dict):
                    continue
                name = str(bl.get("name", "")).strip()
                bl_summary = str(bl.get("summary", "")).strip()
                formula = str(bl.get("key_formula_latex", "")).strip()
                lines.append(f"- **{name}**: {bl_summary}")
                if formula:
                    lines.append(ReporterAgent._latex_block(formula))
            lines.append("")

        # Convergence and complexity from formalization
        convergence = algo_design.get("convergence") or {}
        complexity = algo_design.get("complexity") or {}
        if convergence.get("criterion") or complexity.get("per_iteration"):
            lines.append("### Convergence and Complexity")
            if convergence.get("criterion"):
                lines.append(f"- **Convergence**: {convergence['criterion']}")
                if convergence.get("formula_latex"):
                    lines.append(ReporterAgent._latex_block(convergence["formula_latex"]))
            if complexity.get("per_iteration"):
                lines.append(f"- **Complexity**: {complexity['per_iteration']}")
            if complexity.get("dominant_operation"):
                lines.append(f"- **Dominant operation**: {complexity['dominant_operation']}")
            lines.append("")

        metrics = evaluation_plan.get("primary_metrics") or []
        if metrics:
            lines.append("### Evaluation Metrics")
            for metric in metrics:
                name = str((metric or {}).get("name") or "metric").strip()
                description = str((metric or {}).get("description") or "").strip()
                formula = str((metric or {}).get("formula_latex") or "").strip()
                lines.append(f"- **{name}**: {description}".rstrip(": "))
                if formula:
                    lines.append(ReporterAgent._latex_block(formula))
            lines.append("")

        est_complexity = str(architecture.get("estimated_complexity") or "").strip()
        if est_complexity and not complexity.get("per_iteration"):
            lines.extend(["### Complexity", est_complexity, ""])

        failure_modes = algorithm_spec.get("failure_modes") or summary.get("implementation_risks") or []
        if failure_modes:
            lines.append("### Failure Modes and Risks")
            for item in failure_modes:
                lines.append(f"- {item}")
            lines.append("")

        notebook_problem = str(notebook_narrative.get("problem_setup") or "").strip()
        if notebook_problem:
            lines.extend(["### Notebook Problem Narrative", notebook_problem, ""])

        return "\n".join(line for line in lines if line is not None).strip() or "(No detailed algorithm design block available.)"

    @staticmethod
    def _latex_block(formula: str) -> str:
        cleaned = formula.strip()
        if cleaned.startswith("$$") and cleaned.endswith("$$"):
            return cleaned
        return f"$$\n{cleaned}\n$$"

    @staticmethod
    def _make_markdown_cell(content: str, role: str) -> dict:
        return {
            "cell_type": "markdown",
            "metadata": {
                "language": "markdown",
                "autowisp_role": role,
            },
            "source": [line + "\n" for line in content.strip().splitlines()],
        }

    @staticmethod
    def _build_evaluation_notes(verification_results: dict, simulation_results: dict, report_assets: dict) -> str:
        notes: list[str] = []
        notes.append(f"- **Verification status**: {verification_results.get('status', 'unknown')}")
        ver_msg = verification_results.get("message") or verification_results.get("summary") or ""
        if ver_msg:
            notes.append(f"  - Detail: {str(ver_msg).strip()[:300]}")

        notes.append(f"- **Simulation status**: {simulation_results.get('status', 'unknown')}")
        sim_msg = simulation_results.get("message") or simulation_results.get("summary") or ""
        if sim_msg:
            notes.append(f"  - Detail: {str(sim_msg).strip()[:300]}")

        perf_data = simulation_results.get("performance_data") or {}
        if isinstance(perf_data, dict) and perf_data:
            notes.append(f"- **Performance payload keys**: {', '.join(list(perf_data.keys()))}")

            # Quantitative summary extraction
            x_vals = None
            for xk in ReporterAgent._X_AXIS_KEYS:
                if xk in perf_data and isinstance(perf_data[xk], list):
                    x_vals = perf_data[xk]
                    notes.append(f"- **Operating range**: {xk} = [{x_vals[0]}, ..., {x_vals[-1]}] ({len(x_vals)} points)")
                    break

            # Per-method summary
            method_summaries: list[str] = []
            for key, vals in perf_data.items():
                if key in ReporterAgent._X_AXIS_SET:
                    continue
                if not isinstance(vals, list) or not vals:
                    continue
                numeric = [v for v in vals if isinstance(v, (int, float))]
                if not numeric:
                    continue
                best = min(numeric)
                worst = max(numeric)
                avg = sum(numeric) / len(numeric)
                method_summaries.append(
                    f"  - **{key}**: best={best:.4g}, worst={worst:.4g}, avg={avg:.4g}"
                )
            if method_summaries:
                notes.append("- **Method performance summary**:")
                notes.extend(method_summaries)

            # Trend analysis: check if proposed method improves with x
            for key, vals in perf_data.items():
                if key in ReporterAgent._X_AXIS_SET:
                    continue
                if not isinstance(vals, list) or len(vals) < 3:
                    continue
                numeric = [v for v in vals if isinstance(v, (int, float))]
                if len(numeric) < 3:
                    continue
                increasing = all(numeric[i] <= numeric[i + 1] for i in range(len(numeric) - 1))
                decreasing = all(numeric[i] >= numeric[i + 1] for i in range(len(numeric) - 1))
                if increasing:
                    notes.append(f"- **Trend [{key}]**: monotonically increasing over operating range")
                elif decreasing:
                    notes.append(f"- **Trend [{key}]**: monotonically decreasing over operating range")
                else:
                    notes.append(f"- **Trend [{key}]**: non-monotonic (may warrant investigation)")

        # Sensitivity factors
        sensitivity_factors = simulation_results.get("sensitivity_factors") or []
        if sensitivity_factors:
            notes.append("- **Sensitivity factors tested**: " + ", ".join(
                str(f.get("name", f)) if isinstance(f, dict) else str(f) for f in sensitivity_factors
            ))

        if report_assets.get("key_findings"):
            notes.append("- **Key findings from notebook**:")
            for item in report_assets.get("key_findings"):
                notes.append(f"  - {item}")

        raw_results = simulation_results.get("raw_results") or {}
        if isinstance(raw_results, dict):
            result_notes = raw_results.get("result_notes") or []
            if isinstance(result_notes, list) and result_notes:
                notes.append("- **Result notes from simulation**:")
                for rn in result_notes[:10]:
                    notes.append(f"  - {rn}")

        return "\n".join(notes)

    # Generic x-axis key search order — "x" and "variable_points" are canonical;
    # legacy SNR-specific keys kept only for backward compatibility with old result dicts.
    _X_AXIS_KEYS = ["x", "variable_points", "operating_points", "snr", "snr_points", "snr_db", "snr_range"]
    _X_AXIS_SET = set(_X_AXIS_KEYS) | {"x_label", "xlabel", "ylabel", "title"}
    # Known metric prefixes for auto-grouping raw_results arrays
    _METRIC_PREFIXES = {
        "ber", "nmse", "ser", "pd", "pfa", "sinr", "se", "rate",
        "throughput", "mse", "rmse", "snr", "capacity", "spectral_efficiency",
        "outage", "gain", "error", "loss", "accuracy", "precision", "recall",
    }
    # Metrics that should use logarithmic y-axis
    _LOG_METRICS = {"ber", "ser", "nmse", "mse", "pfa", "outage", "error", "loss"}

    @staticmethod
    def _iter_plot_specs(perf_data: dict):
        top_x = None
        top_x_key = None
        for x_key in ReporterAgent._X_AXIS_KEYS:
            values = perf_data.get(x_key)
            if isinstance(values, list) and len(values) >= 2:
                top_x = values
                top_x_key = x_key
                break
        yielded_any = False
        for metric_key, metric_payload in perf_data.items():
            if not isinstance(metric_payload, dict):
                continue
            x_values = None
            for x_key in ReporterAgent._X_AXIS_KEYS:
                values = metric_payload.get(x_key)
                if isinstance(values, list) and len(values) >= 2:
                    x_values = values
                    break
            x_values = x_values or top_x
            if not isinstance(x_values, list) or len(x_values) < 2:
                continue
            x_label = str(metric_payload.get("x_label") or metric_payload.get("xlabel") or "Operating Point")
            methods = {
                key: value
                for key, value in metric_payload.items()
                if key not in ReporterAgent._X_AXIS_SET and isinstance(value, list) and len(value) == len(x_values)
            }
            if methods:
                yielded_any = True
                yield metric_key, x_values, methods, x_label

        # Flat format: {"proposed": [...], "music": [...], "snr_points": [...], "x_label": "SNR (dB)"}
        # All top-level numeric list values of matching length are treated as curves on one plot.
        if not yielded_any and top_x is not None:
            x_label = str(
                perf_data.get("x_label") or perf_data.get("xlabel")
                or (top_x_key or "operating_point").replace("_", " ").title()
            )
            flat_methods = {
                key: [float(v) for v in value]
                for key, value in perf_data.items()
                if isinstance(value, list)
                and len(value) == len(top_x)
                and key not in ReporterAgent._X_AXIS_SET
                and key not in ("x_label", "xlabel")
                and all(isinstance(v, (int, float)) for v in value)
            }
            if flat_methods:
                yield "performance", top_x, flat_methods, x_label

    @staticmethod
    def _normalize_math_markdown(text: str) -> str:
        normalized = text.replace("\\[", "$$\n").replace("\\]", "\n$$")
        normalized = normalized.replace("\\(", "$ ").replace("\\)", " $")
        normalized = re.sub(r"(?m)^\$\$(.+?)\$\$$", r"$$\n\1\n$$", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized

    @staticmethod
    def _strip_outer_markdown_fence(text: str) -> str:
        stripped = text.strip()
        match = re.match(r"^```(?:markdown|md)?\s*\n([\s\S]*?)\n```\s*$", stripped, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return stripped

    @staticmethod
    def _strip_appendices(text: str) -> str:
        """Remove any Appendix sections the LLM may have generated despite instructions."""
        cleaned = re.sub(
            r"\n## Appendix [A-Z].*?(?=\n## (?!Appendix)|\Z)",
            "",
            text,
            flags=re.DOTALL,
        )
        return cleaned.rstrip()

    @staticmethod
    def _ensure_inline_details(text: str, modeling_details: str, algorithm_details: str) -> str:
        """If the LLM omitted key modeling/algorithm content, inject it into the correct body section."""
        has_modeling = "(No detailed mathematical modeling block available.)" in modeling_details
        has_algorithm = "(No detailed algorithm design block available.)" in algorithm_details

        if not has_modeling:
            # Check if the System Model section is too thin (fewer than 8 non-blank lines)
            model_match = re.search(
                r"(## System Model and Mathematical Formulation\s*\n)(.*?)(?=\n## )",
                text,
                re.DOTALL,
            )
            if model_match:
                section_body = model_match.group(2).strip()
                if len([ln for ln in section_body.splitlines() if ln.strip()]) < 8:
                    new_body = model_match.group(1) + "\n" + modeling_details + "\n\n"
                    text = text[:model_match.start()] + new_body + text[model_match.end():]

        if not has_algorithm:
            algo_match = re.search(
                r"(## Algorithm Design\s*\n)(.*?)(?=\n## )",
                text,
                re.DOTALL,
            )
            if algo_match:
                section_body = algo_match.group(2).strip()
                if len([ln for ln in section_body.splitlines() if ln.strip()]) < 6:
                    new_body = algo_match.group(1) + "\n" + algorithm_details + "\n\n"
                    text = text[:algo_match.start()] + new_body + text[algo_match.end():]

        return text

    @staticmethod
    def _normalize_reliability_section(text: str) -> str:
        lines = text.splitlines()
        start_idx = None
        end_idx = None
        for idx, line in enumerate(lines):
            if re.match(r"^#{1,6}\s+Reliability and Limitations\s*$", line.strip(), re.IGNORECASE):
                start_idx = idx + 1
                break
        if start_idx is None:
            return text
        for idx in range(start_idx, len(lines)):
            if re.match(r"^#{1,2}\s+", lines[idx].strip()):
                end_idx = idx
                break
        if end_idx is None:
            end_idx = len(lines)
        normalized_lines = list(lines)
        for idx in range(start_idx, end_idx):
            stripped = normalized_lines[idx].strip()
            match = re.match(r"^#{3,6}\s+(.*)$", stripped)
            if match:
                heading_text = match.group(1).strip().rstrip(":")
                normalized_lines[idx] = f"- {heading_text}:"
        return "\n".join(normalized_lines)

    @staticmethod
    def _build_footer(task_spec: dict, verification_results: dict, simulation_results: dict) -> str:
        perf_data = simulation_results.get("performance_data") or {}
        # Count methods and operating points
        method_count = 0
        op_count = 0
        for key, val in perf_data.items():
            if key in ReporterAgent._X_AXIS_SET:
                if isinstance(val, list):
                    op_count = len(val)
                continue
            if isinstance(val, list):
                method_count += 1

        parts = [
            "---",
            f"Generated by AutoWiSPA on {datetime.now().isoformat(timespec='seconds')}",
            f"Task category: {task_spec.get('task_category', 'unknown')} | "
            f"Verification: {verification_results.get('status', 'unknown')} | "
            f"Simulation: {simulation_results.get('status', 'unknown')}",
        ]
        if method_count:
            parts.append(f"Methods evaluated: {method_count} | Operating points: {op_count}")
        return "\n".join(parts)