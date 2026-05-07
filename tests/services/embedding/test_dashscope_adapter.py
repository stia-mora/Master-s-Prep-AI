"""Tests for the DashScope (Aliyun) MultiModalEmbedding adapter."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from master_prep_ai.services.embedding.adapters.base import EmbeddingRequest
from master_prep_ai.services.embedding.adapters.dashscope_native import (
    DashScopeMultiModalEmbeddingAdapter,
)


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, output: dict | None = None,
                 usage: dict | None = None, code: str = "", message: str = "",
                 request_id: str = "req-1") -> None:
        self.status_code = status_code
        self.output = output if output is not None else {"embeddings": []}
        self.usage = usage or {}
        self.code = code
        self.message = message
        self.request_id = request_id


def _install_fake_sdk(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_call(*, api_key: str, model: str, input: dict, **kwargs: Any) -> _FakeResponse:  # noqa: A002
        captured.update(
            api_key=api_key,
            model=model,
            input=input,
            kwargs=kwargs,
        )
        return response

    fake_module = types.SimpleNamespace(MultiModalEmbedding=types.SimpleNamespace(call=fake_call))
    monkeypatch.setitem(sys.modules, "dashscope", fake_module)
    return captured


@pytest.mark.asyncio
async def test_text_only_translates_texts_to_contents(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(
        output={"embeddings": [{"index": 0, "embedding": [0.1, 0.2, 0.3], "type": "vl"}]},
    )
    captured = _install_fake_sdk(monkeypatch, response)

    adapter = DashScopeMultiModalEmbeddingAdapter(
        {
            "api_key": "sk-dashscope",
            "base_url": "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
            "model": "qwen3-vl-embedding",
            "dimensions": 1024,
            "request_timeout": 5,
        }
    )
    resp = await adapter.embed(
        EmbeddingRequest(texts=["hello", "world"], model="qwen3-vl-embedding")
    )

    # SDK takes a flat list — it wraps as {"contents": ...} internally.
    assert captured["input"] == [{"text": "hello"}, {"text": "world"}]
    assert captured["model"] == "qwen3-vl-embedding"
    assert captured["api_key"] == "sk-dashscope"
    assert captured["kwargs"].get("dimension") == 1024
    assert "enable_fusion" not in captured["kwargs"]
    assert resp.embeddings == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_multimodal_contents_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(
        output={"embeddings": [{"index": 0, "embedding": [0.4, 0.5], "type": "fusion"}]},
    )
    captured = _install_fake_sdk(monkeypatch, response)

    adapter = DashScopeMultiModalEmbeddingAdapter(
        {
            "api_key": "sk-dashscope",
            "base_url": "https://dashscope.aliyuncs.com/...",
            "model": "qwen3-vl-embedding",
            "dimensions": 0,
            "request_timeout": 5,
        }
    )
    contents = [{"text": "a slide"}, {"image": "https://example.com/img.png"}]
    resp = await adapter.embed(
        EmbeddingRequest(
            texts=[],
            model="qwen3-vl-embedding",
            contents=contents,
            enable_fusion=True,
        )
    )
    # SDK takes a flat list — it wraps as {"contents": ...} internally.
    assert captured["input"] == contents
    assert captured["kwargs"].get("enable_fusion") is True
    assert resp.embeddings == [[0.4, 0.5]]


@pytest.mark.asyncio
async def test_failure_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(
        status_code=400,
        output={"embeddings": []},
        code="InvalidParameter",
        message="dimension out of range",
    )
    _install_fake_sdk(monkeypatch, response)

    adapter = DashScopeMultiModalEmbeddingAdapter(
        {
            "api_key": "sk",
            "base_url": "https://dashscope.aliyuncs.com/...",
            "model": "qwen3-vl-embedding",
            "request_timeout": 5,
        }
    )
    with pytest.raises(RuntimeError) as ei:
        await adapter.embed(EmbeddingRequest(texts=["x"], model="qwen3-vl-embedding"))
    assert "InvalidParameter" in str(ei.value)


def test_get_model_info_reports_multimodal_capability() -> None:
    adapter = DashScopeMultiModalEmbeddingAdapter(
        {
            "api_key": "sk",
            "base_url": "https://...",
            "model": "qwen3-vl-embedding",
        }
    )
    info = adapter.get_model_info()
    assert info["multimodal"] is True
    assert info["provider"] == "aliyun"
    assert 2560 in info["supported_dimensions"]
