"""
Unified LLM API client
Wraps OpenAI / Anthropic / DeepSeek, providing a consistent chat() interface

Enhanced features (inspired by AutoResearchClaw):
  - Model fallback chain (primary model → fallback models auto-switch)
  - Exponential backoff + Jitter retry
  - Adaptive parameters (max_completion_tokens / temperature compatibility)
  - Smart classification of retryable vs non-retryable errors
"""

from __future__ import annotations

import json
import os
import random
import time
import logging
import asyncio
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from utils.event_bus import get_event_bus

# ------------------------------------------------------------------
# Model compatibility constants (ref: ARC)
# ------------------------------------------------------------------
# Models that must use max_completion_tokens instead of max_tokens
_NEW_PARAM_MODELS = frozenset({
    "o3", "o3-mini", "o4-mini",
    "gpt-5", "gpt-5.1", "gpt-5.2", "gpt-5.4",
})

# Models that do not support the temperature parameter (reasoning models)
_NO_TEMPERATURE_MODELS = frozenset({
    "o3", "o3-mini", "o4-mini",
})

# ------------------------------------------------------------------
# Global LLM call log directory (set by main.py at the start of each run())
# ------------------------------------------------------------------
_LLM_LOG_DIR: Optional[Path] = None


def set_llm_log_dir(path: str) -> None:
    """Set the log directory for raw LLM responses; set to None or empty string to disable logging."""
    global _LLM_LOG_DIR  # noqa: PLW0603
    _LLM_LOG_DIR = Path(path) if path else None

logger = logging.getLogger(__name__)


def _clip_preview(text: str, limit: int = 240) -> str:
    if not isinstance(text, str):
        text = str(text)
    text = text.replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _format_prompt_text(messages: list[dict], limit: int = 16000) -> str:
    """Render a readable prompt transcript for UI/event inspection."""
    sections: list[str] = []
    for msg in messages:
        role = str(msg.get("role", "?")).upper()
        content = msg.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, indent=2)
        sections.append(f"[{role}]\n{content.strip()}")
    prompt_text = "\n\n".join(section for section in sections if section.strip())
    if len(prompt_text) <= limit:
        return prompt_text
    return prompt_text[: limit - 15] + "\n... (truncated)"


def _estimate_tokens(text: str) -> int:
    compact = (text or "").strip()
    if not compact:
        return 0
    return max(1, len(compact) // 4)


def _load_project_env() -> None:
    """Auto-load .env from the project root directory to avoid missing load_dotenv in entry scripts."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


def _is_effective_env_value(value: Optional[str]) -> bool:
    """Check if an environment variable has an effective value (filters out example placeholders)."""
    if not value:
        return False
    stripped = value.strip()
    if not stripped:
        return False
    placeholders = {
        "sk-...",
        "sk-ant-...",
        "your_api_key_here",
        "your-key-here",
    }
    if stripped in placeholders:
        return False
    if "..." in stripped:
        return False
    return True


class LLMClient:
    """
    Multi-backend LLM client

    Automatically selects backend based on available API keys in environment variables:
    OPENAI_API_KEY  → openai (gpt-4o)
    ANTHROPIC_API_KEY → anthropic (claude-3-5-sonnet)
    DEEPSEEK_API_KEY  → deepseek (deepseek-chat)
    POE_API_KEY → poe (bot name configurable via POE_BOT, default GPT-4o)
    No key      → local MockLLM (for offline testing)
    """

    SUPPORTED_BACKENDS = ("openai", "anthropic", "deepseek", "poe", "mock")

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.2,
        backend: Optional[str] = None,
        fallback_models: Optional[list[str]] = None,
        default_max_tokens: Optional[int] = None,
        node_max_tokens: Optional[dict[str, int]] = None,
        request_timeout_sec: float = 180.0,
        silence_timeout_sec: float = 45.0,
        retry_attempts: int = 3,
        retry_delay_sec: float = 2.0,
    ):
        _load_project_env()
        self.temperature = temperature
        self.backend = backend or self._detect_backend()
        self.model = model or self._default_model()
        self._fallback_models: list[str] = fallback_models or []
        self.default_max_tokens = int(default_max_tokens) if default_max_tokens else None
        raw_node_max_tokens = node_max_tokens or {}
        self._node_max_tokens = {
            str(key): int(value)
            for key, value in raw_node_max_tokens.items()
            if value is not None
        }
        self.request_timeout_sec = max(float(request_timeout_sec), 0.0)
        self.silence_timeout_sec = max(float(silence_timeout_sec), 0.0)
        self.retry_attempts = max(int(retry_attempts), 1)
        self.retry_delay_sec = max(float(retry_delay_sec), 0.0)
        self._client = self._init_client()
        logger.debug("LLMClient initialized: backend=%s model=%s fallbacks=%s",
                 self.backend, self.model, self._fallback_models or "none")

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------

    def _detect_backend(self) -> str:
        forced_backend = os.getenv("LLM_BACKEND", "").strip().lower()
        if forced_backend:
            if forced_backend not in self.SUPPORTED_BACKENDS:
                logger.warning("Invalid LLM_BACKEND=%s; fallback to auto detect", forced_backend)
            else:
                if forced_backend == "openai" and _is_effective_env_value(os.getenv("OPENAI_API_KEY")):
                    return "openai"
                if forced_backend == "anthropic" and _is_effective_env_value(os.getenv("ANTHROPIC_API_KEY")):
                    return "anthropic"
                if forced_backend == "deepseek" and _is_effective_env_value(os.getenv("DEEPSEEK_API_KEY")):
                    return "deepseek"
                if forced_backend == "poe" and _is_effective_env_value(os.getenv("POE_API_KEY")):
                    return "poe"
                if forced_backend == "mock":
                    return "mock"
                logger.warning("LLM_BACKEND=%s is set but required key is missing/placeholder", forced_backend)

        if _is_effective_env_value(os.getenv("OPENAI_API_KEY")):
            return "openai"
        if _is_effective_env_value(os.getenv("ANTHROPIC_API_KEY")):
            return "anthropic"
        if _is_effective_env_value(os.getenv("DEEPSEEK_API_KEY")):
            return "deepseek"
        if _is_effective_env_value(os.getenv("POE_API_KEY")):
            return "poe"
        logger.warning("No LLM API key found; using mock backend")
        return "mock"

    def _default_model(self) -> str:
        return {
            "openai": "gpt-4o",
            "anthropic": "claude-3-5-sonnet-20241022",
            "deepseek": "deepseek-chat",
            "poe": os.getenv("POE_BOT", "GPT-4o"),
            "mock": "mock",
        }[self.backend]

    @classmethod
    def from_config(cls, config: dict, **overrides) -> "LLMClient":
        """Create client from the llm section of config.yaml, auto-reading fallback_models.

        Usage:
            client = LLMClient.from_config(state["config"])
            client = LLMClient.from_config(state["config"], temperature=0.7)
        """
        llm_cfg = (config or {}).get("llm", {}) or {}
        kwargs: dict = {
            "model": llm_cfg.get("primary_model"),
            "temperature": llm_cfg.get("temperature", 0.2),
            "fallback_models": llm_cfg.get("fallback_models", []),
            "default_max_tokens": llm_cfg.get("max_tokens"),
            "node_max_tokens": llm_cfg.get("node_max_tokens", {}),
            "request_timeout_sec": llm_cfg.get("request_timeout_sec", 180),
            "silence_timeout_sec": llm_cfg.get("silence_timeout_sec", 45),
            "retry_attempts": llm_cfg.get("retry_attempts", 3),
            "retry_delay_sec": llm_cfg.get("retry_delay_sec", 2.0),
        }
        kwargs.update(overrides)
        return cls(**kwargs)

    def get_max_tokens(self, node_name: str = "llm", fallback: Optional[int] = None) -> Optional[int]:
        if node_name in self._node_max_tokens:
            return self._node_max_tokens[node_name]
        return fallback if fallback is not None else self.default_max_tokens

    def _init_client(self):
        if self.backend == "openai":
            try:
                from openai import OpenAI
                return OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=self.request_timeout_sec or None)
            except ImportError as exc:
                raise ImportError("pip install openai>=1.0") from exc

        if self.backend == "anthropic":
            try:
                import anthropic
                return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=self.request_timeout_sec or None)
            except ImportError as exc:
                raise ImportError("pip install anthropic>=0.30") from exc

        if self.backend == "deepseek":
            try:
                from openai import OpenAI
                return OpenAI(
                    api_key=os.environ["DEEPSEEK_API_KEY"],
                    base_url="https://api.deepseek.com",
                    timeout=self.request_timeout_sec or None,
                )
            except ImportError as exc:
                raise ImportError("pip install openai>=1.0  # used for DeepSeek") from exc

        if self.backend == "poe":
            try:
                import fastapi_poe  # noqa: F401 – verify installed
            except ImportError as exc:
                raise ImportError("pip install fastapi-poe") from exc
            return os.environ["POE_API_KEY"]  # directly store key string

        # mock
        return None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        max_tokens: Optional[int] = None,
        retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
        node_name: str = "llm",
    ) -> str:
        """
        Send chat messages and return the model's reply text.

        Enhanced logic: after the primary model fails, automatically tries
        fallback_models; each model internally does exponential backoff + Jitter retry.

        Args:
            messages: Message list in OpenAI format [{"role": ..., "content": ...}]
            max_tokens: Maximum output token count; None uses the backend's default
            retries: Number of retries per model on failure
            retry_delay: Base wait seconds for retry (exponential backoff)

        Returns:
            str: Model reply text
        """
        # Build model try chain: primary model + fallbacks
        model_chain = [self.model] + [m for m in self._fallback_models if m != self.model]
        last_error: Optional[Exception] = None
        resolved_max_tokens = self.get_max_tokens(node_name, max_tokens)
        resolved_retries = self.retry_attempts if retries is None else max(int(retries), 1)
        resolved_retry_delay = self.retry_delay_sec if retry_delay is None else max(float(retry_delay), 0.0)

        for model_name in model_chain:
            try:
                result = self._call_with_retry(
                    messages,
                    resolved_max_tokens,
                    resolved_retries,
                    resolved_retry_delay,
                    model_name,
                    node_name,
                )
                return result
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Model %s failed: %s. Trying next fallback.", model_name, exc)
                last_error = exc

        raise RuntimeError(f"All models failed. Last error: {last_error}") from last_error

    def _call_with_retry(
        self,
        messages: list[dict],
        max_tokens: Optional[int],
        retries: int,
        retry_delay: float,
        model_override: Optional[str] = None,
        node_name: str = "llm",
    ) -> str:
        """Exponential backoff + Jitter retry for a single model."""
        for attempt in range(retries):
            try:
                return self._call(messages, max_tokens, model_override, node_name)
            except Exception as exc:  # pylint: disable=broad-except
                # Check if retryable
                if self._is_non_retryable(exc):
                    raise
                logger.warning(
                    "LLM call failed (attempt %d/%d, model=%s): %s",
                    attempt + 1, retries, model_override or self.model, exc,
                )
                if attempt < retries - 1:
                    delay = retry_delay * (2 ** attempt)
                    delay += random.uniform(0, delay * 0.3)  # Jitter
                    time.sleep(delay)
                else:
                    raise
        return ""  # unreachable

    @staticmethod
    def _is_non_retryable(exc: Exception) -> bool:
        """Determine if the error should not be retried (e.g. 401 auth failure, 403 model unavailable)."""
        exc_str = str(exc).lower()
        # HTTP status code classification
        for keyword in ("401", "invalid api key", "authentication", "403", "not allowed"):
            if keyword in exc_str:
                return True
        # 400 Bad Request without rate limit hint should not be retried
        if "400" in exc_str:
            retryable_hints = ("rate limit", "overloaded", "temporarily", "capacity", "throttl", "retry")
            if not any(hint in exc_str for hint in retryable_hints):
                return True
        return False

    @staticmethod
    def _is_timeout_exception(exc: Exception) -> bool:
        exc_str = str(exc).lower()
        return isinstance(exc, TimeoutError) or any(
            token in exc_str
            for token in ("timeout", "timed out", "read timed out", "stall", "deadline exceeded")
        )

    def _call(
        self,
        messages: list[dict],
        max_tokens: Optional[int],
        model_override: Optional[str] = None,
        node_name: str = "llm",
    ) -> str:
        return self._call_with_node(messages, max_tokens, model_override, node_name)

    def _call_with_node(
        self,
        messages: list[dict],
        max_tokens: Optional[int],
        model_override: Optional[str] = None,
        node_name: str = "llm",
    ) -> str:
        active_model = model_override or self.model
        bus = get_event_bus()
        last_user = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        prompt_text = _format_prompt_text(messages)
        # Estimate from raw message bytes (not clipped prompt_text) to avoid the 16000-char display cap
        raw_chars = sum(
            len(m.get("content") if isinstance(m.get("content"), str) else json.dumps(m.get("content", "")))
            for m in messages
        )
        prompt_tokens_est = max(1, raw_chars // 4)
        bus.emit_llm_start(
            node_name,
            active_model,
            _clip_preview(last_user),
            prompt_text,
            usage={"prompt_tokens_est": prompt_tokens_est},
        )

        if self.backend == "mock":
            result = self._mock_response(messages)
            self._emit_response_chunks(result, node_name=node_name)
            self._log_exchange(messages, result)
            completion_tokens_est = _estimate_tokens(result)
            bus.emit_llm_end(
                node_name,
                active_model,
                _clip_preview(result),
                usage={
                    "completion_tokens_est": completion_tokens_est,
                    "total_tokens_est": prompt_tokens_est + completion_tokens_est,
                },
            )
            return result

        # Adaptive parameter handling
        supports_temp = not any(active_model.startswith(p) for p in _NO_TEMPERATURE_MODELS)
        use_new_param = any(active_model.startswith(p) for p in _NEW_PARAM_MODELS)

        kwargs: dict = {"model": active_model, "messages": messages}
        if supports_temp:
            kwargs["temperature"] = self.temperature
        if max_tokens:
            if use_new_param:
                kwargs["max_completion_tokens"] = max(max_tokens, 32768)  # reasoning models minimum 32k
            else:
                kwargs["max_tokens"] = max_tokens

        if self.backend in ("openai", "deepseek"):
            result, api_usage = self._openai_like_call(kwargs, node_name=node_name)
            self._log_exchange(messages, result)
            usage = self._build_usage(prompt_tokens_est, result, api_usage)
            bus.emit_llm_end(node_name, active_model, _clip_preview(result), usage=usage)
            return result

        if self.backend == "anthropic":
            # Anthropic API: system message must be passed separately
            system_msg = ""
            filtered: list[dict] = []
            for m in messages:
                if m["role"] == "system":
                    system_msg = m["content"]
                else:
                    filtered.append(m)
            ant_kwargs = {**kwargs, "messages": filtered}
            if system_msg:
                ant_kwargs["system"] = system_msg
            ant_kwargs.pop("model")
            result, api_usage = self._anthropic_call(ant_kwargs, active_model, node_name=node_name)
            self._log_exchange(messages, result)
            usage = self._build_usage(prompt_tokens_est, result, api_usage)
            bus.emit_llm_end(node_name, active_model, _clip_preview(result), usage=usage)
            return result

        if self.backend == "poe":
            try:
                loop = asyncio.get_running_loop()
                # Already inside an event loop (e.g. Jupyter)
                import nest_asyncio  # type: ignore
                nest_asyncio.apply()
                result = loop.run_until_complete(self._poe_async_call(messages, node_name=node_name))
            except RuntimeError:
                result = asyncio.run(self._poe_async_call(messages, node_name=node_name))
            self._log_exchange(messages, result)
            usage = self._build_usage(prompt_tokens_est, result, {})
            bus.emit_llm_end(node_name, active_model, _clip_preview(result), usage=usage)
            return result

        raise ValueError(f"Unknown backend: {self.backend}")

    def _emit_response_chunks(self, text: str, chunk_size: int = 150, node_name: str = "llm") -> None:
        bus = get_event_bus()
        if not text:
            return
        for idx in range(0, len(text), chunk_size):
            bus.emit_llm_chunk(node_name, text[idx: idx + chunk_size])

    @staticmethod
    def _build_usage(prompt_tokens_est: int, result: str, api_usage: dict) -> dict:
        """Merge real API usage with estimates. Prefer real counts when available."""
        completion_tokens_est = _estimate_tokens(result)
        prompt_tokens = api_usage.get("prompt_tokens") or prompt_tokens_est
        completion_tokens = api_usage.get("completion_tokens") or completion_tokens_est
        total_tokens = api_usage.get("total_tokens") or (prompt_tokens + completion_tokens)
        is_real = bool(api_usage.get("prompt_tokens") or api_usage.get("completion_tokens"))
        usage: dict = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
        if not is_real:
            # Mark as estimates for display
            usage["prompt_tokens_est"] = prompt_tokens
            usage["completion_tokens_est"] = completion_tokens
            usage["total_tokens_est"] = total_tokens
        return usage

    def _openai_like_call(self, kwargs: dict, node_name: str = "llm") -> tuple[str, dict]:
        """Returns (text, usage_dict). usage_dict may contain prompt_tokens, completion_tokens, total_tokens."""
        request_kwargs = dict(kwargs)
        if self.request_timeout_sec > 0:
            request_kwargs["timeout"] = self.request_timeout_sec
        try:
            stream = self._client.chat.completions.create(**request_kwargs, stream=True, stream_options={"include_usage": True})
            chunks: list[str] = []
            buf: list[str] = []
            buf_len = 0
            bus = get_event_bus()
            last_chunk_at = time.monotonic()
            usage: dict = {}
            for event in stream:
                # Capture usage from the final stream chunk (OpenAI sends it with choices=[])
                if hasattr(event, "usage") and event.usage is not None:
                    u = event.usage
                    usage = {
                        "prompt_tokens": getattr(u, "prompt_tokens", None),
                        "completion_tokens": getattr(u, "completion_tokens", None),
                        "total_tokens": getattr(u, "total_tokens", None),
                    }
                delta = ""
                try:
                    delta = event.choices[0].delta.content or ""
                except Exception:
                    delta = ""
                if delta:
                    last_chunk_at = time.monotonic()
                    chunks.append(delta)
                    buf.append(delta)
                    buf_len += len(delta)
                    # Emit every 150 chars accumulated or on newline (reduces ~98% event dispatch overhead)
                    if buf_len >= 150 or delta.endswith(("\n", ".", "，", "。")):
                        bus.emit_llm_chunk(node_name, "".join(buf))
                        buf.clear()
                        buf_len = 0
                elif self.silence_timeout_sec > 0 and (time.monotonic() - last_chunk_at) > self.silence_timeout_sec:
                    raise TimeoutError(
                        f"LLM stream stalled for {self.silence_timeout_sec:.0f}s during {node_name}"
                    )
            if buf:  # flush remaining
                bus.emit_llm_chunk(node_name, "".join(buf))
            result = "".join(chunks)
            if result:
                return result, usage
        except Exception as exc:
            if self._is_timeout_exception(exc):
                raise TimeoutError(f"LLM request timed out during {node_name}: {exc}") from exc
            logger.debug("OpenAI-like streaming unavailable, fallback to non-stream call: %s", exc)

        response = self._client.chat.completions.create(**request_kwargs)
        result = response.choices[0].message.content or ""
        usage = {}
        if hasattr(response, "usage") and response.usage is not None:
            u = response.usage
            usage = {
                "prompt_tokens": getattr(u, "prompt_tokens", None),
                "completion_tokens": getattr(u, "completion_tokens", None),
                "total_tokens": getattr(u, "total_tokens", None),
            }
        self._emit_response_chunks(result, node_name=node_name)
        return result, usage

    def _anthropic_call(self, kwargs: dict, model: Optional[str] = None, node_name: str = "llm") -> tuple[str, dict]:
        """Returns (text, usage_dict)."""
        active_model = model or self.model
        usage: dict = {}
        try:
            with self._client.messages.stream(model=active_model, **kwargs) as stream:
                chunks: list[str] = []
                buf: list[str] = []
                buf_len = 0
                bus = get_event_bus()
                last_chunk_at = time.monotonic()
                for text in stream.text_stream:
                    if text:
                        last_chunk_at = time.monotonic()
                        chunks.append(text)
                        buf.append(text)
                        buf_len += len(text)
                        if buf_len >= 150 or text.endswith(("\n", ".", "，", "。")):
                            bus.emit_llm_chunk(node_name, "".join(buf))
                            buf.clear()
                            buf_len = 0
                    elif self.silence_timeout_sec > 0 and (time.monotonic() - last_chunk_at) > self.silence_timeout_sec:
                        raise TimeoutError(
                            f"LLM stream stalled for {self.silence_timeout_sec:.0f}s during {node_name}"
                        )
                if buf:
                    bus.emit_llm_chunk(node_name, "".join(buf))
                result = "".join(chunks)
                # Extract usage from the finalized stream message
                try:
                    final_msg = stream.get_final_message()
                    if final_msg and hasattr(final_msg, "usage") and final_msg.usage:
                        u = final_msg.usage
                        usage = {
                            "prompt_tokens": getattr(u, "input_tokens", None),
                            "completion_tokens": getattr(u, "output_tokens", None),
                        }
                        pt = usage.get("prompt_tokens") or 0
                        ct = usage.get("completion_tokens") or 0
                        if pt or ct:
                            usage["total_tokens"] = pt + ct
                except Exception:
                    pass
                if result:
                    return result, usage
        except Exception as exc:
            if self._is_timeout_exception(exc):
                raise TimeoutError(f"LLM request timed out during {node_name}: {exc}") from exc
            logger.debug("Anthropic streaming unavailable, fallback to non-stream call: %s", exc)

        response = self._client.messages.create(model=active_model, **kwargs)
        result = response.content[0].text
        if hasattr(response, "usage") and response.usage:
            u = response.usage
            usage = {
                "prompt_tokens": getattr(u, "input_tokens", None),
                "completion_tokens": getattr(u, "output_tokens", None),
            }
            pt = usage.get("prompt_tokens") or 0
            ct = usage.get("completion_tokens") or 0
            if pt or ct:
                usage["total_tokens"] = pt + ct
        self._emit_response_chunks(result, node_name=node_name)
        return result, usage

    # ------------------------------------------------------------------
    # LLM call logging
    # ------------------------------------------------------------------

    def _log_exchange(self, messages: list[dict], response: str) -> None:
        """Write a single LLM call to both JSONL (full data) and Markdown (readable summary) logs."""
        if _LLM_LOG_DIR is None:
            return
        try:
            _LLM_LOG_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")

            # ── 1. Raw JSONL (preserves full data for programmatic parsing) ──
            entry = {
                "ts": ts,
                "backend": self.backend,
                "model": self.model,
                "messages": messages,
                "response": response,
            }
            log_file = _LLM_LOG_DIR / "llm_calls.jsonl"
            with log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            # ── 2. Readable Markdown summary (for quick manual inspection) ──
            md_file = _LLM_LOG_DIR / "llm_calls.md"
            with md_file.open("a", encoding="utf-8") as f:
                f.write(f"\n---\n## [{ts}] {self.backend} / {self.model}\n\n")
                for i, msg in enumerate(messages):
                    role = msg.get("role", "?")
                    content = msg.get("content", "")
                    # system prompt truncated, user/assistant keep more
                    limit = 400 if role == "system" else 1200
                    snippet = content[:limit] + ("…(truncated)" if len(content) > limit else "")
                    f.write(f"### [{role}]\n\n```\n{snippet}\n```\n\n")
                f.write(f"### [response]\n\n```\n{response[:3000]}{'…(truncated)' if len(response) > 3000 else ''}\n```\n\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to write LLM log: %s", exc)

    # ------------------------------------------------------------------
    # Poe helper: async call to official Poe API
    # ------------------------------------------------------------------

    async def _poe_async_call(self, messages: list[dict], node_name: str = "llm") -> str:
        """
        Use fastapi_poe official SDK to call a Poe bot.
        Converts OpenAI-format messages to Poe ProtocolMessage list.
        """
        import fastapi_poe as fp

        poe_messages: list[fp.ProtocolMessage] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            # Poe roles: "user" / "bot" / "system"
            if role == "assistant":
                role = "bot"
            poe_messages.append(fp.ProtocolMessage(role=role, content=content))

        full = ""
        response_iter = fp.get_bot_response(
            messages=poe_messages,
            bot_name=self.model,
            api_key=self._client,  # self._client stores the POE_API_KEY string
        )
        iterator = response_iter.__aiter__()
        deadline = time.monotonic() + self.request_timeout_sec if self.request_timeout_sec > 0 else None
        while True:
            timeout = self.silence_timeout_sec if self.silence_timeout_sec > 0 else None
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"LLM request timed out during {node_name}")
                timeout = remaining if timeout is None else min(timeout, remaining)
            try:
                partial = await asyncio.wait_for(iterator.__anext__(), timeout=timeout)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError as exc:
                raise TimeoutError(f"LLM stream stalled for {timeout:.0f}s during {node_name}") from exc
            if hasattr(partial, "text"):
                full += partial.text
                if partial.text:
                    get_event_bus().emit_llm_chunk(node_name, partial.text)
        return full

    # ------------------------------------------------------------------
    # Mock backend (for offline testing)
    # ------------------------------------------------------------------

    def _mock_response(self, messages: list[dict]) -> str:
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        return (
            f"[MockLLM] Received message: {last_user[:80]}...\n"
            "This is a mock reply. Please configure a real API key to get actual results."
        )
