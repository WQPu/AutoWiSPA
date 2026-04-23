"""Tests for the notebook-first AutoWiSPA graph."""

import unittest

from graph.nodes import _preserve_task_intent


class TestGraphRoutes(unittest.TestCase):
    def setUp(self):
        from graph.edges import (
            route_after_problem_analysis,
            route_after_simulation,
            route_after_verification,
        )

        self.route_after_problem_analysis = route_after_problem_analysis
        self.route_after_simulation = route_after_simulation
        self.route_after_verification = route_after_verification

    def test_problem_analysis_routes_to_knowledge_retrieval(self):
        self.assertEqual(
            self.route_after_problem_analysis({"task_spec_complete": True}),
            "knowledge_retrieval",
        )

    def test_problem_analysis_ends_when_spec_incomplete(self):
        self.assertEqual(
            self.route_after_problem_analysis({"task_spec_complete": False}),
            "__end__",
        )

    def test_verification_routes_to_simulation_on_pass(self):
        state = {"verification_results": {"status": "passed"}}
        self.assertEqual(self.route_after_verification(state), "simulation")

    def test_verification_routes_back_to_notebook_generation_on_retry(self):
        state = {
            "verification_results": {"status": "error"},
            "verification_retry_count": 0,
            "max_verification_retries": 2,
        }
        self.assertEqual(self.route_after_verification(state), "notebook_generation")

    def test_verification_routes_to_report_after_retry_limit(self):
        state = {
            "verification_results": {"status": "error"},
            "verification_retry_count": 2,
            "max_verification_retries": 2,
        }
        self.assertEqual(self.route_after_verification(state), "report_generation")

    def test_simulation_routes_back_to_notebook_generation_on_retry(self):
        state = {
            "simulation_results": {"status": "error"},
            "simulation_retry_count": 0,
            "max_simulation_retries": 1,
        }
        self.assertEqual(self.route_after_simulation(state), "notebook_generation")

    def test_simulation_routes_to_report_after_retry_limit(self):
        state = {
            "simulation_results": {"status": "error"},
            "simulation_retry_count": 1,
            "max_simulation_retries": 1,
        }
        self.assertEqual(self.route_after_simulation(state), "report_generation")


class TestGraphBuild(unittest.TestCase):
    def test_graph_compiles(self):
        from graph.builder import build_autowisp_graph

        graph = build_autowisp_graph({})
        self.assertEqual(type(graph).__name__, "CompiledStateGraph")


class TestTaskSpecPreservation(unittest.TestCase):
    def test_refinement_keeps_existing_fields_when_overlay_is_partial(self):
        base_spec = {
            "task_category": "doa_estimation",
            "task_description": "Estimate direction of arrival on an 8-element ULA.",
            "three_dimensions": {"mathematical_essence": "angle estimation"},
            "system_model": {
                "waveform": "OFDM",
                "channel_model": "AWGN",
                "snr_range_db": [-5, 25],
            },
            "performance_targets": {
                "primary_metric": "RMSE_deg",
                "secondary_metrics": ["latency_ms"],
            },
        }
        overlay = {
            "system_model": {"waveform": "OFDM"},
            "performance_targets": {"primary_metric": "NMSE"},
        }

        merged = _preserve_task_intent(base_spec, overlay)

        self.assertEqual(merged["task_description"], base_spec["task_description"])
        self.assertEqual(merged["three_dimensions"], base_spec["three_dimensions"])
        self.assertEqual(merged["system_model"]["channel_model"], "AWGN")
        self.assertEqual(merged["system_model"]["snr_range_db"], [-5, 25])
        self.assertEqual(merged["performance_targets"]["primary_metric"], "RMSE_deg")

    def test_refinement_can_update_metric_for_non_doa_tasks(self):
        base_spec = {
            "task_category": "channel_estimation",
            "performance_targets": {"primary_metric": "BER"},
        }
        overlay = {
            "performance_targets": {"primary_metric": "NMSE"},
        }

        merged = _preserve_task_intent(base_spec, overlay)

        self.assertEqual(merged["performance_targets"]["primary_metric"], "NMSE")


class TestSolutionPlanNormalization(unittest.TestCase):
    def test_normalization_restores_required_roles_and_execution_contract(self):
        from graph.nodes import _normalize_solution_plan

        plan = {
            "architecture": {"name": "Sparse Baseline"},
            "evaluation_plan": {"baseline_methods": [{"name": "MUSIC"}]},
            "notebook_plan": [{"role": "title", "cell_type": "markdown"}],
        }
        task_spec = {
            "task_category": "doa_estimation",
            "system_model": {"snr_range_db": [-5, 15]},
            "performance_targets": {"primary_metric": "RMSE_deg"},
        }

        normalized = _normalize_solution_plan(task_spec, plan)

        roles = [item["role"] for item in normalized["notebook_plan"]]
        self.assertIn("execution", roles)
        self.assertIn("evaluation_logic", roles)
        self.assertEqual(normalized["execution_contract"]["primary_metric"], "RMSE_deg")
        self.assertIn("MUSIC", normalized["execution_contract"]["baseline_methods"])
