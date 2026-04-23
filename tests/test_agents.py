"""
Agent module unit tests.
"""

import json
import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch


# Allow direct execution via `python tests/test_agents.py` with correct project imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestProblemAnalyzerAgent(unittest.TestCase):
    """ProblemAnalyzerAgent unit tests."""

    def setUp(self):
        with patch("utils.llm_client.LLMClient") as mock_llm:
            mock_llm.return_value.chat.return_value = """{
                "status": "complete",
                "task_spec": {
                    "task_category": "channel_estimation",
                    "system_model": {
                        "waveform": "OFDM",
                        "antenna_config": {"num_tx": 4, "num_rx": 4, "array_type": "ULA"},
                        "channel_model": "3GPP_TDL-A",
                        "mobility_kmh": 30,
                        "carrier_freq_ghz": 3.5,
                        "bandwidth_mhz": 20,
                        "num_subcarriers": 256,
                        "snr_range_db": [-5, 25]
                    },
                    "performance_targets": {
                        "primary_metric": "NMSE",
                        "target_value": -15.0,
                        "target_snr_db": 10,
                        "secondary_metrics": [],
                        "baseline_algorithms": ["LS", "MMSE"]
                    },
                    "constraints": {
                        "pilot_overhead_max": 0.25,
                        "complexity_order": "O(N^3)",
                        "latency_ms": null,
                        "hardware_target": "GPU",
                        "causality_required": false
                    },
                    "design_preferences": {
                        "approach": "auto",
                        "interpretability": "medium",
                        "training_data_available": true,
                        "online_adaptation": false
                    }
                }
            }"""
            from agents.problem_analyzer import ProblemAnalyzerAgent
            self.agent = ProblemAnalyzerAgent()
            self.agent.llm = mock_llm.return_value

    def test_analyze_returns_valid_task_spec(self):
        query = "Design a 4x4 MIMO-OFDM channel estimation algorithm with NMSE target at SNR=10 dB"
        result = self.agent.analyze(query, conversation_history=[])
        self.assertEqual(result["status"], "complete")
        self.assertIn("task_spec", result)
        self.assertEqual(result["task_spec"]["task_category"], "channel_estimation")

    def test_check_completeness_with_full_spec(self):
        spec = {
            "task_category": "channel_estimation",
            "system_model": {
                "waveform": "OFDM",
                "antenna_config": {"num_tx": 4, "num_rx": 4, "array_type": "ULA"},
                "channel_model": "3GPP_TDL-A",
                "mobility_kmh": 30,
                "carrier_freq_ghz": 3.5,
                "bandwidth_mhz": 20,
                "num_subcarriers": 256,
                "snr_range_db": [-5, 25],
            },
            "performance_targets": {
                "primary_metric": "NMSE",
                "target_value": -15.0,
            },
        }
        is_complete, missing = self.agent.check_completeness(spec)
        self.assertTrue(is_complete)
        self.assertEqual(missing, [])

    def test_analyze_parses_reasoning_prefix_and_normalizes_legacy_schema(self):
        self.agent.llm.chat.return_value = """Thinking... (1s elapsed)
        {
            "status": "complete",
            "task_spec": {
                "task_description": "Estimate DoA for an 8-element ULA.",
                "three_dimensions": {
                    "mathematical_essence": "parameter estimation",
                    "processing_object": "angle of arrival",
                    "system_context": "8x1 ULA at 3.5 GHz"
                },
                "system_params": {
                    "carrier_frequency": 3.5,
                    "num_antennas_rx": 8,
                    "waveform": "OFDM",
                    "channel_model": "AWGN",
                    "snr_range_dB": [-5, 25],
                    "additional_params": {"num_sources_assumption": 1}
                },
                "performance_targets": {
                    "primary_metric": "RMSE_deg",
                    "target_value": null,
                    "secondary_metrics": []
                }
            }
        }
        """

        result = self.agent.analyze("Design a DoA estimator", conversation_history=[])

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["task_spec"]["task_category"], "doa_estimation")
        self.assertEqual(result["task_spec"]["system_model"]["carrier_freq_ghz"], 3.5)
        self.assertEqual(result["task_spec"]["system_model"]["antenna_config"]["num_rx"], 8)
        self.assertEqual(result["task_spec"]["system_model"]["snr_range_db"], [-5, 25])
        self.assertEqual(
            result["task_spec"]["system_model"]["additional_params"]["num_sources_assumption"],
            1,
        )


class TestModelFormalizerAgent(unittest.TestCase):
    """ModelFormalizerAgent unit tests."""

    def setUp(self):
        from agents.model_formalizer import ModelFormalizerAgent

        self.agent = ModelFormalizerAgent(llm=MagicMock())
        self.agent.llm.chat.return_value = """{
            "scenario_spec": {
                "signal_type": "OFDM",
                "core_parameters": {"num_tx": 4, "num_rx": 4},
                "snr_range_db": [-5, 20],
                "test_scenarios": [
                    {"name": "nominal", "description": "baseline", "overrides": {}},
                    {"name": "low_snr", "description": "stress", "overrides": {"snr_db": 0}},
                    {"name": "high_mobility", "description": "mobility", "overrides": {"mobility_kmh": 120}}
                ],
                "data_contract": {
                    "inputs": ["pilots", "received_signal"],
                    "expected_outputs": ["channel_estimate", "nmse_db"]
                },
                "generation_notes": "Use deterministic pilot placement."
            },
            "system_model_doc": "The received signal satisfies $y = Hx + n$.",
            "math_formulation": {
                "problem_type": "estimation",
                "objective": {
                    "type": "estimate",
                    "description": "Estimate the channel from pilots.",
                    "formula_latex": "min_H ||Y-XH||_F^2"
                },
                "variables": [{"symbol": "H", "name": "channel", "domain": "C^(4x4)", "description": "channel matrix"}],
                "constraints": [],
                "key_formulas": [],
                "assumptions": ["Gaussian noise"],
                "model_properties": {
                    "convexity": "convex",
                    "closed_form": true,
                    "iterative_required": false,
                    "special_structure": "pilot-aided"
                },
                "formulation_markdown": "Estimate $H$ from pilots."
            },
            "formalization_summary": {
                "design_implications": ["Keep estimator linear."],
                "evaluation_focus": ["NMSE vs SNR"],
                "implementation_risks": ["pilot contamination"]
            }
        }"""

    def test_formalize_returns_consistent_package(self):
        result = self.agent.formalize(
            task_spec={"task_category": "channel_estimation"},
            retrieved_knowledge={"design_insights": "Use pilot-aided LS warm start."},
        )
        self.assertIn("scenario_spec", result)
        self.assertEqual(result["math_formulation"]["problem_type"], "estimation")
        self.assertEqual(len(result["scenario_spec"]["test_scenarios"]), 3)
        self.agent.llm.chat.assert_called_once()
        self.assertEqual(self.agent.llm.chat.call_args.kwargs["max_tokens"], 4000)

    def test_formalize_parses_reasoning_prefix(self):
        self.agent.llm.chat.return_value = """Thinking... (1s elapsed)
        {
            "scenario_spec": {
                "signal_type": "OFDM",
                "core_parameters": {"num_tx": 4, "num_rx": 4},
                "snr_range_db": [-5, 20],
                "test_scenarios": [
                    {"name": "nominal", "description": "baseline", "overrides": {}},
                    {"name": "low_snr", "description": "stress", "overrides": {"snr_db": 0}},
                    {"name": "high_mobility", "description": "mobility", "overrides": {"mobility_kmh": 120}}
                ],
                "data_contract": {"inputs": ["x"], "expected_outputs": ["y"]},
                "generation_notes": "compact"
            },
            "system_model_doc": "doc",
            "math_formulation": {
                "problem_type": "estimation",
                "objective": {"type": "estimate", "description": "desc", "formula_latex": "f"},
                "variables": [],
                "constraints": [],
                "key_formulas": [],
                "assumptions": [],
                "model_properties": {"convexity": "convex", "closed_form": true, "iterative_required": false, "special_structure": "pilot-aided"},
                "formulation_markdown": "markdown"
            },
            "formalization_summary": {"design_implications": [], "evaluation_focus": [], "implementation_risks": []}
        }
        """

        result = self.agent.formalize(task_spec={"task_category": "channel_estimation"})

        self.assertEqual(result["scenario_spec"]["signal_type"], "OFDM")
        self.assertEqual(result["math_formulation"]["problem_type"], "estimation")

    def test_formalize_compacts_overlong_sections(self):
        self.agent.llm.chat.return_value = json.dumps(
            {
                "scenario_spec": {
                    "signal_type": "OFDM",
                    "core_parameters": {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6, "g": 7, "h": 8, "i": 9},
                    "snr_range_db": [-5, 20],
                    "test_scenarios": [
                        {"name": "nominal", "description": "baseline", "overrides": {}},
                        {"name": "low_snr", "description": "stress", "overrides": {"snr_db": 0}},
                        {"name": "high_mobility", "description": "mobility", "overrides": {"mobility_kmh": 120}},
                        {"name": "extra", "description": "should be removed", "overrides": {}},
                    ],
                    "data_contract": {
                        "inputs": ["i1", "i2", "i3", "i4", "i5", "i6", "i7", "i8", "i9"],
                        "expected_outputs": ["o1", "o2", "o3", "o4", "o5", "o6", "o7", "o8", "o9"],
                    },
                    "generation_notes": "This note is intentionally long. " * 50,
                },
                "system_model_doc": "doc " * 500,
                "math_formulation": {
                    "problem_type": "estimation",
                    "objective": {
                        "type": "estimate",
                        "description": "Estimate the channel from pilots.",
                        "formula_latex": "min_H ||Y-XH||_F^2",
                    },
                    "variables": [
                        {"symbol": "v1", "name": "n1", "domain": "d1", "description": "desc1"},
                        {"symbol": "v2", "name": "n2", "domain": "d2", "description": "desc2"},
                        {"symbol": "v3", "name": "n3", "domain": "d3", "description": "desc3"},
                        {"symbol": "v4", "name": "n4", "domain": "d4", "description": "desc4"},
                        {"symbol": "v5", "name": "n5", "domain": "d5", "description": "desc5"},
                        {"symbol": "v6", "name": "n6", "domain": "d6", "description": "desc6"},
                        {"symbol": "v7", "name": "n7", "domain": "d7", "description": "desc7"},
                    ],
                    "constraints": [
                        {"formula_latex": "c1", "description": "c1", "type": "structural"},
                        {"formula_latex": "c2", "description": "c2", "type": "structural"},
                        {"formula_latex": "c3", "description": "c3", "type": "structural"},
                        {"formula_latex": "c4", "description": "c4", "type": "structural"},
                        {"formula_latex": "c5", "description": "c5", "type": "structural"},
                    ],
                    "key_formulas": [
                        {"name": "f1", "formula_latex": "f1", "description": "f1"},
                        {"name": "f2", "formula_latex": "f2", "description": "f2"},
                        {"name": "f3", "formula_latex": "f3", "description": "f3"},
                        {"name": "f4", "formula_latex": "f4", "description": "f4"},
                        {"name": "f5", "formula_latex": "f5", "description": "f5"},
                        {"name": "f6", "formula_latex": "f6", "description": "f6"},
                    ],
                    "assumptions": ["a1", "a2", "a3", "a4", "a5", "a6"],
                    "model_properties": {
                        "convexity": "convex",
                        "closed_form": True,
                        "iterative_required": False,
                        "special_structure": "pilot-aided",
                    },
                    "formulation_markdown": "markdown " * 500,
                },
                "formalization_summary": {
                    "design_implications": ["d1", "d2", "d3", "d4", "d5"],
                    "evaluation_focus": ["e1", "e2", "e3", "e4", "e5"],
                    "implementation_risks": ["r1", "r2", "r3", "r4", "r5"],
                },
            }
        )

        result = self.agent.formalize(task_spec={"task_category": "channel_estimation"})
        self.assertEqual(len(result["scenario_spec"]["core_parameters"]), 9)
        self.assertEqual(len(result["scenario_spec"]["test_scenarios"]), 4)
        self.assertEqual(len(result["scenario_spec"]["data_contract"]["inputs"]), 9)
        self.assertEqual(len(result["scenario_spec"]["data_contract"]["expected_outputs"]), 9)
        self.assertEqual(len(result["math_formulation"]["variables"]), 7)
        self.assertEqual(len(result["math_formulation"]["constraints"]), 5)
        self.assertEqual(len(result["math_formulation"]["key_formulas"]), 6)
        self.assertEqual(len(result["math_formulation"]["assumptions"]), 6)
        self.assertGreater(len(result["system_model_doc"]), 1200)
        self.assertGreater(len(result["math_formulation"]["formulation_markdown"]), 1200)
        self.assertGreater(len(result["scenario_spec"]["generation_notes"]), 400)
        self.assertEqual(len(result["formalization_summary"]["design_implications"]), 5)



class TestReporterAgent(unittest.TestCase):
    """ReporterAgent utility tests."""

    def setUp(self):
        from agents.reporter import ReporterAgent

        self.agent = ReporterAgent(llm=MagicMock())

    def test_generate_strips_outer_markdown_fence(self):
        self.agent.llm.chat.return_value = "```markdown\n# Title\n\nBody\n```"
        report = self.agent.generate(
            task_spec={"task_category": "channel_estimation"},
            retrieved_knowledge={},
            formalization={},
            solution_plan={},
            notebook={"cells": []},
            verification_results={"status": "passed"},
            simulation_results={"status": "success", "raw_results": {"report_assets": {}}},
        )
        self.assertTrue(report.startswith("# Title"))
        self.assertNotIn("```markdown", report)

    def test_generate_appends_math_and_algorithm_appendices(self):
        self.agent.llm.chat.return_value = "# Title\n\nShort body."
        report = self.agent.generate(
            task_spec={"task_category": "localization"},
            retrieved_knowledge={},
            formalization={
                "system_model_doc": "ToA multilateration with Gaussian range noise.",
                "math_formulation": {
                    "objective": {
                        "description": "Minimize squared range residuals.",
                        "formula_latex": r"\hat{\mathbf{p}} = \arg\min_{\mathbf{p}} \sum_i (r_i - \|\mathbf{p} - \mathbf{b}_i\|)^2",
                    },
                    "constraints": [
                        {
                            "description": "Noisy range measurement model.",
                            "formula_latex": r"r_i = \|\mathbf{p} - \mathbf{b}_i\| + w_i",
                        }
                    ],
                },
            },
            solution_plan={
                "architecture": {
                    "summary": "Linearized LS with WLS refinement.",
                    "pseudocode": "1. Simulate ranges. 2. Linearize. 3. Solve LS/WLS.",
                },
                "algorithm_spec": {
                    "pipeline": [
                        {"step": 1, "name": "Linearization", "purpose": "Construct the Jacobian."}
                    ]
                },
            },
            notebook={"cells": []},
            verification_results={"status": "passed"},
            simulation_results={"status": "success", "raw_results": {"report_assets": {}}},
        )
        self.assertIn("## Appendix A: Mathematical Modeling Details", report)
        self.assertIn(r"\hat{\mathbf{p}}", report)
        self.assertIn("## Appendix B: Algorithm Design Details", report)
        self.assertIn("Linearized LS with WLS refinement.", report)

    def test_enrich_notebook_appends_results_sections(self):
        notebook = {"cells": [{"cell_type": "markdown", "metadata": {"autowisp_role": "title"}, "source": ["# Demo\n"]}]}
        enriched = self.agent.enrich_notebook(
            notebook=notebook,
            verification_results={"status": "passed"},
            simulation_results={
                "status": "success",
                "algorithm": "demo",
                "performance_data": {
                    "RMSE_curve": {
                        "x": [0, 5],
                        "x_label": "SNR (dB)",
                        "proposed": [1.0, 0.5],
                        "baseline_linear": [1.2, 0.8],
                    }
                },
                "raw_results": {
                    "report_assets": {
                        "evaluation_summary": "Comparison exported.",
                        "tables": [],
                    }
                },
            },
        )
        roles = [(cell.get("metadata") or {}).get("autowisp_role") for cell in enriched["cells"]]
        self.assertIn("autowisp_results_summary", roles)
        self.assertIn("autowisp_results_tables", roles)


if __name__ == "__main__":
    unittest.main()
