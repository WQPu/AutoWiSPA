"""Simulation tests for the notebook-first AutoWiSPA flow."""

import unittest

from agents.notebook_generator import NotebookGenerator
from agents.simulator import SimulatorAgent


def _task_spec() -> dict:
    return {
        "task_category": "channel_estimation",
        "system_model": {
            "waveform": "OFDM",
            "channel_model": "3GPP_TDL-A",
            "snr_range_db": [-5, 15],
        },
        "performance_targets": {"primary_metric": "NMSE"},
        "constraints": {},
    }


def _solution_plan() -> dict:
    return {
        "architecture": {"name": "Notebook Baseline", "strategy_label": "structured"},
        "evaluation_plan": {
            "variable_points": [-5, 0, 5, 10, 15],
            "num_monte_carlo": 8,
            "primary_metrics": [{"name": "NMSE"}],
            "baseline_methods": [{"name": "baseline_linear"}],
        },
        "notebook_plan": [{"role": role} for role in [
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
        ]],
    }


class TestNotebookSimulation(unittest.TestCase):
    def setUp(self):
        generator = NotebookGenerator()
        self.task_spec = _task_spec()
        self.solution_plan = _solution_plan()
        self.notebook = generator._build_fallback_notebook(self.task_spec, self.solution_plan, {})

    def test_simulator_executes_notebook(self):
        simulator = SimulatorAgent(config={"sandbox_timeout": 20})
        results = simulator.execute(self.notebook, self.task_spec, self.solution_plan)
        self.assertEqual(results["status"], "success")
        self.assertIn("performance_data", results)
        self.assertIn("NMSE_curve", results["performance_data"])
        report_assets = (results.get("raw_results") or {}).get("report_assets") or {}
        self.assertTrue(report_assets.get("tables"))
        self.assertTrue(report_assets.get("figures") or report_assets.get("figures_metadata"))

    def test_simulator_returns_robustness_block(self):
        simulator = SimulatorAgent(config={"sandbox_timeout": 20})
        results = simulator.execute(self.notebook, self.task_spec, self.solution_plan)
        self.assertEqual(results["status"], "success")
        self.assertIn("robustness", results["performance_data"])
        self.assertIn("channel_mismatch", results["performance_data"]["robustness"])

    def test_simulator_reports_sanity_errors(self):
        broken = {
            **self.notebook,
            "cells": [dict(cell) for cell in self.notebook["cells"]],
        }
        for cell in broken["cells"]:
            if cell.get("cell_type") == "code" and (cell.get("metadata") or {}).get("autowisp_role") == "execution":
                cell["source"] = ["def broken(:\n"]
                break
        simulator = SimulatorAgent(config={"sandbox_timeout": 20})
        results = simulator.execute(broken, self.task_spec, self.solution_plan)
        self.assertEqual(results["status"], "error")
        self.assertEqual(results["stage"], "sanity_check")
