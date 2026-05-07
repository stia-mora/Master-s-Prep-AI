"""Regression: env values must NOT overlay user-managed catalog profiles.

Bug: ``ModelCatalogService.load()`` used to unconditionally call
``_sync_active_services_from_env`` on every load, which copied the .env
``EMBEDDING_HOST`` (etc.) onto whatever profile was currently active. Combined
with the fact that "Save Draft" persists the catalog but does NOT write env,
this destroyed the user's freshly-added second profile after a page refresh:

* User has Default profile (active, env reflects its base_url)
* User clicks "+ Profile", names it "aliyun", fills DashScope URL/key, saves draft
* Catalog now has 2 profiles, aliyun is active. Env still has Default's URL.
* Refresh → load() syncs env onto active (aliyun) → aliyun's base_url is
  overwritten with Default's openrouter URL.

Fix: only run the env→catalog sync while the catalog is in pristine
default-bootstrap state (one auto-seeded profile per service).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from master_prep_ai.services.config import env_store as env_store_module
from master_prep_ai.services.config import model_catalog as model_catalog_module
from master_prep_ai.services.config.env_store import EnvStore
from master_prep_ai.services.config.model_catalog import ModelCatalogService


def _write_env(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture()
def isolated_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    catalog_path = tmp_path / "model_catalog.json"
    env_path = tmp_path / ".env"
    env = EnvStore(env_path)
    monkeypatch.setattr(env_store_module, "_env_store", env, raising=False)
    monkeypatch.setattr(env_store_module, "get_env_store", lambda: env)
    monkeypatch.setattr(model_catalog_module, "get_env_store", lambda: env)
    # Reset the model_catalog singleton so each test gets a fresh service.
    monkeypatch.setattr(ModelCatalogService, "_instance", None, raising=False)
    return catalog_path, env_path


def test_user_added_second_profile_survives_reload(
    isolated_stores: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog_path, env_path = isolated_stores

    # Env reflects the previous "Default" profile values.
    _write_env(
        env_path,
        [
            "EMBEDDING_BINDING=openai",
            "EMBEDDING_MODEL=text-embedding-3-large",
            "EMBEDDING_HOST=https://openrouter.ai/api/v1",
            "EMBEDDING_API_KEY=sk-default",
            "EMBEDDING_DIMENSION=",
        ],
    )

    # Simulate user state after Save Draft on a 2-profile catalog where the
    # user added "aliyun" with a DashScope URL.
    user_catalog: dict[str, Any] = {
        "services": {
            "llm": {
                "active_profile_id": "llm-profile-default",
                "active_model_id": "llm-model-default",
                "profiles": [
                    {
                        "id": "llm-profile-default",
                        "name": "Default LLM Endpoint",
                        "binding": "openai",
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key": "sk-llm",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [{"id": "llm-model-default", "name": "m", "model": "gpt"}],
                    }
                ],
            },
            "embedding": {
                # User-managed: 2 profiles, aliyun is active.
                "active_profile_id": "embedding-profile-1700000000",
                "active_model_id": "embedding-model-1700000000",
                "profiles": [
                    {
                        "id": "embedding-profile-default",
                        "name": "Default Embedding Endpoint",
                        "binding": "openai",
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key": "sk-default",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {
                                "id": "embedding-model-default",
                                "name": "m",
                                "model": "text-embedding-3-large",
                                "dimension": "",
                            }
                        ],
                    },
                    {
                        "id": "embedding-profile-1700000000",
                        "name": "aliyun",
                        "binding": "aliyun",
                        # User typed the DashScope URL & key.
                        "base_url": "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
                        "api_key": "sk-dashscope",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {
                                "id": "embedding-model-1700000000",
                                "name": "qwen3-vl-embedding",
                                "model": "qwen3-vl-embedding",
                                "dimension": "",
                            }
                        ],
                    },
                ],
            },
            "search": {"active_profile_id": None, "profiles": []},
        }
    }
    catalog_path.write_text(json.dumps(user_catalog))

    service = ModelCatalogService(catalog_path)
    loaded = service.load()

    embedding_service = loaded["services"]["embedding"]
    aliyun = next(
        p for p in embedding_service["profiles"] if p["id"] == "embedding-profile-1700000000"
    )
    # The bug: env's openrouter URL was overlaying aliyun's DashScope URL.
    assert aliyun["base_url"].startswith("https://dashscope.aliyuncs.com/")
    assert aliyun["api_key"] == "sk-dashscope"
    assert aliyun["binding"] == "aliyun"
    # And the second profile is still there (not collapsed into a single one).
    assert len(embedding_service["profiles"]) == 2


def test_env_still_seeds_pristine_single_default_profile(
    isolated_stores: tuple[Path, Path],
) -> None:
    """Power-user case: edit .env directly, single default profile in catalog
    → env should still flow into the catalog on next load."""
    catalog_path, env_path = isolated_stores

    _write_env(
        env_path,
        [
            "EMBEDDING_BINDING=openai",
            "EMBEDDING_MODEL=text-embedding-3-small",
            "EMBEDDING_HOST=https://api.openai.com/v1/embeddings",
            "EMBEDDING_API_KEY=sk-newkey",
        ],
    )

    pristine_catalog: dict[str, Any] = {
        "services": {
            "llm": {"active_profile_id": None, "profiles": []},
            "embedding": {
                "active_profile_id": "embedding-profile-default",
                "active_model_id": "embedding-model-default",
                "profiles": [
                    {
                        "id": "embedding-profile-default",
                        "name": "Default Embedding Endpoint",
                        "binding": "openai",
                        "base_url": "stale-old-value",
                        "api_key": "stale-old-key",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {
                                "id": "embedding-model-default",
                                "name": "stale",
                                "model": "stale-model",
                                "dimension": "",
                            }
                        ],
                    }
                ],
            },
            "search": {"active_profile_id": None, "profiles": []},
        }
    }
    catalog_path.write_text(json.dumps(pristine_catalog))

    service = ModelCatalogService(catalog_path)
    loaded = service.load()

    profile = loaded["services"]["embedding"]["profiles"][0]
    # Pristine catalog → env wins (legacy expected behavior preserved).
    assert profile["base_url"] == "https://api.openai.com/v1/embeddings"
    assert profile["api_key"] == "sk-newkey"
    assert profile["models"][0]["model"] == "text-embedding-3-small"
