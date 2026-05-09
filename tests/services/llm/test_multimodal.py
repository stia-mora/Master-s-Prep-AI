"""Tests for multimodal message preparation, including the
``vision_url_supported`` capability bit (Plan B).
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from master_prep_ai.services.llm import multimodal as mm
from master_prep_ai.services.llm.multimodal import prepare_multimodal_messages
from master_prep_ai.services.storage import attachment_store


def _msgs() -> list[dict]:
    return [{"role": "user", "content": "describe"}]


def _img_part_url(message: dict) -> str:
    parts = message["content"]
    img = next(p for p in parts if p.get("type") == "image_url")
    return img["image_url"]["url"]


def test_openai_compat_passes_url_through() -> None:
    """OpenAI-compatible providers (default vision_url_supported=True) accept
    URL-form image_url blocks unchanged."""
    att = SimpleNamespace(type="image", url="https://example.com/cat.png", base64="")
    result = prepare_multimodal_messages(
        _msgs(), [att], binding="openai", model="gpt-4o"
    )
    assert result.images_stripped is False
    assert result.url_images_dropped == 0
    assert _img_part_url(result.messages[0]) == "https://example.com/cat.png"


def test_openai_compat_prefers_base64_when_both_present() -> None:
    """When base64 is set we always inline it — works for everyone."""
    att = SimpleNamespace(
        type="image",
        url="https://example.com/cat.png",
        base64="QUJD",  # "ABC"
        mime_type="image/png",
    )
    result = prepare_multimodal_messages(
        _msgs(), [att], binding="openai", model="gpt-4o"
    )
    url = _img_part_url(result.messages[0])
    assert url.startswith("data:image/png;base64,QUJD")


def test_moonshot_kimi_drops_external_url_only_attachment(caplog) -> None:
    """Moonshot rejects URL-form image_url; an external url-only attachment
    cannot be resolved locally and must be dropped."""
    att = SimpleNamespace(type="image", url="https://example.com/cat.png", base64="")
    with caplog.at_level("WARNING"):
        result = prepare_multimodal_messages(
            _msgs(), [att], binding="moonshot", model="kimi-k2.6"
        )
    # Vision is supported (k2.6 is a vision model), but the url couldn't be
    # inlined → image part is omitted, drop counter increments.
    assert result.vision_supported is True
    assert result.images_stripped is False
    assert result.url_images_dropped == 1
    parts = result.messages[0]["content"]
    assert not any(p.get("type") == "image_url" for p in parts)


def test_moonshot_kimi_resolves_local_attachment_url(tmp_path, monkeypatch) -> None:
    """A ``/api/attachments/...`` URL is read from the AttachmentStore and
    re-encoded as inline base64 before being sent to Moonshot."""
    monkeypatch.setenv("CHAT_ATTACHMENT_DIR", str(tmp_path))
    attachment_store.reset_attachment_store()

    sid, aid, name = "sess1", "att1", "cat.png"
    raw_bytes = b"\x89PNG\r\n\x1a\nFAKE"
    session_dir = tmp_path / sid
    session_dir.mkdir(parents=True)
    (session_dir / f"{aid}_{name}").write_bytes(raw_bytes)

    url = f"/api/attachments/{quote(sid)}/{quote(aid)}/{quote(name)}"
    att = SimpleNamespace(type="image", url=url, base64="")

    try:
        result = prepare_multimodal_messages(
            _msgs(), [att], binding="moonshot", model="kimi-k2.6"
        )
    finally:
        attachment_store.reset_attachment_store()

    assert result.url_images_dropped == 0
    inlined = _img_part_url(result.messages[0])
    expected_b64 = base64.b64encode(raw_bytes).decode("ascii")
    assert inlined == f"data:image/png;base64,{expected_b64}"


def test_anthropic_url_only_attachment_is_dropped_not_sent_empty(caplog) -> None:
    """Previously the Anthropic path silently emitted an empty base64 source.
    Now url-only attachments without local resolution are dropped instead."""
    att = SimpleNamespace(type="image", url="https://example.com/cat.png", base64="")
    with caplog.at_level("WARNING"):
        result = prepare_multimodal_messages(
            _msgs(), [att], binding="anthropic", model="claude-3-5-sonnet"
        )
    assert result.url_images_dropped == 1
    parts = result.messages[0]["content"]
    # No "image" block with empty data leaked through
    for p in parts:
        if p.get("type") == "image":
            data = p.get("source", {}).get("data", "")
            assert data, "Anthropic image part must not have empty base64"


def test_text_only_moonshot_model_strips_images() -> None:
    """A plain Moonshot text model still falls through the supports_vision
    gate and strips images entirely, unaffected by vision_url_supported."""
    att = SimpleNamespace(type="image", base64="QUJD", mime_type="image/png")
    result = prepare_multimodal_messages(
        _msgs(), [att], binding="moonshot", model="moonshot-v1-8k"
    )
    assert result.images_stripped is True
    assert result.vision_supported is False
