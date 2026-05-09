from __future__ import annotations

from master_prep_ai.services.llm import route_model


def _clear_llm_env(monkeypatch) -> None:
    for key in [
        "KAOYAN_ROUTE_MODEL_JSON",
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "DASHSCOPE_API_KEY",
        "GEMINI_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_route_model_non_local_without_api_key_falls_back(monkeypatch) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv(
        "KAOYAN_ROUTE_MODEL_JSON",
        '{"math_eval":{"provider":"openai","binding":"openai","model":"gpt-test"}}',
    )

    route = route_model("math_eval")

    assert route["fallback"] is True
    assert route["provider"] == "openai"
    assert "api_key" not in route


def test_route_model_local_without_api_key_is_allowed(monkeypatch) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv(
        "KAOYAN_ROUTE_MODEL_JSON",
        '{"default":{"provider":"ollama","binding":"ollama","model":"qwen2.5","base_url":"http://localhost:11434/v1"}}',
    )

    route = route_model("socratic")

    assert route["fallback"] is False
    assert route["provider"] == "ollama"
    assert route["model"] == "qwen2.5"


def test_route_model_invalid_json_falls_back(monkeypatch) -> None:
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("KAOYAN_ROUTE_MODEL_JSON", "{bad json")

    route = route_model("memory_update")

    assert route["fallback"] is True
    assert route["provider"] == "mock"
