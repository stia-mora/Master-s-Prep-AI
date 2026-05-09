"""Math answer evaluation with no-key deterministic fallbacks."""

from __future__ import annotations

from fractions import Fraction
import json
import re
from typing import Any
import unicodedata

from ._json import extract_json_object
from .models import AgentEvalResult

_CHOICE_RE = re.compile(r"(?:^|[^A-Za-z])([A-D])(?:[^A-Za-z]|$)", re.IGNORECASE)
_LATEX_FRAC_RE = re.compile(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}")


class MathEvalAgent:
    """Evaluate math answers while keeping tests independent of external LLMs."""

    def __init__(self, language: str = "zh") -> None:
        self.language = language

    async def process(
        self,
        *,
        question: dict[str, Any] | str,
        reference_answer: str | None = None,
        student_steps: list[str] | str | None = None,
        student_answer: str | None = None,
        use_llm: bool | None = None,
    ) -> AgentEvalResult:
        fallback = self._heuristic_eval(
            question=question,
            reference_answer=reference_answer,
            student_steps=student_steps,
            student_answer=student_answer,
        )
        if use_llm:
            llm_result = await self._try_llm_eval(
                question=question,
                reference_answer=reference_answer,
                student_steps=student_steps,
                student_answer=student_answer,
            )
            if llm_result is not None:
                return llm_result
        return fallback

    def _heuristic_eval(
        self,
        *,
        question: dict[str, Any] | str,
        reference_answer: str | None,
        student_steps: list[str] | str | None,
        student_answer: str | None,
    ) -> AgentEvalResult:
        ref = str(reference_answer if reference_answer is not None else _question_answer(question) or "")
        answer = str(student_answer or "").strip()
        steps_text = _steps_text(student_steps)
        candidate = answer or _last_nonempty_line(steps_text)

        if not candidate:
            return AgentEvalResult(
                is_correct=False,
                score=0.0,
                error_step="missing_answer",
                hint=_hint("先写出你的最终答案或关键推导步骤。", "Write a final answer or at least one key step.", self.language),
                confidence=0.9,
                raw_reason="No student answer or steps were provided.",
                grading_method="fallback",
            )

        if not ref:
            partial = bool(steps_text)
            return AgentEvalResult(
                is_correct=False,
                score=0.5 if partial else 0.0,
                error_step=None if partial else "missing_reference",
                hint=_hint("缺少参考答案，只能给出步骤完整性提示。", "No reference answer is available; only completeness can be checked.", self.language),
                confidence=0.35,
                raw_reason="Reference answer is missing.",
                grading_method="fallback",
            )

        if _answers_equivalent(candidate, ref) or (answer and _answers_equivalent(answer, ref)):
            return AgentEvalResult(
                is_correct=True,
                score=1.0,
                error_step=None,
                hint=_hint("答案匹配。请再检查书写规范和关键条件。", "The answer matches. Check notation and key conditions.", self.language),
                confidence=0.88,
                raw_reason="Student answer matches the reference by choice/string/numeric heuristic.",
                grading_method="heuristic",
            )

        if steps_text and _normalized_answer(ref) in _normalized_answer(steps_text):
            return AgentEvalResult(
                is_correct=True,
                score=0.85,
                error_step=None,
                hint=_hint("推导中出现了参考结论，请把最终答案单独写清楚。", "Your work contains the reference conclusion; write the final answer clearly.", self.language),
                confidence=0.65,
                raw_reason="Reference answer appears in student steps.",
                grading_method="heuristic",
            )

        error_step = _first_suspicious_step(steps_text, ref)
        return AgentEvalResult(
            is_correct=False,
            score=0.25 if steps_text else 0.0,
            error_step=error_step,
            hint=_hint(
                "对照参考答案检查最后一步；若是计算题，先核对符号、分母和边界条件。",
                "Compare your final step with the reference; check signs, denominators, and boundary conditions.",
                self.language,
            ),
            confidence=0.72,
            raw_reason=f"Student answer `{candidate}` does not match reference `{ref}`.",
            grading_method="heuristic",
        )

    async def _try_llm_eval(
        self,
        *,
        question: dict[str, Any] | str,
        reference_answer: str | None,
        student_steps: list[str] | str | None,
        student_answer: str | None,
    ) -> AgentEvalResult | None:
        try:
            from master_prep_ai.kaoyan.agent_adapters import route_model

            route = route_model("math_eval", difficulty=None, latency_budget="medium", cost_budget="medium")
            if route.get("fallback"):
                return None
            from master_prep_ai.services.llm import complete

            system_prompt = (
                "You are a strict postgraduate entrance exam math evaluator. "
                "Return JSON only with is_correct, score, error_step, hint, confidence, raw_reason."
            )
            prompt = json.dumps(
                {
                    "question": question,
                    "reference_answer": reference_answer,
                    "student_steps": student_steps,
                    "student_answer": student_answer,
                },
                ensure_ascii=False,
            )
            raw = await complete(
                prompt,
                system_prompt=system_prompt,
                model=str(route.get("model") or ""),
                binding=str(route.get("binding") or route.get("provider") or ""),
                max_retries=0,
                temperature=0.0,
            )
        except Exception:
            return None

        parsed = extract_json_object(raw)
        if not parsed:
            return None
        try:
            score = parsed.get("score")
            score_value = None if score is None else max(0.0, min(1.0, float(score)))
            confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.6))))
        except (TypeError, ValueError):
            return None
        return AgentEvalResult(
            is_correct=bool(parsed.get("is_correct")),
            score=score_value,
            error_step=str(parsed.get("error_step") or "") or None,
            hint=str(parsed.get("hint") or ""),
            confidence=confidence,
            raw_reason=str(parsed.get("raw_reason") or ""),
            grading_method="llm",
        )


def _question_answer(question: dict[str, Any] | str) -> str:
    if isinstance(question, dict):
        return str(question.get("answer") or question.get("correct_answer") or "")
    return ""


def _steps_text(student_steps: list[str] | str | None) -> str:
    if isinstance(student_steps, list):
        return "\n".join(str(item) for item in student_steps if str(item).strip())
    return str(student_steps or "").strip()


def _last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def _normalized_answer(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = text.replace("−", "-").replace("，", ",").replace("。", ".")
    text = _LATEX_FRAC_RE.sub(r"\1/\2", text)
    text = re.sub(r"\\(?:left|right|mathrm|text|,|;|!|quad|qquad)", "", text)
    text = re.sub(r"[\s$`*_{}[\]()]|答案|解得|所以|故|therefore|answer", "", text, flags=re.IGNORECASE)
    return text.lower().strip("：:;,.")


def _choice(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).upper()
    match = _CHOICE_RE.search(f" {normalized} ")
    return match.group(1).upper() if match else ""


def _number(value: str) -> Fraction | None:
    text = _normalized_answer(value)
    if not text:
        return None
    frac_match = re.search(r"[-+]?\d+\s*/\s*[-+]?\d+", text)
    if frac_match:
        try:
            return Fraction(frac_match.group(0).replace(" ", ""))
        except (ValueError, ZeroDivisionError):
            return None
    number_match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not number_match:
        return None
    try:
        return Fraction(number_match.group(0))
    except ValueError:
        return None


def _answers_equivalent(student: str, reference: str) -> bool:
    student_choice = _choice(student)
    ref_choice = _choice(reference)
    if student_choice or ref_choice:
        return bool(student_choice and ref_choice and student_choice == ref_choice)

    s_norm = _normalized_answer(student)
    r_norm = _normalized_answer(reference)
    if s_norm and r_norm and (s_norm == r_norm or s_norm in r_norm or r_norm in s_norm):
        return True

    s_num = _number(student)
    r_num = _number(reference)
    if s_num is not None and r_num is not None:
        return abs(float(s_num - r_num)) <= 1e-8
    return False


def _first_suspicious_step(steps_text: str, reference: str) -> str | None:
    if not steps_text:
        return "final_answer"
    lines = [line.strip() for line in steps_text.splitlines() if line.strip()]
    if not lines:
        return "final_answer"
    ref_num = _number(reference)
    if ref_num is not None:
        for index, line in enumerate(lines, start=1):
            line_num = _number(line)
            if line_num is not None and abs(float(line_num - ref_num)) > 1e-8:
                return f"step_{index}"
    return f"step_{len(lines)}"


def _hint(zh: str, en: str, language: str) -> str:
    return zh if language.lower().startswith("zh") else en


__all__ = ["MathEvalAgent"]
