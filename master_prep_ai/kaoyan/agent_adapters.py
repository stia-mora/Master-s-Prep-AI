"""Stable adapter functions for Kaoyan agent capabilities."""

from __future__ import annotations

from typing import Any

from master_prep_ai.agents.kaoyan import MathEvalAgent, MemoryManager, SocraticAgent
from master_prep_ai.agents.kaoyan.models import AgentEvalResult


async def socratic_next_turn(
    context: dict[str, Any] | str | None,
    student_message: str,
    state: str | None = None,
    language: str = "zh",
    use_llm: bool | None = None,
) -> dict[str, Any]:
    result = await SocraticAgent(language=language).process(
        context=context,
        student_message=student_message,
        state=state,
        use_llm=use_llm,
    )
    return result.to_dict()


async def math_eval(
    question: dict[str, Any] | str,
    reference_answer: str | None = None,
    student_steps: list[str] | str | None = None,
    student_answer: str | None = None,
    language: str = "zh",
    use_llm: bool | None = None,
) -> AgentEvalResult:
    return await MathEvalAgent(language=language).process(
        question=question,
        reference_answer=reference_answer,
        student_steps=student_steps,
        student_answer=student_answer,
        use_llm=use_llm,
    )


async def memory_update(
    user_id: str,
    event_type: str,
    payload: dict[str, Any] | None,
    language: str = "zh",
    use_llm: bool | None = None,
) -> dict[str, Any]:
    result = await MemoryManager(language=language).process(
        user_id=user_id,
        event_type=event_type,
        payload=payload or {},
        use_llm=use_llm,
    )
    return result.to_dict()


def route_model(
    task_type: str,
    difficulty: int | str | None = None,
    latency_budget: str | None = None,
    cost_budget: str | None = None,
) -> dict[str, Any]:
    try:
        from master_prep_ai.services.llm.routing_service import route_model as _route_model

        return _route_model(
            task_type=task_type,
            difficulty=difficulty,
            latency_budget=latency_budget,
            cost_budget=cost_budget,
        )
    except Exception as exc:
        return {
            "provider": "mock",
            "model": "mock",
            "binding": "mock",
            "fallback": True,
            "reason": f"model routing unavailable: {exc}",
        }


__all__ = [
    "math_eval",
    "memory_update",
    "route_model",
    "socratic_next_turn",
]
