"""
Markdown ↔ Dict conversion tool

Used after migrating Agent output from JSON to Markdown format,
parsing LLM-returned Markdown into dict structures consumable by code.
"""

from __future__ import annotations

import json
import re


# ── JSON compatibility layer ──────────────────────────────────────────────────

def try_json_first(text: str) -> dict | list | None:
    """Try to parse text as JSON (including ```json ``` code block extraction)."""
    text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    m = re.search(r"```(?:json)?\s*([\[{].*?[\]}])\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
    return None


# ── Markdown Section parsing ──────────────────────────────────────────────────

def parse_md_sections(text: str, level: int = 2) -> dict[str, str]:
    """Split Markdown by ##/### headings into {heading: content} dict."""
    prefix = "#" * level + " "
    sections: dict[str, str] = {}
    current_key = ""
    buf: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith(prefix) and not stripped.startswith(prefix + "#"):
            if current_key:
                sections[current_key] = "\n".join(buf).strip()
            current_key = stripped[len(prefix):].strip()
            buf = []
        else:
            buf.append(line)
    if current_key:
        sections[current_key] = "\n".join(buf).strip()
    return sections


# ── Element extraction ─────────────────────────────────────────────────────────

def extract_bullets(text: str) -> list[str]:
    """Extract `- xxx` or `* xxx` list items."""
    items = []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("- "):
            items.append(s[2:].strip())
        elif s.startswith("* "):
            items.append(s[2:].strip())
    return items


def extract_kv_bold(text: str) -> dict[str, str]:
    """Extract `**key**: value` format key-value pairs."""
    result: dict[str, str] = {}
    for m in re.finditer(r"\*\*(.+?)\*\*\s*[:：]\s*(.+)", text):
        result[m.group(1).strip()] = m.group(2).strip()
    return result


def extract_table_rows(text: str) -> list[dict[str, str]]:
    """Parse Markdown table into list[dict], using headers as keys."""
    lines = [l.strip() for l in text.split("\n") if l.strip().startswith("|")]
    if len(lines) < 3:
        return []
    headers = [h.strip() for h in lines[0].split("|")[1:-1]]
    rows = []
    for line in lines[2:]:
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


def extract_numbered_items(text: str) -> list[str]:
    """Extract `1. xxx` numbered list items."""
    items = []
    for line in text.split("\n"):
        s = line.strip()
        m = re.match(r"\d+[.、]\s*(.+)", s)
        if m:
            items.append(m.group(1).strip())
    return items


# ── Dict → Readable Markdown conversion (for HITL display) ────────────────────────────

def dict_to_readable_md(d: dict | list | str, title: str = "", max_depth: int = 3) -> str:
    """Convert dict/list to human-readable Markdown text."""
    if isinstance(d, str):
        return d
    parts: list[str] = []
    if title:
        parts.append(f"#### {title}")
    _render_value(d, parts, depth=0, max_depth=max_depth)
    return "\n".join(parts)


def _render_value(val, parts: list[str], depth: int, max_depth: int) -> None:
    indent = "  " * depth
    if depth >= max_depth:
        parts.append(f"{indent}{str(val)[:200]}")
        return
    if isinstance(val, dict):
        for k, v in val.items():
            if isinstance(v, (dict, list)):
                parts.append(f"{indent}- **{k}**:")
                _render_value(v, parts, depth + 1, max_depth)
            else:
                parts.append(f"{indent}- **{k}**: {v}")
    elif isinstance(val, list):
        for item in val[:20]:
            if isinstance(item, dict):
                first_val = next(iter(item.values()), "")
                parts.append(f"{indent}- {first_val}")
                for k2, v2 in list(item.items())[1:]:
                    parts.append(f"{indent}  - {k2}: {v2}")
            else:
                parts.append(f"{indent}- {item}")
    else:
        parts.append(f"{indent}{val}")
