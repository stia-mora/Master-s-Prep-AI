#!/usr/bin/env python
"""Batch convert PDFs to Markdown with MinerU, chunking large PDFs for resumable runs."""

from __future__ import annotations

import argparse
import hashlib
import io
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter


IMAGE_MD_RE = re.compile(r"(!\[[^\]]*\]\()([^\)]+)(\))")
HTML_SRC_RE = re.compile(r"(\bsrc=[\"'])([^\"']+)([\"'])", re.IGNORECASE)
URL_SCHEMES = ("http://", "https://", "data:", "mailto:", "#")


class RunLogger:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, message: str) -> None:
        line = message.rstrip("\n")
        print(line, flush=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def block(self, title: str, text: str) -> None:
        if not text:
            return
        self.write(f"--- {title} ---")
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(text.rstrip("\n") + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert PDFs under a folder to Markdown with MinerU in resumable 20-page chunks."
    )
    parser.add_argument("--input-root", default=r".\test data", help="Folder to scan for PDF files.")
    parser.add_argument("--output-root", default=r".\mineru_markdown", help="Central output folder.")
    parser.add_argument("--chunk-pages", type=int, default=5, help="Pages per physical PDF chunk.")
    parser.add_argument("--backend", default="pipeline", help="MinerU backend.")
    parser.add_argument("--method", default="auto", choices=["auto", "txt", "ocr"], help="MinerU parse method.")
    parser.add_argument("--lang", default="ch", help="MinerU OCR language.")
    parser.add_argument(
        "--engine",
        default="auto",
        choices=["auto", "mineru", "markitdown", "pypdf"],
        help="Conversion engine. auto uses MinerU when available, then MarkItDown, then pypdf text extraction.",
    )
    parser.add_argument("--force", action="store_true", help="Rebuild outputs even when final Markdown exists.")
    parser.add_argument("--dry-run", action="store_true", help="Only print the PDF/chunk plan; do not write outputs.")
    parser.add_argument("--limit", type=int, default=0, help="Optional maximum number of PDFs to process, useful for smoke tests.")
    parser.add_argument("--mineru-bin", default="", help="Optional explicit path to mineru executable.")
    return parser.parse_args()


def resolve_mineru_bin(explicit: str = "") -> str:
    if explicit:
        return str(Path(explicit).expanduser().resolve())
    found = shutil.which("mineru")
    if found:
        return found
    env_dir = Path(sys.executable).resolve().parent
    candidate_dirs = [env_dir, env_dir / "Scripts"]
    for candidate_dir in candidate_dirs:
        for name in ("mineru.exe", "mineru"):
            candidate = candidate_dir / name
            if candidate.exists():
                return str(candidate)
    return "mineru"


def is_command_available(command: str) -> bool:
    command_path = Path(command)
    if command_path.exists():
        return True
    return shutil.which(command) is not None


def is_module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def safe_relative(path: Path, base: Path) -> Path:
    try:
        return path.relative_to(base)
    except ValueError:
        return Path(path.name)


def hash_pdf_id(pdf_path: Path, input_root: Path) -> str:
    rel = safe_relative(pdf_path, input_root).as_posix().casefold()
    digest = hashlib.sha1(rel.encode("utf-8", errors="replace")).hexdigest()
    return digest[:16]


def read_page_count(pdf_path: Path) -> int:
    return len(PdfReader(str(pdf_path)).pages)


def chunk_ranges(page_count: int, chunk_pages: int) -> list[tuple[int, int]]:
    return [(start, min(start + chunk_pages, page_count)) for start in range(0, page_count, chunk_pages)]


def make_pdf_metadata(pdf_path: Path, input_root: Path, pages: int, args: argparse.Namespace) -> dict[str, Any]:
    stat = pdf_path.stat()
    return {
        "source": str(pdf_path.resolve()),
        "relative_source": safe_relative(pdf_path, input_root).as_posix(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "pages": pages,
        "chunk_pages": args.chunk_pages,
        "backend": args.backend,
        "method": args.method,
        "lang": args.lang,
    }


def load_state(state_path: Path) -> dict[str, Any] | None:
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, state_path)


def reset_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def split_pdf(pdf_path: Path, chunk_pdf: Path, start: int, end: int) -> None:
    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    for page_index in range(start, end):
        writer.add_page(reader.pages[page_index])
    chunk_pdf.parent.mkdir(parents=True, exist_ok=True)
    with chunk_pdf.open("wb") as f:
        writer.write(f)


def run_mineru(
    mineru_bin: str,
    chunk_pdf: Path,
    chunk_output_root: Path,
    args: argparse.Namespace,
    logger: RunLogger,
) -> None:
    command = [
        mineru_bin,
        "-p",
        str(chunk_pdf),
        "-o",
        str(chunk_output_root),
        "-b",
        args.backend,
        "-m",
        args.method,
        "-l",
        args.lang,
    ]
    logger.write("Running MinerU: " + " ".join(f'"{x}"' if " " in x else x for x in command))
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("MINERU_LOG_LEVEL", "INFO")
    result = subprocess.run(
        command,
        cwd=str(Path.cwd()),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    logger.block("mineru stdout", result.stdout)
    logger.block("mineru stderr", result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"MinerU failed with exit code {result.returncode}")


def find_chunk_markdown(chunk_output_root: Path, chunk_stem: str) -> Path:
    md_files = sorted(chunk_output_root.rglob("*.md"), key=lambda p: (len(str(p)), str(p).casefold()))
    if not md_files:
        raise FileNotFoundError(f"MinerU produced no markdown under {chunk_output_root}")
    exact = [p for p in md_files if p.stem == chunk_stem]
    if len(exact) == 1:
        return exact[0]
    plain = [p for p in md_files if not p.stem.endswith(("_content_list", "_middle", "_model"))]
    if len(plain) == 1:
        return plain[0]
    if len(md_files) == 1:
        return md_files[0]
    raise RuntimeError("Expected one markdown file, found: " + ", ".join(str(p) for p in md_files))


def is_external_link(link: str) -> bool:
    stripped = link.strip()
    return stripped.startswith(URL_SCHEMES) or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", stripped) is not None


def split_link(link: str) -> tuple[str, str]:
    hash_pos = link.find("#")
    query_pos = link.find("?")
    positions = [pos for pos in (hash_pos, query_pos) if pos >= 0]
    if not positions:
        return link, ""
    pos = min(positions)
    return link[:pos], link[pos:]


def copy_linked_asset(link: str, md_file: Path, final_md: Path, asset_chunk_dir: Path) -> str:
    if is_external_link(link):
        return link
    raw_path, suffix = split_link(link.strip())
    if not raw_path:
        return link
    decoded_path = urllib.parse.unquote(raw_path).replace("/", os.sep)
    source = (md_file.parent / decoded_path).resolve()
    if not source.exists() or not source.is_file():
        return link
    relative_source = Path(decoded_path)
    if relative_source.is_absolute() or ".." in relative_source.parts:
        relative_source = Path(source.name)
    destination = asset_chunk_dir / relative_source
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    rel_to_md = os.path.relpath(destination, start=final_md.parent).replace(os.sep, "/")
    return rel_to_md + suffix


def copy_images_dir(md_file: Path, asset_chunk_dir: Path) -> None:
    images_dir = md_file.parent / "images"
    if images_dir.exists() and images_dir.is_dir():
        target = asset_chunk_dir / "images"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(images_dir, target)


def rewrite_markdown_assets(markdown: str, md_file: Path, final_md: Path, asset_chunk_dir: Path) -> str:
    def replace_md(match: re.Match[str]) -> str:
        return match.group(1) + copy_linked_asset(match.group(2), md_file, final_md, asset_chunk_dir) + match.group(3)

    def replace_src(match: re.Match[str]) -> str:
        return match.group(1) + copy_linked_asset(match.group(2), md_file, final_md, asset_chunk_dir) + match.group(3)

    rewritten = IMAGE_MD_RE.sub(replace_md, markdown)
    return HTML_SRC_RE.sub(replace_src, rewritten)


def append_chunk_to_partial(
    partial_md: Path,
    final_md: Path,
    source_md: Path,
    asset_dir: Path,
    chunk_index: int,
    start: int,
    end: int,
) -> None:
    partial_md.parent.mkdir(parents=True, exist_ok=True)
    asset_chunk_dir = asset_dir / f"chunk_{chunk_index:04d}"
    asset_chunk_dir.mkdir(parents=True, exist_ok=True)
    copy_images_dir(source_md, asset_chunk_dir)
    content = source_md.read_text(encoding="utf-8", errors="replace")
    content = rewrite_markdown_assets(content, source_md, final_md, asset_chunk_dir)
    header = f"\n\n<!-- chunk {chunk_index + 1:04d}, pages {start + 1}-{end} -->\n\n"
    with partial_md.open("a", encoding="utf-8") as f:
        if partial_md.stat().st_size > 0:
            f.write("\n\n")
        f.write(header)
        f.write(content.strip())
        f.write("\n")


def paths_for_pdf(pdf_path: Path, input_root: Path, output_root: Path) -> dict[str, Path]:
    pdf_id = hash_pdf_id(pdf_path, input_root)
    rel_pdf = safe_relative(pdf_path, input_root)
    rel_parent = rel_pdf.parent
    final_md = output_root / rel_parent / f"{pdf_path.stem}.md"
    return {
        "pdf_id": Path(pdf_id),
        "final_md": final_md,
        "partial_md": final_md.with_suffix(final_md.suffix + ".partial"),
        "asset_dir": output_root / "assets" / rel_parent / pdf_path.stem,
        "state_path": output_root / "state" / f"{pdf_id}.json",
        "work_dir": output_root / "work" / pdf_id,
    }


def ensure_resume_state(
    state_path: Path,
    partial_md: Path,
    metadata: dict[str, Any],
    ranges: list[tuple[int, int]],
) -> dict[str, Any]:
    existing = load_state(state_path)
    expected_chunks = [
        {"index": i, "start": start, "end": end, "status": "pending"}
        for i, (start, end) in enumerate(ranges)
    ]
    if existing and existing.get("metadata") == metadata and partial_md.exists():
        return existing
    if existing and existing.get("status") == "complete":
        return existing
    reset_path(partial_md)
    return {
        "status": "running",
        "metadata": metadata,
        "chunks": expected_chunks,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def completed_indexes(state: dict[str, Any]) -> set[int]:
    return {int(chunk["index"]) for chunk in state.get("chunks", []) if chunk.get("status") == "complete"}


def mark_chunk_complete(state: dict[str, Any], index: int) -> None:
    for chunk in state.get("chunks", []):
        if int(chunk["index"]) == index:
            chunk["status"] = "complete"
            chunk["completed_at"] = datetime.now().isoformat(timespec="seconds")
            break
    state["status"] = "running"
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")


def mark_pdf_complete(state: dict[str, Any], final_md: Path) -> None:
    state["status"] = "complete"
    state["final_markdown"] = str(final_md)
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")


def process_pdf(
    pdf_path: Path,
    input_root: Path,
    output_root: Path,
    mineru_bin: str,
    args: argparse.Namespace,
    logger: RunLogger,
) -> str:
    paths = paths_for_pdf(pdf_path, input_root, output_root)
    final_md = paths["final_md"]
    partial_md = paths["partial_md"]
    asset_dir = paths["asset_dir"]
    state_path = paths["state_path"]
    work_dir = paths["work_dir"]

    if final_md.exists() and not args.force:
        logger.write(f"SKIP existing: {pdf_path}")
        return "skipped"

    if args.force:
        for target in (final_md, partial_md, asset_dir, state_path, work_dir):
            reset_path(target)

    page_count = read_page_count(pdf_path)
    ranges = chunk_ranges(page_count, args.chunk_pages)
    metadata = make_pdf_metadata(pdf_path, input_root, page_count, args)
    state = ensure_resume_state(state_path, partial_md, metadata, ranges)

    final_md.parent.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)
    chunk_dir = work_dir / "chunks"
    mineru_work_root = work_dir / "mineru"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    mineru_work_root.mkdir(parents=True, exist_ok=True)

    logger.write(f"PROCESS {pdf_path} ({page_count} pages, {len(ranges)} chunks)")
    done = completed_indexes(state)

    for chunk_index, (start, end) in enumerate(ranges):
        if chunk_index in done:
            logger.write(f"  resume skip chunk {chunk_index + 1}/{len(ranges)} pages {start + 1}-{end}")
            continue
        chunk_stem = f"{pdf_path.stem}__chunk_{chunk_index + 1:04d}_p{start + 1:04d}-{end:04d}"
        chunk_pdf = chunk_dir / f"{chunk_stem}.pdf"
        chunk_output_root = mineru_work_root / f"chunk_{chunk_index + 1:04d}"
        reset_path(chunk_output_root)
        logger.write(f"  chunk {chunk_index + 1}/{len(ranges)} pages {start + 1}-{end}")
        split_pdf(pdf_path, chunk_pdf, start, end)
        run_mineru(mineru_bin, chunk_pdf, chunk_output_root, args, logger)
        chunk_md = find_chunk_markdown(chunk_output_root, chunk_stem)
        append_chunk_to_partial(partial_md, final_md, chunk_md, asset_dir, chunk_index, start, end)
        mark_chunk_complete(state, chunk_index)
        write_state(state_path, state)
        reset_path(chunk_pdf)
        reset_path(chunk_output_root)

    if len(completed_indexes(state)) != len(ranges):
        raise RuntimeError(f"Not all chunks completed for {pdf_path}")
    os.replace(partial_md, final_md)
    mark_pdf_complete(state, final_md)
    write_state(state_path, state)
    reset_path(work_dir)
    logger.write(f"DONE {final_md}")
    return "done"


def normalize_extracted_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    collapsed: list[str] = []
    blank_seen = False
    for line in lines:
        if not line.strip():
            if not blank_seen:
                collapsed.append("")
            blank_seen = True
            continue
        collapsed.append(line)
        blank_seen = False
    return "\n".join(collapsed).strip()


def process_pdf_with_pypdf(
    pdf_path: Path,
    input_root: Path,
    output_root: Path,
    args: argparse.Namespace,
    logger: RunLogger,
) -> str:
    paths = paths_for_pdf(pdf_path, input_root, output_root)
    final_md = paths["final_md"]
    state_path = paths["state_path"]

    if final_md.exists() and not args.force:
        logger.write(f"SKIP existing: {pdf_path}")
        return "skipped"

    if args.force:
        for target in (final_md, state_path):
            reset_path(target)

    reader = PdfReader(str(pdf_path))
    page_count = len(reader.pages)
    metadata = make_pdf_metadata(pdf_path, input_root, page_count, args)
    metadata["engine"] = "pypdf"

    logger.write(f"PROCESS {pdf_path} ({page_count} pages, pypdf text extraction)")
    final_md.parent.mkdir(parents=True, exist_ok=True)
    temp_md = final_md.with_suffix(final_md.suffix + ".tmp")

    pages_with_text = 0
    total_chars = 0
    with temp_md.open("w", encoding="utf-8", newline="\n") as f:
        f.write(f"# {pdf_path.stem}\n\n")
        f.write(f"<!-- source: {safe_relative(pdf_path, input_root).as_posix()} -->\n")
        f.write(f"<!-- pages: {page_count} -->\n")
        for page_number, page in enumerate(reader.pages, start=1):
            text = normalize_extracted_text(page.extract_text() or "")
            if text:
                pages_with_text += 1
                total_chars += len(text)
                f.write(f"\n\n<!-- page {page_number} -->\n\n")
                f.write(text)
            else:
                f.write(f"\n\n<!-- page {page_number}: no extractable text -->\n")
        f.write("\n")

    if total_chars == 0:
        temp_md.unlink(missing_ok=True)
        logger.write(f"FAILED {pdf_path}: no extractable text; OCR runtime such as MinerU is required")
        return "failed"

    os.replace(temp_md, final_md)
    state = {
        "status": "complete",
        "metadata": metadata,
        "final_markdown": str(final_md),
        "pages_with_text": pages_with_text,
        "total_chars": total_chars,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_state(state_path, state)
    logger.write(f"DONE {final_md} (pages_with_text={pages_with_text}, chars={total_chars})")
    return "done"


def process_pdf_with_markitdown(
    pdf_path: Path,
    input_root: Path,
    output_root: Path,
    args: argparse.Namespace,
    logger: RunLogger,
) -> str:
    paths = paths_for_pdf(pdf_path, input_root, output_root)
    final_md = paths["final_md"]
    state_path = paths["state_path"]

    if final_md.exists() and not args.force:
        logger.write(f"SKIP existing: {pdf_path}")
        return "skipped"

    if args.force:
        for target in (final_md, state_path):
            reset_path(target)

    from markitdown import MarkItDown

    page_count = read_page_count(pdf_path)
    metadata = make_pdf_metadata(pdf_path, input_root, page_count, args)
    metadata["engine"] = "markitdown"

    logger.write(f"PROCESS {pdf_path} ({page_count} pages, MarkItDown)")
    if os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI

        converter = MarkItDown(
            enable_plugins=True,
            llm_client=OpenAI(),
            llm_model=os.environ.get("MARKITDOWN_OCR_MODEL", "gpt-4o"),
        )
        logger.write("MarkItDown OCR plugin enabled")
    else:
        converter = MarkItDown()
        logger.write("MarkItDown OCR plugin skipped: OPENAI_API_KEY is not set")
    result = converter.convert(str(pdf_path))
    text = normalize_extracted_text(result.text_content or "")

    if not text:
        if os.environ.get("OPENAI_API_KEY"):
            logger.write("MarkItDown produced no text; rendering PDF pages for OCR")
            text = ocr_pdf_pages_with_llm(pdf_path, logger)
        else:
            logger.write(f"FAILED {pdf_path}: MarkItDown produced no text; set OPENAI_API_KEY to enable OCR for scanned PDFs")
            return "failed"

    if not text:
        logger.write(f"FAILED {pdf_path}: OCR produced no text")
        return "failed"

    final_md.parent.mkdir(parents=True, exist_ok=True)
    temp_md = final_md.with_suffix(final_md.suffix + ".tmp")
    with temp_md.open("w", encoding="utf-8", newline="\n") as f:
        f.write(f"# {pdf_path.stem}\n\n")
        f.write(f"<!-- source: {safe_relative(pdf_path, input_root).as_posix()} -->\n")
        f.write(f"<!-- pages: {page_count} -->\n")
        f.write("<!-- engine: markitdown -->\n\n")
        f.write(text)
        f.write("\n")
    os.replace(temp_md, final_md)

    state = {
        "status": "complete",
        "metadata": metadata,
        "final_markdown": str(final_md),
        "total_chars": len(text),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_state(state_path, state)
    logger.write(f"DONE {final_md} (chars={len(text)})")
    return "done"


def ocr_pdf_pages_with_llm(pdf_path: Path, logger: RunLogger) -> str:
    try:
        import fitz
        from markitdown_ocr import LLMVisionOCRService
        from openai import OpenAI
    except Exception as exc:
        logger.write(f"PDF page OCR unavailable: {exc}")
        return ""

    model = os.environ.get("MARKITDOWN_OCR_MODEL", "gpt-4o")
    service = LLMVisionOCRService(
        client=OpenAI(),
        model=model,
        default_prompt=(
            "Extract all readable text, math expressions, tables, and question numbers from this exam page. "
            "Return clean Markdown only. Preserve Chinese text, formulas, answer choices, and layout order. "
            "Do not add commentary."
        ),
    )
    doc = fitz.open(str(pdf_path))
    cache_dir = pdf_path.parent / ".ocr-cache" / pdf_path.stem
    cache_dir.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    for page_index in range(doc.page_count):
        cache_file = cache_dir / f"page_{page_index + 1:04d}.md"
        if cache_file.exists():
            page_text = cache_file.read_text(encoding="utf-8").strip()
            if page_text:
                parts.append(f"<!-- page {page_index + 1} -->\n\n{page_text}")
                logger.write(f"OCR page {page_index + 1}: cached {len(page_text)} chars")
                continue
        page = doc.load_page(page_index)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image_stream = io.BytesIO(pix.tobytes("png"))
        result = service.extract_text(image_stream)
        if result.error:
            logger.write(f"OCR page {page_index + 1} error: {result.error}")
        page_text = (result.text or "").strip()
        if page_text:
            cache_file.write_text(page_text, encoding="utf-8")
            parts.append(f"<!-- page {page_index + 1} -->\n\n{page_text}")
            logger.write(f"OCR page {page_index + 1}: {len(page_text)} chars")
        else:
            logger.write(f"OCR page {page_index + 1}: empty")
    doc.close()
    return "\n\n".join(parts).strip()


def main() -> int:
    args = parse_args()
    if args.chunk_pages <= 0:
        raise SystemExit("--chunk-pages must be greater than 0")

    input_root = Path(args.input_root).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    if not input_root.exists() or not input_root.is_dir():
        raise SystemExit(f"Input root does not exist or is not a directory: {input_root}")

    pdfs = sorted(input_root.rglob("*.pdf"), key=lambda p: str(p).casefold())
    if args.limit and args.limit > 0:
        pdfs = pdfs[: args.limit]

    if args.dry_run:
        print(f"Input root: {input_root}")
        print(f"Output root: {output_root}")
        print(f"Engine: {args.engine}")
        print(f"PDF count: {len(pdfs)}")
        total_chunks = 0
        for pdf in pdfs:
            pages = read_page_count(pdf)
            ranges = chunk_ranges(pages, args.chunk_pages)
            total_chunks += len(ranges)
            rel = safe_relative(pdf, input_root).as_posix()
            range_text = ", ".join(f"{start + 1}-{end}" for start, end in ranges)
            print(f"- {rel}: {pages} pages -> {len(ranges)} chunks [{range_text}]")
        print(f"Total chunks: {total_chunks}")
        return 0

    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = RunLogger(output_root / "logs" / f"run_{run_stamp}.log")
    mineru_bin = ""
    engine = args.engine
    if engine in ("auto", "mineru"):
        mineru_bin = resolve_mineru_bin(args.mineru_bin)
        if not is_command_available(mineru_bin):
            if engine == "mineru":
                logger.write(f"MinerU executable not found: {mineru_bin}")
                return 1
            engine = "markitdown" if is_module_available("markitdown") else "pypdf"
    if engine == "markitdown" and not is_module_available("markitdown"):
        logger.write("MarkItDown is not installed")
        return 1
    logger.write(f"Started at {datetime.now().isoformat(timespec='seconds')}")
    logger.write(f"Input root: {input_root}")
    logger.write(f"Output root: {output_root}")
    logger.write(f"Engine: {engine}")
    if mineru_bin:
        logger.write(f"MinerU executable: {mineru_bin}")
    logger.write(f"PDF count: {len(pdfs)}")

    counts = {"done": 0, "skipped": 0, "failed": 0}
    start_time = time.time()
    for pdf in pdfs:
        try:
            if engine == "pypdf":
                status = process_pdf_with_pypdf(pdf, input_root, output_root, args, logger)
            elif engine == "markitdown":
                status = process_pdf_with_markitdown(pdf, input_root, output_root, args, logger)
            else:
                status = process_pdf(pdf, input_root, output_root, mineru_bin, args, logger)
            counts[status] = counts.get(status, 0) + 1
        except Exception as exc:
            counts["failed"] += 1
            logger.write(f"FAILED {pdf}: {exc}")

    elapsed = time.time() - start_time
    logger.write(
        "Summary: "
        + ", ".join(f"{key}={value}" for key, value in counts.items())
        + f", elapsed_seconds={elapsed:.1f}"
    )
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
