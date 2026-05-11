"""LLM provider abstraction module."""

from master_prep_ai.tutorbot.providers.base import LLMProvider, LLMResponse

__all__ = ["LLMProvider", "LLMResponse", "OpenAICompatProvider", "AnthropicProvider"]


def __getattr__(name: str):
    if name == "OpenAICompatProvider":
        from master_prep_ai.tutorbot.providers.openai_compat_provider import OpenAICompatProvider

        return OpenAICompatProvider
    if name == "AnthropicProvider":
        from master_prep_ai.tutorbot.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider
    # Legacy alias
    if name == "LiteLLMProvider":
        from master_prep_ai.tutorbot.providers.openai_compat_provider import OpenAICompatProvider

        return OpenAICompatProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
