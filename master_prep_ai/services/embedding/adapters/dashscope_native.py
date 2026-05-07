"""Aliyun DashScope MultiModalEmbedding adapter.

Uses the ``dashscope`` Python SDK (``dashscope.MultiModalEmbedding.call``)
because DashScope's native API shape (`input.contents=[{text|image|video}]` +
`parameters={dimension, enable_fusion}`) does not match the OpenAI contract.
The SDK call is synchronous, so we run it in a thread pool to keep the rest
of the embedding stack non-blocking.
"""

from __future__ import annotations

import asyncio
from http import HTTPStatus
import logging
from typing import Any, Dict, List

from .base import BaseEmbeddingAdapter, EmbeddingRequest, EmbeddingResponse

logger = logging.getLogger(__name__)


class DashScopeMultiModalEmbeddingAdapter(BaseEmbeddingAdapter):
    """Adapter for Aliyun DashScope (Bailian) multimodal embedding."""

    MODELS_INFO = {
        "qwen3-vl-embedding": {
            "default": 2560,
            "dimensions": [256, 512, 768, 1024, 1536, 2048, 2560],
            "multimodal": True,
        },
        "multimodal-embedding-v1": {
            "default": 1536,
            "dimensions": [],
            "multimodal": True,
        },
        "text-embedding-v3": {
            "default": 1024,
            "dimensions": [],
            "multimodal": False,
        },
        "text-embedding-v4": {
            "default": 1024,
            "dimensions": [],
            "multimodal": False,
        },
    }

    def _build_contents(self, request: EmbeddingRequest) -> List[Dict[str, Any]]:
        if request.contents:
            return [item for item in request.contents if isinstance(item, dict)]
        return [{"text": text} for text in request.texts]

    def _build_parameters(self, request: EmbeddingRequest) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        dim_value = request.dimensions or self.dimensions
        if dim_value:
            params["dimension"] = dim_value
        if request.enable_fusion is not None:
            params["enable_fusion"] = bool(request.enable_fusion)
        return params

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        try:
            from dashscope import MultiModalEmbedding
        except ImportError as exc:
            raise ImportError(
                "dashscope SDK not installed. Run `pip install dashscope` "
                "(or add to your project deps) to enable Aliyun DashScope."
            ) from exc

        contents = self._build_contents(request)
        parameters = self._build_parameters(request)
        model_name = request.model or self.model

        logger.debug(
            "Calling dashscope.MultiModalEmbedding.call "
            f"(model={model_name}, items={len(contents)}, params={parameters})"
        )

        # SDK call is sync — run in worker thread to avoid blocking the loop.
        # IMPORTANT: the dashscope SDK takes a flat list for `input`
        # (e.g. ``input=[{"text": "..."}]``) and internally wraps it as
        # ``{"contents": [...]}`` before POSTing to the REST endpoint. Do NOT
        # pass ``{"contents": contents}`` here — that produces a double-wrap
        # and the API responds with HTTP 400 ("Input should be a valid list").
        resp = await asyncio.to_thread(
            MultiModalEmbedding.call,
            api_key=self.api_key,
            model=model_name,
            input=contents,
            **parameters,
        )

        self._raise_on_error(resp, model_name)
        return self._parse_response(resp, model_name, request)

    def _raise_on_error(self, resp: Any, model_name: str) -> None:
        status_code = getattr(resp, "status_code", None)
        if status_code is None or status_code == HTTPStatus.OK:
            return
        code = getattr(resp, "code", "") or ""
        message = getattr(resp, "message", "") or ""
        request_id = getattr(resp, "request_id", "") or ""
        raise RuntimeError(
            f"DashScope MultiModalEmbedding call failed: "
            f"status={status_code}, code={code}, message={message}, "
            f"model={model_name}, request_id={request_id}"
        )

    def _parse_response(
        self, resp: Any, model_name: str, request: EmbeddingRequest
    ) -> EmbeddingResponse:
        output = getattr(resp, "output", None)
        if output is None:
            raise ValueError(f"DashScope response missing `output` (request_id={getattr(resp, 'request_id', '')})")

        # `output` is dict-like in the SDK.
        if isinstance(output, dict):
            raw = output.get("embeddings") or []
        else:
            raw = getattr(output, "embeddings", None) or []

        embeddings: List[List[float]] = []
        for item in raw:
            if isinstance(item, dict):
                vec = item.get("embedding")
            else:
                vec = getattr(item, "embedding", None)
            if vec is None:
                continue
            embeddings.append(list(vec))

        if not embeddings:
            raise ValueError(
                "DashScope response parsed successfully but no embedding vectors were returned."
            )

        usage = getattr(resp, "usage", {}) or {}
        if not isinstance(usage, dict):
            usage = {
                k: getattr(usage, k, None)
                for k in ("input_tokens", "output_tokens", "total_tokens")
                if hasattr(usage, k)
            }

        actual_dims = len(embeddings[0]) if embeddings else 0
        logger.info(
            f"Successfully generated {len(embeddings)} DashScope embeddings "
            f"(model: {model_name}, dimensions: {actual_dims}, "
            f"fusion={request.enable_fusion})"
        )

        return EmbeddingResponse(
            embeddings=embeddings,
            model=model_name,
            dimensions=actual_dims,
            usage=usage,
        )

    def get_model_info(self) -> Dict[str, Any]:
        info = self.MODELS_INFO.get(self.model or "", {})
        return {
            "model": self.model,
            "dimensions": info.get("default", self.dimensions),
            "supported_dimensions": info.get("dimensions", []),
            "supports_variable_dimensions": bool(info.get("dimensions")),
            "multimodal": bool(info.get("multimodal", False)),
            "provider": "aliyun",
        }
