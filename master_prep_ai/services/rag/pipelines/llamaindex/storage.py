"""Storage operations for the LlamaIndex RAG pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any

from llama_index.core import StorageContext, VectorStoreIndex, load_index_from_storage

from master_prep_ai.services.rag.index_versioning import (
    EmbeddingSignature,
    find_matching_version,
    resolve_storage_dir_for_read,
    resolve_storage_dir_for_write,
)


@dataclass(frozen=True)
class AddStoragePlan:
    existing_storage: Path | None
    storage_dir: Path


def cleanup_failed_version_dir(storage_dir: Path) -> bool:
    """Remove an empty flat version dir created by a failed indexing attempt."""
    if not storage_dir.is_dir() or not storage_dir.name.startswith("version-"):
        return False
    storage_empty = not any(child for child in storage_dir.iterdir() if child.name != "meta.json")
    meta_path = storage_dir / "meta.json"
    if storage_empty and not meta_path.exists():
        shutil.rmtree(storage_dir, ignore_errors=True)
        return True
    return False


def resolve_add_storage_plan(
    kb_dir: Path, signature: EmbeddingSignature | None
) -> AddStoragePlan:
    """Choose existing/new storage dirs for incremental adds."""
    matching_version = find_matching_version(kb_dir, signature) if signature is not None else None
    existing_storage = Path(str(matching_version["storage_path"])) if matching_version else None

    if matching_version and matching_version.get("layout") == "flat":
        return AddStoragePlan(existing_storage=existing_storage, storage_dir=existing_storage)

    if matching_version:
        return AddStoragePlan(
            existing_storage=existing_storage,
            storage_dir=resolve_storage_dir_for_write(kb_dir, signature),
        )

    fallback_storage = resolve_storage_dir_for_read(kb_dir, signature)
    existing_storage = fallback_storage
    fallback_is_flat = (
        fallback_storage is not None
        and fallback_storage.parent == kb_dir
        and fallback_storage.name.startswith("version-")
    )
    storage_dir = (
        fallback_storage
        if fallback_is_flat
        else resolve_storage_dir_for_write(kb_dir, signature)
    )
    return AddStoragePlan(existing_storage=existing_storage, storage_dir=storage_dir)


def create_index(documents: list[Any], storage_dir: Path, *, show_progress: bool = True) -> int:
    index = VectorStoreIndex.from_documents(documents, show_progress=show_progress)
    index.storage_context.persist(persist_dir=str(storage_dir))
    return len(documents)


def insert_documents(
    existing_storage: Path, storage_dir: Path, documents: list[Any]
) -> int:
    storage_context = StorageContext.from_defaults(persist_dir=str(existing_storage))
    index = load_index_from_storage(storage_context)
    for document in documents:
        index.insert(document)
    index.storage_context.persist(persist_dir=str(storage_dir))
    return len(documents)


def retrieve_nodes(storage_dir: Path, query: str, *, top_k: int = 5) -> list[Any]:
    storage_context = StorageContext.from_defaults(persist_dir=str(storage_dir))
    index = load_index_from_storage(storage_context)
    retriever = index.as_retriever(similarity_top_k=top_k)
    return retriever.retrieve(query)


def delete_kb_dir(kb_dir: Path) -> bool:
    if kb_dir.exists():
        shutil.rmtree(kb_dir)
        return True
    return False
