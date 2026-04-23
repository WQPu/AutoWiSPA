"""Notebook-first simulation agent for AutoWiSPA."""

from __future__ import annotations

import ast
import time
from typing import Optional


class SimulatorAgent:
    """Execute notebook code in the sandbox and collect performance data."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.sandbox = self._build_sandbox()

    def _build_sandbox(self):
        from simulation.sandbox import DockerSandbox, SubprocessSandbox

        sandbox_type = self.config.get("sandbox_type", "subprocess")
        timeout = int(self.config.get("sandbox_timeout", 300))
        if sandbox_type == "docker":
            return DockerSandbox(timeout=timeout)
        return SubprocessSandbox(timeout=timeout)

    def execute(
        self,
        notebook: dict,
        task_spec: dict,
        solution_plan: Optional[dict] = None,
    ) -> dict:
        started_at = time.time()
        sanity = self._sanity_check(notebook)
        if not sanity["passed"]:
            return {
                "status": "error",
                "stage": "sanity_check",
                "error_log": sanity["errors"],
                "execution_time": time.time() - started_at,
            }

        eval_config = self._build_eval_config(task_spec or {}, solution_plan or {})
        results = self.sandbox.run_notebook(notebook=notebook, eval_config=eval_config)
        if results.get("status") == "error":
            return {
                "status": "error",
                "stage": "execution",
                "error_log": results.get("error", "Unknown notebook execution error"),
                "execution_time": time.time() - started_at,
                "eval_config": eval_config,
            }

        payload = results.get("results", results)
        performance_data = payload.get("performance_data") if isinstance(payload, dict) else payload
        if not isinstance(payload, dict):
            payload = {"raw_results": payload}

        robustness = self._run_robustness_tests(notebook, task_spec or {}, solution_plan or {}, eval_config)
        if isinstance(robustness, dict) and robustness.get("status") == "error":
            return {
                "status": "error",
                "stage": "robustness",
                "error_log": robustness.get("error", "Unknown robustness error"),
                "execution_time": time.time() - started_at,
                "eval_config": eval_config,
            }

        merged_perf = performance_data if isinstance(performance_data, dict) else {"raw_results": performance_data}
        if robustness:
            merged_perf = {**merged_perf, "robustness": robustness}

        return {
            "status": "success",
            "evaluation_level": "notebook",
            "performance_data": merged_perf,
            "algorithm": payload.get("algorithm", "unknown"),
            "elapsed_sec": payload.get("elapsed_sec"),
            "execution_time": time.time() - started_at,
            "eval_config": eval_config,
            "raw_results": payload,
        }

    def _sanity_check(self, notebook: dict) -> dict:
        errors = []
        for index, cell in enumerate(notebook.get("cells") or [], start=1):
            if cell.get("cell_type") != "code":
                continue
            source = "".join(cell.get("source") or [])
            try:
                ast.parse(source)
            except SyntaxError as exc:
                role = (cell.get("metadata") or {}).get("autowisp_role", f"code_{index}")
                errors.append(f"SyntaxError in role '{role}': {exc}")
        return {"passed": not errors, "errors": errors}

    def _build_eval_config(self, task_spec: dict, solution_plan: dict) -> dict:
        evaluation_plan = solution_plan.get("evaluation_plan") or {}
        system_model = task_spec.get("system_model") or {}
        variable_points = evaluation_plan.get("variable_points")
        if not variable_points:
            # Try to derive from task spec operating range (may be SNR or other axis)
            operating_range = system_model.get("snr_range_db") or system_model.get("operating_range")
            if isinstance(operating_range, list) and len(operating_range) >= 2:
                start = int(operating_range[0])
                stop = int(operating_range[1])
                step = 5 if stop >= start else -5
                variable_points = list(range(start, stop + step, step))
            else:
                variable_points = [0, 1, 2, 3, 4]
        return {
            "variable_points": variable_points,
            "num_trials": int(evaluation_plan.get("num_monte_carlo") or self.config.get("quick_eval_samples") or 80),
            "primary_metrics": [
                (item or {}).get("name")
                for item in (evaluation_plan.get("primary_metrics") or [])
                if item
            ],
            "baseline_methods": [
                (item or {}).get("name")
                if isinstance(item, dict)
                else item
                for item in (evaluation_plan.get("baseline_methods") or [])
            ],
            "system_model": system_model,
            "performance_targets": task_spec.get("performance_targets") or {},
            "constraints": task_spec.get("constraints") or {},
        }

    def _run_robustness_tests(
        self,
        notebook: dict,
        task_spec: dict,
        solution_plan: dict,
        eval_config: dict,
    ) -> dict:
        original_channel = (task_spec.get("system_model") or {}).get("channel_model", "")
        mismatch_channels = {
            "3GPP_TDL-A": "3GPP_TDL-C",
            "TDL-A": "TDL-C",
            "TDL-C": "TDL-A",
            "Rayleigh": "Rician",
        }
        override = mismatch_channels.get(original_channel)
        if not override:
            return {}

        robustness_config = dict(eval_config)
        robustness_config["channel_override"] = override
        points = eval_config.get("variable_points", [])
        robustness_config["variable_points"] = points[: min(4, len(points))]
        results = self.sandbox.run_notebook(notebook=notebook, eval_config=robustness_config)
        if results.get("status") == "error":
            return {"status": "error", "error": results.get("error", "Robustness execution failed")}
        payload = results.get("results", results)
        return {"channel_mismatch": payload.get("performance_data", payload), "channel_override": override}