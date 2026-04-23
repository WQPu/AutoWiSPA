"""
Event Bus — Communication bridge between AutoWiSPA nodes and the Web frontend

Design principles:
- Global singleton, obtained via get_event_bus()
- No-op (NoOpBus) in non-Web mode, zero intrusion
- Supports synchronous emit + async HITL blocking wait
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional


class EventType(str, Enum):
    """Event type enumeration"""

    # ── Node lifecycle ──
    NODE_START = "node_start"           # Node starts execution
    NODE_END = "node_end"               # Node finishes execution

    # ── Data updates ──
    STATE_UPDATE = "state_update"       # State field update
    LOG = "log"                         # Log message

    # ── HITL ──
    HITL_REQUEST = "hitl_request"       # Request human feedback (frontend shows input)
    HITL_RESPONSE = "hitl_response"     # Human feedback returned (frontend submits)

    # ── Simulation ──
    SANDBOX_START = "sandbox_start"     # Sandbox starts execution
    SANDBOX_END = "sandbox_end"         # Sandbox finishes execution
    SANDBOX_STDOUT = "sandbox_stdout"   # Sandbox stdout incremental output
    SANDBOX_STDERR = "sandbox_stderr"   # Sandbox stderr incremental output

    # ── Data snapshot (Phase 2) ──
    CODE_UPDATE = "code_update"         # Code package update (pushed after S4 generation)
    PERF_UPDATE = "perf_update"         # Performance data update (pushed after S5 success)

    # ── LLM stream (Phase 3) ──
    LLM_START = "llm_start"             # An LLM call starts
    LLM_CHUNK = "llm_chunk"             # LLM incremental output
    LLM_END = "llm_end"                 # An LLM call ends

    # ── Iteration comparison (Phase 3) ──
    ITERATION_UPDATE = "iteration_update"  # Comparison data after each review round


@dataclass
class Event:
    """A single event"""
    type: EventType
    node: str = ""
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    seq: int = 0
    run_id: str = ""


class EventBus:
    """
    Thread-safe event bus, supports:
    1. emit()          — Synchronously publish events, notify all subscribers
    2. wait_for_human() — Block current thread until frontend submits HITL feedback
    3. subscribe()      — Register callback
    """

    def __init__(self) -> None:
        self._subscribers: list[Callable[[Event], None]] = []
        self._lock = threading.Lock()
        # HITL blocking mechanism: each wait_for_human creates a (threading.Event, result_slot) pair
        self._hitl_event: Optional[threading.Event] = None
        self._hitl_result: Optional[dict] = None
        # Event history (for frontend polling mode)
        self._history: list[Event] = []
        self._run_id: str = ""
        self._seq: int = 0
        self._event_log_file: Optional[Path] = None
        # Chunk buffer: accumulates per-node LLM streaming text so that only
        # one llm_end record (with full text) is written to disk instead of
        # thousands of individual llm_chunk records.
        self._chunk_buffers: dict[str, list[str]] = {}

    # ── Subscribe / Publish ──

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def emit(self, event: Event) -> None:
        with self._lock:
            self._seq += 1
            event.seq = self._seq
            if not event.run_id:
                event.run_id = self._run_id
            # LLM_CHUNK not written to history or log file — chunks are
            # buffered in _chunk_buffers and flushed as part of llm_end.
            if event.type != EventType.LLM_CHUNK:
                self._history.append(event)
            subs = list(self._subscribers)
            log_file = self._event_log_file
        if log_file is not None and event.type != EventType.LLM_CHUNK:
            try:
                payload = {
                    "seq": event.seq,
                    "run_id": event.run_id,
                    "timestamp": event.timestamp,
                    "type": event.type.value,
                    "node": event.node,
                    "data": event.data,
                }
                with log_file.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            except Exception:
                pass
        for cb in subs:
            try:
                cb(event)
            except Exception:
                pass  # Subscriber exceptions should not affect main flow

    def configure_run(self, run_id: str, log_dir: str | None = None) -> None:
        with self._lock:
            self._run_id = run_id
            self._seq = 0
            if log_dir:
                path = Path(log_dir)
                path.mkdir(parents=True, exist_ok=True)
                self._event_log_file = path / "events.jsonl"
            else:
                self._event_log_file = None

    # ── Convenience emit ──

    def emit_node_start(self, node: str, data: dict | None = None) -> None:
        self.emit(Event(type=EventType.NODE_START, node=node, data=data or {}))

    def emit_node_end(self, node: str, data: dict | None = None) -> None:
        self.emit(Event(type=EventType.NODE_END, node=node, data=data or {}))

    def emit_state_update(self, node: str, data: dict) -> None:
        self.emit(Event(type=EventType.STATE_UPDATE, node=node, data=data))

    def emit_log(self, node: str, message: str, level: str = "info") -> None:
        self.emit(Event(type=EventType.LOG, node=node, data={"message": message, "level": level}))

    def emit_llm_start(
        self,
        node: str,
        model: str,
        prompt_preview: str = "",
        prompt_text: str = "",
        usage: dict | None = None,
    ) -> None:
        # Reset chunk buffer for this node before the new LLM call.
        with self._lock:
            self._chunk_buffers[node] = []
        payload = {"model": model, "prompt_preview": prompt_preview, "prompt_text": prompt_text}
        if usage:
            payload.update(usage)
        self.emit(Event(type=EventType.LLM_START, node=node, data=payload))

    def emit_llm_chunk(self, node: str, chunk: str) -> None:
        # Accumulate text in buffer (no disk write); still push to subscribers
        # so the Web UI receives real-time streaming tokens.
        with self._lock:
            self._chunk_buffers.setdefault(node, []).append(chunk)
        self.emit(Event(type=EventType.LLM_CHUNK, node=node, data={"chunk": chunk}))

    def emit_llm_end(self, node: str, model: str, response_preview: str = "", usage: dict | None = None) -> None:
        # Flush accumulated chunk buffer into the llm_end event as response_full.
        # This produces one log record per LLM call instead of thousands of chunk records.
        with self._lock:
            full_text = "".join(self._chunk_buffers.pop(node, []))
        payload = {"model": model, "response_preview": response_preview, "response_full": full_text}
        if usage:
            payload.update(usage)
        self.emit(Event(type=EventType.LLM_END, node=node, data=payload))

    def emit_sandbox_start(self, node: str, data: dict | None = None) -> None:
        self.emit(Event(type=EventType.SANDBOX_START, node=node, data=data or {}))

    def emit_sandbox_end(self, node: str, data: dict | None = None) -> None:
        self.emit(Event(type=EventType.SANDBOX_END, node=node, data=data or {}))

    def emit_sandbox_stdout(self, node: str, chunk: str) -> None:
        self.emit(Event(type=EventType.SANDBOX_STDOUT, node=node, data={"chunk": chunk}))

    def emit_sandbox_stderr(self, node: str, chunk: str) -> None:
        self.emit(Event(type=EventType.SANDBOX_STDERR, node=node, data={"chunk": chunk}))

    def emit_iteration_update(self, node: str, data: dict) -> None:
        self.emit(Event(type=EventType.ITERATION_UPDATE, node=node, data=data))

    # ── HITL (Human feedback) ──

    def wait_for_human(self, node: str, prompt: str, context: dict | None = None, timeout: float = 10) -> dict:
        """
        Block at the current node, waiting for frontend to submit feedback.

        Args:
            node: Node name
            prompt: Prompt text displayed to the user
            context: Context data to display to the user
            timeout: Timeout in seconds, default 10 minutes

        Returns:
            {"action": "approve" | "revise" | "skip", "feedback": "..."}
        """
        self._hitl_event = threading.Event()
        self._hitl_result = None

        self.emit(Event(
            type=EventType.HITL_REQUEST,
            node=node,
            data={"prompt": prompt, "context": context or {}, "timeout": timeout},
        ))

        got = self._hitl_event.wait(timeout=timeout)
        if not got:
            payload = {"action": "approve", "feedback": "[auto-approve: timeout]", "timed_out": True}
            self.emit(Event(type=EventType.HITL_RESPONSE, node=node, data=payload))
            return payload

        return self._hitl_result or {"action": "approve", "feedback": ""}

    def submit_human_feedback(self, action: str, feedback: str = "") -> None:
        """Called by frontend: submit human feedback, unblocking wait_for_human."""
        self._hitl_result = {"action": action, "feedback": feedback}
        self.emit(Event(
            type=EventType.HITL_RESPONSE,
            node="",
            data={"action": action, "feedback": feedback},
        ))
        if self._hitl_event is not None:
            self._hitl_event.set()

    # ── Query ──

    def get_history(self, since: int = 0) -> list[Event]:
        """Get all events after the given index"""
        with self._lock:
            return list(self._history[since:])

    @property
    def history_len(self) -> int:
        return len(self._history)

    def clear(self) -> None:
        with self._lock:
            self._history.clear()
            self._subscribers.clear()
            self._chunk_buffers.clear()
            self._hitl_event = None
            self._hitl_result = None
            self._seq = 0
            self._event_log_file = None


class NoOpBus(EventBus):
    """No-op event bus, used in non-Web mode; all methods are no-ops."""

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        pass

    def emit(self, event: Event) -> None:
        pass

    def wait_for_human(self, node: str, prompt: str, context: dict | None = None, timeout: float = 10) -> dict:
        return {"action": "approve", "feedback": ""}

    def submit_human_feedback(self, action: str, feedback: str = "") -> None:
        pass

    def get_history(self, since: int = 0) -> list[Event]:
        return []

    def clear(self) -> None:
        pass

    def configure_run(self, run_id: str, log_dir: str | None = None) -> None:
        pass


# ── Global singleton ──

_bus: EventBus = NoOpBus()


def get_event_bus() -> EventBus:
    return _bus


def activate_event_bus() -> EventBus:
    """Activate the real event bus (called once in Web mode)"""
    global _bus
    _bus = EventBus()
    return _bus
