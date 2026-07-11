import sys
from pathlib import Path

from pypdf import PdfReader


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: extract_pdf_text.py <pdf>", file=sys.stderr)
        return 2

    pdf_path = Path(sys.argv[1])
    reader = PdfReader(str(pdf_path))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as error:
            text = f"[第 {index} 页文字提取失败：{error}]"
        if text.strip():
            pages.append(f"\n\n<!-- page:{index} -->\n{text.strip()}")

    sys.stdout.write("\n".join(pages))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
