"""Task-level model routing for Kaoyan agent adapters."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

_LOCAL_PROVIDERS = {"ollama", "vllm", "lm_studio", "llama_cpp", "ovms", "local"}


def route_model(
    task_type: str,
    difficulty: int | str | None = None,
    latency_budget: str | None = None,
    cost_budget: str | None = None,
) -> dict[str, Any]:
    """Return a key-free routing decision for a Kaoyan task.

    The return shape is intentionally small and contains no API key. If a
    non-local route has no usable credentials, ``fallback`` is true so callers
    can skip network calls and use deterministic behavior.
    """

    task = str(task_type or "default").strip() or "default"
    override = _route_from_env(task)
    if override is not None:
        return _finalize_route(
            override,
            source="KAOYAN_ROUTE_MODEL_JSON",
            difficulty=difficulty,
            latency_budget=latency_budget,
            cost_budget=cost_budget,
        )

    try:
        from master_prep_ai.services.llm.config import get_llm_config

        config = get_llm_config()
    except Exception as exc:
        return _mock_route(f"LLM config unavailable: {exc}")

    route = {
        "provider": getattr(config, "provider_name", None) or getattr(config, "binding", None) or "openai",
        "model": getattr(config, "model", "") or "",
        "binding": getattr(config, "binding", None) or getattr(config, "provider_name", None) or "openai",
        "_api_key_present": bool(getattr(config, "api_key", "") or _provider_env_key(getattr(config, "provider_name", "") or getattr(config, "binding", ""))),
        "_base_url": getattr(config, "effective_url", None) or getattr(config, "base_url", None) or "",
    }
    return _finalize_route(
        route,
        source="llm_config",
        difficulty=difficulty,
        latency_budget=latency_budget,
        cost_budget=cost_budget,
    )


def _route_from_env(task_type: str) -> dict[str, Any] | None:
    raw = os.getenv("KAOYAN_ROUTE_MODEL_JSON", "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"provider": "mock", "model": "mock", "binding": "mock", "fallback": True, "reason": "Invalid KAOYAN_ROUTE_MODEL_JSON"}
    if not isinstance(parsed, dict):
        return {"provider": "mock", "model": "mock", "binding": "mock", "fallback": True, "reason": "KAOYAN_ROUTE_MODEL_JSON must be an object"}
    selected = parsed.get(task_type) or parsed.get("default") or parsed
    return dict(selected) if isinstance(selected, dict) else None


def _finalize_route(
    route: dict[str, Any],
    *,
    source: str,
    difficulty: int | str | None,
    latency_budget: str | None,
    cost_budget: str | None,
) -> dict[str, Any]:
    provider = str(route.get("provider") or route.get("binding") or "openai").strip() or "openai"
    binding = str(route.get("binding") or provider).strip() or provider
    model = str(route.get("model") or os.getenv("LLM_MODEL") or "mock").strip() or "mock"
    base_url = str(route.get("_base_url") or route.get("base_url") or os.getenv("LLM_HOST") or "")
    local = provider.lower() in _LOCAL_PROVIDERS or binding.lower() in _LOCAL_PROVIDERS or _is_local_url(base_url)
    api_key_present = bool(route.get("_api_key_present")) or bool(route.get("api_key_present"))
    if not api_key_present:
        api_key_present = bool(_provider_env_key(provider) or _provider_env_key(binding) or os.getenv("LLM_API_KEY", "").strip())

    fallback = bool(route.get("fallback", False))
    reason = str(route.get("reason") or "configured route")
    if not model or model == "mock":
        fallback = True
        reason = "No model configured"
    elif not local and not api_key_present:
        fallback = True
        reason = f"No API key configured for non-local provider `{provider}`"
    elif not fallback:
        reason = f"Using {source}"

    return {
        "provider": provider,
        "model": model,
        "binding": binding,
        "fallback": fallback,
        "reason": reason,
    }


def _mock_route(reason: str) -> dict[str, Any]:
    return {
        "provider": "mock",
        "model": "mock",
        "binding": "mock",
        "fallback": True,
        "reason": reason,
    }


def _provider_env_key(provider: str | None) -> str:
    name = str(provider or "").strip().lower()
    env_map = {
        "openai": "OPENAI_API_KEY",
        "azure_openai": "AZURE_OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "dashscope": "DASHSCOPE_API_KEY",
        "moonshot": "MOONSHOT_API_KEY",
        "siliconflow": "SILICONFLOW_API_KEY",
        "zhipu": "ZAI_API_KEY",
    }
    key_name = env_map.get(name)
    return os.getenv(key_name, "").strip() if key_name else ""


def _is_local_url(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = urlparse(value if "://" in value else f"http://{value}")
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local")


__all__ = ["route_model"]
