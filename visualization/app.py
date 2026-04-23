from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, render_template, request, send_file
from matplotlib.figure import Figure


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
DEFAULT_EXPERIMENTS_ROOT = PROJECT_ROOT / "experiments"
TIMESTAMP_RUN_PATTERN = re.compile(r"^\d{8}_\d{6}$")
CJK_TEXT_PATTERN = re.compile(r"[\u3400-\u9fff]")
FILE_PATH_PATTERN = re.compile(r"[A-Za-z0-9_./-]+\.py")

WORKFLOW_STEPS = [
    {"id": "problem_analysis", "code": "S1", "label": "Problem Analysis"},
    {"id": "knowledge_retrieval", "code": "S2", "label": "Knowledge Retrieval"},
    {"id": "model_formulation", "code": "S3", "label": "Model Formulation"},
    {"id": "solution_planning", "code": "S4", "label": "Solution Planning"},
    {"id": "notebook_generation", "code": "S5", "label": "Notebook Generation"},
    {"id": "verification", "code": "S6", "label": "Notebook Verification"},
    {"id": "simulation", "code": "S7", "label": "Notebook Simulation"},
    {"id": "review", "code": "R", "label": "Review Feedback", "optional": True},
    {"id": "report_generation", "code": "S8", "label": "Report Generation"},
]

ARTIFACT_HINTS = (
    "task_spec.json",
    "retrieved_knowledge.json",
    "problem_formalization.json",
    "solution_plan.json",
    "notebook_plan.json",
    "simulation.ipynb",
    "verification_results.json",
    "simulation_results.json",
    "review_feedback.json",
    "report.md",
    "execution_trace.json",
    "checkpoint.json",
)

WORKFLOW_INDEX = {stage["id"]: index for index, stage in enumerate(WORKFLOW_STEPS)}
WORKFLOW_BY_ID = {stage["id"]: stage for stage in WORKFLOW_STEPS}

STATUS_LABELS = {
    "completed": "Completed",
    "active": "Running",
    "pending": "Pending",
    "issue": "Needs Attention",
}

CONTEXT_BUTTON_LABEL = "View Full Context"

PLOT_X_KEYS = ("snr_db_list", "snr_list", "x", "x_values", "variable_points", "operating_points")

logger = logging.getLogger(__name__)
app = Flask(
    __name__,
    template_folder=str(APP_DIR / "templates"),
    static_folder=str(APP_DIR / "static"),
)

experiments_root = DEFAULT_EXPERIMENTS_ROOT
custom_root_dirs: list[Path] = []


def _root_token(root: Path) -> str:
    resolved = root.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix() or resolved.name
    except ValueError:
        digest = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:12]
        return f"root-{digest}"


def _root_label(root: Path) -> str:
    resolved = root.resolve()
    try:
        relative = resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
        return f"{PROJECT_ROOT.name}/{relative}" if relative else PROJECT_ROOT.name
    except ValueError:
        parts = resolved.parts[-2:]
        return "/".join(parts) if parts else (resolved.name or "data")


def _display_run_path(root: Path, run_dir: Path | None = None) -> str:
    base = _root_label(root)
    if run_dir is None:
        return base
    return f"{base}/{run_dir.name}"


def _register_root_dir(path: Path) -> Path:
    resolved = path.resolve()
    if resolved not in custom_root_dirs:
        custom_root_dirs.append(resolved)
    return resolved


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _iso_from_timestamp(timestamp: float) -> str:
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")


def _iso_timestamp(path: Path) -> str:
    return _iso_from_timestamp(_safe_mtime(path))


def _human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{size_bytes} B"


def _truncate(text: Any, limit: int = 320) -> str:
    if text is None:
        return ""
    rendered = str(text).strip()
    if len(rendered) <= limit:
        return rendered
    return rendered[: limit - 3].rstrip() + "..."


def _normalize_display_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\\n" in normalized and normalized.count("\\n") >= normalized.count("\n"):
        normalized = normalized.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
    return normalized


def _looks_like_markdown(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return any(
        re.search(pattern, stripped, flags=re.MULTILINE)
        for pattern in (
            r"^#{1,6}\s+",
            r"^```",
            r"^\s*[-*+]\s+",
            r"^\s*\d+\.\s+",
            r"^\s*>\s+",
            r"^\|.+\|$",
        )
    )


def _context_format(source: str, content: Any, format_hint: str = "") -> str:
    if format_hint:
        return format_hint
    if isinstance(content, (dict, list)):
        return "json"

    source_lower = source.lower()
    if source_lower.endswith(".md"):
        return "markdown"
    if source_lower.endswith(".py"):
        return "code"
    if source_lower.endswith(".json"):
        return "json"

    rendered = _render_full_text(content)
    if _looks_like_markdown(rendered):
        return "markdown"
    return "text"


def _render_text(value: Any, limit: int = 1000) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _truncate(_normalize_display_text(value), limit)
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2)
    except TypeError:
        text = str(value)
    return _truncate(text, limit)


def _render_full_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _normalize_display_text(value)
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except TypeError:
        return str(value)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_json(path: Path) -> Any:
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(_read_text(path))
    except json.JSONDecodeError:
        return None


def _read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []

    entries: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    entries.append(record)
    except OSError:
        return []

    if limit and len(entries) > limit:
        return entries[-limit:]
    return entries


def _format_seconds(value: Any, precision: int = 2) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.{precision}f}s"
    rendered = str(value or "").strip()
    if not rendered:
        return "n/a"
    return rendered if rendered.endswith("s") else f"{rendered}s"


def _display_key_label(key: str) -> str:
    overrides = {
        "snr_db_list": "SNR (dB)",
        "snr_list": "SNR",
        "pd_list": "Pd",
        "pfa_list": "Pfa",
        "theoretical_pd_list": "Theoretical Pd",
        "field": "Field",
        "value": "Value",
    }
    if key in overrides:
        return overrides[key]

    words = key.replace("_", " ").split()
    tokens = []
    for word in words:
        upper = word.upper()
        if upper in {"SNR", "PD", "PFA", "AWGN", "GLR", "CFAR", "MRC"}:
            tokens.append(upper)
        elif word.lower() == "db":
            tokens.append("dB")
        else:
            tokens.append(word.capitalize())
    return " ".join(tokens) or key


def _format_table_value(value: Any) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.6g}"
    if isinstance(value, (dict, list)):
        return _truncate(_render_full_text(value), 160)
    return str(value)


def _build_table_preview(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        key_order: list[str] = []
        for item in value[:12]:
            for key, item_value in item.items():
                if key in key_order or isinstance(item_value, (dict, list)):
                    continue
                key_order.append(key)
        if len(key_order) >= 2:
            return {
                "columns": [{"key": key, "label": _display_key_label(key)} for key in key_order],
                "rows": [
                    {key: _format_table_value(item.get(key)) for key in key_order}
                    for item in value[:60]
                ],
            }

    if not isinstance(value, dict):
        return None

    list_columns = [
        (key, column)
        for key, column in value.items()
        if isinstance(column, list) and column and all(not isinstance(item, (dict, list)) for item in column)
    ]
    candidate_lengths = sorted({len(column) for _, column in list_columns if len(column) > 1}, reverse=True)
    for length in candidate_lengths:
        columns = [(key, column) for key, column in list_columns if len(column) == length]
        if len(columns) < 2:
            continue
        return {
            "columns": [{"key": key, "label": _display_key_label(key)} for key, _ in columns],
            "rows": [
                {key: _format_table_value(column[index]) for key, column in columns}
                for index in range(length)
            ],
        }

    scalar_keys = [
        key
        for key, item_value in value.items()
        if item_value not in (None, "") and not isinstance(item_value, (dict, list))
    ]
    if len(scalar_keys) >= 2:
        return {
            "columns": [
                {"key": "field", "label": _display_key_label("field")},
                {"key": "value", "label": _display_key_label("value")},
            ],
            "rows": [
                {"field": _display_key_label(key), "value": _format_table_value(value.get(key))}
                for key in scalar_keys
            ],
        }

    return None


def _clean_reasoning_prefix(text: str) -> str:
    cleaned = re.sub(r"^(?:Thinking\.\.\.\s*\(\d+s elapsed\)\s*)+", "", _normalize_display_text(text), flags=re.IGNORECASE)
    return cleaned.lstrip()


def _report_preview_text(text: Any, limit: int = 7000) -> str:
    normalized = _normalize_display_text(str(text or ""))
    cleaned = _clean_reasoning_prefix(normalized) or normalized
    return _truncate(cleaned, limit)


def _format_confidence(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value * 100:.0f}%" if 0 <= value <= 1 else f"{value:.1f}"
    rendered = str(value or "").strip()
    return rendered or "n/a"


def _is_reference_metric(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("crb", "theoretical", "target", "mask", "gap", "baseline"))


def _metric_direction(metric_name: str) -> str:
    lowered = metric_name.lower()
    if any(token in lowered for token in ("runtime", "time", "latency", "complexity", "flops", "ops", "cost", "threshold")):
        return "min"
    if any(token in lowered for token in ("gain", "improvement", "auc", "accuracy", "success", "resolution", "recall", "precision", "throughput", "score", "probability")):
        return "max"
    if "pd" in lowered:
        return "max"
    if any(token in lowered for token in ("nmse", "mse", "rmse", "mae", "error", "loss", "gap", "ber", "wer", "fer", "distance")):
        return "min"
    if any(token in lowered for token in ("pd", "probability", "auc", "accuracy", "success", "recall")):
        return "max"
    return "min"


def _best_scalar_entry(values: Any, *, direction: str) -> tuple[str, Any] | None:
    if not isinstance(values, dict):
        return None
    candidates = [
        (key, value)
        for key, value in values.items()
        if isinstance(value, (int, float)) and not _is_reference_metric(key)
    ]
    if not candidates:
        return None
    if direction == "max":
        return max(candidates, key=lambda item: item[1])
    return min(candidates, key=lambda item: item[1])


def _best_curve_entry(curve: Any, metric_name: str) -> tuple[str, Any] | None:
    if not isinstance(curve, dict):
        return None
    direction = _metric_direction(metric_name)
    best_label = ""
    best_value: Any = None
    for key, values in curve.items():
        if key in {"x", "x_label", "y_label"} or not _is_numeric_list(values) or _is_reference_metric(key):
            continue
        candidate = max(values) if direction == "max" else min(values)
        if best_value is None:
            best_label = key
            best_value = candidate
            continue
        if direction == "max" and candidate > best_value:
            best_label = key
            best_value = candidate
        if direction == "min" and candidate < best_value:
            best_label = key
            best_value = candidate
    if not best_label:
        return None
    return best_label, best_value


def _format_named_summary(name: Any, value: Any, *, value_suffix: str = "", key_suffix: str = "") -> str:
    label = str(name or "").strip()
    rendered_value = f"{_format_table_value(value)}{value_suffix}"
    if re.fullmatch(r"-?\d+(?:\.\d+)?", label):
        suffix = f"{label}{key_suffix}".strip()
        return f"{rendered_value} at {suffix}"
    return f"{_display_key_label(label)} · {rendered_value}"


def _normalized_metric_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _is_numeric_scalar_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and all(isinstance(item, (int, float)) for item in value.values())


def _is_curve_dict(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    x_values = value.get("x")
    if not _is_numeric_list(x_values):
        return False
    return any(
        key not in {"x", "x_label", "y_label"} and _is_numeric_list(series) and len(series) == len(x_values)
        for key, series in value.items()
    )


def _select_primary_curve(performance_data: dict[str, Any], primary_metric: str) -> tuple[str, dict[str, Any] | None]:
    metric_curve = performance_data.get("metric_curve")
    if _is_curve_dict(metric_curve):
        return "metric_curve", metric_curve

    normalized_primary = _normalized_metric_token(primary_metric)
    curve_sections = [(key, value) for key, value in performance_data.items() if _is_curve_dict(value)]
    for key, value in curve_sections:
        if normalized_primary and normalized_primary in _normalized_metric_token(key):
            return key, value
        y_label = str(value.get("y_label") or "").strip()
        if normalized_primary and normalized_primary in _normalized_metric_token(y_label):
            return key, value

    if curve_sections:
        return curve_sections[0]
    return "", None


def _resolve_primary_metric_name(
    performance_data: dict[str, Any],
    task_spec: dict[str, Any],
    curve_key: str,
    curve: dict[str, Any] | None,
) -> str:
    primary_metric = performance_data.get("primary_metric_name") or ((task_spec.get("performance_targets") or {}).get("primary_metric") if isinstance(task_spec, dict) else "")
    if primary_metric:
        return str(primary_metric)
    if isinstance(curve, dict):
        y_label = str(curve.get("y_label") or "").strip()
        if y_label:
            return y_label
    return _display_key_label(curve_key) if curve_key else ""


def _axis_key_suffix(curve: Any) -> str:
    if not isinstance(curve, dict):
        return ""
    x_label = str(curve.get("x_label") or "").lower()
    if "db" in x_label or "snr" in x_label:
        return " dB"
    return ""


def _summary_prefix(metric_name: str, direction: str) -> str:
    lowered = metric_name.lower()
    if any(token in lowered for token in ("runtime", "time", "latency")):
        return "Fastest" if direction == "min" else "Highest"
    if any(token in lowered for token in ("complexity", "flops", "ops", "cost", "memory")):
        return "Lowest" if direction == "min" else "Highest"
    return "Best" if direction == "max" else "Lowest"


def _scalar_section_summary_rows(
    performance_data: dict[str, Any],
    *,
    skip_keys: set[str],
    key_suffix: str = "",
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for key, value in performance_data.items():
        if key in skip_keys or _is_reference_metric(key) or not _is_numeric_scalar_dict(value):
            continue
        direction = _metric_direction(key)
        best_entry = _best_scalar_entry(value, direction=direction)
        if not best_entry:
            continue
        rows.append(
            {
                "field": f"{_summary_prefix(key, direction)} {_display_key_label(key)}",
                "value": _format_named_summary(best_entry[0], best_entry[1], key_suffix=key_suffix),
            }
        )
    return rows


def _scalar_value_summary_rows(performance_data: dict[str, Any], *, skip_keys: set[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for key, value in performance_data.items():
        if key in skip_keys or _is_reference_metric(key) or not isinstance(value, (int, float)):
            continue
        rows.append({"field": _display_key_label(key), "value": _format_table_value(value)})
    return rows


def _axis_range_label(curve: Any) -> str:
    if not isinstance(curve, dict):
        return ""
    x_values = curve.get("x")
    if not isinstance(x_values, list) or not x_values:
        return ""
    start = _format_table_value(x_values[0])
    end = _format_table_value(x_values[-1])
    x_label = str(curve.get("x_label") or "").strip()
    if "snr" in x_label.lower():
        return f"{start} to {end} dB"
    return f"{start} to {end}" + (f" ({x_label})" if x_label else "")


def _build_performance_summary_table(bundle: dict[str, Any]) -> dict[str, Any] | None:
    task_spec = _artifact_or_state(bundle, "task_spec") or {}
    simulation_results = _artifact_or_state(bundle, "simulation_results") or {}
    performance_data = simulation_results.get("performance_data") or {}
    if not isinstance(performance_data, dict) or not performance_data:
        return None

    curve_key, metric_curve = _select_primary_curve(performance_data, str(performance_data.get("primary_metric_name") or ""))
    primary_metric = _resolve_primary_metric_name(performance_data, task_spec, curve_key, metric_curve)
    best_primary = _best_curve_entry(metric_curve, str(primary_metric or "metric")) if metric_curve else None
    key_suffix = _axis_key_suffix(metric_curve)
    section_labels = [_display_key_label(key) for key, value in performance_data.items() if isinstance(value, dict)]
    skip_keys = {"primary_metric_name", curve_key}

    rows: list[dict[str, str]] = []
    if primary_metric:
        rows.append({"field": "Primary Metric", "value": str(primary_metric)})
    range_label = _axis_range_label(metric_curve)
    if range_label:
        rows.append({"field": "Operating Range", "value": range_label})
    if best_primary:
        rows.append(
            {
                "field": "Best Primary Result",
                "value": _format_named_summary(best_primary[0], best_primary[1]),
            }
        )
    rows.extend(_scalar_section_summary_rows(performance_data, skip_keys=skip_keys, key_suffix=key_suffix)[:3])
    rows.extend(_scalar_value_summary_rows(performance_data, skip_keys=skip_keys)[:2])
    if section_labels:
        rows.append({"field": "Result Sections", "value": ", ".join(section_labels[:4])})

    if not rows:
        return None

    return {
        "columns": [
            {"key": "field", "label": _display_key_label("field")},
            {"key": "value", "label": _display_key_label("value")},
        ],
        "rows": rows,
    }


def _build_performance_metric_cards(bundle: dict[str, Any], elapsed_seconds: Any) -> list[dict[str, str]]:
    task_spec = _artifact_or_state(bundle, "task_spec") or {}
    simulation_results = _artifact_or_state(bundle, "simulation_results") or {}
    performance_data = simulation_results.get("performance_data") or {}
    if not isinstance(performance_data, dict) or not performance_data:
        return []

    curve_key, metric_curve = _select_primary_curve(performance_data, str(performance_data.get("primary_metric_name") or ""))
    primary_metric = _resolve_primary_metric_name(performance_data, task_spec, curve_key, metric_curve)
    best_primary = _best_curve_entry(metric_curve, str(primary_metric or "metric")) if metric_curve else None
    range_label = _axis_range_label(metric_curve)

    metrics: list[dict[str, str]] = []
    if primary_metric:
        metrics.append({"label": "Primary Metric", "value": str(primary_metric)})
    if best_primary:
        metrics.append({"label": "Best Result", "value": _format_named_summary(best_primary[0], best_primary[1])})
    if range_label:
        metrics.append({"label": "Range", "value": range_label})
    metrics.append({"label": "Eval Time", "value": _format_seconds(elapsed_seconds)})
    return metrics[:4]


def _is_numeric_list(value: Any) -> bool:
    return isinstance(value, list) and value and all(isinstance(item, (int, float)) for item in value)


def _build_plot_specs_from_dict(data: dict[str, Any], prefix: str = "") -> list[dict[str, Any]]:
    plot_specs: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return plot_specs

    x_key = None
    x_values = None
    for candidate in PLOT_X_KEYS:
        values = data.get(candidate)
        if _is_numeric_list(values):
            x_key = candidate
            x_values = values
            break

    if x_key and x_values:
        series = []
        for key, values in data.items():
            if key == x_key or not _is_numeric_list(values) or len(values) != len(x_values):
                continue
            series.append({"label": key, "values": values})
        if series:
            plot_specs.append(
                {
                    "title": (prefix + "Performance Curves").strip(),
                    "x_label": x_key,
                    "x_values": x_values,
                    "series": series,
                }
            )

    for key, value in data.items():
        if isinstance(value, dict):
            plot_specs.extend(_build_plot_specs_from_dict(value, f"{prefix}{key} · "))
    return plot_specs


def _build_plot_specs(simulation_results: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(simulation_results, dict):
        return []

    specs: list[dict[str, Any]] = []
    performance_data = simulation_results.get("performance_data")
    if isinstance(performance_data, dict):
        specs.extend(_build_plot_specs_from_dict(performance_data))

    raw_results = simulation_results.get("raw_results")
    if isinstance(raw_results, dict):
        specs.extend(_build_plot_specs_from_dict(raw_results, "raw_results · "))

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for spec in specs:
        signature = (spec["title"], spec["x_label"])
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(spec)
    return deduped[:4]


def _latest_activity_mtime(run_dir: Path) -> float:
    latest = _safe_mtime(run_dir)
    try:
        for path in run_dir.rglob("*"):
            if path.is_file():
                latest = max(latest, _safe_mtime(path))
    except OSError:
        return latest
    return latest


def _looks_like_experiment_dir(run_dir: Path) -> bool:
    return any((run_dir / artifact_name).exists() for artifact_name in ARTIFACT_HINTS)


def _looks_like_experiments_root(root: Path) -> bool:
    if not root.exists() or not root.is_dir():
        return False

    try:
        return any(
            child.is_dir() and not child.name.startswith(".") and _looks_like_experiment_dir(child)
            for child in root.iterdir()
        )
    except OSError:
        return False


def _candidate_root_dirs() -> list[Path]:
    seen: set[Path] = set()
    candidates: list[Path] = []

    def add(path: Path, *, force: bool = False) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved in seen or not resolved.exists() or not resolved.is_dir():
            return
        if force or _looks_like_experiments_root(resolved):
            seen.add(resolved)
            candidates.append(resolved)

    add(experiments_root, force=True)
    for custom_root in custom_root_dirs:
        add(custom_root, force=True)

    try:
        first_level_dirs = [child for child in PROJECT_ROOT.iterdir() if child.is_dir() and not child.name.startswith(".")]
    except OSError:
        first_level_dirs = []

    for child in first_level_dirs:
        add(child)
        try:
            nested_dirs = [grand for grand in child.iterdir() if grand.is_dir() and not grand.name.startswith(".")]
        except OSError:
            continue
        for grand in nested_dirs:
            add(grand)

    default_root = experiments_root.resolve()
    candidates.sort(key=lambda path: (0 if path == default_root else 1, _root_label(path).lower()))
    return candidates


def _root_options() -> list[dict[str, str]]:
    return [{"key": _root_token(root), "label": _root_label(root)} for root in _candidate_root_dirs()]


def _resolve_root_dir(root_key: str) -> Path:
    if not root_key:
        return experiments_root.resolve()

    for root in _candidate_root_dirs():
        if _root_token(root) == root_key:
            return root.resolve()

    abort(400, description=f"Unknown data root: {root_key}")


def _pick_root_dir() -> Path | None:
    if sys.platform == "darwin":
        script = 'POSIX path of (choose folder with prompt "Select Data Folder")'
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            logger.warning("macOS directory picker is unavailable: %s", exc)
            return None

        if result.returncode != 0:
            logger.info("macOS directory picker cancelled or failed: %s", (result.stderr or "").strip())
            return None

        selected = (result.stdout or "").strip()
        if not selected:
            return None

        try:
            return _register_root_dir(Path(selected))
        except OSError:
            return None

    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # pragma: no cover - platform-specific import path
        logger.warning("Directory picker is unavailable: %s", exc)
        return None

    dialog_root = tk.Tk()
    dialog_root.withdraw()
    dialog_root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(initialdir=str(experiments_root), mustexist=True)
    finally:
        dialog_root.destroy()

    if not selected:
        return None

    try:
        return _register_root_dir(Path(selected))
    except OSError:
        return None


def _list_run_dirs(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []

    sortable_runs: list[dict[str, Any]] = []
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        if not _looks_like_experiment_dir(child):
            continue
        latest_activity = _latest_activity_mtime(child)
        sortable_runs.append(
            {
                "name": child.name,
                "sort_key": latest_activity,
                "modified": _iso_from_timestamp(latest_activity),
            }
        )

    sortable_runs.sort(key=lambda item: item["sort_key"], reverse=True)
    return [{"name": item["name"], "modified": item["modified"]} for item in sortable_runs]


def _default_run_name(runs: list[dict[str, Any]]) -> str:
    return runs[0]["name"] if runs else ""


def _resolve_run_dir(run_name: str, root: Path) -> Path:
    candidate = (root / run_name).resolve()
    if not candidate.exists() or not candidate.is_dir():
        abort(404, description=f"Unknown experiment folder: {run_name}")
    if root.resolve() not in candidate.parents:
        abort(400, description="Invalid run path")
    return candidate


def _contains_cjk(value: Any) -> bool:
    return bool(CJK_TEXT_PATTERN.search(str(value or "")))


def _english_fragment(value: Any, fallback: str = "") -> str:
    text = _truncate(value, 240)
    if not text:
        return fallback
    if not _contains_cjk(text):
        return text

    prefix = re.split(r"[:：]", text, maxsplit=1)[0].strip()
    if prefix and not _contains_cjk(prefix) and re.search(r"[A-Za-z0-9]", prefix):
        return prefix
    return fallback


def _list_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _file_list_from_text(value: Any) -> list[str]:
    matches = FILE_PATH_PATTERN.findall(str(value or ""))
    seen: set[str] = set()
    files: list[str] = []
    for match in matches:
        if match not in seen:
            seen.add(match)
            files.append(match)
    return files


def _extract_math_line(value: Any) -> str:
    text = str(value or "")
    block = re.search(r"\$\$(.+?)\$\$", text, re.DOTALL)
    if block:
        return _truncate(block.group(0).strip(), 180)
    inline = re.search(r"\$(.+?)\$", text, re.DOTALL)
    if inline:
        return _truncate(inline.group(0).strip(), 180)
    return ""


def _latest_review_payload(bundle: dict[str, Any], trace_payload: Any = None) -> Any:
    review_feedback = bundle.get("review_feedback")
    if review_feedback not in (None, "", [], {}):
        return review_feedback

    iteration_history = bundle.get("iteration_history")
    if isinstance(iteration_history, list) and iteration_history:
        latest_iteration = iteration_history[-1]
        if isinstance(latest_iteration, dict):
            feedback = latest_iteration.get("feedback")
            if feedback not in (None, "", [], {}):
                return feedback
            return latest_iteration

    return trace_payload or {}


def _review_preview_lines(review_payload: Any) -> list[str]:
    if isinstance(review_payload, str):
        text = _truncate(_normalize_display_text(review_payload), 720)
        return [text] if text else []

    if not isinstance(review_payload, dict):
        text = _truncate(_render_full_text(review_payload), 720)
        return [text] if text else []

    lines: list[str] = []
    assessment = review_payload.get("overall_assessment")
    score = review_payload.get("score")
    header_parts = []
    if assessment not in (None, ""):
        header_parts.append(str(assessment))
    if score not in (None, ""):
        header_parts.append(f"score {score}")
    if header_parts:
        lines.append(" · ".join(header_parts))

    strengths = [str(item) for item in (review_payload.get("strengths") or []) if str(item).strip()]
    if strengths:
        lines.append(f"Strengths: {_truncate('；'.join(strengths[:2]), 240)}")

    weaknesses = [str(item) for item in (review_payload.get("weaknesses") or []) if str(item).strip()]
    if weaknesses:
        lines.append(f"Weaknesses: {_truncate('；'.join(weaknesses[:2]), 240)}")

    suggestion_texts: list[str] = []
    for item in (review_payload.get("improvement_suggestions") or [])[:2]:
        if isinstance(item, dict):
            suggestion_text = item.get("specific_action") or item.get("suggestion") or item.get("expected_improvement")
            if suggestion_text:
                suggestion_texts.append(str(suggestion_text))
        elif str(item).strip():
            suggestion_texts.append(str(item))
    if suggestion_texts:
        lines.append(f"Improvements: {_truncate('；'.join(suggestion_texts), 260)}")

    if not lines:
        rendered = _truncate(_render_full_text(review_payload), 720)
        if rendered:
            lines.append(rendered)
    return lines


def _checkpoint_step_id(stage_name: Any) -> str:
    raw = str(stage_name or "").strip()
    if not raw:
        return ""

    lower = raw.lower()
    aliases = {
        "problem_analysis": "problem_analysis",
        "knowledge_retrieval": "knowledge_retrieval",
        "model_formulation": "model_formulation",
        "problem_formalization": "model_formulation",
        "solution_planning": "solution_planning",
        "algorithm_specification": "solution_planning",
        "notebook_generation": "notebook_generation",
        "code_generation": "notebook_generation",
        "verification": "verification",
        "simulation": "simulation",
        "report_generation": "report_generation",
        "file_generation": "notebook_generation",
        "critic": "review",
        "result_review": "review",
        "review": "review",
    }
    if lower in aliases:
        return aliases[lower]

    mapping = {
        "s1": "problem_analysis",
        "s2": "knowledge_retrieval",
        "s3": "model_formulation",
        "s3a": "model_formulation",
        "s3b": "model_formulation",
        "s4": "solution_planning",
        "s4b": "solution_planning",
        "s5": "notebook_generation",
        "s6": "verification",
        "s7": "simulation",
        "s8": "report_generation",
    }
    return mapping.get(lower, "")


def _trace_step_id(item: dict[str, Any]) -> str:
    raw_stage = str(item.get("stage") or "").strip()
    title = str(item.get("title") or "")
    lower_title = title.lower()

    if "评审" in title or "review" in lower_title:
        return "review"
    if raw_stage == "S6" and ("verification" in lower_title or "验证" in title):
        return "verification"
    if raw_stage == "S6" and ("generation" in lower_title or "notebook" in lower_title or "代码" in title):
        return "notebook_generation"
    if raw_stage == "S7" and ("仿真" in title or "evaluation" in lower_title or "simulation" in lower_title):
        return "simulation"

    mapping = {
        "S1": "problem_analysis",
        "S2": "knowledge_retrieval",
        "S3": "model_formulation",
        "S3a": "model_formulation",
        "S3b": "model_formulation",
        "S4": "solution_planning",
        "S4b": "solution_planning",
        "S5": "notebook_generation",
        "S6": "verification",
        "S7": "simulation",
        "S8": "report_generation",
    }
    return mapping.get(raw_stage) or _checkpoint_step_id(raw_stage)


def _workflow_label(step_id: str) -> str:
    step = WORKFLOW_BY_ID.get(step_id)
    if not step:
        return step_id or "Unknown Step"
    return f"{step['code']} · {step['label']}"


def _display_trace_label(item: dict[str, Any]) -> str:
    step_id = _trace_step_id(item)
    if step_id:
        return _workflow_label(step_id)
    raw_stage = str(item.get("stage") or "").strip()
    return raw_stage or "Trace Event"


def _latest_trace_for_step(trace: list[dict[str, Any]], step_id: str) -> dict[str, Any] | None:
    for item in reversed(trace):
        if _trace_step_id(item) == step_id:
            return item
    return None


def _artifact_or_state(bundle: dict[str, Any], key: str) -> Any:
    value = bundle.get(key)
    if value not in (None, "", [], {}):
        return value
    state = bundle.get("state") or {}
    return state.get(key)


def _solution_plan_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    payload = _artifact_or_state(bundle, "solution_plan") or bundle.get("algorithm_spec") or {}
    return payload if isinstance(payload, dict) else {}


def _solution_algorithm_spec(bundle: dict[str, Any]) -> dict[str, Any]:
    solution_plan = _solution_plan_payload(bundle)
    nested = solution_plan.get("algorithm_spec") if isinstance(solution_plan, dict) else None
    if isinstance(nested, dict) and nested:
        return nested
    legacy = bundle.get("algorithm_spec") or {}
    return legacy if isinstance(legacy, dict) else {}


def _notebook_plan_payload(bundle: dict[str, Any]) -> list[Any]:
    payload = bundle.get("notebook_plan")
    if isinstance(payload, list):
        return payload
    legacy = bundle.get("code_plan")
    if isinstance(legacy, list):
        return legacy
    return []


def _task_description_from_llm_calls(llm_calls: list[dict[str, Any]]) -> str:
    supplement_candidates: list[str] = []
    request_candidates: list[str] = []
    json_candidates: list[str] = []
    placeholder_descriptions = {
        "对任务数学本质、约束和场景的补充说明",
        "对任务数学本质、约束和场景的补充说明。",
    }

    for entry in llm_calls or []:
        if not isinstance(entry, dict):
            continue
        for message in entry.get("messages") or []:
            if not isinstance(message, dict) or str(message.get("role") or "").lower() != "user":
                continue

            content = _render_full_text(message.get("content"))
            request_match = re.search(r"请分析以下需求并输出任务规格：\s*(.*?)\s*(?:参考 Schema：|$)", content, flags=re.DOTALL)
            if request_match:
                request_text = " ".join(line.strip() for line in request_match.group(1).splitlines() if line.strip())
                if request_text:
                    request_candidates.append(request_text)

            supplement_match = re.search(r"补充信息[:：]\s*(.+)", content)
            if supplement_match:
                supplement_text = supplement_match.group(1).strip()
                if supplement_text:
                    supplement_candidates.append(supplement_text)

            fenced_json = re.search(r"```json\s*(\{.*?\})\s*```", content, flags=re.DOTALL)
            candidate_blocks = [fenced_json.group(1)] if fenced_json else []
            stripped = content.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                candidate_blocks.append(stripped)

            for candidate in candidate_blocks:
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    continue
                if not isinstance(parsed, dict):
                    continue

                task_description = parsed.get("task_description")
                if isinstance(task_description, str) and task_description.strip() and task_description.strip() not in placeholder_descriptions:
                    json_candidates.append(task_description.strip())

                nested_task_spec = parsed.get("task_spec")
                if isinstance(nested_task_spec, dict):
                    nested_description = nested_task_spec.get("task_description")
                    if isinstance(nested_description, str) and nested_description.strip() and nested_description.strip() not in placeholder_descriptions:
                        json_candidates.append(nested_description.strip())

            inline_match = re.search(r'"task_description"\s*:\s*"([^"]+)"', content)
            if inline_match and inline_match.group(1).strip() and inline_match.group(1).strip() not in placeholder_descriptions:
                json_candidates.append(inline_match.group(1).strip())

    for candidates in (supplement_candidates, request_candidates, json_candidates):
        if candidates:
            return candidates[0]
    return ""


def _original_user_query(bundle: dict[str, Any]) -> str:
    checkpoint = bundle.get("checkpoint") or {}
    state = bundle.get("state") or {}
    task_spec = bundle.get("task_spec") or {}

    for candidate in (
        bundle.get("user_query"),
        state.get("user_query"),
        checkpoint.get("user_query"),
        task_spec.get("task_description") if isinstance(task_spec, dict) else "",
        _task_description_from_llm_calls(bundle.get("llm_calls") or []),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _load_bundle(run_dir: Path) -> dict[str, Any]:
    checkpoint = _read_json(run_dir / "checkpoint.json")
    state = checkpoint.get("state") if isinstance(checkpoint, dict) and isinstance(checkpoint.get("state"), dict) else {}

    trace_data = _read_json(run_dir / "execution_trace.json")
    if not isinstance(trace_data, list):
        trace_data = state.get("execution_trace") if isinstance(state.get("execution_trace"), list) else []

    notebook = _read_json(run_dir / "simulation.ipynb")
    if not isinstance(notebook, dict):
        notebook = state.get("final_notebook") or state.get("notebook")
        if not isinstance(notebook, dict):
            notebook = None

    report_text = _read_text(run_dir / "report.md")
    if not report_text and isinstance(state.get("final_report"), str):
        report_text = state["final_report"]

    solution_plan = _read_json(run_dir / "solution_plan.json") or state.get("solution_plan") or _read_json(run_dir / "algorithm_spec.json") or state.get("algorithm_spec")
    notebook_plan = _read_json(run_dir / "notebook_plan.json") or _read_json(run_dir / "code_plan.json")
    algorithm_spec = _read_json(run_dir / "algorithm_spec.json")
    if algorithm_spec is None and isinstance(solution_plan, dict):
        algorithm_spec = solution_plan.get("algorithm_spec")

    bundle = {
        "run_dir": run_dir,
        "checkpoint": checkpoint if isinstance(checkpoint, dict) else {},
        "state": state,
        "trace": [item for item in trace_data if isinstance(item, dict)],
        "task_spec": _read_json(run_dir / "task_spec.json") or state.get("task_spec"),
        "retrieved_knowledge": _read_json(run_dir / "retrieved_knowledge.json") or state.get("retrieved_knowledge"),
        "problem_formalization": _read_json(run_dir / "problem_formalization.json") or state.get("problem_formalization"),
        "solution_plan": solution_plan,
        "verification_results": _read_json(run_dir / "verification_results.json") or state.get("verification_results"),
        "simulation_results": _read_json(run_dir / "simulation_results.json") or state.get("simulation_results"),
        "review_feedback": _read_json(run_dir / "review_feedback.json") or state.get("review_feedback"),
        "notebook_plan": notebook_plan,
        "code_plan": notebook_plan,
        "algorithm_spec": algorithm_spec,
        "code_package": _read_json(run_dir / "code_package.json"),
        "iteration_history": _read_json(run_dir / "iteration_history.json"),
        "notebook": notebook,
        "report_text": report_text,
        "llm_calls": _read_jsonl(run_dir / "llm_logs" / "llm_calls.jsonl", limit=8),
        "user_query": state.get("user_query") or (checkpoint.get("user_query") if isinstance(checkpoint, dict) else ""),
    }
    bundle["plot_specs"] = _build_plot_specs(bundle.get("simulation_results"))
    return bundle


def _has_step_output(bundle: dict[str, Any], step_id: str) -> bool:
    task_spec = _artifact_or_state(bundle, "task_spec") or {}
    knowledge = _artifact_or_state(bundle, "retrieved_knowledge") or {}
    formalization = _artifact_or_state(bundle, "problem_formalization") or {}
    solution_plan = _solution_plan_payload(bundle)
    notebook_plan = _notebook_plan_payload(bundle)
    verification_results = _artifact_or_state(bundle, "verification_results") or {}
    simulation_results = _artifact_or_state(bundle, "simulation_results") or {}
    state_map = {
        "problem_analysis": bool(task_spec) or _latest_trace_for_step(bundle.get("trace", []), step_id) is not None,
        "knowledge_retrieval": bool(knowledge) or _latest_trace_for_step(bundle.get("trace", []), step_id) is not None,
        "model_formulation": bool(formalization) or _latest_trace_for_step(bundle.get("trace", []), step_id) is not None,
        "solution_planning": bool(solution_plan) or _latest_trace_for_step(bundle.get("trace", []), step_id) is not None,
        "notebook_generation": bool(notebook_plan) or bool(bundle.get("notebook")) or _latest_trace_for_step(bundle.get("trace", []), step_id) is not None,
        "verification": bool(verification_results) or _latest_trace_for_step(bundle.get("trace", []), step_id) is not None,
        "simulation": bool(simulation_results) or _latest_trace_for_step(bundle.get("trace", []), step_id) is not None,
        "review": bool(bundle.get("review_feedback") or bundle.get("iteration_history")) or _latest_trace_for_step(bundle.get("trace", []), step_id) is not None,
        "report_generation": bool(bundle.get("report_text")) or _latest_trace_for_step(bundle.get("trace", []), step_id) is not None,
    }
    return state_map.get(step_id, False)


def _current_step_id(bundle: dict[str, Any]) -> str:
    if _is_finished(bundle):
        return "report_generation"

    for item in reversed(bundle.get("trace") or []):
        step_id = _trace_step_id(item)
        if step_id:
            return step_id

    checkpoint = bundle.get("checkpoint") or {}
    checkpoint_step = _checkpoint_step_id(checkpoint.get("stage"))
    if checkpoint_step:
        return checkpoint_step
    return "problem_analysis"


def _is_finished(bundle: dict[str, Any]) -> bool:
    if bundle.get("report_text"):
        return True
    state = bundle.get("state") or {}
    return bool(state.get("final_report"))


def _step_summary_line(step_id: str, bundle: dict[str, Any]) -> str:
    task_spec = _artifact_or_state(bundle, "task_spec") or {}
    knowledge = _artifact_or_state(bundle, "retrieved_knowledge") or {}
    formalization = _artifact_or_state(bundle, "problem_formalization") or {}
    solution_plan = _solution_plan_payload(bundle)
    algorithm_spec = _solution_algorithm_spec(bundle)
    notebook_plan = _notebook_plan_payload(bundle)
    verification_results = _artifact_or_state(bundle, "verification_results") or {}
    simulation_results = _artifact_or_state(bundle, "simulation_results") or {}
    report_text = bundle.get("report_text") or ""
    trace_item = _latest_trace_for_step(bundle.get("trace", []), step_id)
    trace_payload = trace_item.get("payload") if isinstance(trace_item, dict) else {}

    if step_id == "problem_analysis":
        metric = ((task_spec.get("performance_targets") or {}).get("primary_metric") or "task spec captured")
        return f"Primary metric {metric}"
    if step_id == "knowledge_retrieval":
        return f"Papers {_list_count(knowledge.get('relevant_papers'))}"
    if step_id == "model_formulation":
        scenario_spec = formalization.get("scenario_spec") or {}
        math_formulation = formalization.get("math_formulation") or {}
        formula_count = _list_count(math_formulation.get("key_formulas"))
        scenario_count = _list_count(scenario_spec.get("test_scenarios"))
        return f"Scenarios {scenario_count} · formulas {formula_count}"
    if step_id == "solution_planning":
        evaluation_plan = solution_plan.get("evaluation_plan") or {}
        pipeline_steps = _list_count(algorithm_spec.get("pipeline"))
        variable_points = _list_count(evaluation_plan.get("variable_points"))
        return f"Pipeline steps {pipeline_steps} · sweep points {variable_points}"
    if step_id == "notebook_generation":
        notebook = bundle.get("notebook") or {}
        notebook_cells = _list_count(notebook.get("cells")) if isinstance(notebook, dict) else 0
        return f"Notebook cells {notebook_cells or 0} · planned sections {len(notebook_plan)}"
    if step_id == "verification":
        return f"{verification_results.get('status', 'missing')} · errors {_list_count(verification_results.get('errors'))} · warnings {_list_count(verification_results.get('warnings'))}"
    if step_id == "simulation":
        execution_time = simulation_results.get("execution_time")
        time_label = f" · {_format_seconds(execution_time)}" if execution_time not in (None, "") else ""
        return f"{simulation_results.get('status', 'missing')}{time_label}"
    if step_id == "review":
        review_payload = _latest_review_payload(bundle)
        if isinstance(review_payload, dict) and review_payload.get("score") not in (None, ""):
            return f"Review score {review_payload.get('score')}"
        return "Review feedback recorded"
    if step_id == "report_generation":
        return f"Report size {_human_size(len(report_text.encode('utf-8')))}" if report_text else "Awaiting final report"
    return "Awaiting artifact"


def _enabled_workflow_steps(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    has_review = bool(
        bundle.get("review_feedback")
        or bundle.get("iteration_history")
        or _latest_trace_for_step(bundle.get("trace") or [], "review")
    )
    for step in WORKFLOW_STEPS:
        if step["id"] == "review" and not has_review:
            continue
        steps.append(step)
    return steps


def _build_pipeline(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    steps = _enabled_workflow_steps(bundle)
    current_step = _current_step_id(bundle)
    current_index = next((index for index, step in enumerate(steps) if step["id"] == current_step), 0)
    finished = _is_finished(bundle)
    verification_results = _artifact_or_state(bundle, "verification_results") or {}
    simulation_results = _artifact_or_state(bundle, "simulation_results") or {}

    items: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        step_id = step["id"]
        has_output = _has_step_output(bundle, step_id)

        if finished and step_id == "report_generation":
            status = "completed"
        elif step_id == current_step and not finished:
            status = "active"
        elif has_output:
            status = "completed"
        else:
            status = "pending"

        if step_id == "verification" and verification_results:
            verify_status = str(verification_results.get("status") or "").lower()
            if verify_status not in {"", "passed", "success", "ok"}:
                status = "issue" if current_step != step_id else "active"

        if step_id == "simulation" and simulation_results:
            simulation_status = str(simulation_results.get("status") or "").lower()
            if simulation_status == "error":
                status = "issue" if current_step != step_id else "active"
            elif simulation_status in {"success", "passed", "ok"} and status == "pending":
                status = "completed"

        items.append(
            {
                "key": step_id,
                "code": step["code"],
                "label": step["label"],
                "status": status,
                "status_label": STATUS_LABELS[status],
                "summary": _step_summary_line(step_id, bundle),
            }
        )
    return items


def _build_mission(bundle: dict[str, Any]) -> dict[str, Any]:
    solution_plan = _solution_plan_payload(bundle)
    algorithm_spec = _solution_algorithm_spec(bundle)
    simulation_results = _artifact_or_state(bundle, "simulation_results") or {}
    performance_data = simulation_results.get("performance_data") or {}
    verification_results = _artifact_or_state(bundle, "verification_results") or {}
    notebook_plan = _notebook_plan_payload(bundle)
    notebook_cells = _list_count((bundle.get("notebook") or {}).get("cells")) if isinstance(bundle.get("notebook"), dict) else 0
    user_query = _original_user_query(bundle)

    query_bits = []
    if user_query:
        query_bits.append(user_query)
    else:
        architecture = solution_plan.get("architecture") or {}
        algorithm_name = _english_fragment(architecture.get("name") or architecture.get("summary") or algorithm_spec.get("objective"), "Selected design artifact available")
        if algorithm_name:
            query_bits.append(f"Primary design: {algorithm_name}.")
        if notebook_cells or notebook_plan:
            query_bits.append(f"Notebook prepared: {notebook_cells or len(notebook_plan)} cells or planned sections.")
        if verification_results:
            query_bits.append(f"Verification status: {verification_results.get('status', 'missing')}.")
        if simulation_results:
            query_bits.append(f"Simulation status: {simulation_results.get('status', 'missing')}.")
        if bundle.get("report_text"):
            query_bits.append("A final report artifact is present in the selected folder.")

    chips = [
        _english_fragment((solution_plan.get("architecture") or {}).get("strategy_label") or (solution_plan.get("architecture") or {}).get("name") or algorithm_spec.get("objective"), "Structured design"),
        _english_fragment(simulation_results.get("evaluation_level"), "Simulation ready") if simulation_results else "Simulation artifact",
        f"Trace events {len(bundle.get('trace') or [])}",
        f"LLM calls {len(bundle.get('llm_calls') or [])}",
    ]

    query_text = " ".join(query_bits) or "This dashboard follows the selected run and summarizes its structured artifacts in English."

    return {
        "query": query_text,
        "format": "markdown" if _looks_like_markdown(query_text) else "text",
        "chips": [chip for chip in chips if chip],
    }


def _build_overview_cards(bundle: dict[str, Any], latest_activity: float) -> list[dict[str, str]]:
    current_step = _current_step_id(bundle)
    verification_results = _artifact_or_state(bundle, "verification_results") or {}
    simulation_results = _artifact_or_state(bundle, "simulation_results") or {}
    latest_timestamp = _iso_from_timestamp(latest_activity)
    report_status = "available" if bundle.get("report_text") else "waiting"

    return [
        {"label": "Observed Step", "value": _workflow_label(current_step)},
        {"label": "Verification", "value": str(verification_results.get("status") or "waiting")},
        {"label": "Simulation", "value": str(simulation_results.get("status") or "waiting")},
        {"label": "Report", "value": report_status},
        {"label": "LLM Calls", "value": str(len(bundle.get("llm_calls") or []))},
        {"label": "Last Activity", "value": latest_timestamp or "N/A"},
    ]


def _build_runtime_summary(bundle: dict[str, Any], latest_activity: float) -> dict[str, Any]:
    state = bundle.get("state") or {}
    current_step = _current_step_id(bundle)
    age_seconds = max(0.0, time.time() - latest_activity) if latest_activity else 999999.0
    finished = _is_finished(bundle)

    if finished:
        live_label = "COMPLETE"
    elif age_seconds < 25:
        live_label = "LIVE"
    else:
        live_label = "IDLE"

    summary_lines = [
        f"Observed workflow step: {_workflow_label(current_step)}",
        f"Verification retries: {state.get('verification_retry_count', 0)} / {state.get('max_verification_retries', '-')}",
        f"Simulation retries: {state.get('simulation_retry_count', 0)} / {state.get('max_simulation_retries', '-')}",
    ]

    error_lines: list[str] = []
    termination_reason = state.get("termination_reason")
    if termination_reason:
        error_lines.append(f"Termination reason: {_truncate(termination_reason, 220)}")
    error_state = state.get("error_state")
    if error_state:
        error_lines.append(f"Error state: {_truncate(error_state, 220)}")

    return {
        "live_label": live_label,
        "latest_activity_ts": latest_activity,
        "static_lines": summary_lines,
        "error_lines": error_lines,
    }


def _build_execution_feed(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    feed: list[dict[str, Any]] = []
    trace = bundle.get("trace") or []
    for item in trace:
        feed.append(
            {
                "stage_label": _display_trace_label(item),
                "title": _truncate(item.get("title") or "Trace update", 120),
                "summary_lines": [
                    _truncate(line, 160)
                    for line in (item.get("summary_lines") or [])
                    if str(line).strip()
                ],
            }
        )

    if feed:
        return feed

    checkpoint = bundle.get("checkpoint") or {}
    if checkpoint:
        checkpoint_stage = _checkpoint_step_id(checkpoint.get("stage"))
        return [
            {
                "stage_label": _workflow_label(checkpoint_stage) if checkpoint_stage else str(checkpoint.get("stage") or "Checkpoint"),
                "title": "Checkpoint detected",
                "summary_lines": [
                    f"Saved at: {checkpoint.get('timestamp', 'unknown')}",
                    f"Phase: {(bundle.get('state') or {}).get('current_phase', 'unknown')}",
                ],
            }
        ]
    return []


def _build_llm_feed(bundle: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, str]] = []
    for display_index, entry in enumerate(_llm_display_entries(bundle)):
        messages = entry.get("messages") or []
        user_prompt = next((message.get("content", "") for message in reversed(messages) if message.get("role") == "user"), "")
        system_prompt = next((message.get("content", "") for message in messages if message.get("role") == "system"), "")
        prompt_context = _context_link("llm", index=display_index, slot="prompt") if _llm_prompt_text(entry) else None
        response_context = _context_link("llm", index=display_index, slot="response") if _render_full_text(entry.get("response")) else None
        entries.append(
            {
                "timestamp": str(entry.get("ts") or ""),
                "model": str(entry.get("model") or "unknown"),
                "prompt_preview": _truncate(user_prompt or system_prompt, 280),
                "response_preview": _truncate(entry.get("response") or "", 440),
                "prompt_context": prompt_context,
                "response_context": response_context,
            }
        )

    latest_model = entries[0]["model"] if entries else "idle"
    return {
        "latest_model": latest_model,
        "entries": entries[:4],
    }


def _notebook_stats(bundle: dict[str, Any]) -> dict[str, Any]:
    notebook = bundle.get("notebook") or {}
    cells = notebook.get("cells") or []
    code_cells = [cell for cell in cells if cell.get("cell_type") == "code"]
    markdown_cells = [cell for cell in cells if cell.get("cell_type") == "markdown"]
    roles = []
    for cell in cells:
        role = (cell.get("metadata") or {}).get("autowisp_role")
        if role:
            roles.append(str(role))
    return {
        "cell_count": len(cells),
        "code_cells": len(code_cells),
        "markdown_cells": len(markdown_cells),
        "roles": roles[:8],
    }


def _code_counts(run_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for folder_name in ("algorithms", "evaluation", "scenario"):
        folder = run_dir / folder_name
        if folder.exists():
            counts[folder_name] = len([path for path in folder.rglob("*.py") if path.is_file()])
        else:
            counts[folder_name] = 0
    return counts


def _join_lines(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line).strip()


def _issue_preview(value: Any, limit: int = 3) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, list):
        return _join_lines([_truncate(_render_full_text(item), 220) for item in value[:limit]])
    return _truncate(_render_full_text(value), 420)


def _context_link(source: str, **kwargs: Any) -> dict[str, Any]:
    link: dict[str, Any] = {"source": source, "label": CONTEXT_BUTTON_LABEL}
    for key, value in kwargs.items():
        if value not in (None, ""):
            link[key] = value
    return link


def _context_payload(title: str, source: str, content: Any, error: str = "", format_hint: str = "") -> dict[str, str]:
    text = _render_full_text(content)
    return {
        "title": title,
        "source": source,
        "content": text,
        "error": error or "",
        "format": _context_format(source, content, format_hint),
    }


def _json_artifact_context(
    run_dir: Path,
    file_name: str,
    title: str,
    *,
    fallback: Any = None,
    fallback_source: str = "execution_trace.json",
) -> dict[str, str]:
    file_path = run_dir / file_name
    artifact = _read_json(file_path)
    if artifact is not None:
        return _context_payload(title, file_name, artifact, format_hint="json")
    if fallback not in (None, "", [], {}):
        return _context_payload(title, fallback_source, fallback, format_hint="json")
    return _context_payload(title, file_name, "", format_hint="json")


def _text_artifact_context(
    run_dir: Path,
    file_name: str,
    title: str,
    *,
    fallback: str = "",
    fallback_source: str = "execution_trace.json",
) -> dict[str, str]:
    file_path = run_dir / file_name
    format_hint = "markdown" if file_name.lower().endswith(".md") else "text"
    content = _read_text(file_path)
    if content:
        return _context_payload(title, file_name, content, format_hint=format_hint)
    if fallback:
        return _context_payload(title, fallback_source, fallback, format_hint=format_hint)
    return _context_payload(title, file_name, "", format_hint=format_hint)


def _generated_code_context(run_dir: Path, code_package: Any) -> dict[str, str]:
    sections: list[str] = []
    for folder_name in ("scenario", "algorithms", "evaluation"):
        folder = run_dir / folder_name
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*.py")):
            if not path.is_file():
                continue
            rendered = _read_text(path)
            if not rendered:
                continue
            sections.append(f"===== {path.relative_to(run_dir)} =====\n{rendered}".rstrip())

    if sections:
        return _context_payload(
            "Generated Source Files",
            "scenario/, algorithms/, evaluation/",
            "\n\n".join(sections),
            format_hint="code",
        )
    if code_package not in (None, "", [], {}):
        return _context_payload("Generated Source Package", "code_package.json", code_package, format_hint="json")
    return _context_payload("Generated Source Files", "code_package.json", "", format_hint="code")


def _notebook_generation_context(run_dir: Path, bundle: dict[str, Any], trace_payload: Any) -> dict[str, str]:
    notebook = bundle.get("notebook")
    if isinstance(notebook, dict) and notebook:
        return _context_payload("Generated Notebook", "simulation.ipynb", notebook, format_hint="json")
    notebook_plan = _notebook_plan_payload(bundle)
    if notebook_plan:
        return _context_payload("Notebook Plan Context", "notebook_plan.json", notebook_plan, format_hint="json")
    if trace_payload not in (None, "", [], {}):
        return _context_payload("Notebook Generation Context", "execution_trace.json", trace_payload, format_hint="json")
    return _context_payload("Notebook Generation Context", "notebook_plan.json", "", format_hint="json")


def _llm_prompt_text(entry: dict[str, Any]) -> str:
    rendered_messages: list[str] = []
    for message in entry.get("messages") or []:
        role = str(message.get("role") or "unknown").upper()
        content = _render_full_text(message.get("content"))
        if not content:
            continue
        rendered_messages.append(f"[{role}]\n{content}".rstrip())
    return "\n\n".join(rendered_messages).strip()


def _llm_display_entries(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return list(reversed(bundle.get("llm_calls") or []))[:4]


def _stage_context_link(step_id: str, bundle: dict[str, Any]) -> dict[str, Any] | None:
    trace_item = _latest_trace_for_step(bundle.get("trace") or [], step_id)
    trace_payload = trace_item.get("payload") if isinstance(trace_item, dict) and isinstance(trace_item.get("payload"), dict) else {}
    run_dir = bundle["run_dir"]
    solution_plan = _solution_plan_payload(bundle)
    notebook_plan = _notebook_plan_payload(bundle)

    if step_id == "problem_analysis" and (bundle.get("task_spec") or trace_payload):
        return _context_link("stage", step=step_id)
    if step_id == "knowledge_retrieval" and (bundle.get("retrieved_knowledge") or trace_payload):
        return _context_link("stage", step=step_id)
    if step_id == "model_formulation" and (bundle.get("problem_formalization") or trace_payload):
        return _context_link("stage", step=step_id)
    if step_id == "solution_planning" and (solution_plan or trace_payload):
        return _context_link("stage", step=step_id)
    if step_id == "notebook_generation" and (
        bundle.get("notebook")
        or notebook_plan
        or bundle.get("code_package")
        or any((run_dir / folder_name).exists() for folder_name in ("scenario", "algorithms", "evaluation"))
    ):
        return _context_link("stage", step=step_id)
    if step_id == "verification" and (bundle.get("verification_results") or trace_payload):
        return _context_link("stage", step=step_id)
    if step_id == "simulation" and (bundle.get("simulation_results") or trace_payload):
        return _context_link("stage", step=step_id)
    if step_id == "review" and (bundle.get("review_feedback") or bundle.get("iteration_history") or trace_payload):
        return _context_link("stage", step=step_id)
    if step_id == "report_generation" and bundle.get("report_text"):
        return _context_link("stage", step=step_id)
    return None


def _stage_context_payload(step_id: str, bundle: dict[str, Any]) -> dict[str, str]:
    run_dir = bundle["run_dir"]
    trace_item = _latest_trace_for_step(bundle.get("trace") or [], step_id)
    trace_payload = trace_item.get("payload") if isinstance(trace_item, dict) and isinstance(trace_item.get("payload"), dict) else {}

    if step_id == "problem_analysis":
        return _json_artifact_context(run_dir, "task_spec.json", "Problem Analysis Context", fallback=bundle.get("task_spec") or trace_payload)
    if step_id == "knowledge_retrieval":
        return _json_artifact_context(run_dir, "retrieved_knowledge.json", "Knowledge Retrieval Context", fallback=bundle.get("retrieved_knowledge") or trace_payload)
    if step_id == "model_formulation":
        return _json_artifact_context(
            run_dir,
            "problem_formalization.json",
            "Model Formulation Context",
            fallback=bundle.get("problem_formalization") or trace_payload,
        )
    if step_id == "solution_planning":
        return _json_artifact_context(run_dir, "solution_plan.json", "Solution Planning Context", fallback=_solution_plan_payload(bundle) or trace_payload)
    if step_id == "notebook_generation":
        return _notebook_generation_context(run_dir, bundle, trace_payload)
    if step_id == "verification":
        return _json_artifact_context(run_dir, "verification_results.json", "Verification Context", fallback=bundle.get("verification_results") or trace_payload)
    if step_id == "simulation":
        return _json_artifact_context(run_dir, "simulation_results.json", "Simulation Context", fallback=bundle.get("simulation_results") or trace_payload)
    if step_id == "review":
        review_payload = bundle.get("review_feedback") or _latest_review_payload(bundle, trace_payload)
        return _json_artifact_context(
            run_dir,
            "review_feedback.json",
            "Review Context",
            fallback=review_payload,
            fallback_source="iteration_history.json",
        )
    if step_id == "report_generation":
        return _text_artifact_context(run_dir, "report.md", "Final Report Context", fallback=bundle.get("report_text") or "")
    return _context_payload("Full Context", "execution_trace.json", "", format_hint="text")


def _report_context_payload(bundle: dict[str, Any]) -> dict[str, str]:
    return _text_artifact_context(bundle["run_dir"], "report.md", "Final Report Context", fallback=bundle.get("report_text") or "")


def _llm_context_payload(bundle: dict[str, Any], index: int, slot: str) -> dict[str, str]:
    entries = _llm_display_entries(bundle)
    if index < 0 or index >= len(entries):
        return _context_payload("LLM Context", "llm_logs/llm_calls.jsonl", "", format_hint="text")

    entry = entries[index]
    source = "llm_logs/llm_calls.jsonl"
    title_prefix = f"{entry.get('model', 'LLM')} · {entry.get('ts', '')}".strip(" ·")
    if slot == "prompt":
        prompt_text = _llm_prompt_text(entry)
        prompt_format = "markdown" if _looks_like_markdown(prompt_text) else "text"
        return _context_payload(f"Prompt Context · {title_prefix}", source, prompt_text, format_hint=prompt_format)
    if slot == "response":
        response_payload = entry.get("response")
        response_text = _render_full_text(response_payload)
        response_format = "json" if isinstance(response_payload, (dict, list)) else ("markdown" if _looks_like_markdown(response_text) else "text")
        return _context_payload(f"Response Context · {title_prefix}", source, response_payload if isinstance(response_payload, (dict, list)) else response_text, format_hint=response_format)
    return _context_payload("LLM Context", source, "", format_hint="text")


def _finalize_stage_card(card: dict[str, Any], stage_status: str) -> dict[str, Any]:
    if card.get("is_placeholder") and stage_status in {"completed", "issue"} and not card.get("error_message"):
        card["error_message"] = "Expected artifact is missing or could not be rendered."
    return card


def _build_stage_card(step_id: str, bundle: dict[str, Any], stage_status: str) -> dict[str, Any]:
    task_spec = _artifact_or_state(bundle, "task_spec") or {}
    knowledge = _artifact_or_state(bundle, "retrieved_knowledge") or {}
    formalization = _artifact_or_state(bundle, "problem_formalization") or {}
    solution_plan = _solution_plan_payload(bundle)
    algorithm_spec = _solution_algorithm_spec(bundle)
    notebook_plan = _notebook_plan_payload(bundle)
    code_package = bundle.get("code_package") or {}
    verification_results = _artifact_or_state(bundle, "verification_results") or {}
    simulation_results = _artifact_or_state(bundle, "simulation_results") or {}
    report_text = bundle.get("report_text") or ""
    notebook_info = _notebook_stats(bundle)
    code_counts = _code_counts(bundle["run_dir"])
    trace_item = _latest_trace_for_step(bundle.get("trace") or [], step_id)
    trace_payload = trace_item.get("payload") if isinstance(trace_item, dict) and isinstance(trace_item.get("payload"), dict) else {}
    trace_summary = trace_item.get("summary_lines") if isinstance(trace_item, dict) else []

    step = WORKFLOW_BY_ID[step_id]
    card = {
        "key": step_id,
        "code": step["code"],
        "label": step["label"],
        "status": stage_status,
        "status_label": STATUS_LABELS[stage_status],
        "headline": "Awaiting output",
        "meta": [],
        "body": "No displayable artifact is available for this workflow step yet.",
        "body_format": "text",
        "is_placeholder": True,
        "error_message": "",
        "context": _stage_context_link(step_id, bundle),
    }

    if step_id == "problem_analysis":
        payload = task_spec or trace_payload
        performance = (payload.get("performance_targets") or {}) if isinstance(payload, dict) else {}
        card["headline"] = "Structured task requirements captured"
        card["meta"] = [
            f"Metric {performance.get('primary_metric') or 'n/a'}",
            f"Constraint groups {len(payload.get('constraints') or {}) if isinstance(payload.get('constraints'), dict) else len(payload.get('constraints') or []) if isinstance(payload, dict) else 0}",
            f"Design preferences {len(payload.get('design_preferences') or {}) if isinstance(payload.get('design_preferences'), dict) else len(payload.get('design_preferences') or []) if isinstance(payload, dict) else 0}",
        ]
        card["body"] = _join_lines(
            [
                "The original user request is preserved in the run metadata.",
                f"Primary metric: {performance.get('primary_metric') or 'n/a'}.",
                f"Target value: {performance.get('target_value') if performance.get('target_value') not in (None, '') else 'n/a'}.",
                f"Target SNR: {performance.get('target_snr_db') if performance.get('target_snr_db') not in (None, '') else 'n/a'}.",
            ]
        )
        card["is_placeholder"] = False
        return card

    if step_id == "knowledge_retrieval":
        payload = knowledge or trace_payload
        papers = payload.get("relevant_papers") or []
        titles = [paper.get("title") for paper in papers if isinstance(paper, dict) and paper.get("title")][:3]
        card["headline"] = f"{len(papers)} papers retrieved"
        card["meta"] = [
            f"Algorithms {len(payload.get('relevant_algorithms') or [])}",
            f"Simulation libraries {len(payload.get('simulation_libraries') or [])}",
            "Search query captured" if payload.get("paper_search_query") else "Search query missing",
        ]
        card["body"] = _join_lines(titles or ["Bibliographic retrieval results are stored in the selected folder."])
        card["is_placeholder"] = False
        return card

    if step_id == "model_formulation":
        payload = formalization or trace_payload
        scenario_spec = payload.get("scenario_spec") or {} if isinstance(payload, dict) else {}
        math_formulation = payload.get("math_formulation") or {} if isinstance(payload, dict) else {}
        signal_type = _english_fragment(scenario_spec.get("signal_type"), "").strip()
        if not signal_type or signal_type.lower() in {"unknown", "n/a"}:
            signal_type = "Structured system model"
        formula_count = len(math_formulation.get("key_formulas") or []) if isinstance(math_formulation, dict) else 0
        scenario_count = len(scenario_spec.get("test_scenarios") or []) if isinstance(scenario_spec, dict) else 0
        variable_count = len(math_formulation.get("variables") or []) if isinstance(math_formulation, dict) else 0
        meta = []
        if scenario_count:
            meta.append(f"Scenarios {scenario_count}")
        if formula_count:
            meta.append(f"Formulas {formula_count}")
        if variable_count:
            meta.append(f"Variables {variable_count}")
        if not meta:
            meta = ["Scenario spec available", "System model documented", "Math formulation captured"]
        card["headline"] = "Structured signal and system model ready"
        card["meta"] = meta
        card["body"] = _join_lines(
            [
                signal_type,
                _truncate(payload.get("system_model_doc") or "", 320) if isinstance(payload, dict) else "",
                _truncate(((math_formulation.get("objective") or {}).get("description") or ""), 220) if isinstance(math_formulation, dict) else "",
            ]
        ) or "Problem formalization is stored in the selected run."
        card["is_placeholder"] = False if payload else True
        return card

    if step_id == "solution_planning":
        payload = solution_plan or trace_payload
        architecture = payload.get("architecture") or {} if isinstance(payload, dict) else {}
        evaluation_plan = payload.get("evaluation_plan") or {} if isinstance(payload, dict) else {}
        baseline_methods = ((algorithm_spec.get("evaluation_contract") or {}).get("baseline_methods") or []) if isinstance(algorithm_spec, dict) else []
        card["headline"] = _english_fragment(architecture.get("name") or architecture.get("strategy_label"), "Solution plan captured")
        card["meta"] = [
            f"Pipeline steps {len(algorithm_spec.get('pipeline') or []) if isinstance(algorithm_spec, dict) else 0}",
            f"Sweep points {len(evaluation_plan.get('variable_points') or []) if isinstance(evaluation_plan, dict) else 0}",
            f"Baselines {len(baseline_methods)}",
        ]
        card["body"] = _join_lines(
            [
                _truncate(str(architecture.get("summary") or architecture.get("rationale") or ""), 320),
                f"Primary variable: {evaluation_plan.get('independent_variable')}." if isinstance(evaluation_plan, dict) and evaluation_plan.get("independent_variable") else "",
            ]
        ) or "Solution planning metadata is stored in the selected run."
        card["is_placeholder"] = False if payload else True
        return card

    if step_id == "notebook_generation":
        planned_roles = [str(item.get("role")) for item in notebook_plan[:5] if isinstance(item, dict) and item.get("role")]
        headline = "Notebook generated" if notebook_info["cell_count"] else "Notebook structure prepared"
        card["headline"] = headline
        card["meta"] = [
            f"Planned sections {len(notebook_plan)}",
            f"Notebook cells {notebook_info['cell_count']}",
            f"Code folders {sum(code_counts.values())}",
        ]
        card["body"] = _join_lines(planned_roles or notebook_info.get("roles") or ["Notebook structure metadata is stored in the selected run."])
        card["is_placeholder"] = False if notebook_plan or bundle.get("notebook") or code_package else True
        return _finalize_stage_card(card, stage_status)

    if step_id == "verification":
        result = verification_results or trace_payload
        required_roles = result.get("required_roles") or [] if isinstance(result, dict) else []
        notebook_summary = result.get("notebook_summary") or {} if isinstance(result, dict) else {}
        guidance = result.get("repair_guidance") or [] if isinstance(result, dict) else []
        card["headline"] = f"Verification status: {result.get('status', 'missing') if isinstance(result, dict) else 'missing'}"
        card["meta"] = [
            f"Errors {len(result.get('errors') or []) if isinstance(result, dict) else 0}",
            f"Warnings {len(result.get('warnings') or []) if isinstance(result, dict) else 0}",
            f"Required roles {len(required_roles)}",
        ]
        card["body"] = _join_lines(
            guidance
            or required_roles
            or [
                f"Notebook cells: {notebook_summary.get('cells', notebook_info['cell_count'])}",
                f"Code cells: {notebook_summary.get('code_cells', notebook_info['code_cells'])}",
                f"Markdown cells: {notebook_summary.get('markdown_cells', notebook_info['markdown_cells'])}",
            ]
        )
        card["is_placeholder"] = False if result else True
        if isinstance(result, dict):
            card["error_message"] = _issue_preview(result.get("errors") or result.get("warnings"))
            if stage_status == "issue" and not card["error_message"]:
                card["error_message"] = "Verification reported issues, but no detailed error payload was captured."
        return _finalize_stage_card(card, stage_status)

    if step_id == "simulation":
        result = simulation_results or trace_payload
        performance_data = result.get("performance_data") or {} if isinstance(result, dict) else {}
        metric_sections = [key for key, value in performance_data.items() if isinstance(value, dict)] if isinstance(performance_data, dict) else []
        algorithm_label = _english_fragment(result.get("evaluation_level") if isinstance(result, dict) else "", "Simulation result captured")
        body_lines = [algorithm_label]
        error_log = result.get("error_log") if isinstance(result, dict) else ""
        if metric_sections:
            body_lines.extend(
                [
                    f"Performance sections: {', '.join(_display_key_label(key) for key in metric_sections[:4])}.",
                    f"Elapsed: {_format_seconds(result.get('execution_time'))}." if isinstance(result, dict) and result.get("execution_time") not in (None, "") else "",
                    f"Result keys: {len(performance_data)}.",
                ]
            )
        elif performance_data:
            body_lines.append(_truncate(_render_full_text(performance_data), 520))
        elif error_log:
            body_lines.append(_truncate(_normalize_display_text(str(error_log)), 520))
            if "Traceback" in str(error_log):
                card["body_format"] = "code"
        else:
            result_preview = _render_text(result, 520)
            body_lines.append(result_preview or "Simulation output is present in the selected artifact.")
        card["headline"] = f"Simulation status: {result.get('status', 'missing') if isinstance(result, dict) else 'missing'}"
        card["meta"] = [
            str(result.get("evaluation_level") or result.get("stage") or "n/a") if isinstance(result, dict) else "n/a",
            f"Elapsed {_format_seconds(result.get('execution_time'))}" if isinstance(result, dict) and result.get("execution_time") not in (None, "") else "Elapsed n/a",
            f"Plot specs {len(bundle.get('plot_specs') or [])}",
        ]
        card["body"] = _join_lines(body_lines)
        card["is_placeholder"] = False if result else True
        if isinstance(result, dict) and str(result.get("status") or "").lower() == "error":
            card["error_message"] = _issue_preview(result.get("error_log")) or "Simulation reported an error."
        return _finalize_stage_card(card, stage_status)

    if step_id == "review":
        review_payload = _latest_review_payload(bundle, trace_payload)
        review_score = None
        confidence = None
        summary = ""
        risks: list[str] = []
        actions: list[str] = []
        if isinstance(review_payload, dict):
            review_score = review_payload.get("overall_score") if review_payload.get("overall_score") not in (None, "") else review_payload.get("score")
            confidence = review_payload.get("confidence")
            summary = str(review_payload.get("summary") or review_payload.get("overall_assessment") or "").strip()
            risks = [str(item) for item in (review_payload.get("technical_risks") or (review_payload.get("result_health") or {}).get("main_concerns") or review_payload.get("weaknesses") or []) if str(item).strip()]
            actions = [str(item) for item in (review_payload.get("actionable_notes") or review_payload.get("improvement_suggestions") or []) if str(item).strip()]
        card["headline"] = f"Review score {_format_table_value(review_score)}" if review_score not in (None, "") else "Review summary available"
        card["meta"] = [
            f"Confidence {_format_confidence(confidence)}",
            f"Risks {len(risks)}",
            f"Actions {len(actions)}",
        ]
        card["body"] = _join_lines(
            [
                _truncate(summary, 320),
                f"Top risk: {_truncate(risks[0], 220)}" if risks else "",
                f"Next action: {_truncate(actions[0], 220)}" if actions else "",
            ]
        ) or "Review feedback artifact is available for this run."
        card["is_placeholder"] = False if (review_payload not in (None, "", [], {}) or trace_item) else True
        return _finalize_stage_card(card, stage_status)

    if step_id == "report_generation":
        card["headline"] = "Final report available" if report_text else "Awaiting final report"
        card["meta"] = [
            f"Size {_human_size(len(report_text.encode('utf-8')))}" if report_text else "Report not written",
            f"Trace {len(bundle.get('trace') or [])}",
            f"LLM {len(bundle.get('llm_calls') or [])}",
        ]
        if report_text:
            card["body"] = _report_preview_text(report_text, 900)
            card["body_format"] = "markdown"
            card["is_placeholder"] = False
        elif stage_status in {"active", "completed", "issue"}:
            card["error_message"] = "The run reached report generation, but report.md is missing or unreadable."
        return _finalize_stage_card(card, stage_status)

    return _finalize_stage_card(card, stage_status)


def _build_stage_cards(bundle: dict[str, Any], pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status_by_key = {item["key"]: item["status"] for item in pipeline}
    return [_build_stage_card(stage["id"], bundle, status_by_key.get(stage["id"], "pending")) for stage in _enabled_workflow_steps(bundle)]


def _build_focus(bundle: dict[str, Any], stage_cards: list[dict[str, Any]]) -> dict[str, Any]:
    current_step = _current_step_id(bundle)
    for card in stage_cards:
        if card["key"] == current_step:
            trace_item = _latest_trace_for_step(bundle.get("trace") or [], current_step)
            return {
                "stage_label": _workflow_label(current_step),
                "status": card["status"],
                "status_label": card["status_label"],
                "headline": card["headline"],
                "meta": card["meta"],
                "body": card["body"],
                "body_format": card.get("body_format", "text"),
                "summary_lines": (trace_item.get("summary_lines") or [])[:8] if trace_item else [],
                "is_placeholder": card.get("is_placeholder", False),
                "error_message": card.get("error_message", ""),
                "context": card.get("context"),
            }

    fallback = stage_cards[0] if stage_cards else {
        "label": "Waiting",
        "status": "pending",
        "status_label": STATUS_LABELS["pending"],
        "headline": "Awaiting experiment output",
        "meta": [],
        "body": "No experiment folder is currently available under the selected root.",
        "is_placeholder": True,
    }
    return {
        "stage_label": fallback.get("label", "Waiting"),
        "status": fallback.get("status", "pending"),
        "status_label": fallback.get("status_label", STATUS_LABELS["pending"]),
        "headline": fallback.get("headline", "Awaiting experiment output"),
        "meta": fallback.get("meta", []),
        "body": fallback.get("body", ""),
        "body_format": fallback.get("body_format", "text"),
        "summary_lines": [],
        "is_placeholder": fallback.get("is_placeholder", True),
        "error_message": fallback.get("error_message", ""),
        "context": fallback.get("context"),
    }


def _metric_at_target(performance_data: dict[str, Any], metric_key: str, task_spec: dict[str, Any]) -> str:
    values = performance_data.get(metric_key) or []
    snr_values = performance_data.get("snr_db_list") or performance_data.get("snr_list") or []
    target_snr = ((task_spec.get("performance_targets") or {}).get("target_snr_db") if isinstance(task_spec, dict) else None)
    if not values:
        return "n/a"
    if target_snr is None or not snr_values:
        return f"{values[-1]:.3f}" if isinstance(values[-1], (int, float)) else str(values[-1])
    best_index = min(range(len(snr_values)), key=lambda index: abs(float(snr_values[index]) - float(target_snr)))
    metric_value = values[best_index]
    if isinstance(metric_value, (int, float)):
        return f"{metric_value:.3f}"
    return str(metric_value)


def _build_performance_panel(bundle: dict[str, Any]) -> dict[str, Any]:
    simulation_results = _artifact_or_state(bundle, "simulation_results") or {}
    performance_data = simulation_results.get("performance_data") or {}
    plot_specs = bundle.get("plot_specs") or []
    run_name = bundle["run_dir"].name
    plot_version = _iso_timestamp(bundle["run_dir"] / "simulation_results.json") if plot_specs else ""
    error_message = ""
    summary = ""
    summary_format = "text"
    summary_table = None
    context = _context_link("stage", step="simulation") if simulation_results not in (None, "", [], {}) else None

    metrics: list[dict[str, str]] = []
    if isinstance(performance_data, dict) and performance_data:
        elapsed_seconds = performance_data.get("elapsed_sec", simulation_results.get("execution_time"))
        metrics = _build_performance_metric_cards(bundle, elapsed_seconds)
        summary_table = _build_performance_summary_table(bundle) or _build_table_preview(performance_data)
        if summary_table:
            summary_format = "table"
        else:
            summary = _render_full_text(performance_data)
            summary_format = "json"
    else:
        status_value = str(simulation_results.get("status") or ("not-run" if _is_finished(bundle) else "missing"))
        metrics.append({"label": "Status", "value": status_value})
        if simulation_results.get("execution_time") is not None:
            metrics.append({"label": "Elapsed", "value": _format_seconds(simulation_results["execution_time"])})
    if str(simulation_results.get("status") or "").lower() == "error":
        error_message = _issue_preview(simulation_results.get("error_log")) or "Simulation reported an error."

    summary_source = simulation_results.get("error_log") or performance_data
    if not summary and summary_table is None:
        if isinstance(summary_source, str) and summary_source.strip():
            summary = _normalize_display_text(summary_source)
            summary_format = "code" if "Traceback" in summary else ("markdown" if _looks_like_markdown(summary) else "text")
        elif summary_source:
            summary = _render_full_text(summary_source)
            summary_format = "json" if isinstance(summary_source, (dict, list)) else "text"
        else:
            summary = "Simulation was not executed for this run." if _is_finished(bundle) else "No simulation result is available yet."
            summary_format = "text"

    return {
        "summary": summary,
        "summary_format": summary_format,
        "summary_table": summary_table,
        "metrics": metrics,
        "plot_url": f"/api/plot/{run_name}?index=0" if plot_specs else "",
        "plot_version": plot_version,
        "is_placeholder": not bool(summary_source) and not _is_finished(bundle),
        "error_message": error_message,
        "context": context,
    }


def _build_report_panel(bundle: dict[str, Any]) -> dict[str, Any]:
    report_text = bundle.get("report_text") or ""
    if not report_text:
        return {
            "headline": "Final Report / Live Draft",
            "content": "No report text is available yet. This panel will switch to the latest report preview as the run approaches completion.",
            "format": "text",
            "is_placeholder": True,
            "context": None,
            "error_message": "The run completed without a readable report artifact." if _is_finished(bundle) else "",
        }
    return {
        "headline": "Final Report / Live Draft",
        "content": _report_preview_text(report_text, 7000),
        "format": "markdown",
        "is_placeholder": False,
        "context": _context_link("report"),
        "error_message": "",
    }


def _build_dashboard_snapshot(run_dir: Path, root: Path) -> dict[str, Any]:
    bundle = _load_bundle(run_dir)
    pipeline = _build_pipeline(bundle)
    latest_activity = _latest_activity_mtime(run_dir)
    stage_cards = _build_stage_cards(bundle, pipeline)
    available_runs = _list_run_dirs(root)

    return {
        "run": {
            "name": run_dir.name,
            "path": _display_run_path(root, run_dir),
            "experiments_root": _root_label(root),
            "root_key": _root_token(root),
            "available_roots": _root_options(),
            "updated_at": _iso_from_timestamp(latest_activity),
            "available_runs": available_runs,
        },
        "mission": _build_mission(bundle),
        "overview_cards": _build_overview_cards(bundle, latest_activity),
        "pipeline": pipeline,
        "execution_feed": _build_execution_feed(bundle),
        "focus": _build_focus(bundle, stage_cards),
        "runtime": _build_runtime_summary(bundle, latest_activity),
        "llm_feed": _build_llm_feed(bundle),
        "stage_cards": stage_cards,
        "report": _build_report_panel(bundle),
        "performance": _build_performance_panel(bundle),
    }


def _empty_dashboard_snapshot(root: Path) -> dict[str, Any]:
    empty_pipeline = [
        {
            "key": stage["id"],
            "code": stage["code"],
            "label": stage["label"],
            "status": "pending",
            "status_label": STATUS_LABELS["pending"],
            "summary": "Awaiting experiment output",
        }
        for stage in WORKFLOW_STEPS
        if not stage.get("optional")
    ]
    empty_cards = [
        {
            "key": stage["id"],
            "code": stage["code"],
            "label": stage["label"],
            "status": "pending",
            "status_label": STATUS_LABELS["pending"],
            "headline": "Awaiting output",
            "meta": [],
            "body": "Start a run and this panel will automatically show the latest structured summary for the step.",
            "is_placeholder": True,
        }
        for stage in WORKFLOW_STEPS
        if not stage.get("optional")
    ]
    return {
        "run": {
            "name": "NO RUN",
            "path": _display_run_path(root),
            "experiments_root": _root_label(root),
            "root_key": _root_token(root),
            "available_roots": _root_options(),
            "updated_at": "",
            "available_runs": _list_run_dirs(root),
        },
        "mission": {
            "query": "Start a run and this monitor will automatically follow the newest run while presenting English summaries of the available artifacts.",
            "format": "text",
            "chips": ["AUTO-FOLLOW", "LIVE MONITOR"],
        },
        "overview_cards": [
            {"label": "Observed Step", "value": "Waiting"},
            {"label": "Verification", "value": "waiting"},
            {"label": "Simulation", "value": "waiting"},
            {"label": "Report", "value": "waiting"},
            {"label": "LLM Calls", "value": "0"},
            {"label": "Last Activity", "value": "N/A"},
        ],
        "pipeline": empty_pipeline,
        "execution_feed": [],
        "focus": {
            "stage_label": "Waiting",
            "status": "pending",
            "status_label": STATUS_LABELS["pending"],
            "headline": "No experiment output detected yet",
            "meta": [],
            "body": "The dashboard now follows experiment artifacts instead of the raw folder tree, and it will update automatically once a run appears.",
            "summary_lines": [],
            "is_placeholder": True,
            "error_message": "",
            "context": None,
        },
        "runtime": {
            "live_label": "IDLE",
            "latest_activity_ts": 0,
            "static_lines": [
                "No run folder is currently available under the selected data folder.",
                "After main.py starts writing artifacts, the page will switch to the latest run automatically.",
            ],
            "error_lines": [],
        },
        "llm_feed": {"latest_model": "idle", "entries": []},
        "stage_cards": empty_cards,
        "report": {
            "headline": "Final Report / Live Draft",
            "content": "No report is available yet.",
            "format": "text",
            "is_placeholder": True,
            "context": None,
            "error_message": "",
        },
        "performance": {
            "summary": "No simulation metrics are available yet.",
            "metrics": [{"label": "Status", "value": "waiting"}],
            "plot_url": "",
            "plot_version": "",
            "is_placeholder": True,
            "error_message": "",
        },
    }


def _plot_png(run_dir: Path, index: int) -> bytes:
    bundle = _load_bundle(run_dir)
    plot_specs = bundle.get("plot_specs") or []
    if index < 0 or index >= len(plot_specs):
        abort(404, description="Unknown plot")

    spec = plot_specs[index]
    figure = Figure(figsize=(7.2, 4.1), tight_layout=True)
    axis = figure.subplots()
    figure.patch.set_facecolor("#091425")
    axis.set_facecolor("#0d1c31")

    palette = ["#31d0ff", "#ffc857", "#4be38f", "#ff7d93", "#8ac6ff", "#f59e0b"]
    for series_index, series in enumerate(spec["series"]):
        axis.plot(
            spec["x_values"],
            series["values"],
            marker="o",
            linewidth=2.0,
            color=palette[series_index % len(palette)],
            label=series["label"],
        )

    axis.set_title(spec["title"], color="#d6e8ff")
    axis.set_xlabel(spec["x_label"], color="#9db3d1")
    axis.tick_params(colors="#9db3d1")
    axis.grid(True, alpha=0.18, color="#6d86aa")
    for spine in axis.spines.values():
        spine.set_color("#26486d")

    if len(spec["series"]) <= 8:
        legend = axis.legend(loc="best", frameon=False)
        for text in legend.get_texts():
            text.set_color("#d6e8ff")

    image_buffer = io.BytesIO()
    figure.savefig(image_buffer, format="png", dpi=140, facecolor=figure.get_facecolor())
    image_buffer.seek(0)
    return image_buffer.getvalue()


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/api/roots/pick", methods=["POST"])
def pick_root() -> Any:
    selected = _pick_root_dir()
    if selected is None:
        return jsonify({"root_key": "", "label": "", "cancelled": True})

    return jsonify(
        {
            "root_key": _root_token(selected),
            "label": _root_label(selected),
            "cancelled": False,
        }
    )


@app.route("/api/dashboard")
def dashboard() -> Any:
    selected_root = _resolve_root_dir(request.args.get("root", "").strip())
    requested_run = request.args.get("run", "").strip()
    if requested_run:
        run_dir = _resolve_run_dir(requested_run, selected_root)
        return jsonify(_build_dashboard_snapshot(run_dir, selected_root))

    runs = _list_run_dirs(selected_root)
    default_run = _default_run_name(runs)
    if not default_run:
        return jsonify(_empty_dashboard_snapshot(selected_root))
    return jsonify(_build_dashboard_snapshot(_resolve_run_dir(default_run, selected_root), selected_root))


@app.route("/api/context/<run_name>")
def context_payload(run_name: str) -> Any:
    selected_root = _resolve_root_dir(request.args.get("root", "").strip())
    run_dir = _resolve_run_dir(run_name, selected_root)
    bundle = _load_bundle(run_dir)
    source = request.args.get("source", "").strip().lower()

    if source == "report":
        return jsonify(_report_context_payload(bundle))

    if source == "stage":
        step_id = request.args.get("step", "").strip()
        if step_id not in WORKFLOW_BY_ID:
            abort(404, description=f"Unknown workflow step: {step_id}")
        return jsonify(_stage_context_payload(step_id, bundle))

    if source == "llm":
        slot = request.args.get("slot", "response").strip().lower()
        try:
            index = int(request.args.get("index", "0"))
        except ValueError:
            abort(400, description="Invalid LLM entry index")
        return jsonify(_llm_context_payload(bundle, index, slot))

    abort(400, description="Unknown context source")


@app.route("/api/plot/<run_name>")
def plot_png(run_name: str) -> Any:
    plot_index = int(request.args.get("index", "0"))
    selected_root = _resolve_root_dir(request.args.get("root", "").strip())
    run_dir = _resolve_run_dir(run_name, selected_root)
    png_bytes = _plot_png(run_dir, plot_index)
    return send_file(io.BytesIO(png_bytes), mimetype="image/png")


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoWiSPA stage monitor")
    parser.add_argument(
        "--experiments-root",
        type=str,
        default=str(DEFAULT_EXPERIMENTS_ROOT),
        help="Path to the experiments directory",
    )
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--log-level", type=str, default="INFO")
    args = parser.parse_args()

    global experiments_root  # noqa: PLW0603
    experiments_root = Path(args.experiments_root).resolve()

    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(level=log_level, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    logger.info("Serving stage monitor from %s", experiments_root)
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()