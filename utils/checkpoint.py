"""
Checkpoint / Resume system (inspired by AutoResearchClaw)

Writes an atomic checkpoint after each node completes; supports resuming from interruption.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Whitelist of serializable state fields (excludes non-serializable objects)
_SERIALIZABLE_KEYS = frozenset({
    "user_query", "conversation_history", "task_spec", "task_spec_complete",
    "clarification_questions", "retrieved_knowledge", "problem_formalization",
    "solution_plan", "notebook", "notebook_validated", "verification_results",
    "simulation_results", "review_feedback", "max_simulation_retries",
    "max_verification_retries", "max_review_retries", "simulation_retry_count",
    "verification_retry_count", "review_retry_count", "execution_trace",
    "final_report", "final_notebook", "current_phase", "should_terminate",
    "termination_reason", "error_state", "config",
})

# Node execution order (used to determine where to resume)
NODE_ORDER = [
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


class CheckpointManager:
    """Manages checkpoint read/write for experiment runs."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.checkpoint_file = output_dir / "checkpoint.json"

    def save(self, stage: str, state: dict[str, Any]) -> None:
        """Write checkpoint after a stage completes (atomic write)."""
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            # Filter serializable fields
            serializable = {}
            for k, v in state.items():
                if k in _SERIALIZABLE_KEYS:
                    try:
                        json.dumps(v, ensure_ascii=False)
                        serializable[k] = v
                    except (TypeError, ValueError):
                        logger.debug("Checkpoint: skipping non-serializable key %s", k)
                        continue

            checkpoint = {
                "stage": stage,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "state": serializable,
            }
            # Atomic write: write to temp file then rename
            tmp = self.checkpoint_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.rename(self.checkpoint_file)
            logger.debug("Checkpoint saved: stage=%s → %s", stage, self.checkpoint_file)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save checkpoint: %s", exc)

    def load(self) -> Optional[dict[str, Any]]:
        """Load the latest checkpoint; returns None if no recoverable state exists."""
        if not self.checkpoint_file.exists():
            return None
        try:
            data = json.loads(self.checkpoint_file.read_text(encoding="utf-8"))
            logger.info("Checkpoint loaded: stage=%s time=%s", data.get("stage"), data.get("timestamp"))
            return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load checkpoint: %s", exc)
            return None

    def get_resume_stage(self) -> Optional[str]:
        """Return which node to resume execution from.

        Logic: the checkpoint records the last completed stage;
        resume starts from the next stage.
        """
        ckpt = self.load()
        if not ckpt:
            return None

        completed_stage = ckpt.get("stage", "")
        if completed_stage not in NODE_ORDER:
            return None

        idx = NODE_ORDER.index(completed_stage)
        if idx + 1 < len(NODE_ORDER):
            return NODE_ORDER[idx + 1]
        # All stages already completed
        return None

    def get_saved_state(self) -> dict[str, Any]:
        """Return the saved state dict (empty dict if no checkpoint exists)."""
        ckpt = self.load()
        if not ckpt:
            return {}
        return ckpt.get("state", {})

    def clear(self) -> None:
        """Clear checkpoint (called after experiment completes)."""
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()
            logger.info("Checkpoint cleared.")
