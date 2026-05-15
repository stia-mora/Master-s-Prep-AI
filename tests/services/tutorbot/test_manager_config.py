"""Unit tests for TutorBotManager config persistence & merging."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from master_prep_ai.services.tutorbot.manager import BotConfig, TutorBotInstance, TutorBotManager


@pytest.fixture
def manager(tmp_path: Path) -> TutorBotManager:
    """Return a TutorBotManager whose data dir is a fresh temp directory."""
    mgr = TutorBotManager()
    # Replace the path service with a stub so reads/writes stay sandboxed.
    mgr._path_service = SimpleNamespace(  # type: ignore[assignment]
        project_root=tmp_path,
        get_memory_dir=lambda: tmp_path / "memory",
    )
    return mgr


# ---------------------------------------------------------------------------
# load_bot_config / save_bot_config
# ---------------------------------------------------------------------------


class TestLoadAndSave:
    def test_load_returns_none_when_no_config(self, manager: TutorBotManager):
        assert manager.load_bot_config("nonexistent") is None

    def test_save_then_load_roundtrip(self, manager: TutorBotManager):
        cfg = BotConfig(
            name="My Bot",
            description="d",
            persona="p",
            channels={"telegram": {"enabled": True, "token": "tok"}},
            model="gpt-4o",
        )
        manager.save_bot_config("bot-a", cfg)

        loaded = manager.load_bot_config("bot-a")
        assert loaded == cfg

    def test_load_corrupt_yaml_returns_none(self, manager: TutorBotManager):
        bot_dir = manager._bot_dir("bad-bot")
        bot_dir.mkdir(parents=True, exist_ok=True)
        (bot_dir / "config.yaml").write_text(": not :: valid : yaml ::", encoding="utf-8")

        assert manager.load_bot_config("bad-bot") is None


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_save_uses_temp_file_and_replace(self, manager: TutorBotManager, monkeypatch):
        """save_bot_config must write to a temp file then atomically replace.

        We assert that:
          1. A ``.tmp`` file is created during the write.
          2. After the call, only the final ``config.yaml`` exists (the temp
             file has been moved into place via Path.replace).
        """
        cfg = BotConfig(name="atomic", channels={"telegram": {"enabled": True}})

        observed: dict[str, list[Path]] = {"tmp_writes": [], "replaces": []}
        original_write_text = Path.write_text
        original_replace = Path.replace

        def tracked_write_text(self_path: Path, *args, **kwargs):
            if self_path.suffix == ".tmp":
                observed["tmp_writes"].append(Path(self_path))
            return original_write_text(self_path, *args, **kwargs)

        def tracked_replace(self_path: Path, target: Path):
            observed["replaces"].append((Path(self_path), Path(target)))
            return original_replace(self_path, target)

        monkeypatch.setattr(Path, "write_text", tracked_write_text)
        monkeypatch.setattr(Path, "replace", tracked_replace)

        manager.save_bot_config("atomic-bot", cfg)

        bot_dir = manager._bot_dir("atomic-bot")
        final = bot_dir / "config.yaml"
        tmp = bot_dir / "config.yaml.tmp"

        assert final.exists()
        assert not tmp.exists(), "Temp file must be moved away after save"
        assert observed["tmp_writes"], "Expected a write to a .tmp file"
        assert observed["replaces"], "Expected Path.replace to be called"

    def test_save_does_not_corrupt_existing_on_failed_write(
        self, manager: TutorBotManager, monkeypatch
    ):
        """If the write fails midway, the previous on-disk config must survive."""
        good_cfg = BotConfig(name="orig", channels={"telegram": {"enabled": True}})
        manager.save_bot_config("safe-bot", good_cfg)

        original_write_text = Path.write_text

        def boom(self_path: Path, *args, **kwargs):
            if self_path.suffix == ".tmp":
                raise OSError("disk full")
            return original_write_text(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", boom)

        with pytest.raises(OSError):
            manager.save_bot_config("safe-bot", BotConfig(name="new", channels={}))

        # Original config must still be intact.
        loaded = manager.load_bot_config("safe-bot")
        assert loaded == good_cfg


# ---------------------------------------------------------------------------
# merge_bot_config
# ---------------------------------------------------------------------------


class TestMergeBotConfig:
    def test_merge_with_no_existing_uses_defaults(self, manager: TutorBotManager):
        merged = manager.merge_bot_config("brand-new", {"name": "X"})
        assert merged.name == "X"
        assert merged.description == ""
        assert merged.channels == {}

    def test_merge_keeps_existing_when_overrides_omit_field(self, manager: TutorBotManager):
        manager.save_bot_config(
            "bot-1",
            BotConfig(name="Disk", description="dd", channels={"telegram": {}}),
        )

        merged = manager.merge_bot_config("bot-1", {"persona": "p"})
        assert merged.name == "Disk"
        assert merged.description == "dd"
        assert merged.persona == "p"
        assert merged.channels == {"telegram": {}}

    def test_merge_treats_none_as_not_provided(self, manager: TutorBotManager):
        manager.save_bot_config(
            "bot-2",
            BotConfig(name="Disk", description="dd"),
        )

        merged = manager.merge_bot_config("bot-2", {"description": None, "name": "New"})
        assert merged.name == "New"
        assert merged.description == "dd"

    def test_merge_treats_empty_string_and_dict_as_explicit_clear(self, manager: TutorBotManager):
        manager.save_bot_config(
            "bot-3",
            BotConfig(
                name="Disk",
                description="dd",
                channels={"telegram": {"enabled": True}},
            ),
        )

        merged = manager.merge_bot_config("bot-3", {"description": "", "channels": {}})
        assert merged.description == ""
        assert merged.channels == {}

    def test_merge_ignores_unknown_keys(self, manager: TutorBotManager):
        merged = manager.merge_bot_config("bot-4", {"name": "X", "unknown_field": "boom"})
        assert merged.name == "X"
        assert not hasattr(merged, "unknown_field")


# ---------------------------------------------------------------------------
# auto_start persistence during lifecycle stops
# ---------------------------------------------------------------------------


class TestAutoStartPersistence:
    def _config_data(self, manager: TutorBotManager, bot_id: str) -> dict:
        return yaml.safe_load(
            (manager._bot_dir(bot_id) / "config.yaml").read_text(encoding="utf-8")
        )

    def _register_instance(
        self,
        manager: TutorBotManager,
        bot_id: str,
        cfg: BotConfig | None = None,
    ) -> BotConfig:
        cfg = cfg or BotConfig(name=bot_id)
        manager._bots[bot_id] = TutorBotInstance(bot_id=bot_id, config=cfg)
        return cfg

    def test_manual_stop_disables_future_auto_start(self, manager: TutorBotManager):
        cfg = BotConfig(name="manual")
        manager.save_bot_config("manual-bot", cfg, auto_start=True)
        self._register_instance(manager, "manual-bot", cfg)

        assert asyncio.run(manager.stop_bot("manual-bot")) is True

        assert self._config_data(manager, "manual-bot")["auto_start"] is False
        assert manager.get_bot("manual-bot") is None

    def test_shutdown_stop_all_preserves_auto_start_true(self, manager: TutorBotManager):
        cfg = BotConfig(name="restartable")
        manager.save_bot_config("restartable-bot", cfg, auto_start=True)
        self._register_instance(manager, "restartable-bot", cfg)

        asyncio.run(manager.stop_all())

        assert self._config_data(manager, "restartable-bot")["auto_start"] is True
        assert manager.get_bot("restartable-bot") is None

    def test_shutdown_stop_all_preserves_existing_auto_start_false(
        self, manager: TutorBotManager
    ):
        cfg = BotConfig(name="manual-only")
        manager.save_bot_config("manual-only-bot", cfg, auto_start=False)
        self._register_instance(manager, "manual-only-bot", cfg)

        asyncio.run(manager.stop_all())

        assert self._config_data(manager, "manual-only-bot")["auto_start"] is False


def test_start_bot_passes_shared_memory_dir(
    manager: TutorBotManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Path | None] = {}

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            captured["shared_memory_dir"] = kwargs.get("shared_memory_dir")
            self.model = kwargs.get("model") or "fake-model"

        async def run(self) -> None:
            return None

        async def process_direct(self, *_args, **_kwargs) -> str:
            return "ok"

    class FakeHeartbeat:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def start(self) -> None:
            return None

    monkeypatch.setattr("master_prep_ai.tutorbot.agent.loop.AgentLoop", FakeAgentLoop)
    monkeypatch.setattr(
        "master_prep_ai.tutorbot.providers.master_prep_ai_adapter.create_master_prep_ai_provider",
        lambda: object(),
    )
    monkeypatch.setattr(
        "master_prep_ai.services.tutorbot.manager.TutorBotManager._build_channel_manager",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "master_prep_ai.services.tutorbot.manager.TutorBotManager._outbound_router",
        lambda *_args, **_kwargs: _done(),
    )
    monkeypatch.setattr("master_prep_ai.tutorbot.heartbeat.HeartbeatService", FakeHeartbeat)

    async def run_start() -> None:
        instance = await manager.start_bot("shared-memory-bot", BotConfig(name="bot"))
        for task in instance.tasks:
            task.cancel()

    async def _done() -> None:
        return None

    asyncio.run(run_start())

    assert captured["shared_memory_dir"] == tmp_path / "memory"
