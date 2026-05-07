"""
Multimodal Message Utilities
=============================

Converts plain-text messages + image attachments into the multimodal
message format expected by vision-capable LLMs.

Supports:
- OpenAI-compatible API (content array with image_url blocks)
- Anthropic API (content array with image source blocks)
"""

from __future__ import annotations

import base64 as _b64
from dataclasses import dataclass
import logging
from typing import Any
from urllib.parse import unquote, urlparse

from .capabilities import supports_vision, supports_vision_url

logger = logging.getLogger(__name__)

MIME_FALLBACK = "image/png"
_LOCAL_ATTACHMENT_PREFIX = "/api/attachments/"


@dataclass
class MultimodalResult:
    """Result of multimodal message preparation."""

    messages: list[dict[str, Any]]
    vision_supported: bool
    images_stripped: bool
    # Number of url-only images we had to drop because the provider requires
    # base64 and we couldn't resolve the URL locally (external URL or missing
    # file). The caller can surface this to the user.
    url_images_dropped: int = 0


def _guess_mime_type(filename: str, fallback: str = MIME_FALLBACK) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "svg": "image/svg+xml",
    }.get(ext, fallback)


def _build_openai_image_part(
    *,
    base64_data: str,
    mime_type: str,
    url: str = "",
) -> dict[str, Any]:
    if url:
        image_url = url
    else:
        image_url = f"data:{mime_type};base64,{base64_data}"
    return {"type": "image_url", "image_url": {"url": image_url}}


def _build_anthropic_image_part(
    *,
    base64_data: str,
    mime_type: str,
) -> dict[str, Any]:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": mime_type,
            "data": base64_data,
        },
    }


def _image_placeholder(url: str = "", filename: str = "") -> str:
    label = filename or url
    return f"[image: {label}]" if label else "[image omitted]"


def _resolve_local_attachment_url(url: str) -> tuple[str, str] | None:
    """Resolve a ``/api/attachments/<sid>/<aid>/<name>`` URL to (base64, mime).

    External URLs (http/https) are not fetched here — that would be sync
    network IO inside an async-friendly path and a security footgun. Returns
    None for anything we cannot resolve from the local AttachmentStore.
    """
    if not url:
        return None
    parsed = urlparse(url)
    path = parsed.path or url
    if not path.startswith(_LOCAL_ATTACHMENT_PREFIX):
        return None
    parts = path[len(_LOCAL_ATTACHMENT_PREFIX) :].split("/")
    if len(parts) != 3:
        return None
    sid, aid, name = (unquote(p) for p in parts)
    try:
        # Local import to avoid an import-time cycle: storage already imports
        # capabilities indirectly via path service.
        from master_prep_ai.services.storage import get_attachment_store

        store = get_attachment_store()
        resolve = getattr(store, "resolve_path", None)
        if resolve is None:
            return None
        target = resolve(session_id=sid, attachment_id=aid, filename=name)
        if target is None:
            return None
        data = target.read_bytes()
    except Exception as exc:
        logger.warning("failed to resolve local attachment %s: %s", url, exc)
        return None
    return _b64.b64encode(data).decode("ascii"), _guess_mime_type(name)


def prepare_multimodal_messages(
    messages: list[dict[str, Any]],
    attachments: list[Any] | None,
    binding: str = "openai",
    model: str | None = None,
) -> MultimodalResult:
    """
    Inject image attachments into the last user message.

    If the model supports vision the last user message ``content`` field is
    converted from a plain string into a content-parts array that includes
    both the original text and the image(s).

    If the model does **not** support vision, the messages are returned
    unchanged and ``images_stripped`` is set to ``True`` so the caller
    can emit a warning to the user.

    Args:
        messages: The OpenAI-style messages list (may be mutated).
        attachments: ``Attachment`` objects from ``UnifiedContext``.
        binding: Provider binding (``"openai"``, ``"anthropic"``, …).
        model: Model name used for capability lookup.

    Returns:
        A ``MultimodalResult`` with the (potentially modified) messages.
    """
    if not attachments:
        return MultimodalResult(
            messages=messages,
            vision_supported=True,
            images_stripped=False,
        )

    image_attachments = [a for a in attachments if getattr(a, "type", "") == "image"]
    if not image_attachments:
        return MultimodalResult(
            messages=messages,
            vision_supported=True,
            images_stripped=False,
        )

    vision_ok = supports_vision(binding, model)

    if not vision_ok:
        logger.info(
            "Model %s/%s does not support vision – stripping %d image(s)",
            binding,
            model,
            len(image_attachments),
        )
        return MultimodalResult(
            messages=messages,
            vision_supported=False,
            images_stripped=True,
        )

    last_user_idx = _find_last_user_message(messages)
    if last_user_idx is None:
        return MultimodalResult(
            messages=messages,
            vision_supported=True,
            images_stripped=False,
        )

    is_anthropic = (binding or "").lower() in ("anthropic", "claude")
    # Anthropic adapter only emits base64 source blocks, and providers like
    # Moonshot reject URL form outright. In both cases url-only attachments
    # must be resolved to bytes before injection.
    require_base64 = is_anthropic or not supports_vision_url(binding, model)
    dropped = _inject_images(
        messages,
        last_user_idx,
        image_attachments,
        anthropic=is_anthropic,
        require_base64=require_base64,
    )

    return MultimodalResult(
        messages=messages,
        vision_supported=True,
        images_stripped=False,
        url_images_dropped=dropped,
    )


def _find_last_user_message(messages: list[dict[str, Any]]) -> int | None:
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            return i
    return None


def _inject_images(
    messages: list[dict[str, Any]],
    user_idx: int,
    image_attachments: list[Any],
    *,
    anthropic: bool = False,
    require_base64: bool = False,
) -> int:
    """Inject image parts into the user message at *user_idx*.

    Returns the count of url-only attachments we had to drop because the
    provider needs base64 and the URL could not be resolved locally.
    """
    msg = messages[user_idx]
    original_content = msg.get("content", "")

    if isinstance(original_content, str):
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": original_content}]
    elif isinstance(original_content, list):
        content_parts = list(original_content)
    else:
        content_parts = [{"type": "text", "text": str(original_content)}]

    dropped = 0
    for att in image_attachments:
        mime = getattr(att, "mime_type", "") or _guess_mime_type(
            getattr(att, "filename", "image.png")
        )
        b64 = getattr(att, "base64", "") or ""
        url = getattr(att, "url", "") or ""

        if not b64 and not url:
            continue

        # If the provider needs base64 and the attachment only carries a URL,
        # resolve it from the local AttachmentStore. External URLs cannot be
        # resolved synchronously here and are dropped with a warning.
        if not b64 and require_base64 and url:
            resolved = _resolve_local_attachment_url(url)
            if resolved is not None:
                b64, resolved_mime = resolved
                mime = mime or resolved_mime
            else:
                logger.warning(
                    "Dropping url-only image %r: provider requires base64 but"
                    " URL is not a local attachment-store path",
                    url,
                )
                dropped += 1
                continue

        if anthropic:
            if not b64:
                logger.warning("Anthropic image part requires base64; dropping %r", url)
                dropped += 1
                continue
            content_parts.append(_build_anthropic_image_part(base64_data=b64, mime_type=mime))
        else:
            if b64:
                # Always prefer inline base64 when available — providers that
                # reject URL form (Moonshot) accept this; providers that
                # accept URLs accept this too.
                content_parts.append(
                    _build_openai_image_part(base64_data=b64, mime_type=mime)
                )
            else:
                content_parts.append(
                    _build_openai_image_part(base64_data="", mime_type=mime, url=url)
                )

    messages[user_idx] = {**msg, "content": content_parts}
    return dropped


def has_image_parts(messages: list[dict[str, Any]]) -> bool:
    """Return True when any message content contains image blocks."""
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") in {"image_url", "image"}:
                return True
    return False


def strip_image_parts(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace image blocks with text placeholders for fallback retries."""
    stripped: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            stripped.append(dict(msg))
            continue
        new_content: list[dict[str, Any]] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") in {"image_url", "image"}:
                image_url = item.get("image_url") or {}
                url = image_url.get("url", "") if isinstance(image_url, dict) else ""
                meta = item.get("_meta") or {}
                filename = ""
                if isinstance(meta, dict):
                    filename = str(meta.get("path") or meta.get("filename") or "")
                new_content.append({"type": "text", "text": _image_placeholder(url, filename)})
            else:
                new_content.append(item)
        stripped.append({**msg, "content": new_content})
    return stripped


__all__ = [
    "MultimodalResult",
    "has_image_parts",
    "prepare_multimodal_messages",
    "strip_image_parts",
]
