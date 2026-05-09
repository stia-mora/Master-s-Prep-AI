"""Backward-compatible re-export of shared prompt language helpers."""

from master_prep_ai.services.prompt.language import (
    append_language_directive,
    language_directive,
    language_label,
    normalize_language,
)

__all__ = [
    "append_language_directive",
    "language_directive",
    "language_label",
    "normalize_language",
]
