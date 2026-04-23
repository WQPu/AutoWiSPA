"""
Knowledge base module unit tests.
"""

import unittest
import json
import tempfile
import os
from pathlib import Path


class TestAlgorithmRetriever(unittest.TestCase):
    """AlgorithmRetriever unit tests."""

    def setUp(self):
        # Create temporary knowledge base directory
        self.tmpdir = tempfile.mkdtemp()
        # Write minimal test data
        test_data = {
            "algorithms": [
                {
                    "id": "LS_CE",
                    "name": "Least Squares Channel Estimation",
                    "task_type": "channel_estimation",
                    "system_type": ["OFDM"],
                    "complexity": "O(N_pilot)",
                    "description": "Direct least squares estimation at pilot subcarriers.",
                    "keywords": ["ls", "channel estimation", "pilots"],
                }
            ]
        }
        algo_dir = Path(self.tmpdir) / "algorithms"
        algo_dir.mkdir()
        with open(algo_dir / "channel_estimation.json", "w") as f:
            json.dump(test_data, f)

        from knowledge_base.retriever import AlgorithmRetriever
        self.retriever = AlgorithmRetriever(algorithms_dir=str(algo_dir))

    def test_retrieve_returns_list(self):
        results = self.retriever.retrieve(
            task_type="channel_estimation",
            query="OFDM least squares",
        )
        self.assertIsInstance(results, list)

    def test_retrieve_finds_known_algorithm(self):
        results = self.retriever.retrieve(
            task_type="channel_estimation",
            query="least squares pilots OFDM",
            top_k=5,
        )
        ids = [r.get("id", "") for r in results]
        self.assertIn("LS_CE", ids)

    def test_retrieve_empty_for_unknown_task(self):
        # Unknown task type should not raise an error
        results = self.retriever.retrieve(
            task_type="nonexistent_task",
            query="something",
        )
        self.assertIsInstance(results, list)


class TestBenchmarkRetriever(unittest.TestCase):
    """BenchmarkRetriever unit tests."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        bm_data = {
            "task_type": "channel_estimation",
            "system": "MIMO-OFDM",
            "benchmarks": {
                "LS": {"snr_db": [-5, 0, 5, 10], "nmse_db": [-3, -6, -9, -12]},
                "MMSE": {"snr_db": [-5, 0, 5, 10], "nmse_db": [-8, -12, -16, -20]},
            }
        }
        with open(os.path.join(self.tmpdir, "ce_mimo_ofdm.json"), "w") as f:
            json.dump(bm_data, f)

        from knowledge_base.retriever import BenchmarkRetriever
        self.retriever = BenchmarkRetriever(benchmarks_dir=self.tmpdir)

    def test_get_benchmark_returns_dict(self):
        result = self.retriever.get_benchmark("ce_mimo_ofdm")
        self.assertIsInstance(result, dict)
        self.assertIn("benchmarks", result)

    def test_get_benchmark_none_for_unknown(self):
        result = self.retriever.get_benchmark("nonexistent")
        self.assertIsNone(result)


class TestKnowledgeBaseBuilder(unittest.TestCase):
    """KnowledgeBaseBuilder smoke test (no ChromaDB required)."""

    def test_builder_instantiation(self):
        from knowledge_base.builder import KnowledgeBaseBuilder
        with tempfile.TemporaryDirectory() as tmpdir:
            # Should be instantiable (graceful degradation if chromadb is not installed)
            try:
                builder = KnowledgeBaseBuilder(persist_directory=tmpdir)
                self.assertIsNotNone(builder)
            except ImportError:
                self.skipTest("chromadb not installed")


if __name__ == "__main__":
    unittest.main()
