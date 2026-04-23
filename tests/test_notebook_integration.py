"""Notebook integration tests for the notebook-first AutoWiSPA pipeline."""

import unittest

from agents.notebook_generator import NotebookGenerator
from agents.verifier import VerificationAgent
from simulation.sandbox import _build_notebook_code_package


def _task_spec() -> dict:
    return {
        "task_category": "doa_estimation",
        "system_model": {
            "waveform": "OFDM",
            "channel_model": "3GPP_TDL-A",
            "snr_range_db": [-10, 20],
        },
        "performance_targets": {"primary_metric": "RMSE"},
    }


def _solution_plan() -> dict:
    return {
        "architecture": {"name": "Notebook Baseline", "strategy_label": "structured"},
        "evaluation_plan": {
            "variable_points": [-10, -5, 0, 5, 10, 15, 20],
            "num_monte_carlo": 20,
            "primary_metrics": [{"name": "RMSE"}],
        },
        "notebook_plan": [
            {"role": "title"},
            {"role": "problem_setup"},
            {"role": "modeling_summary"},
            {"role": "imports_setup"},
            {"role": "data_generation"},
            {"role": "algorithm_core"},
            {"role": "evaluation_logic"},
            {"role": "execution"},
            {"role": "plotting"},
            {"role": "result_notes"},
        ],
    }


class TestNotebookFallback(unittest.TestCase):
    def setUp(self):
        self.generator = NotebookGenerator()
        self.task_spec = _task_spec()
        self.solution_plan = _solution_plan()
        self.notebook = self.generator._build_fallback_notebook(self.task_spec, self.solution_plan, {})

    def test_fallback_notebook_has_expected_roles(self):
        roles = [
            (cell.get("metadata") or {}).get("autowisp_role")
            for cell in self.notebook.get("cells", [])
        ]
        for role in [
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
        ]:
            self.assertIn(role, roles)

    def test_summarize_notebook_reports_counts(self):
        summary = self.generator.summarize_notebook(self.notebook)
        self.assertEqual(summary["cells"], 10)
        self.assertGreaterEqual(summary["code_cells"], 5)
        self.assertIn("execution", summary["code_roles"])

    def test_generation_prompt_embeds_execution_contract(self):
        prompt = self.generator._build_generation_prompt(
            self.task_spec,
            {"relevant_papers": [{"title": "Paper A", "year": 2024}]},
            {},
            self.solution_plan,
        )

        self.assertIn("## Implementation Contract", prompt)
        self.assertIn("baseline_methods", prompt)
        self.assertIn("required_result_keys", prompt)

    def test_extract_code_cells_includes_execution(self):
        code_cells = self.generator.extract_code_cells(self.notebook)
        roles = [cell["role"] for cell in code_cells]
        self.assertIn("execution", roles)
        self.assertIn("evaluation_logic", roles)

    def test_parse_sections_supports_marker_format(self):
        response = """
# ========== MARKDOWN: title ==========
Title cell

# ========== CODE: execution ==========
RESULTS = {"algorithm": "demo", "elapsed_sec": 0.1, "performance_data": {}}
"""
        sections = self.generator._parse_sections(response)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0][0], "markdown")
        self.assertEqual(sections[1][1], "execution")

    def test_finalize_adds_results_contract_when_execution_is_missing_results(self):
        notebook = {
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {"autowisp_role": "title"},
                    "source": ["# Demo\n"],
                },
                {
                    "cell_type": "markdown",
                    "metadata": {"autowisp_role": "problem_setup"},
                    "source": ["setup\n"],
                },
                {
                    "cell_type": "markdown",
                    "metadata": {"autowisp_role": "modeling_summary"},
                    "source": ["model\n"],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "imports_setup"},
                    "source": ["import time\n"],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "data_generation"},
                    "source": ["def generate_dataset(config):\n    return {'x': 1.0}\n"],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "algorithm_core"},
                    "source": ["def estimate(sample):\n    return sample['x']\n"],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "evaluation_logic"},
                    "source": [
                        "def run_evaluation(eval_config):\n",
                        "    return {'algorithm': 'demo', 'elapsed_sec': 0.1, 'performance_data': {'RMSE_vs_SNR': {'snr': [0, 5], 'proposed': [1.0, 0.6]}}}\n",
                    ],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "execution"},
                    "source": ["print('execution without results')\n"],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "plotting"},
                    "source": ["plot_cache = []\n"],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "markdown",
                    "metadata": {"autowisp_role": "result_notes"},
                    "source": ["notes\n"],
                },
            ],
        }

        hardened = self.generator._finalize_notebook(notebook, self.task_spec, self.solution_plan, {}, allow_repair=False)
        result = VerificationAgent().verify_notebook(hardened, self.task_spec, self.solution_plan)

        execution_source = ""
        evaluation_source = ""
        for cell in hardened["cells"]:
            role = (cell.get("metadata") or {}).get("autowisp_role")
            if role == "execution":
                execution_source = "".join(cell.get("source") or [])
            if role == "evaluation_logic":
                evaluation_source = "".join(cell.get("source") or [])

        self.assertIn("AUTO-WISP EXECUTION CONTRACT", execution_source)
        self.assertIn("AUTO-WISP RESULTS HELPER", evaluation_source)
        self.assertEqual(result["status"], "passed")

    def test_finalize_converts_code_role_markdown_into_executable_code(self):
        notebook = {
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {"autowisp_role": "title"},
                    "source": ["# Demo\n"],
                },
                {
                    "cell_type": "markdown",
                    "metadata": {"autowisp_role": "problem_setup"},
                    "source": ["setup\n"],
                },
                {
                    "cell_type": "markdown",
                    "metadata": {"autowisp_role": "modeling_summary"},
                    "source": ["model\n"],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "imports_setup"},
                    "source": ["import time\n"],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "data_generation"},
                    "source": ["DATA = {'snr': [0, 5]}\n"],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "algorithm_core"},
                    "source": ["ALGO = 'demo'\n"],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "markdown",
                    "metadata": {"autowisp_role": "evaluation_logic"},
                    "source": [
                        "# AUTO-WISP RESULTS HELPER\n",
                        "def _autowisp_normalize_results(candidate):\n",
                        "    return candidate\n",
                        "def run_experiment(eval_config=None):\n",
                        "    return {'algorithm': 'demo', 'elapsed_sec': 0.1, 'performance_data': {'RMSE_vs_SNR': {'snr': [0, 5], 'proposed': [1.0, 0.5]}}, 'report_assets': {'tables': []}}\n",
                    ],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "execution"},
                    "source": [
                        "RESULTS = run_experiment({'snr_points': [0, 5]})\n",
                        "RESULTS = _autowisp_normalize_results(RESULTS)\n",
                    ],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "plotting"},
                    "source": ["plot_cache = []\n"],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "markdown",
                    "metadata": {"autowisp_role": "result_notes"},
                    "source": ["notes\n"],
                },
            ],
        }

        hardened = self.generator._finalize_notebook(notebook, self.task_spec, self.solution_plan, {}, allow_repair=False)
        role_to_type = {
            (cell.get("metadata") or {}).get("autowisp_role"): cell.get("cell_type")
            for cell in hardened["cells"]
        }
        code_package = _build_notebook_code_package(hardened)

        self.assertEqual(role_to_type["evaluation_logic"], "code")
        self.assertIn("def _autowisp_normalize_results", code_package["notebook_runtime.py"])
        self.assertIn("run_experiment", code_package["notebook_runtime.py"])

    def test_finalize_comments_narrative_lines_in_invalid_code_cell(self):
        notebook = {
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {"autowisp_role": "title"},
                    "source": ["# Demo\n"],
                },
                {
                    "cell_type": "markdown",
                    "metadata": {"autowisp_role": "problem_setup"},
                    "source": ["setup\n"],
                },
                {
                    "cell_type": "markdown",
                    "metadata": {"autowisp_role": "modeling_summary"},
                    "source": ["model\n"],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "imports_setup"},
                    "source": ["import time\n"],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "data_generation"},
                    "source": ["DATA = {'snr': [0, 5]}\n"],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "algorithm_core"},
                    "source": ["ALGO = 'demo'\n"],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "evaluation_logic"},
                    "source": [
                        "We evaluate the estimator over SNR.\n",
                        "- RMSE in degrees\n",
                        "def run_experiment(eval_config=None):\n",
                        "    return {'algorithm': 'demo', 'elapsed_sec': 0.1, 'performance_data': {'RMSE_vs_SNR': {'snr': [0, 5], 'proposed': [1.0, 0.5]}}, 'report_assets': {'tables': []}}\n",
                    ],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "execution"},
                    "source": ["RESULTS = run_experiment({'snr_points': [0, 5]})\n"],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "code",
                    "metadata": {"autowisp_role": "plotting"},
                    "source": ["plot_cache = []\n"],
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "markdown",
                    "metadata": {"autowisp_role": "result_notes"},
                    "source": ["notes\n"],
                },
            ],
        }

        hardened = self.generator._finalize_notebook(notebook, self.task_spec, self.solution_plan, {}, allow_repair=False)
        result = VerificationAgent().verify_notebook(hardened, self.task_spec, self.solution_plan)
        evaluation_source = next(
            "".join(cell.get("source") or [])
            for cell in hardened["cells"]
            if (cell.get("metadata") or {}).get("autowisp_role") == "evaluation_logic"
        )

        self.assertIn("# We evaluate the estimator over SNR.", evaluation_source)
        self.assertIn("# - RMSE in degrees", evaluation_source)
        self.assertEqual(result["status"], "passed")


class TestNotebookVerification(unittest.TestCase):
    def setUp(self):
        self.generator = NotebookGenerator()
        self.task_spec = _task_spec()
        self.solution_plan = _solution_plan()
        self.notebook = self.generator._build_fallback_notebook(self.task_spec, self.solution_plan, {})
        self.verifier = VerificationAgent()

    def test_verifier_accepts_fallback_notebook(self):
        result = self.verifier.verify_notebook(self.notebook, self.task_spec, self.solution_plan)
        self.assertEqual(result["status"], "passed")

    def test_verifier_rejects_missing_execution_cell(self):
        broken = {
            **self.notebook,
            "cells": [
                cell
                for cell in self.notebook["cells"]
                if (cell.get("metadata") or {}).get("autowisp_role") != "execution"
            ],
        }
        result = self.verifier.verify_notebook(broken, self.task_spec, self.solution_plan)
        self.assertEqual(result["status"], "error")
        self.assertTrue(any("execution" in err for err in result["errors"]))

    def test_verifier_accepts_direct_results_assignment(self):
        direct_results = {
            **self.notebook,
            "cells": [dict(cell) for cell in self.notebook["cells"]],
        }
        for cell in direct_results["cells"]:
            role = (cell.get("metadata") or {}).get("autowisp_role")
            if role == "evaluation_logic":
                cell["source"] = ["THRESHOLD = 0.1\n"]
            if role == "execution":
                cell["source"] = [
                    "RESULTS = {\n",
                    "    'algorithm': 'direct',\n",
                    "    'elapsed_sec': 0.01,\n",
                    "    'performance_data': {'RMSE_vs_SNR': {'snr': [0, 5], 'proposed': [1.0, 0.5]}},\n",
                    "}\n",
                ]

        result = self.verifier.verify_notebook(direct_results, self.task_spec, self.solution_plan)
        self.assertEqual(result["status"], "passed")

    def test_verifier_accepts_run_evaluation_entrypoint(self):
        alt_notebook = {
            **self.notebook,
            "cells": [dict(cell) for cell in self.notebook["cells"]],
        }
        for cell in alt_notebook["cells"]:
            role = (cell.get("metadata") or {}).get("autowisp_role")
            if role == "evaluation_logic":
                cell["source"] = [
                    "def run_evaluation(eval_config):\n",
                    "    return {'algorithm': 'alt', 'elapsed_sec': 0.02, 'performance_data': {'RMSE_vs_SNR': {'snr': [0, 5], 'proposed': [1.0, 0.6]}}}\n",
                ]
            if role == "execution":
                cell["source"] = ["RESULTS = run_evaluation({'snr_points': [0, 5]})\n"]

        result = self.verifier.verify_notebook(alt_notebook, self.task_spec, self.solution_plan)
        self.assertEqual(result["status"], "passed")

    def test_verifier_rejects_missing_planned_baseline_coverage(self):
        plan = {
            **self.solution_plan,
            "execution_contract": {
                "primary_metric": "RMSE",
                "baseline_methods": ["MUSIC"],
                "required_roles": [item["role"] for item in self.solution_plan["notebook_plan"]],
                "required_result_keys": ["algorithm", "elapsed_sec", "performance_data", "report_assets"],
                "comparison_required": True,
            },
        }
        broken = {
            **self.notebook,
            "cells": [dict(cell) for cell in self.notebook["cells"]],
        }
        for cell in broken["cells"]:
            role = (cell.get("metadata") or {}).get("autowisp_role")
            if role == "evaluation_logic":
                cell["source"] = [
                    "def run_experiment(eval_config=None):\n",
                    "    return {'algorithm': 'demo', 'elapsed_sec': 0.1, 'performance_data': {'RMSE_curve': {'x': [0, 5], 'proposed': [1.0, 0.5]}}, 'report_assets': {'problem_summary': 'ok', 'solution_summary': 'ok', 'evaluation_summary': 'ok', 'tables': [], 'figures': []}}\n",
                ]
            if role == "plotting":
                cell["source"] = ["comparison_artifacts = []\n"]

        result = self.verifier.verify_notebook(broken, self.task_spec, plan)

        self.assertEqual(result["status"], "error")
        self.assertTrue(any("baseline" in err.lower() for err in result["errors"]))
