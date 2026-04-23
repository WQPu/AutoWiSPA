"""
Utility module unit tests: ComplexityAnalyzer, CodeValidator.
"""

import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# ComplexityAnalyzer tests
# ===========================================================================

class TestComplexityAnalyzerFromCode(unittest.TestCase):
    """ComplexityAnalyzer.estimate_from_code tests."""

    def setUp(self):
        from utils.complexity_analyzer import ComplexityAnalyzer
        self.analyzer = ComplexityAnalyzer()

    def test_empty_function_is_o1(self):
        code = "def f():\n    return 1"
        result = self.analyzer.estimate_from_code(code)
        self.assertEqual(result.time_complexity, "O(1)")

    def test_single_loop_is_on(self):
        code = "for i in range(n):\n    x = i"
        result = self.analyzer.estimate_from_code(code)
        self.assertEqual(result.time_complexity, "O(N)")

    def test_nested_loop_is_on2(self):
        code = (
            "for i in range(n):\n"
            "    for j in range(n):\n"
            "        x = i + j"
        )
        result = self.analyzer.estimate_from_code(code)
        self.assertEqual(result.time_complexity, "O(N²)")
        self.assertTrue(result.has_nested_loops)

    def test_matrix_inverse_detected_on3(self):
        code = "import numpy as np\nA_inv = np.linalg.inv(A)"
        result = self.analyzer.estimate_from_code(code)
        self.assertEqual(result.time_complexity, "O(N³)")
        self.assertIn("matrix", result.dominant_operation)

    def test_fft_detected_onlogn(self):
        code = "import numpy as np\nY = np.fft.fft(x)"
        result = self.analyzer.estimate_from_code(code)
        self.assertEqual(result.time_complexity, "O(N log N)")

    def test_matrix_multiply_operator_detected(self):
        code = "C = A @ B"
        result = self.analyzer.estimate_from_code(code)
        self.assertEqual(result.time_complexity, "O(N³)")

    def test_recursion_detected(self):
        code = (
            "def fib(n):\n"
            "    if n <= 1:\n"
            "        return n\n"
            "    return fib(n-1) + fib(n-2)"
        )
        result = self.analyzer.estimate_from_code(code)
        self.assertIn("ecursi", result.time_complexity)

    def test_syntax_error_returns_gracefully(self):
        result = self.analyzer.estimate_from_code("def f( :")
        self.assertIn("syntax error", result.time_complexity.lower())

    def test_high_cost_ops_appear_in_notes(self):
        code = "import numpy as np\nU, S, Vh = np.linalg.svd(A)"
        result = self.analyzer.estimate_from_code(code)
        self.assertTrue(len(result.notes) > 0)

    def test_space_complexity_on_nested_loop(self):
        code = "for i in range(n):\n    for j in range(n):\n        pass"
        result = self.analyzer.estimate_from_code(code)
        self.assertEqual(result.space_complexity, "O(N²)")

    def test_space_complexity_single_loop(self):
        code = "for i in range(n):\n    pass"
        result = self.analyzer.estimate_from_code(code)
        self.assertEqual(result.space_complexity, "O(N)")


class TestComplexityAnalyzerFromDescription(unittest.TestCase):
    """ComplexityAnalyzer.estimate_from_description tests."""

    def setUp(self):
        from utils.complexity_analyzer import ComplexityAnalyzer
        self.analyzer = ComplexityAnalyzer()

    def test_ls_known_complexity(self):
        result = self.analyzer.estimate_from_description("ls")
        self.assertEqual(result.time_complexity, "O(N³)")

    def test_mmse_known_complexity(self):
        result = self.analyzer.estimate_from_description("mmse")
        self.assertEqual(result.time_complexity, "O(N³)")

    def test_fft_known_complexity(self):
        result = self.analyzer.estimate_from_description("fft")
        self.assertEqual(result.time_complexity, "O(N log N)")

    def test_omp_has_nested_loops(self):
        result = self.analyzer.estimate_from_description("omp")
        self.assertTrue(result.has_nested_loops)

    def test_unknown_algorithm_returns_unknown(self):
        result = self.analyzer.estimate_from_description("nonexistent_algo_xyz")
        self.assertEqual(result.time_complexity, "Unknown")
        self.assertTrue(len(result.notes) > 0)

    def test_case_insensitive(self):
        result = self.analyzer.estimate_from_description("LS")
        self.assertEqual(result.time_complexity, "O(N³)")


# ===========================================================================
# CodeValidator tests
# ===========================================================================

class TestCodeValidatorSyntax(unittest.TestCase):
    """CodeValidator syntax check tests."""

    def setUp(self):
        from utils.code_validator import CodeValidator
        self.validator = CodeValidator()

    def test_valid_code_passes(self):
        code = "import numpy as np\ndef f(x):\n    return np.sum(x)"
        result = self.validator.validate(code)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.syntax_errors, [])

    def test_syntax_error_detected(self):
        code = "def f(x\n    return x"
        result = self.validator.validate(code)
        self.assertFalse(result.is_valid)
        self.assertTrue(len(result.syntax_errors) > 0)

    def test_validate_syntax_only_ok(self):
        ok, err = self.validator.validate_syntax_only("x = 1 + 2")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_validate_syntax_only_fail(self):
        ok, err = self.validator.validate_syntax_only("def :")
        self.assertFalse(ok)
        self.assertIsNotNone(err)


class TestCodeValidatorSecurity(unittest.TestCase):
    """CodeValidator security scan tests."""

    def setUp(self):
        from utils.code_validator import CodeValidator
        self.validator = CodeValidator()

    def test_os_system_flagged(self):
        code = "import os\nos.system('ls')"
        result = self.validator.validate(code)
        self.assertFalse(result.is_valid)
        self.assertTrue(result.has_security_issues)

    def test_eval_flagged(self):
        code = "result = eval('1+1')"
        result = self.validator.validate(code)
        self.assertFalse(result.is_valid)

    def test_exec_flagged(self):
        code = 'exec("import os")'
        result = self.validator.validate(code)
        self.assertFalse(result.is_valid)

    def test_subprocess_flagged(self):
        code = "import subprocess\nsubprocess.run(['ls'])"
        result = self.validator.validate(code)
        self.assertFalse(result.is_valid)

    def test_file_write_flagged(self):
        code = "with open('/tmp/x', 'w') as f:\n    f.write('data')"
        result = self.validator.validate(code)
        self.assertFalse(result.is_valid)

    def test_clean_code_no_security_issues(self):
        code = (
            "import numpy as np\n"
            "def estimate(H, snr):\n"
            "    return np.linalg.pinv(H)"
        )
        result = self.validator.validate(code)
        self.assertFalse(result.has_security_issues)


class TestCodeValidatorStyle(unittest.TestCase):
    """CodeValidator code style check tests."""

    def setUp(self):
        from utils.code_validator import CodeValidator
        self.validator = CodeValidator()

    def test_long_line_flagged(self):
        code = "x = " + "a" * 120  # exceeds 120 characters
        result = self.validator.validate(code)
        self.assertTrue(len(result.style_warnings) > 0)

    def test_wildcard_import_flagged(self):
        code = "from numpy import *"
        result = self.validator.validate(code)
        self.assertTrue(any("import *" in w for w in result.style_warnings))

    def test_normal_import_no_style_warning(self):
        code = "import numpy as np"
        result = self.validator.validate(code)
        self.assertEqual(result.style_warnings, [])


class TestLLMClientPromptEvents(unittest.TestCase):
    """LLMClient event emission tests."""

    def test_llm_start_event_contains_full_prompt_text(self):
        from utils.event_bus import EventBus, EventType
        from utils.llm_client import LLMClient

        bus = EventBus()
        client = LLMClient(backend="mock", model="mock")

        messages = [
            {"role": "system", "content": "You are a test system prompt."},
            {"role": "user", "content": "Please solve this test task."},
        ]

        with patch("utils.llm_client.get_event_bus", return_value=bus), patch.dict(os.environ, {}, clear=False):
            _ = client.chat(messages)

        history = bus.get_history()
        llm_start = next(event for event in history if event.type == EventType.LLM_START)
        self.assertEqual(llm_start.data["model"], "mock")
        self.assertIn("Please solve this test task.", llm_start.data["prompt_preview"])
        self.assertIn("[SYSTEM]", llm_start.data["prompt_text"])
        self.assertIn("You are a test system prompt.", llm_start.data["prompt_text"])
        self.assertIn("[USER]", llm_start.data["prompt_text"])


if __name__ == "__main__":
    unittest.main()
