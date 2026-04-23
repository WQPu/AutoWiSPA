"""
Algorithm complexity analysis tool
Estimates time/space complexity of code via AST static analysis
"""

from __future__ import annotations

import ast
import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ComplexityEstimate:
    time_complexity: str         # e.g. "O(N^3)", "O(N log N)"
    space_complexity: str        # e.g. "O(N^2)"
    flops_estimate: Optional[str] = None   # e.g. "~2*N^3 FLOPs (matrix multiply)"
    has_nested_loops: bool = False
    dominant_operation: str = "unknown"
    notes: list[str] = None

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


class ComplexityAnalyzer:
    """
    Code complexity static analyzer

    Uses heuristic rules:
    - Detect nested loop depth → polynomial complexity
    - Recognize numpy matrix operations → FLOPs estimation
    - Recognize recursion → recursive complexity hint
    """

    # Common FLOPs patterns for numpy/scipy operations
    HIGH_COST_PATTERNS = [
        (r"np\.linalg\.inv\s*\(", "Matrix inversion O(N³)"),
        (r"np\.linalg\.svd\s*\(", "SVD decomposition O(N³)"),
        (r"np\.linalg\.eig\s*\(", "Eigendecomposition O(N³)"),
        (r"np\.dot\s*\(|@", "Matrix multiplication O(N³)"),
        (r"np\.fft\.fft\s*\(", "FFT O(N log N)"),
        (r"np\.linalg\.solve\s*\(", "Linear system solve O(N³)"),
        (r"scipy\.optimize\.", "Numerical optimization (iterative)"),
    ]

    def estimate_from_code(self, code: str) -> ComplexityEstimate:
        """
        Estimate complexity from Python source code

        Returns:
            ComplexityEstimate object
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return ComplexityEstimate(
                time_complexity="Unknown (syntax error)",
                space_complexity="Unknown",
            )

        loop_depth = self._max_loop_depth(tree)
        has_recursion = self._has_recursion(tree)
        high_cost_ops = self._find_high_cost_ops(code)

        return self._build_estimate(loop_depth, has_recursion, high_cost_ops)

    def estimate_from_description(self, algorithm_name: str, n_param: str = "N") -> ComplexityEstimate:
        """
        Return known complexity by algorithm name (knowledge base lookup)
        """
        db = {
            "ls": ComplexityEstimate("O(N³)", "O(N²)", "2N³ FLOPs", False, "pseudo-inverse"),
            "mmse": ComplexityEstimate("O(N³)", "O(N²)", "2N³ + N FLOPs", False, "matrix inversion"),
            "omp": ComplexityEstimate("O(K·N·M)", "O(KN)", None, True, "sparse pursuit"),
            "admm": ComplexityEstimate("O(T·N³)", "O(N²)", None, True, "iterative"),
            "fft": ComplexityEstimate("O(N log N)", "O(N)", None, False, "FFT"),
            "svd": ComplexityEstimate("O(N³)", "O(N²)", "4/3 N³ FLOPs", False, "SVD"),
        }
        key = algorithm_name.lower().replace("-", "_").replace(" ", "_")
        if key in db:
            return db[key]
        return ComplexityEstimate(
            time_complexity="Unknown",
            space_complexity="Unknown",
            notes=[f"No known complexity for '{algorithm_name}'"],
        )

    # ------------------------------------------------------------------
    # AST analysis helpers
    # ------------------------------------------------------------------

    def _max_loop_depth(self, tree: ast.AST) -> int:
        """Recursively compute maximum loop nesting depth"""
        return self._loop_depth_visitor(tree, 0)

    def _loop_depth_visitor(self, node: ast.AST, current_depth: int) -> int:
        max_depth = current_depth
        for child in ast.walk(node):
            if isinstance(child, (ast.For, ast.While)):
                depth = current_depth + 1
                for grandchild in ast.walk(child):
                    if grandchild is not child and isinstance(grandchild, (ast.For, ast.While)):
                        depth = max(depth, current_depth + 2)
                max_depth = max(max_depth, depth)
        return max_depth

    def _has_recursion(self, tree: ast.AST) -> bool:
        """Detect whether recursive function calls exist"""
        func_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in func_names:
                    return True
        return False

    def _find_high_cost_ops(self, code: str) -> list[str]:
        found = []
        for pattern, desc in self.HIGH_COST_PATTERNS:
            if re.search(pattern, code):
                found.append(desc)
        return found

    def _build_estimate(
        self,
        loop_depth: int,
        has_recursion: bool,
        high_cost_ops: list[str],
    ) -> ComplexityEstimate:
        notes = []

        # Determine polynomial order from nested loop depth
        poly_map = {0: "O(1)", 1: "O(N)", 2: "O(N²)", 3: "O(N³)", 4: "O(N⁴)"}
        loop_complexity = poly_map.get(loop_depth, f"O(N^{loop_depth})")

        # High-cost operations typically dominate complexity
        if "Matrix inversion O(N³)" in high_cost_ops or "Matrix multiplication O(N³)" in high_cost_ops:
            time_complexity = "O(N³)"
            dominant = "matrix operations"
            flops = "~2N³ FLOPs"
        elif "FFT O(N log N)" in high_cost_ops:
            time_complexity = "O(N log N)"
            dominant = "FFT"
            flops = "~5N log₂N FLOPs"
        elif has_recursion:
            time_complexity = "Recursive (needs further analysis)"
            dominant = "recursion"
            flops = None
            notes.append("Recursion detected; please manually analyze exact complexity")
        else:
            time_complexity = loop_complexity
            dominant = f"{loop_depth}-level nested loops"
            flops = None

        if high_cost_ops:
            notes.extend([f"High-cost operation detected: {op}" for op in high_cost_ops])

        space_complexity = "O(N²)" if loop_depth >= 2 else "O(N)"

        return ComplexityEstimate(
            time_complexity=time_complexity,
            space_complexity=space_complexity,
            flops_estimate=flops,
            has_nested_loops=loop_depth > 1,
            dominant_operation=dominant,
            notes=notes,
        )
