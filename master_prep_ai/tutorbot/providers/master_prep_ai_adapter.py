"""LLM provider adapter that reuses Master Prep AI's LLM configuration.

When TutorBot runs in-process inside the Master Prep AI server, this provider
reads api_key / model / base_url from Master Prep AI's unified config and
delegates to the appropriate provider (OpenAICompat or Anthropic).
"""

from __future__ import annotations

from master_prep_ai.services.llm.provider_core.base import LLMProvider


def create_master_prep_ai_provider() -> LLMProvider:
    """Build a provider pre-configured from Master Prep AI's LLMConfig."""
    from master_prep_ai.services.llm.provider_factory import get_runtime_provider

    return get_runtime_provider()
