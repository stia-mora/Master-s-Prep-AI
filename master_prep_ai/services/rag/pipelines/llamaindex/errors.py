"""Error normalization for LlamaIndex-backed RAG retrieval."""

from __future__ import annotations

from typing import Any, Dict


def search_error_result(query: str, exc: Exception) -> Dict[str, Any]:
    """Convert retrieval failures into actionable tool output."""
    message = str(exc)
    lower = message.lower()

    if "embedding provider returned invalid" in lower:
        return {
            "query": query,
            "answer": (
                "RAG search failed because the embedding provider returned an "
                f"invalid query vector: {message}"
            ),
            "content": "",
            "provider": "llamaindex",
            "error": message,
            "error_type": "invalid_embedding_provider_response",
        }

    null_vector_similarity_error = (
        "unsupported operand type(s) for *" in lower
        and "nonetype" in lower
        and "float" in lower
    )
    shape_vector_error = "inhomogeneous shape" in lower or (
        "shapes" in lower and "not aligned" in lower
    )
    if null_vector_similarity_error or shape_vector_error:
        return {
            "query": query,
            "answer": (
                "RAG search failed because this knowledge base index contains "
                "invalid embedding vectors. Re-index the knowledge base with "
                "the current embedding provider/model before querying it again."
            ),
            "content": "",
            "provider": "llamaindex",
            "error": message,
            "error_type": "invalid_embedding_index",
            "needs_reindex": True,
        }

    return {
        "query": query,
        "answer": f"Search failed: {message}",
        "content": "",
        "provider": "llamaindex",
        "error": message,
    }
