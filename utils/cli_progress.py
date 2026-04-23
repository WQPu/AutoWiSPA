"""
Terminal progress reporting for AutoWiSPA CLI runs.

Design: Print clean stage separators and timing. Detailed node output
is handled by Python logging (RichHandler) via ``_log_trace`` in nodes.py,
which is shared with the web dashboard — keeping both outputs consistent.
"""

from __future__ import annotations

import time
from typing import Optional

from utils.event_bus import Event, EventBus, EventType


STAGE_ORDER = [
    "problem_analysis",
    "knowledge_retrieval",
    "model_formulation",
    "solution_planning",
    "notebook_generation",
    "verification",
    "simulation",
    "report_generation",
    "result_review",
]

STAGE_LABELS = {
    "problem_analysis": "Problem Analysis",
    "knowledge_retrieval": "Knowledge Retrieval",
    "model_formulation": "Model Formulation",
    "solution_planning": "Solution Planning",
    "notebook_generation": "Notebook Generation",
    "verification": "Verification",
    "simulation": "Simulation",
    "report_generation": "Report Generation",
    "result_review": "Result Review",
}

LINE_WIDTH = 62


class CliProgressReporter:
    """Clean terminal progress reporter backed by the event bus.

    Prints visual stage headers and completion markers.  All detailed
    information (task type, paper counts, verification status, etc.)
    comes from ``logging.info`` in the pipeline nodes so the CLI and
    web dashboard share identical informational output.
    """

    def __init__(self) -> None:
        self.total = len(STAGE_ORDER)
        self._start_times: dict[str, float] = {}
        self._visit_count: dict[str, int] = {}

    def attach(self, bus: EventBus) -> "CliProgressReporter":
        bus.subscribe(self._handle_event)
        return self

    # ── helpers ──────────────────────────────────────────────

    @staticmethod
    def _idx(node: str) -> Optional[int]:
        if node in STAGE_ORDER:
            return STAGE_ORDER.index(node) + 1
        return None

    @staticmethod
    def _print(text: str) -> None:
        print(text, flush=True)

    # ── event handler ───────────────────────────────────────

    def _handle_event(self, event: Event) -> None:
        etype = event.type

        # ── Stage start: draw a separator header ────────────
        if etype == EventType.NODE_START:
            idx = self._idx(event.node)
            if idx is None:
                return
            label = STAGE_LABELS[event.node]
            self._start_times[event.node] = time.time()
            count = self._visit_count.get(event.node, 0) + 1
            self._visit_count[event.node] = count
            suffix = f" · retry {count - 1}" if count > 1 else ""
            header = f"[{idx}/{self.total}] {label}{suffix}"
            pad = max(1, LINE_WIDTH - len(header) - 5)
            self._print(f"\n─── {header} " + "─" * pad)
            return

        # ── Stage end: one-line completion with elapsed time ─
        if etype == EventType.NODE_END:
            idx = self._idx(event.node)
            if idx is None:
                return
            label = STAGE_LABELS[event.node]
            elapsed = time.time() - self._start_times.get(event.node, time.time())
            summary = str(event.data.get("summary", ""))
            first_line = summary.strip().split("\n", 1)[0].lower()
            mark = "✗" if "error" in first_line else "✓"
            self._print(f"[{idx}/{self.total}] {mark} {label} ({elapsed:.1f}s)")
            return

        # ── LLM call: subtle single-line indicator ──────────
        if etype == EventType.LLM_START:
            model = event.data.get("model", "unknown")
            prompt_est = event.data.get("prompt_tokens_est")
            token_info = f"  (~{prompt_est} prompt tokens)" if prompt_est else ""
            self._print(f"    ⟡ Calling {model}{token_info} …")
            self._llm_start_time = time.time()
            return

        # ── LLM response: show preview + token usage ────────
        if etype == EventType.LLM_END:
            model = event.data.get("model", "unknown")
            preview = event.data.get("response_preview", "")
            elapsed = time.time() - getattr(self, "_llm_start_time", time.time())
            # Prefer real tokens; fall back to estimates
            is_est = "total_tokens_est" in event.data
            prompt_t = event.data.get("prompt_tokens") or event.data.get("prompt_tokens_est")
            comp_t = event.data.get("completion_tokens") or event.data.get("completion_tokens_est")
            total_t = event.data.get("total_tokens") or event.data.get("total_tokens_est")
            prefix = "~" if is_est else ""
            parts: list[str] = [f"{elapsed:.1f}s"]
            if comp_t:
                parts.append(f"{prefix}{comp_t} completion")
            if total_t:
                parts.append(f"{prefix}{total_t} total tokens")
            token_info = ", ".join(parts)
            self._print(f"    ✦ {model} replied ({token_info})")
            if preview:
                clipped = preview[:120].replace("\n", " ")
                if len(preview) > 120:
                    clipped += "…"
                self._print(f"      ↳ {clipped}")
            return

        # ── Sandbox lifecycle ───────────────────────────────
        if etype == EventType.SANDBOX_START:
            timeout = event.data.get("timeout")
            extra = f", timeout {timeout}s" if timeout else ""
            self._print(f"    ⟡ Sandbox executing{extra} …")
            return

        if etype == EventType.SANDBOX_END:
            status = event.data.get("status", "done")
            elapsed_val = event.data.get("elapsed")
            suffix = f" ({elapsed_val:.2f}s)" if isinstance(elapsed_val, (int, float)) else ""
            self._print(f"    ⟡ Sandbox {status}{suffix}")
            return

        # All other events (LLM_CHUNK, LLM_END, HITL, LOG, etc.)
        # are intentionally suppressed — RichHandler logging provides
        # the detailed output that is consistent with the web dashboard.


def attach_cli_progress(bus: EventBus) -> CliProgressReporter:
    """Attach a CLI progress reporter to the given event bus."""
    return CliProgressReporter().attach(bus)