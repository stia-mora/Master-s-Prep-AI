from __future__ import annotations

import asyncio

from master_prep_ai.kaoyan.agent_adapters import memory_update


def test_memory_update_practice_event_generates_patch_and_mastery_delta() -> None:
    result = asyncio.run(
        memory_update(
            user_id="student-1",
            event_type="practice_submit",
            payload={
                "session_id": "s1",
                "accuracy": 0.5,
                "wrong_question_ids": ["q2"],
                "answers": [
                    {"question_id": "q1", "knowledge_id": "k1", "is_correct": True},
                    {"question_id": "q2", "knowledge_id": "k2", "is_correct": False, "error_reason": "sign error"},
                ],
            },
            language="en",
        )
    )

    assert result["profile_patch"]["last_practice_accuracy"] == 0.5
    assert result["profile_patch"]["recent_wrong_question_ids"] == ["q2"]
    assert len(result["mastery_delta"]) == 2
    assert result["audit_log"]["user_id"] == "student-1"
    assert result["audit_log"]["source_ids"]


def test_memory_update_diagnostic_event_uses_profile_draft() -> None:
    result = asyncio.run(
        memory_update(
            user_id="student-1",
            event_type="diagnostic_submit",
            payload={
                "report_id": "r1",
                "profile_draft": {
                    "baseline_level": "basic",
                    "weak_modules": ["limits"],
                    "recommended_daily_minutes": 180,
                },
            },
            language="en",
        )
    )

    assert result["profile_patch"]["baseline_level"] == "basic"
    assert result["profile_patch"]["weak_modules"] == ["limits"]
    assert result["audit_log"]["event_type"] == "diagnostic_submit"
