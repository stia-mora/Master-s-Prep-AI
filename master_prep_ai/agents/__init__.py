"""
Agents Module - Unified agent system for OpenTutor.

This module provides a unified BaseAgent class and module-specific agents:
- solve: Question solving agents (MainSolver, SolveAgent, etc.)
- research: Deep research agents (DecomposeAgent, ResearchAgent, etc.)
- question: Question generation agents (ReAct architecture, separate base)
- chat: Lightweight conversational agent with session management

Note: ``co_writer`` and ``book`` are independent top-level modules under
``master_prep_ai/`` (e.g. ``master_prep_ai.co_writer``, ``master_prep_ai.book``). They
still inherit from :class:`BaseAgent` defined here but are not part of
the ``master_prep_ai.agents`` package.

Usage:
    from master_prep_ai.agents.base_agent import BaseAgent

    class MyAgent(BaseAgent):
        async def process(self, *args, **kwargs):
            ...
"""

__all__ = ["BaseAgent", "ChatAgent", "SessionManager"]


def __getattr__(name: str):
    if name == "BaseAgent":
        from .base_agent import BaseAgent

        return BaseAgent
    if name in {"ChatAgent", "SessionManager"}:
        from .chat import ChatAgent, SessionManager

        return {"ChatAgent": ChatAgent, "SessionManager": SessionManager}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
