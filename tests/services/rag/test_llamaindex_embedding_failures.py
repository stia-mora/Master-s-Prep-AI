from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_custom_embedding_rejects_null_coordinates(monkeypatch: pytest.MonkeyPatch) -> None:
    from master_prep_ai.services.rag.pipelines.llamaindex import (
        embedding_adapter as embedding_module,
    )

    class _FakeClient:
        config = SimpleNamespace(binding="openai", model="bad-embed")

        async def embed(self, texts, progress_callback=None):
            return [[0.1, None, 0.3] for _ in texts]

    monkeypatch.setattr(embedding_module, "get_embedding_client", lambda: _FakeClient())

    embedding = embedding_module.CustomEmbedding()

    with pytest.raises(ValueError, match="dimension 1 is null"):
        embedding._get_text_embeddings(["chunk"])


@pytest.mark.asyncio
async def test_search_returns_reindex_hint_for_null_vector_index(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from master_prep_ai.services.rag.pipelines.llamaindex import storage as storage_module
    from master_prep_ai.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline

    storage_dir = tmp_path / "kb" / "version-1"
    storage_dir.mkdir(parents=True)
    (storage_dir / "docstore.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        LlamaIndexPipeline,
        "_configure_settings",
        lambda self: None,
    )
    monkeypatch.setattr(
        storage_module,
        "retrieve_nodes",
        lambda storage_dir, query, top_k=5: (_ for _ in ()).throw(
            TypeError("unsupported operand type(s) for *: 'NoneType' and 'float'")
        ),
    )

    pipeline = LlamaIndexPipeline(
        kb_base_dir=str(tmp_path),
        signature_provider=lambda: None,
    )

    result = await pipeline.search("what is this?", "kb")

    assert result["error_type"] == "invalid_embedding_index"
    assert result["needs_reindex"] is True
    assert "Re-index the knowledge base" in result["answer"]
    assert "unsupported operand" not in result["answer"]
