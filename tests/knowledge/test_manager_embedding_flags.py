from __future__ import annotations

import json
from pathlib import Path

import pytest

from master_prep_ai.knowledge.manager import KnowledgeBaseManager


class _Signature:
    def __init__(self, sig_hash: str = "active-signature") -> None:
        self._hash = sig_hash

    def hash(self) -> str:
        return self._hash


def _patch_active_embedding(monkeypatch: pytest.MonkeyPatch, sig_hash: str = "active-signature") -> None:
    from master_prep_ai.knowledge import manager as manager_module
    from master_prep_ai.services.rag import embedding_signature

    monkeypatch.setattr(manager_module, "_get_embedding_fingerprint", lambda: ("embed-active", 4096))
    monkeypatch.setattr(
        embedding_signature,
        "signature_from_embedding_config",
        lambda: _Signature(sig_hash),
    )


def test_in_progress_empty_version_dir_does_not_mark_new_kb_reindex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_embedding(monkeypatch)

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(
        name="new-kb",
        status="processing",
        progress={
            "stage": "processing_documents",
            "message": "Embedding chunks",
            "percent": 20,
        },
    )

    # The LlamaIndex writer allocates version-N before it has persisted docstore.json.
    (tmp_path / "new-kb" / "version-1").mkdir(parents=True)

    reloaded = KnowledgeBaseManager(base_dir=str(tmp_path))
    entry = reloaded.config["knowledge_bases"]["new-kb"]
    assert entry.get("needs_reindex", False) is False
    assert entry.get("embedding_mismatch", False) is False

    info = reloaded.get_info("new-kb")
    assert info["status"] == "processing"
    assert info["statistics"]["needs_reindex"] is False


def test_ready_version_without_active_signature_marks_reindex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_embedding(monkeypatch, sig_hash="active-signature")

    kb_dir = tmp_path / "old-kb"
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"signature": "old-signature", "version": "version-1"}),
        encoding="utf-8",
    )

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.config.setdefault("knowledge_bases", {})["old-kb"] = {
        "path": "old-kb",
        "rag_provider": "llamaindex",
    }
    manager._save_config()

    reloaded = KnowledgeBaseManager(base_dir=str(tmp_path))
    entry = reloaded.config["knowledge_bases"]["old-kb"]
    assert entry["needs_reindex"] is True
    assert entry["embedding_mismatch"] is True

