"""AI helpers for Kaoyan MVP flows with deterministic fallbacks."""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

from .learning_store import DEFAULT_USER_ID, KaoyanLearningStore

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _ai_timeout_seconds() -> float:
    try:
        return max(3.0, float(os.getenv("KAOYAN_AI_TIMEOUT_SECONDS", "20")))
    except ValueError:
        return 20.0


def _extract_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_RE.search(text)
        if not match:
            raise
        return json.loads(match.group(0))


async def call_llm_complete(prompt: str, system_prompt: str, image_data: str | None = None) -> tuple[str, str]:
    """Import the optional LLM stack lazily so API startup can fall back cleanly."""
    from deeptutor.services.llm import complete, get_llm_config

    model = ""
    try:
        model = str(get_llm_config().model or "")
    except Exception:
        model = ""
    response = await complete(prompt, system_prompt=system_prompt, max_retries=0, image_data=image_data)
    return str(response or ""), model


class KaoyanAIService:
    def __init__(self, learning_store: KaoyanLearningStore) -> None:
        self.learning_store = learning_store

    async def complete_json(
        self,
        *,
        action_type: str,
        system_prompt: str,
        prompt: str,
        user_id: str = DEFAULT_USER_ID,
        image_data: str | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        try:
            response, model = await asyncio.wait_for(
                call_llm_complete(prompt, system_prompt, image_data=image_data),
                timeout=_ai_timeout_seconds(),
            )
            parsed = _extract_json(response)
            self.learning_store.log_ai_action(
                action_type=action_type,
                prompt=prompt,
                model=model,
                status="success",
                response_text=response,
                payload={"parsed": parsed},
                user_id=user_id,
            )
            return parsed, {"ai_used": True, "status": "success", "message": "AI 已生成增强结果"}
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            self._log_failure(action_type, prompt, f"AI timeout/cancelled: {exc}", user_id)
            return None, {"ai_used": False, "status": "fallback", "message": "AI 增强失败，已使用基础策略"}
        except Exception as exc:
            self._log_failure(action_type, prompt, str(exc), user_id)
            return None, {"ai_used": False, "status": "fallback", "message": "AI 增强失败，已使用基础策略"}

    async def complete_text(
        self,
        *,
        action_type: str,
        system_prompt: str,
        prompt: str,
        fallback: str,
        user_id: str = DEFAULT_USER_ID,
        image_data: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        try:
            response, model = await asyncio.wait_for(
                call_llm_complete(prompt, system_prompt, image_data=image_data),
                timeout=_ai_timeout_seconds(),
            )
            response = response.strip()
            self.learning_store.log_ai_action(
                action_type=action_type,
                prompt=prompt,
                model=model,
                status="success",
                response_text=response,
                user_id=user_id,
            )
            return response or fallback, {"ai_used": True, "status": "success", "message": "AI 已生成增强结果"}
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            self._log_failure(action_type, prompt, f"AI timeout/cancelled: {exc}", user_id)
            return fallback, {"ai_used": False, "status": "fallback", "message": "AI 增强失败，已使用基础策略"}
        except Exception as exc:
            self._log_failure(action_type, prompt, str(exc), user_id)
            return fallback, {"ai_used": False, "status": "fallback", "message": "AI 增强失败，已使用基础策略"}

    def _log_failure(self, action_type: str, prompt: str, error: str, user_id: str) -> None:
        self.learning_store.log_ai_action(
            action_type=action_type,
            prompt=prompt,
            status="failed",
            error_message=error,
            user_id=user_id,
        )