from __future__ import annotations

import asyncio

from master_prep_ai.agents.kaoyan.socratic_agent import SocraticAgent


def test_socratic_agent_fallback_starts_with_assessment_question() -> None:
    result = asyncio.run(
        SocraticAgent(language="en").process(
            context={"question": "Solve x^2=4"},
            student_message="",
            state=None,
        )
    )

    assert result.state == "ASSESS"
    assert "?" in result.question
    assert result.hints
    assert "x = 2" not in result.question


def test_socratic_agent_state_progression_is_predictable() -> None:
    result = asyncio.run(
        SocraticAgent(language="en").process(
            context={"question": "Find the limit"},
            student_message="I know it is a limit problem.",
            state="ASSESS",
        )
    )

    assert result.state == "GUIDE"
    assert "?" in result.question


def test_socratic_agent_uses_llm_json_when_available(monkeypatch) -> None:
    monkeypatch.setattr(
        "master_prep_ai.kaoyan.agent_adapters.route_model",
        lambda *_args, **_kwargs: {
            "provider": "openai",
            "model": "gpt-test",
            "binding": "openai",
            "fallback": False,
            "reason": "test",
        },
    )

    async def fake_complete(*_args, **_kwargs):
        return '{"state":"VERIFY","question":"Can you check your derivative?","hints":["differentiate once"]}'

    monkeypatch.setattr("master_prep_ai.services.llm.complete", fake_complete)

    result = asyncio.run(
        SocraticAgent(language="en").process(
            context={"question": "Differentiate x^2"},
            student_message="I got 2x.",
            state="GUIDE",
            use_llm=True,
        )
    )

    assert result.state == "VERIFY"
    assert result.question == "Can you check your derivative?"
    assert result.hints == ["differentiate once"]
