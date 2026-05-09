from __future__ import annotations

import asyncio

from master_prep_ai.kaoyan import ai_service
from master_prep_ai.kaoyan.agent_adapters import (
    math_eval,
    memory_update,
    route_model,
    socratic_next_turn,
)


def test_agent_adapters_are_reexported_from_ai_service() -> None:
    assert ai_service.socratic_next_turn is socratic_next_turn
    assert ai_service.math_eval is math_eval
    assert ai_service.memory_update is memory_update
    assert ai_service.route_model is route_model


def test_socratic_adapter_returns_plain_dict() -> None:
    result = asyncio.run(
        socratic_next_turn(
            context={"question": "Solve x^2=4"},
            student_message="I think it factors.",
            state="ASSESS",
            language="en",
        )
    )

    assert set(result) == {"state", "question", "hints"}
    assert result["state"] == "GUIDE"


def test_math_eval_adapter_returns_agent_eval_result() -> None:
    result = asyncio.run(
        math_eval(
            question="Compute 2+2",
            reference_answer="4",
            student_answer="4",
            language="en",
        )
    )

    assert result.is_correct is True
    assert result.to_dict()["grading_method"] == "heuristic"


def test_memory_update_adapter_returns_plain_dict() -> None:
    result = asyncio.run(
        memory_update(
            user_id="u1",
            event_type="review_submit",
            payload={"review_id": "rev1", "knowledge_id": "k1", "status": "mastered"},
            language="en",
        )
    )

    assert set(result) == {"profile_patch", "mastery_delta", "audit_log"}
    assert result["mastery_delta"][0]["knowledge_id"] == "k1"
