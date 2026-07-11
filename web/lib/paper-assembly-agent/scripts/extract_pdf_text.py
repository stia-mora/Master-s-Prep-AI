import base64
import os
import sys
import tempfile
from pathlib import Path


def load_dotenv() -> None:
    current = Path(__file__).resolve()
    for parent in [current.parent, *current.parents]:
        env_file = parent / ".env"
        if not env_file.exists():
            continue
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return


def markitdown_text(pdf_path: Path) -> str:
    try:
        from markitdown import MarkItDown
    except Exception:
        return ""

    try:
        result = MarkItDown().convert(str(pdf_path))
        return (getattr(result, "text_content", "") or "").strip()
    except Exception:
        return ""


def pypdf_text(pdf_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        return ""

    pages = []
    try:
        reader = PdfReader(str(pdf_path))
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"\n\n<!-- page:{index} -->\n{text.strip()}")
    except Exception:
        return ""
    return "\n".join(pages).strip()


def ocr_with_llm(pdf_path: Path) -> str:
    if not os.environ.get("OPENAI_API_KEY"):
        return ""
    try:
        import fitz
        from markitdown_ocr import LLMVisionOCRService
        from openai import OpenAI
    except Exception:
        return ""

    base_url = os.environ.get("OPENAI_BASE_URL") or None
    model = os.environ.get("MARKITDOWN_OCR_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-4o"
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=base_url)
    service = LLMVisionOCRService(client=client, model=model)
    chunks = []

    with tempfile.TemporaryDirectory(prefix="paper-assembly-ocr-") as tmp:
        tmp_dir = Path(tmp)
        document = fitz.open(str(pdf_path))
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image_path = tmp_dir / f"page_{page_index + 1:04d}.png"
            pixmap.save(str(image_path))
            image_bytes = image_path.read_bytes()
            image_b64 = base64.b64encode(image_bytes).decode("ascii")
            try:
                text = service(image_b64, mime_type="image/png")
            except TypeError:
                text = service(image_bytes, mime_type="image/png")
            text = str(text or "").strip()
            if text:
                chunks.append(f"\n\n<!-- page:{page_index + 1} -->\n{text}")

    return "\n".join(chunks).strip()


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: extract_pdf_text.py <pdf>", file=sys.stderr)
        return 2

    load_dotenv()
    pdf_path = Path(sys.argv[1])
    text = markitdown_text(pdf_path) or pypdf_text(pdf_path)
    if len(text.strip()) < 80:
        text = ocr_with_llm(pdf_path) or text

    sys.stdout.write(text.strip())
    return 0 if text.strip() else 1


if __name__ == "__main__":
    raise SystemExit(main())
