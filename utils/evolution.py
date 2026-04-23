"""
Evolution Store — Self-evolution learning system

Inspired by AutoResearchClaw's evolution.py: extracts lessons learned from failures,
persists them to a JSONL file, and injects relevant lessons into prompts in
subsequent runs to avoid repeating the same mistakes.

Usage:
    store = EvolutionStore(Path("./experiments/evolution"))
    store.append(LessonEntry(
        stage_name="simulation",
        category="experiment",
        severity="error",
        description="evaluate.py calls plt.show() causing sandbox to hang",
    ))
    overlay = store.build_overlay("file_generation", max_lessons=5)
    sp = pm.for_stage("file_generation", evolution_overlay=overlay)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class LessonCategory(str, Enum):
    """Issue classification for extracted lessons."""
    SYSTEM = "system"           # Environment, timeout, network
    EXPERIMENT = "experiment"   # Code validation, sandbox timeout, runtime error
    CODEGEN = "codegen"         # Code generation quality issues
    DESIGN = "design"           # Architecture/algorithm design flaws
    ANALYSIS = "analysis"       # Weak analysis, missing comparison
    PIPELINE = "pipeline"       # Stage orchestration, routing issues


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LessonEntry:
    """A single lesson extracted from a pipeline run."""
    stage_name: str
    category: str
    severity: str       # "info", "warning", "error"
    description: str
    timestamp: str = ""
    run_id: str = ""
    stage_num: int = 0

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LessonEntry:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Persistent Store
# ---------------------------------------------------------------------------

class EvolutionStore:
    """JSONL-backed persistent store for lessons learned."""

    _DEFAULT_STORE_DIR = Path(__file__).resolve().parents[1] / ".evolution"

    def __init__(self, store_dir: Path | str | None = None) -> None:
        self.store_dir = Path(store_dir) if store_dir else self._DEFAULT_STORE_DIR
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._store_path = self.store_dir / "lessons.jsonl"
        self._path = self._store_path  # alias for internal use

    def append(self, lesson: LessonEntry) -> None:
        """Append a single lesson to the JSONL store."""
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(lesson.to_dict(), ensure_ascii=False) + "\n")

    def append_many(self, lessons: list[LessonEntry]) -> None:
        """Bulk append lessons."""
        if not lessons:
            return
        with open(self._path, "a", encoding="utf-8") as f:
            for lesson in lessons:
                f.write(json.dumps(lesson.to_dict(), ensure_ascii=False) + "\n")

    def query(
        self,
        stage_name: str | None = None,
        category: str | None = None,
        severity: str | None = None,
        limit: int = 50,
    ) -> list[LessonEntry]:
        """Query lessons by optional filters."""
        if not self._path.exists():
            return []

        results: list[LessonEntry] = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = LessonEntry.from_dict(data)
                    if stage_name and entry.stage_name != stage_name:
                        continue
                    if category and entry.category != category:
                        continue
                    if severity and entry.severity != severity:
                        continue
                    results.append(entry)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if len(results) >= limit:
                    break
        return results

    def build_overlay(
        self,
        stage_name: str,
        *,
        max_lessons: int = 5,
        include_related: bool = True,
    ) -> str:
        """Build a prompt overlay string with relevant lessons for a stage.

        Parameters
        ----------
        stage_name : str
            The current stage (e.g. "file_generation", "simulation").
        max_lessons : int
            Max lessons to include.
        include_related : bool
            If True, also include lessons from closely related stages.

        Returns
        -------
        str
            Formatted overlay text ready for prompt injection (empty if no lessons).
        """
        # Related stage mappings
        related_stages: dict[str, list[str]] = {
            "file_generation": ["verification", "simulation", "codegen"],
            "verification": ["file_generation", "simulation"],
            "simulation": ["file_generation", "verification"],
            "architecture_design": ["optimization", "critic"],
            "optimization": ["critic", "architecture_design"],
            "critic": ["simulation", "optimization"],
        }

        # Collect lessons: exact match first, then related
        lessons = self.query(stage_name=stage_name, limit=max_lessons)

        if include_related and len(lessons) < max_lessons:
            for related in related_stages.get(stage_name, []):
                remaining = max_lessons - len(lessons)
                if remaining <= 0:
                    break
                related_lessons = self.query(stage_name=related, limit=remaining)
                lessons.extend(related_lessons)

        if not lessons:
            return ""

        lines = ["## Lessons from prior runs (please apply to the current stage)"]
        for i, lesson in enumerate(lessons[:max_lessons], 1):
            severity_icon = {"error": "✖", "warning": "⚠", "info": "ℹ"}.get(
                lesson.severity, "•"
            )
            lines.append(
                f"{i}. [{severity_icon}] Stage {lesson.stage_name}: {lesson.description}"
            )
        return "\n".join(lines)

    def total_lessons(self) -> int:
        """Return total number of lessons stored."""
        if not self._path.exists():
            return 0
        with open(self._path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())


# ---------------------------------------------------------------------------
# Lesson Extraction Helpers
# ---------------------------------------------------------------------------

# Stage name → stage number mapping
_STAGE_NUMBERS: dict[str, int] = {
    "problem_analysis": 1,
    "knowledge_retrieval": 2,
    "architecture_design": 3,
    "spec_generation": 4,
    "plan_generation": 5,
    "file_generation": 6,
    "verification": 7,
    "simulation": 8,
    "critic": 9,
    "optimization": 10,
    "report_generation": 11,
}


def _classify_error(stage_name: str, error_text: str) -> str:
    """Classify an error into a LessonCategory based on keywords."""
    error_lower = error_text.lower()
    if any(kw in error_lower for kw in ("timeout", "killed", "oom", "memory")):
        return LessonCategory.SYSTEM
    if any(kw in error_lower for kw in ("syntax", "import", "name", "attribute", "type")):
        return LessonCategory.CODEGEN
    if any(kw in error_lower for kw in ("sandbox", "subprocess", "evaluate", "run_evaluation")):
        return LessonCategory.EXPERIMENT
    if any(kw in error_lower for kw in ("score", "metric", "performance")):
        return LessonCategory.ANALYSIS
    if stage_name in ("architecture_design", "optimization"):
        return LessonCategory.DESIGN
    return LessonCategory.PIPELINE


def extract_lessons_from_trace(
    execution_trace: list[dict],
    *,
    run_id: str = "",
    critic_feedback: dict | None = None,
    simulation_results: dict | None = None,
    verification_results: dict | None = None,
) -> list[LessonEntry]:
    """Extract lessons from AutoWiSPA execution trace and results.

    This function is called at end-of-run to distill reusable knowledge.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lessons: list[LessonEntry] = []

    # 1. Lessons from verification failures
    if verification_results and verification_results.get("status") == "error":
        for error in verification_results.get("errors", []):
            lessons.append(LessonEntry(
                stage_name="verification",
                stage_num=_STAGE_NUMBERS.get("verification", 7),
                category=LessonCategory.CODEGEN,
                severity="error",
                description=f"Code validation failed: {str(error)[:200]}",
                timestamp=now,
                run_id=run_id,
            ))

    # 2. Lessons from simulation errors
    if simulation_results and simulation_results.get("status") == "error":
        error_log = simulation_results.get("error_log", "unknown error")
        category = _classify_error("simulation", error_log)
        lessons.append(LessonEntry(
            stage_name="simulation",
            stage_num=_STAGE_NUMBERS.get("simulation", 8),
            category=category,
            severity="error",
            description=f"Simulation execution failed: {str(error_log)[:200]}",
            timestamp=now,
            run_id=run_id,
        ))

    # 3. Lessons from low critic scores
    if critic_feedback:
        score = critic_feedback.get("score", 10)
        if score < 4:
            for weakness in critic_feedback.get("weaknesses", [])[:2]:
                lessons.append(LessonEntry(
                    stage_name="critic",
                    stage_num=_STAGE_NUMBERS.get("critic", 9),
                    category=LessonCategory.DESIGN,
                    severity="warning",
                    description=f"Low score(={score}) weakness: {str(weakness)[:200]}",
                    timestamp=now,
                    run_id=run_id,
                ))

    # 4. Lessons from execution trace errors
    for entry in execution_trace:
        if entry.get("payload", {}).get("status") == "error":
            stage = entry.get("stage", "unknown")
            summary = entry.get("summary_lines", [""])[0] if entry.get("summary_lines") else ""
            lessons.append(LessonEntry(
                stage_name=stage,
                stage_num=_STAGE_NUMBERS.get(stage, 0),
                category=_classify_error(stage, summary),
                severity="error",
                description=f"Node error: {summary[:200]}",
                timestamp=now,
                run_id=run_id,
            ))

    return lessons
