"""Kaoyan memory patch generator with auditable deterministic output."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from ._json import extract_json_object
from .models import MemoryUpdateResult


class MemoryManager:
    """Generate memory patches without mutating A/C business stores."""

    def __init__(self, language: str = "zh") -> None:
        self.language = language

    async def process(
        self,
        *,
        user_id: str,
        event_type: str,
        payload: dict[str, Any] | None,
        use_llm: bool | None = None,
    ) -> MemoryUpdateResult:
        payload = payload or {}
        fallback = self._fallback_update(user_id=user_id, event_type=event_type, payload=payload)
        if use_llm:
            llm_result = await self._try_llm_update(
                user_id=user_id,
                event_type=event_type,
                payload=payload,
            )
            if llm_result is not None:
                return llm_result
        return fallback

    def _fallback_update(
        self,
        *,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> MemoryUpdateResult:
        event = str(event_type or "unknown").strip() or "unknown"
        profile_patch: dict[str, Any] = {}
        mastery_delta = self._mastery_delta(event, payload)

        if event.startswith("diagnostic"):
            draft = payload.get("profile_draft") if isinstance(payload.get("profile_draft"), dict) else {}
            if draft:
                for key in [
                    "baseline_level",
                    "weak_modules",
                    "module_scores",
                    "recommended_daily_minutes",
                    "plan_focus",
                ]:
                    if key in draft:
                        profile_patch[key] = draft[key]
            weak_ids = payload.get("weak_knowledge_ids")
            if isinstance(weak_ids, list):
                profile_patch["weak_knowledge_ids"] = [str(item) for item in weak_ids if str(item)]
        elif event.startswith("practice"):
            accuracy = _coerce_float(payload.get("accuracy"))
            if accuracy is not None:
                profile_patch["last_practice_accuracy"] = accuracy
            wrong_ids = payload.get("wrong_question_ids")
            if isinstance(wrong_ids, list):
                profile_patch["recent_wrong_question_ids"] = [str(item) for item in wrong_ids if str(item)]
        elif event.startswith("review"):
            status = str(payload.get("status") or payload.get("review_status") or "").strip()
            if status:
                profile_patch["last_review_status"] = status

        audit_log = {
            "user_id": str(user_id),
            "event_type": event,
            "source_ids": _source_ids(payload),
            "summary": self._summary(event, profile_patch, mastery_delta),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "strategy": "deterministic",
        }
        return MemoryUpdateResult(
            profile_patch=profile_patch,
            mastery_delta=mastery_delta,
            audit_log=audit_log,
        )

    async def _try_llm_update(
        self,
        *,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> MemoryUpdateResult | None:
        try:
            from master_prep_ai.kaoyan.agent_adapters import route_model

            route = route_model("memory_update", latency_budget="low", cost_budget="low")
            if route.get("fallback"):
                return None
            from master_prep_ai.services.llm import complete

            system_prompt = (
                "You produce auditable memory updates for a learning app. "
                "Return JSON only with profile_patch, mastery_delta, audit_log. "
                "Do not include secrets or raw API keys."
            )
            prompt = json.dumps(
                {"user_id": user_id, "event_type": event_type, "payload": payload},
                ensure_ascii=False,
            )
            raw = await complete(
                prompt,
                system_prompt=system_prompt,
                model=str(route.get("model") or ""),
                binding=str(route.get("binding") or route.get("provider") or ""),
                max_retries=0,
                temperature=0.1,
            )
        except Exception:
            return None

        parsed = extract_json_object(raw)
        if not parsed:
            return None
        profile_patch = parsed.get("profile_patch")
        mastery_delta = parsed.get("mastery_delta")
        audit_log = parsed.get("audit_log")
        if not isinstance(profile_patch, dict) or not isinstance(mastery_delta, list):
            return None
        if not isinstance(audit_log, dict):
            audit_log = {}
        audit_log.setdefault("user_id", str(user_id))
        audit_log.setdefault("event_type", str(event_type or "unknown"))
        audit_log.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        audit_log.setdefault("strategy", "llm")
        return MemoryUpdateResult(
            profile_patch=profile_patch,
            mastery_delta=[item for item in mastery_delta if isinstance(item, dict)],
            audit_log=audit_log,
        )

    def _mastery_delta(self, event_type: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = payload.get("answers") or payload.get("mastery_updates") or []
        if isinstance(candidates, dict):
            candidates = [candidates]
        deltas: list[dict[str, Any]] = []
        if isinstance(candidates, list):
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                knowledge_id = str(item.get("knowledge_id") or "").strip()
                if not knowledge_id:
                    continue
                correct = bool(item.get("is_correct"))
                deltas.append(
                    {
                        "knowledge_id": knowledge_id,
                        "delta": 0.08 if correct else -0.12,
                        "reason": item.get("error_reason") or event_type,
                        "source_id": item.get("question_id") or item.get("source_id") or "",
                    }
                )
        knowledge_id = str(payload.get("knowledge_id") or "").strip()
        if knowledge_id and not deltas:
            status = str(payload.get("status") or "").lower()
            delta = 0.04 if status in {"reviewed", "mastered", "correct"} else -0.04
            deltas.append({"knowledge_id": knowledge_id, "delta": delta, "reason": event_type, "source_id": payload.get("source_id") or ""})
        return deltas

    def _summary(
        self,
        event_type: str,
        profile_patch: dict[str, Any],
        mastery_delta: list[dict[str, Any]],
    ) -> str:
        if self.language.lower().startswith("zh"):
            return f"{event_type} 事件生成 {len(profile_patch)} 个画像字段和 {len(mastery_delta)} 条掌握度变化。"
        return f"{event_type} generated {len(profile_patch)} profile fields and {len(mastery_delta)} mastery changes."


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_ids(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ["session_id", "record_id", "report_id", "question_id", "review_id", "source_id"]:
        value = str(payload.get(key) or "").strip()
        if value:
            values.append(value)
    for key in ["wrong_question_ids", "question_ids"]:
        raw = payload.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if str(item))
    return values[:20]


__all__ = ["MemoryManager"]
