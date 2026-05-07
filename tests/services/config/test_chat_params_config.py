"""Tests for chat capability per-stage token configuration via agents.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from master_prep_ai.services.config import loader as loader_module
from master_prep_ai.services.config.loader import (
    DEFAULT_CHAT_PARAMS,
    get_chat_params,
)


def _write_agents_yaml(tmp_path: Path, content: dict[str, Any]) -> Path:
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    agents_file = settings_dir / "agents.yaml"
    agents_file.write_text(yaml.dump(content), encoding="utf-8")
    return tmp_path


class TestGetChatParams:
    """Verify get_chat_params() correctly resolves capabilities.chat."""

    def test_returns_defaults_when_file_missing(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(loader_module, "PROJECT_ROOT", tmp_path)
        params = get_chat_params()
        assert params == DEFAULT_CHAT_PARAMS

    def test_returns_defaults_when_chat_section_absent(self, tmp_path: Path, monkeypatch):
        project_root = _write_agents_yaml(
            tmp_path,
            {
                "capabilities": {"solve": {"temperature": 0.3}},
            },
        )
        monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)
        params = get_chat_params()
        assert params["temperature"] == DEFAULT_CHAT_PARAMS["temperature"]
        assert params["responding"]["max_tokens"] == 8000
        assert params["thinking"]["max_tokens"] == 2000

    def test_overrides_specific_stage_only(self, tmp_path: Path, monkeypatch):
        project_root = _write_agents_yaml(
            tmp_path,
            {
                "capabilities": {
                    "chat": {
                        "responding": {"max_tokens": 12000},
                    },
                },
            },
        )
        monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)
        params = get_chat_params()
        assert params["responding"]["max_tokens"] == 12000
        assert params["answer_now"]["max_tokens"] == 8000
        assert params["thinking"]["max_tokens"] == 2000
        assert params["temperature"] == 0.2

    def test_overrides_temperature(self, tmp_path: Path, monkeypatch):
        project_root = _write_agents_yaml(
            tmp_path,
            {
                "capabilities": {"chat": {"temperature": 0.7}},
            },
        )
        monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)
        params = get_chat_params()
        assert params["temperature"] == 0.7
        assert params["responding"]["max_tokens"] == 8000

    def test_full_chat_block_round_trip(self, tmp_path: Path, monkeypatch):
        project_root = _write_agents_yaml(
            tmp_path,
            {
                "capabilities": {
                    "chat": {
                        "temperature": 0.4,
                        "responding": {"max_tokens": 16000},
                        "answer_now": {"max_tokens": 16000},
                        "thinking": {"max_tokens": 3000},
                        "observing": {"max_tokens": 3000},
                        "acting": {"max_tokens": 3000},
                        "react_fallback": {"max_tokens": 2500},
                    },
                },
            },
        )
        monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)
        params = get_chat_params()
        assert params["temperature"] == 0.4
        assert params["responding"]["max_tokens"] == 16000
        assert params["answer_now"]["max_tokens"] == 16000
        assert params["thinking"]["max_tokens"] == 3000
        assert params["observing"]["max_tokens"] == 3000
        assert params["acting"]["max_tokens"] == 3000
        assert params["react_fallback"]["max_tokens"] == 2500


class TestChatLimitsDataclass:
    """Verify _ChatLimits.from_config gracefully handles malformed input."""

    def test_from_config_with_empty_dict_uses_fallbacks(self):
        from master_prep_ai.agents.chat.agentic_pipeline import _ChatLimits

        limits = _ChatLimits.from_config({})
        assert limits.responding == 8000
        assert limits.answer_now == 8000
        assert limits.thinking == 2000
        assert limits.observing == 2000
        assert limits.acting == 2000
        assert limits.react_fallback == 1500

    def test_from_config_with_chat_params_defaults(self):
        from master_prep_ai.agents.chat.agentic_pipeline import _ChatLimits

        limits = _ChatLimits.from_config(DEFAULT_CHAT_PARAMS)
        assert limits.responding == 8000
        assert limits.react_fallback == 1500

    def test_from_config_coerces_string_numbers(self):
        from master_prep_ai.agents.chat.agentic_pipeline import _ChatLimits

        limits = _ChatLimits.from_config({"responding": {"max_tokens": "5000"}})
        assert limits.responding == 5000

    def test_from_config_falls_back_on_garbage(self):
        from master_prep_ai.agents.chat.agentic_pipeline import _ChatLimits

        limits = _ChatLimits.from_config({"responding": {"max_tokens": "abc"}})
        assert limits.responding == 8000

    def test_from_config_handles_non_dict_stage_value(self):
        from master_prep_ai.agents.chat.agentic_pipeline import _ChatLimits

        limits = _ChatLimits.from_config({"responding": 12345})
        assert limits.responding == 8000
