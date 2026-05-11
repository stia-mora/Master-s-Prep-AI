"""Embedding-signature helpers for RAG index version selection."""

from __future__ import annotations

import logging
from typing import Any

from master_prep_ai.services.rag.index_versioning import EmbeddingSignature

logger = logging.getLogger(__name__)


def signature_from_config(config: Any) -> EmbeddingSignature:
    """Build a stable RAG index signature from an embedding config object."""
    return EmbeddingSignature(
        binding=(getattr(config, "binding", "") or "").strip().lower(),
        model=(getattr(config, "model", "") or "").strip(),
        dimension=int(getattr(config, "dim", 0) or 0),
        base_url=(
            getattr(config, "effective_url", None)
            or getattr(config, "base_url", None)
            or ""
        ).strip(),
        api_version=(getattr(config, "api_version", "") or "").strip(),
    )


def signature_from_embedding_config() -> EmbeddingSignature | None:
    """Compute the signature for the currently-active embedding config."""
    try:
        from master_prep_ai.services.embedding import get_embedding_config
    except Exception:  # pragma: no cover - import error
        return None

    try:
        return signature_from_config(get_embedding_config())
    except Exception as exc:
        logger.debug(f"Cannot resolve embedding signature: {exc}")
        return None
