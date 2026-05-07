"""Tests for normalized embedding runtime resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from master_prep_ai.services.config.env_store import EnvStore
from master_prep_ai.services.config.provider_runtime import resolve_embedding_runtime_config


@pytest.fixture(autouse=True)
def _isolate_send_dimensions_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip ``EMBEDDING_SEND_DIMENSIONS`` from ``os.environ`` for the duration of
    each test. The real project ``.env`` (and other tests) can leave this
    populated, which short-circuits ``as_summary``'s ``os.getenv`` fallback and
    breaks the "auto / None" assertions."""
    monkeypatch.delenv("EMBEDDING_SEND_DIMENSIONS", raising=False)


def _build_catalog(
    *,
    embedding_profile: dict | None = None,
    embedding_model: dict | None = None,
) -> dict:
    embedding_profile = embedding_profile or {
        "id": "embedding-p",
        "name": "Embedding",
        "binding": "openai",
        "base_url": "",
        "api_key": "",
        "api_version": "",
        "extra_headers": {},
        "models": [{"id": "embedding-m", "name": "m", "model": "text-embedding-3-large"}],
    }
    if embedding_model is not None:
        # Replace whichever model lives at the active slot so the override is
        # actually visible to ``resolve_embedding_runtime_config``.
        embedding_profile["models"] = [embedding_model]
    embedding_model = embedding_profile["models"][0]
    return {
        "version": 1,
        "services": {
            "llm": {"active_profile_id": None, "active_model_id": None, "profiles": []},
            "embedding": {
                "active_profile_id": embedding_profile["id"],
                "active_model_id": embedding_model["id"],
                "profiles": [embedding_profile],
            },
            "search": {"active_profile_id": None, "profiles": []},
        },
    }


def _env(tmp_path: Path, lines: list[str]) -> EnvStore:
    defaults = [
        "EMBEDDING_BINDING=",
        "EMBEDDING_MODEL=",
        "EMBEDDING_API_KEY=",
        "EMBEDDING_HOST=",
        "EMBEDDING_DIMENSION=",
        "EMBEDDING_API_VERSION=",
        "OPENAI_API_KEY=",
        "AZURE_OPENAI_API_KEY=",
        "AZURE_API_KEY=",
        "COHERE_API_KEY=",
        "JINA_API_KEY=",
        "HOSTED_VLLM_API_KEY=",
    ]
    env_path = tmp_path / ".env"
    env_path.write_text("\n".join(defaults + lines) + "\n", encoding="utf-8")
    return EnvStore(path=env_path)


def test_embedding_explicit_binding_and_headers(tmp_path: Path) -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "jina",
            "base_url": "",
            "api_key": "jina-key",
            "api_version": "",
            "extra_headers": {"X-App": "demo"},
            "models": [
                {
                    "id": "embedding-m",
                    "name": "jina",
                    "model": "jina-embeddings-v3",
                    "dimension": "1024",
                }
            ],
        }
    )
    env = _env(
        tmp_path,
        [
            "EMBEDDING_BINDING=",
            "EMBEDDING_MODEL=",
            "EMBEDDING_API_KEY=",
            "EMBEDDING_HOST=",
            "EMBEDDING_DIMENSION=",
            "EMBEDDING_API_VERSION=",
        ],
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog, env_store=env)
    assert resolved.provider_name == "jina"
    assert resolved.provider_mode == "standard"
    # v1.3.0: provider defaults are full embedding endpoint URLs.
    assert resolved.effective_url == "https://api.jina.ai/v1/embeddings"
    assert resolved.extra_headers == {"X-App": "demo"}
    assert resolved.dimension == 1024


def test_embedding_alias_canonicalization_google_to_openai(tmp_path: Path) -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "google",
            "base_url": "",
            "api_key": "k",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "embedding-m", "name": "m", "model": "text-embedding-3-small"}],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog, env_store=_env(tmp_path, []))
    assert resolved.provider_name == "openai"
    assert resolved.binding == "openai"


def test_embedding_local_fallback_from_base_url(tmp_path: Path) -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "",
            "base_url": "http://localhost:11434",
            "api_key": "",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "embedding-m", "name": "m", "model": "nomic-embed-text"}],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog, env_store=_env(tmp_path, []))
    assert resolved.provider_name == "ollama"
    assert resolved.provider_mode == "local"
    assert resolved.api_key == "sk-no-key-required"


def test_embedding_openai_default_base_injected(tmp_path: Path) -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "openai",
            "base_url": "",
            "api_key": "sk-test",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "embedding-m", "name": "m", "model": "text-embedding-3-large"}],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog, env_store=_env(tmp_path, []))
    assert resolved.provider_name == "openai"
    # v1.3.0: provider defaults are full embedding endpoint URLs.
    assert resolved.effective_url == "https://api.openai.com/v1/embeddings"


def test_embedding_send_dimensions_default_is_none(tmp_path: Path) -> None:
    """Catalogs without the field should resolve to ``None`` (Auto behaviour)."""
    catalog = _build_catalog()  # default model has no `send_dimensions`
    resolved = resolve_embedding_runtime_config(catalog=catalog, env_store=_env(tmp_path, []))
    assert resolved.send_dimensions is None


@pytest.mark.parametrize(
    ("catalog_value", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),
        ("false", False),
        ("on", True),
        ("off", False),
        ("", None),
        ("garbage", None),
    ],
)
def test_embedding_send_dimensions_parsed_from_catalog(
    tmp_path: Path,
    catalog_value: object,
    expected: bool | None,
) -> None:
    catalog = _build_catalog(
        embedding_model={
            "id": "embedding-m",
            "name": "m",
            "model": "text-embedding-v4",
            "dimension": "1024",
            "send_dimensions": catalog_value,
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog, env_store=_env(tmp_path, []))
    assert resolved.send_dimensions is expected


def test_embedding_send_dimensions_env_fallback_when_catalog_unset(tmp_path: Path) -> None:
    """When the catalog has no flag, fall back to the env value."""
    catalog = _build_catalog()
    env = _env(tmp_path, ["EMBEDDING_SEND_DIMENSIONS=false"])
    resolved = resolve_embedding_runtime_config(catalog=catalog, env_store=env)
    assert resolved.send_dimensions is False


def test_embedding_send_dimensions_catalog_wins_over_env(tmp_path: Path) -> None:
    """An explicit catalog value overrides whatever is in .env."""
    catalog = _build_catalog(
        embedding_model={
            "id": "embedding-m",
            "name": "m",
            "model": "text-embedding-3-large",
            "dimension": "3072",
            "send_dimensions": True,
        }
    )
    env = _env(tmp_path, ["EMBEDDING_SEND_DIMENSIONS=false"])
    resolved = resolve_embedding_runtime_config(catalog=catalog, env_store=env)
    assert resolved.send_dimensions is True


def test_embedding_custom_openai_sdk_uses_user_supplied_base_url(tmp_path: Path) -> None:
    """`custom_openai_sdk` accepts any user-supplied URL verbatim and routes
    through the AsyncOpenAI client (which appends `/embeddings` itself)."""
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "custom_openai_sdk",
            "base_url": "https://my-proxy.example.com/v1",
            "api_key": "sk-custom",
            "api_version": "",
            "extra_headers": {},
            "models": [
                {
                    "id": "embedding-m",
                    "name": "m",
                    "model": "text-embedding-3-large",
                    "dimension": "3072",
                }
            ],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog, env_store=_env(tmp_path, []))
    assert resolved.provider_name == "custom_openai_sdk"
    assert resolved.binding == "custom_openai_sdk"
    assert resolved.effective_url == "https://my-proxy.example.com/v1"
    assert resolved.api_key == "sk-custom"


def test_embedding_openrouter_default_base_url_injected(tmp_path: Path) -> None:
    """When no base URL is set, the OpenRouter spec's default fills in."""
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "openrouter",
            "base_url": "",
            "api_key": "sk-or-xxxxx",
            "api_version": "",
            "extra_headers": {},
            "models": [
                {
                    "id": "embedding-m",
                    "name": "m",
                    "model": "qwen/qwen3-embedding-8b",
                }
            ],
        }
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog, env_store=_env(tmp_path, []))
    assert resolved.provider_name == "openrouter"
    assert resolved.binding == "openrouter"
    assert resolved.effective_url == "https://openrouter.ai/api/v1"


def test_embedding_openrouter_env_key_fallback(tmp_path: Path) -> None:
    """`OPENROUTER_API_KEY` env var fills in when the profile has no key."""
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "openrouter",
            "base_url": "",
            "api_key": "",
            "api_version": "",
            "extra_headers": {},
            "models": [
                {"id": "embedding-m", "name": "m", "model": "qwen/qwen3-embedding-8b"}
            ],
        }
    )
    env = _env(tmp_path, ["OPENROUTER_API_KEY=sk-or-from-env"])
    resolved = resolve_embedding_runtime_config(catalog=catalog, env_store=env)
    assert resolved.provider_name == "openrouter"
    assert resolved.api_key == "sk-or-from-env"


def test_embedding_provider_env_key_fallback(tmp_path: Path) -> None:
    catalog = _build_catalog(
        embedding_profile={
            "id": "embedding-p",
            "name": "Embedding",
            "binding": "cohere",
            "base_url": "",
            "api_key": "",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "embedding-m", "name": "m", "model": "embed-v4.0"}],
        }
    )
    env = _env(
        tmp_path,
        [
            "COHERE_API_KEY=cohere-test-key",
            "EMBEDDING_BINDING=",
            "EMBEDDING_MODEL=",
            "EMBEDDING_API_KEY=",
            "EMBEDDING_HOST=",
            "EMBEDDING_DIMENSION=",
            "EMBEDDING_API_VERSION=",
        ],
    )
    resolved = resolve_embedding_runtime_config(catalog=catalog, env_store=env)
    assert resolved.provider_name == "cohere"
    assert resolved.api_key == "cohere-test-key"
