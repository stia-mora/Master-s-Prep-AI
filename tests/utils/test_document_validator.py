from __future__ import annotations

from master_prep_ai.services.rag.file_routing import FileTypeRouter
from master_prep_ai.utils.document_validator import DocumentValidator


def test_validate_upload_safety_preserves_unicode_and_lowercases_extension() -> None:
    safe_name = DocumentValidator.validate_upload_safety(
        "中文资料/数学 讲义#1(最终版).PDF",
        1024,
        allowed_extensions=FileTypeRouter.get_supported_extensions(),
    )

    assert safe_name == "数学 讲义#1(最终版).pdf"


def test_validate_upload_safety_strips_windows_path_components() -> None:
    safe_name = DocumentValidator.validate_upload_safety(
        r"C:\Users\frank\资料\报告.MD",
        128,
        allowed_extensions=FileTypeRouter.get_supported_extensions(),
    )

    assert safe_name == "报告.md"
