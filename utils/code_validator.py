"""
Python code validation tool
Provides syntax checking, AST-level static analysis, and security scanning

Inspired by AutoResearchClaw's validator.py:
- AST-level forbidden import checking (subprocess, os, shutil, etc.)
- AST-level forbidden callable checking (os.system, eval, exec, etc.)
- format_issues_for_llm() for repair prompt usage
"""

from __future__ import annotations

import ast
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Dangerous call patterns forbidden in generated code (regex fallback)
DANGEROUS_PATTERNS = [
    r"\bos\.system\s*\(",
    r"\bsubprocess\.",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\b__import__\s*\(",
    r"\bopen\s*\(.*['\"]w['\"]",   # write file
    r"\bshutil\.rmtree\s*\(",
    r"\bos\.remove\s*\(",
]

# AST-level forbidden module imports
FORBIDDEN_IMPORTS: frozenset[str] = frozenset({
    "subprocess", "shutil", "socket", "http",
    "urllib", "requests", "ftplib", "smtplib",
    "webbrowser", "xmlrpc", "multiprocessing",
})

# AST-level forbidden callables (module.function format)
FORBIDDEN_CALLABLES: frozenset[str] = frozenset({
    "os.system", "os.popen", "os.exec", "os.execvp", "os.spawn",
    "os.remove", "os.unlink", "os.rmdir", "os.makedirs",
    "subprocess.run", "subprocess.call", "subprocess.Popen",
    "shutil.rmtree", "shutil.move", "shutil.copy",
    "eval", "exec", "compile", "__import__",
})

# Risky but not forbidden patterns (generate warnings instead of errors)
RISKY_PATTERNS: list[str] = [
    "input(",       # may cause sandbox to hang
    "plt.show(",    # may cause sandbox to hang
    "pdb.set_trace",
    "breakpoint()",
    "cv2.imshow(",
]


@dataclass
class ValidationResult:
    is_valid: bool
    syntax_errors: list[str] = field(default_factory=list)
    security_warnings: list[str] = field(default_factory=list)
    style_warnings: list[str] = field(default_factory=list)

    @property
    def has_security_issues(self) -> bool:
        return len(self.security_warnings) > 0


class CodeValidator:
    """Code validator: syntax + security scan + basic style check"""

    def validate(self, code: str, filename: str = "<generated>") -> ValidationResult:
        """
        Comprehensive code validation

        Args:
            code: Python source code string
            filename: Filename displayed in error messages

        Returns:
            ValidationResult
        """
        result = ValidationResult(is_valid=True)

        # 1. Syntax check
        syntax_ok = self._check_syntax(code, filename, result)
        if not syntax_ok:
            result.is_valid = False

        # 2. Security scan (attempt even if syntax has errors)
        self._check_security(code, result)
        if result.has_security_issues:
            result.is_valid = False

        # 3. Basic style
        self._check_style(code, result)

        return result

    def validate_syntax_only(self, code: str) -> tuple[bool, Optional[str]]:
        """Quick syntax check, returns (is_ok, error_message)"""
        try:
            ast.parse(code)
            return True, None
        except SyntaxError as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # Internal checkers
    # ------------------------------------------------------------------

    def _check_syntax(self, code: str, filename: str, result: ValidationResult) -> bool:
        try:
            ast.parse(code, filename=filename)
            return True
        except SyntaxError as exc:
            result.syntax_errors.append(f"SyntaxError at line {exc.lineno}: {exc.msg}")
            return False

    def _check_security(self, code: str, result: ValidationResult) -> None:
        # Regex-based patterns (fast fallback)
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, code):
                result.security_warnings.append(
                    f"Dangerous pattern detected: {pattern}"
                )

        # AST-based import & callable checks (more precise)
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return  # Syntax check already reported

        for node in ast.walk(tree):
            # Check forbidden imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_module = alias.name.split(".")[0]
                    if top_module in FORBIDDEN_IMPORTS:
                        result.security_warnings.append(
                            f"Forbidden import at line {node.lineno}: {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top_module = node.module.split(".")[0]
                    if top_module in FORBIDDEN_IMPORTS:
                        result.security_warnings.append(
                            f"Forbidden import at line {node.lineno}: from {node.module}"
                        )

            # Check forbidden callables
            if isinstance(node, ast.Call):
                call_name = self._resolve_call_name(node)
                if call_name in FORBIDDEN_CALLABLES:
                    result.security_warnings.append(
                        f"Forbidden call at line {node.lineno}: {call_name}"
                    )

        # Risky patterns (warnings, not errors)
        for pattern in RISKY_PATTERNS:
            if pattern in code:
                result.style_warnings.append(
                    f"Risky pattern (may cause sandbox hang): {pattern}"
                )

    @staticmethod
    def _resolve_call_name(node: ast.Call) -> str:
        """Resolve a call node to its dotted name string."""
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            parts = []
            current = func
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        return ""

    def _check_style(self, code: str, result: ValidationResult) -> None:
        lines = code.splitlines()
        for i, line in enumerate(lines, start=1):
            if len(line) > 120:
                result.style_warnings.append(f"Line {i} exceeds 120 characters")
        if "import *" in code:
            result.style_warnings.append("Wildcard import detected (import *)")


def format_issues_for_llm(result: ValidationResult) -> str:
    """Format validation issues as text for LLM repair prompt.

    Returns a concise, actionable summary string that can be injected
    into a code-repair prompt.
    """
    lines: list[str] = []
    for err in result.syntax_errors:
        lines.append(f"- [SYNTAX ERROR] {err}")
    for warn in result.security_warnings:
        lines.append(f"- [SECURITY] {warn}")
    for warn in result.style_warnings:
        lines.append(f"- [WARNING] {warn}")
    return "\n".join(lines) if lines else "No issues found."
