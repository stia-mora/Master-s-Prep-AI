from __future__ import annotations

import asyncio

from master_prep_ai.agents.kaoyan.math_eval_agent import MathEvalAgent


def test_math_eval_choice_answer_is_correct() -> None:
    result = asyncio.run(
        MathEvalAgent(language="en").process(
            question={"question_type": "choice"},
            reference_answer="B",
            student_answer="I choose B.",
        )
    )

    assert result.is_correct is True
    assert result.score == 1.0
    assert result.grading_method == "heuristic"


def test_math_eval_fraction_and_decimal_are_equivalent() -> None:
    result = asyncio.run(
        MathEvalAgent(language="en").process(
            question="Compute 1/2",
            reference_answer="1/2",
            student_answer="0.5",
        )
    )

    assert result.is_correct is True
    assert result.confidence >= 0.8


def test_math_eval_missing_answer_returns_fallback_result() -> None:
    result = asyncio.run(
        MathEvalAgent(language="en").process(
            question="Solve x^2 = 4",
            reference_answer="x=2 or x=-2",
            student_steps=[],
        )
    )

    assert result.is_correct is False
    assert result.error_step == "missing_answer"
    assert result.grading_method == "fallback"


def test_math_eval_wrong_step_has_error_step() -> None:
    result = asyncio.run(
        MathEvalAgent(language="en").process(
            question="Compute 1+1",
            reference_answer="2",
            student_steps=["1+1=3"],
            student_answer="3",
        )
    )

    assert result.is_correct is False
    assert result.error_step in {"step_1", "final_answer"}
    assert result.hint


def test_math_eval_uses_llm_json_when_available(monkeypatch) -> None:
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
        return '{"is_correct":false,"score":0.4,"error_step":"step_2","hint":"Check the sign.","confidence":0.8,"raw_reason":"sign error"}'

    monkeypatch.setattr("master_prep_ai.services.llm.complete", fake_complete)

    result = asyncio.run(
        MathEvalAgent(language="en").process(
            question="Compute a derivative",
            reference_answer="2x",
            student_steps=["x^2", "-2x"],
            student_answer="-2x",
            use_llm=True,
        )
    )

    assert result.grading_method == "llm"
    assert result.error_step == "step_2"
    assert result.score == 0.4
