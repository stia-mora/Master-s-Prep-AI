"""Prepare local LaTeX packages used by Kaoyan PDF generation."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from master_prep_ai.kaoyan.pdf_renderer import PdfRenderError, ensure_latex_packages


def main() -> int:
    try:
        result = ensure_latex_packages()
    except PdfRenderError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    ok = not result.get("failed")
    print(json.dumps({"ok": ok, **result}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())