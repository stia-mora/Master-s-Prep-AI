"""Deterministic Socratic tutoring turn generator for Kaoyan flows."""

from __future__ import annotations

import json
from typing import Any

from ._json import extract_json_object
from .models import SocraticState, SocraticTurnResult

_STATES: tuple[SocraticState, ...] = ("ASSESS", "GUIDE", "VERIFY", "CONSOLIDATE")
_NEXT_STATE: dict[SocraticState, SocraticState] = {
    "ASSESS": "GUIDE",
    "GUIDE": "VERIFY",
    "VERIFY": "CONSOLIDATE",
    "CONSOLIDATE": "CONSOLIDATE",
}

_ZH_QUESTIONS: dict[SocraticState, str] = {
    "ASSESS": "你现在能先说出题目在问什么，以及你已经想到的第一个相关知识点吗？",
    "GUIDE": "这个题里哪个条件最适合连接到定义、公式或图像直觉？",
    "VERIFY": "你能把刚才的关键一步代回题目条件，检查它是否真的成立吗？",
    "CONSOLIDATE": "请用一句话总结这题最关键的入口，下次看到类似题你会先做什么？",
}
_EN_QUESTIONS: dict[SocraticState, str] = {
    "ASSESS": "Can you first restate what the problem asks and name one related idea you recognize?",
    "GUIDE": "Which condition in the problem best connects to a definition, formula, or visual intuition?",
    "VERIFY": "Can you substitute your key step back into the problem conditions and check whether it holds?",
    "CONSOLIDATE": "In one sentence, what is the main entry point you would use next time?",
}
_ZH_HINTS: dict[SocraticState, list[str]] = {
    "ASSESS": ["先识别题型", "说出已知量和目标量"],
    "GUIDE": ["从定义或核心公式入手", "只推进一个小步骤"],
    "VERIFY": ["检查符号、条件和边界", "用反代或特例验证"],
    "CONSOLIDATE": ["提炼入口", "记录易错点"],
}
_EN_HINTS: dict[SocraticState, list[str]] = {
    "ASSESS": ["Identify the question type", "Name the knowns and the target"],
    "GUIDE": ["Start from a definition or core formula", "Advance one small step"],
    "VERIFY": ["Check signs, conditions, and boundaries", "Verify by substitution or a special case"],
    "CONSOLIDATE": ["Extract the entry point", "Record the trap"],
}


def normalize_state(state: str | None) -> SocraticState:
    value = str(state or "ASSESS").strip().upper()
    return value if value in _STATES else "ASSESS"  # type: ignore[return-value]


class SocraticAgent:
    """One-turn Socratic state machine.

    The fallback path intentionally asks a question instead of solving the
    problem outright, so tests and no-key deployments preserve the tutoring
    contract.
    """

    def __init__(self, language: str = "zh") -> None:
        self.language = language

    async def process(
        self,
        *,
        context: dict[str, Any] | str | None,
        student_message: str,
        state: str | None = None,
        use_llm: bool | None = None,
    ) -> SocraticTurnResult:
        current = normalize_state(state)
        next_state = current if not str(student_message or "").strip() else _NEXT_STATE[current]
        if use_llm:
            llm_result = await self._try_llm_turn(
                context=context,
                student_message=student_message,
                current_state=current,
                next_state=next_state,
            )
            if llm_result is not None:
                return llm_result
        return self._fallback_turn(next_state, student_message)

    def _fallback_turn(self, state: SocraticState, student_message: str) -> SocraticTurnResult:
        zh = self.language.lower().startswith("zh")
        questions = _ZH_QUESTIONS if zh else _EN_QUESTIONS
        hints = _ZH_HINTS if zh else _EN_HINTS
        if not str(student_message or "").strip():
            state = "ASSESS"
        return SocraticTurnResult(state=state, question=questions[state], hints=list(hints[state]))

    async def _try_llm_turn(
        self,
        *,
        context: dict[str, Any] | str | None,
        student_message: str,
        current_state: SocraticState,
        next_state: SocraticState,
    ) -> SocraticTurnResult | None:
        try:
            from master_prep_ai.kaoyan.agent_adapters import route_model

            route = route_model("socratic", latency_budget="medium", cost_budget="low")
            if route.get("fallback"):
                return None
            from master_prep_ai.services.llm import complete

            system_prompt = (
                "You are a Socratic math tutor. Return JSON only with state, question, hints. "
                "Ask exactly one question and do not reveal the final answer."
            )
            prompt = (
                f"Language: {self.language}\n"
                f"Current state: {current_state}\nNext state: {next_state}\n"
                f"Context: {json.dumps(context or {}, ensure_ascii=False)}\n"
                f"Student message: {student_message}\n"
            )
            raw = await complete(
                prompt,
                system_prompt=system_prompt,
                model=str(route.get("model") or ""),
                binding=str(route.get("binding") or route.get("provider") or ""),
                max_retries=0,
                temperature=0.2,
            )
        except Exception:
            return None

        parsed = extract_json_object(raw)
        if not parsed:
            return None
        state = normalize_state(str(parsed.get("state") or next_state))
        question = str(parsed.get("question") or "").strip()
        hints = parsed.get("hints")
        if not question:
            return None
        return SocraticTurnResult(
            state=state,
            question=question,
            hints=[str(item) for item in hints] if isinstance(hints, list) else [],
        )


__all__ = ["SocraticAgent", "normalize_state"]
