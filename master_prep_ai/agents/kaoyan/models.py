"""Stable public result models for Kaoyan agent adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SocraticState = Literal["ASSESS", "GUIDE", "VERIFY", "CONSOLIDATE"]
GradingMethod = Literal["heuristic", "llm", "fallback"]


@dataclass(slots=True)
class SocraticTurnResult:
    state: SocraticState
    question: str
    hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgentEvalResult:
    is_correct: bool
    score: float | None
    error_step: str | None
    hint: str
    confidence: float
    raw_reason: str
    grading_method: GradingMethod

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MemoryUpdateResult:
    profile_patch: dict[str, Any]
    mastery_delta: list[dict[str, Any]]
    audit_log: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "AgentEvalResult",
    "GradingMethod",
    "MemoryUpdateResult",
    "SocraticState",
    "SocraticTurnResult",
]
