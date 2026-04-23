"""Notebook-first verification for AutoWiSPA."""

from __future__ import annotations

import ast
import re
from typing import Optional


DEFAULT_REQUIRED_ROLES = [
    "title",
    "problem_setup",
    "modeling_summary",
    "imports_setup",
    "data_generation",
    "algorithm_core",
    "evaluation_logic",
    "execution",
]


class VerificationAgent:
    """Validate notebook structure and code cell readiness before simulation."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}

    def verify_notebook(
        self,
        notebook: dict,
        task_spec: Optional[dict] = None,
        solution_plan: Optional[dict] = None,
    ) -> dict:
        errors: list[str] = []
        warnings: list[str] = []

        if not isinstance(notebook, dict) or not notebook.get("cells"):
            return {
                "status": "error",
                "errors": ["Notebook is empty, cannot proceed to simulation"],
                "warnings": [],
                "repair_guidance": ["Generate a notebook with markdown and code cells before verification"],
                "required_roles": self._required_roles(solution_plan or {}),
            }

        cells = notebook.get("cells") or []
        code_cells = [cell for cell in cells if cell.get("cell_type") == "code"]
        markdown_cells = [cell for cell in cells if cell.get("cell_type") == "markdown"]
        if not code_cells:
            errors.append("Notebook contains no code cells")
        if not markdown_cells:
            warnings.append("Notebook contains no markdown explanation cells")

        role_map = self._build_role_map(cells)
        required_roles = self._required_roles(solution_plan or {})
        for role in required_roles:
            if role not in role_map:
                errors.append(f"Missing required notebook role: {role}")

        syntax_errors = self._check_syntax(code_cells)
        errors.extend(syntax_errors)
        warnings.extend(self._check_risky_patterns(code_cells))
        errors.extend(self._check_execution_contract(role_map))
        warnings.extend(self._check_metric_alignment(notebook, task_spec or {}, solution_plan or {}))
        errors.extend(self._check_semantic_contract(role_map, task_spec or {}, solution_plan or {}))
        errors.extend(self._check_evaluation_sweep(role_map, task_spec or {}, solution_plan or {}))
        warnings.extend(self._check_suspicious_patterns(role_map, task_spec or {}, solution_plan or {}))

        status = "passed" if not errors else "error"
        return {
            "status": status,
            "errors": errors,
            "warnings": warnings,
            "repair_guidance": self._build_repair_guidance(errors, warnings),
            "required_roles": required_roles,
            "notebook_summary": {
                "cells": len(cells),
                "code_cells": len(code_cells),
                "markdown_cells": len(markdown_cells),
                "roles": list(role_map.keys()),
            },
        }

    def verify(
        self,
        code_package: dict[str, str],
        task_spec: Optional[dict] = None,
        algorithm_spec: Optional[dict] = None,
    ) -> dict:
        """Compatibility wrapper for legacy call sites."""
        notebook = {
            "cells": [
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": path.rsplit("/", 1)[-1].replace(".py", "")},
                    "source": content.splitlines(keepends=True),
                }
                for path, content in (code_package or {}).items()
            ]
        }
        solution_plan = {"notebook_plan": [{"role": "execution"}]}
        return self.verify_notebook(notebook, task_spec=task_spec, solution_plan=solution_plan)

    @staticmethod
    def _build_role_map(cells: list[dict]) -> dict[str, dict]:
        role_map: dict[str, dict] = {}
        for index, cell in enumerate(cells, start=1):
            role = (cell.get("metadata") or {}).get("autowisp_role", f"cell_{index}")
            role_map[role] = cell
        return role_map

    @staticmethod
    def _required_roles(solution_plan: dict) -> list[str]:
        roles = []
        for item in solution_plan.get("notebook_plan") or []:
            role = str((item or {}).get("role", "")).strip().lower().replace("-", "_").replace(" ", "_")
            if role:
                roles.append(role)
        if not roles:
            roles = list(DEFAULT_REQUIRED_ROLES)
        for role in DEFAULT_REQUIRED_ROLES:
            if role not in roles:
                roles.append(role)
        return roles

    @staticmethod
    def _check_syntax(code_cells: list[dict]) -> list[str]:
        errors = []
        for index, cell in enumerate(code_cells, start=1):
            source = "".join(cell.get("source") or [])
            role = (cell.get("metadata") or {}).get("autowisp_role", f"code_{index}")
            try:
                ast.parse(source)
            except SyntaxError as exc:
                errors.append(f"Syntax error in role '{role}': {exc}")
        return errors

    @staticmethod
    def _check_risky_patterns(code_cells: list[dict]) -> list[str]:
        warnings = []
        risky_tokens = {
            "input(": "Detected input(), may block execution",
            "breakpoint(": "Detected breakpoint(), may pause execution",
            "pdb.set_trace(": "Detected pdb.set_trace(), may pause execution",
            "plt.show(": "Detected plt.show(), may block non-interactive execution",
        }
        for index, cell in enumerate(code_cells, start=1):
            source = "".join(cell.get("source") or [])
            role = (cell.get("metadata") or {}).get("autowisp_role", f"code_{index}")
            for token, message in risky_tokens.items():
                if token in source:
                    warnings.append(f"Role '{role}': {message}")
        return warnings

    @staticmethod
    def _check_execution_contract(role_map: dict[str, dict]) -> list[str]:
        errors = []
        execution_cell = role_map.get("execution")
        evaluation_cell = role_map.get("evaluation_logic")
        if evaluation_cell is None:
            errors.append("Notebook is missing evaluation_logic code cell")
        if execution_cell is None:
            errors.append("Notebook is missing execution code cell")
            return errors
        execution_source = "".join(execution_cell.get("source") or [])
        if "RESULTS" not in execution_source:
            errors.append("Execution cell does not assign RESULTS")

        if evaluation_cell is not None:
            evaluation_source = "".join(evaluation_cell.get("source") or [])
            defines_run_experiment = "def run_experiment" in evaluation_source
            defines_run_evaluation = "def run_evaluation" in evaluation_source
            invokes_supported_runner = any(
                token in execution_source for token in ["run_experiment(", "run_evaluation("]
            )

            if defines_run_experiment and "run_experiment(" not in execution_source and "RESULTS" not in execution_source:
                errors.append("Execution cell does not invoke run_experiment")

            if defines_run_evaluation and not invokes_supported_runner and "RESULTS" not in execution_source:
                errors.append("Execution cell does not invoke run_evaluation")

            if not defines_run_experiment and not defines_run_evaluation and "RESULTS" not in execution_source:
                errors.append("Notebook defines neither run_experiment nor run_evaluation, and execution does not create RESULTS directly")
        return errors

    @staticmethod
    def _check_metric_alignment(notebook: dict, task_spec: dict, solution_plan: dict) -> list[str]:
        warnings = []
        primary_metric = (task_spec.get("performance_targets") or {}).get("primary_metric")
        solution_metrics = [
            (item or {}).get("name")
            for item in ((solution_plan.get("evaluation_plan") or {}).get("primary_metrics") or [])
            if item
        ]
        if primary_metric and solution_metrics and primary_metric not in solution_metrics:
            warnings.append(
                f"Task primary metric '{primary_metric}' is not explicitly listed in evaluation_plan primary_metrics {solution_metrics}"
            )
        roles = [
            (cell.get("metadata") or {}).get("autowisp_role", "")
            for cell in notebook.get("cells") or []
            if cell.get("cell_type") == "code"
        ]
        if "plotting" not in roles:
            warnings.append("Notebook does not contain a plotting code cell")
        return warnings

    @staticmethod
    def _execution_contract(solution_plan: dict, task_spec: dict) -> dict:
        contract = dict(solution_plan.get("execution_contract") or {})
        evaluation_plan = solution_plan.get("evaluation_plan") or {}
        primary_metric = contract.get("primary_metric") or (task_spec.get("performance_targets") or {}).get("primary_metric")
        baseline_methods = contract.get("baseline_methods") or [
            (item or {}).get("name")
            for item in (evaluation_plan.get("baseline_methods") or [])
            if isinstance(item, dict) and (item or {}).get("name")
        ]
        contract.setdefault("primary_metric", primary_metric)
        contract.setdefault("baseline_methods", baseline_methods)
        contract.setdefault("independent_variable", evaluation_plan.get("independent_variable") or "Operating Point")
        contract.setdefault("variable_points", evaluation_plan.get("variable_points") or [])
        contract.setdefault("required_result_keys", ["algorithm", "elapsed_sec", "performance_data", "report_assets"])
        contract.setdefault("comparison_required", bool(contract.get("baseline_methods")))
        return contract

    @staticmethod
    def _baseline_tokens(name: str) -> list[str]:
        cleaned = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
        if not cleaned:
            return []
        tokens = {cleaned, cleaned.replace("_", "")}
        tokens.update(part for part in cleaned.split("_") if len(part) >= 3)
        generic = {"baseline", "method", "proposed", "reference", "algorithm", "estimator"}
        return [token for token in tokens if token not in generic]

    @staticmethod
    def _check_semantic_contract(role_map: dict[str, dict], task_spec: dict, solution_plan: dict) -> list[str]:
        errors = []
        contract = VerificationAgent._execution_contract(solution_plan, task_spec)
        combined_code = "\n".join(
            "".join((cell.get("source") or []))
            for cell in role_map.values()
            if cell.get("cell_type") == "code"
        ).lower()
        combined_text = "\n".join(
            "".join((cell.get("source") or []))
            for cell in role_map.values()
        ).lower()

        primary_metric = str(contract.get("primary_metric") or "").strip().lower()
        if primary_metric and primary_metric not in combined_text:
            errors.append(f"Notebook does not reference the planned primary metric '{contract.get('primary_metric')}'")

        if contract.get("comparison_required"):
            baseline_methods = [item for item in (contract.get("baseline_methods") or []) if item]
            coverage_found = False
            for baseline_name in baseline_methods:
                for token in VerificationAgent._baseline_tokens(baseline_name):
                    if token in combined_code:
                        coverage_found = True
                        break
                if coverage_found:
                    break
            if not coverage_found and baseline_methods:
                errors.append("Notebook does not implement or reference any planned baseline method for comparison")

        required_result_keys = [str(item) for item in (contract.get("required_result_keys") or []) if item]
        execution_source = "".join((role_map.get("execution") or {}).get("source") or [])
        evaluation_source = "".join((role_map.get("evaluation_logic") or {}).get("source") or [])
        result_contract_text = f"{evaluation_source}\n{execution_source}"
        for key in required_result_keys:
            if key == "report_assets":
                continue
            if key not in result_contract_text:
                errors.append(f"Notebook does not preserve required RESULTS key '{key}' in evaluation or execution logic")

        return errors

    @staticmethod
    def _check_suspicious_patterns(role_map: dict[str, dict], task_spec: dict, solution_plan: dict) -> list[str]:
        warnings = []
        evaluation_source = "".join((role_map.get("evaluation_logic") or {}).get("source") or [])
        execution_source = "".join((role_map.get("execution") or {}).get("source") or [])
        combined = f"{evaluation_source}\n{execution_source}".lower()
        if any(token in combined for token in ["placeholder", "dummy", "fake_result", "fabricated"]):
            warnings.append("Notebook contains placeholder-style result generation tokens that may indicate untrustworthy metrics")

        if "report_assets" not in combined:
            warnings.append("Notebook does not expose report_assets explicitly; downstream notebook hardening may need to inject report summaries")

        return warnings

    @staticmethod
    def _check_evaluation_sweep(role_map: dict[str, dict], task_spec: dict, solution_plan: dict) -> list[str]:
        """Check that the notebook actually sweeps operating points instead of replicating a single result."""
        errors = []
        evaluation_source = "".join((role_map.get("evaluation_logic") or {}).get("source") or [])
        execution_source = "".join((role_map.get("execution") or {}).get("source") or [])
        # Only check eval + execution for sweep logic (algorithm_core has legitimate array math)
        sweep_combined = f"{evaluation_source}\n{execution_source}".lower()

        variable_points = (VerificationAgent._execution_contract(solution_plan, task_spec).get("variable_points") or [])
        if len(variable_points) >= 2:
            has_loop = "for " in sweep_combined or "while " in sweep_combined
            has_sweep_call = any(token in sweep_combined for token in [
                "variable_points", "operating_points", "eval_config",
                "snr_points", "snr_db_range", "snr_range",
            ])
            if not has_loop and not has_sweep_call:
                errors.append(
                    "Notebook does not sweep the planned operating points: "
                    "evaluation_logic or execution must loop over the variable axis to produce per-point metrics"
                )

        # Detect replicated-constant pattern only in evaluation/execution code.
        # Use tighter patterns to avoid false positives from NumPy array math (e.g. `arr * 2`).
        replicate_patterns = [
            r"=\s*\[[^\[\]]+\]\s*\*\s*len\(",     # x = [val] * len(...)
            r"=\s*\[[^\[\]]+\]\s*\*\s*\d{2,}",    # x = [val] * 10  (only >=2 digits to skip small constants)
        ]
        for pattern in replicate_patterns:
            if re.search(pattern, sweep_combined):
                errors.append(
                    "Notebook appears to replicate a single metric value across operating points "
                    "instead of computing each point independently (detected array replication pattern)"
                )
                break

        return errors

    @staticmethod
    def _build_repair_guidance(errors: list[str], warnings: list[str]) -> list[str]:
        guidance = []
        if any("Missing required notebook role" in err for err in errors):
            guidance.append("Restore all required notebook roles from the solution plan before rerunning verification")
        if any("Syntax error" in err for err in errors):
            guidance.append("Repair code cell syntax errors before simulation")
        if any("RESULTS" in err for err in errors):
            guidance.append("Ensure the execution cell assigns a RESULTS dict containing algorithm, elapsed_sec, and performance_data")
        if any("run_experiment" in err for err in errors):
            guidance.append("Ensure evaluation_logic defines run_experiment and execution calls it")
        if any("run_evaluation" in err for err in errors):
            guidance.append("Ensure evaluation_logic defines run_evaluation and execution calls it, or create RESULTS directly in execution")
        if any("sweep" in err.lower() or "replicate" in err.lower() for err in errors):
            guidance.append("The evaluation function must loop over each operating point independently; do not compute one value and copy it to all points")
        if any("block" in warn or "pause" in warn for warn in warnings):
            guidance.append("Remove blocking calls such as input, breakpoint, pdb.set_trace, and plt.show")
        if not guidance:
            guidance.append("Notebook verification passed")
        return guidance