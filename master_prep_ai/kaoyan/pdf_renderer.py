"""PDF rendering for Kaoyan offline practice sheets."""

from __future__ import annotations

from functools import lru_cache
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class PdfRenderError(RuntimeError):
    """Raised when the local LaTeX toolchain cannot render a practice PDF."""


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_INVALID_RE = re.compile("[\uffff\ufffe]")
_MATH_RE = re.compile(
    r"(\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)|(?<!\\)\$(?!\$).*?(?<!\\)\$)",
    re.S,
)
_BLANK_RE = re.compile(r"(?:(?:\\\\|\\)?_){3,}|_{3,}")
_BLANK_TEX = r"\underline{\hspace{2.8cm}}"
_TEXT_MATH_SYMBOLS = {
    "≤": r"$\leq$",
    "≥": r"$\geq$",
    "∞": r"$\infty$",
    "→": r"$\to$",
    "←": r"$\leftarrow$",
    "↔": r"$\leftrightarrow$",
    "≠": r"$\ne$",
    "≈": r"$\approx$",
    "±": r"$\pm$",
    "×": r"$\times$",
    "÷": r"$\div$",
    "∑": r"$\sum$",
    "∫": r"$\int$",
    "√": r"$\sqrt{\ }$",
    "π": r"$\pi$",
    "α": r"$\alpha$",
    "β": r"$\beta$",
    "γ": r"$\gamma$",
    "δ": r"$\delta$",
    "θ": r"$\theta$",
    "λ": r"$\lambda$",
}
_MATH_SYMBOLS = {key: value.strip("$") for key, value in _TEXT_MATH_SYMBOLS.items()}
_MATH_SYMBOLS.update({"’": "'", "′": "'", "−": "-", "，": ",", "。": "."})


_DEFAULT_LATEX_PACKAGES = (
    "ctex",
    "geometry",
    "enumitem",
    "fontspec",
    "iftex",
    "amsmath",
    "amsfonts",
    "mathtools",
    "unicode-math",
    "lm",
    "fandol",
)


def render_practice_pdf(payload: dict[str, Any]) -> bytes:
    """Render a practice PDF with XeLaTeX and return the PDF bytes."""
    xelatex = _resolve_xelatex()
    _prepare_latex_for_render(xelatex)
    tex_source = build_practice_tex(payload)
    with tempfile.TemporaryDirectory(prefix="kaoyan_pdf_") as tmp:
        tmp_path = Path(tmp)
        tex_path = tmp_path / "practice.tex"
        pdf_path = tmp_path / "practice.pdf"
        tex_path.write_text(tex_source, encoding="utf-8")
        try:
            completed = subprocess.run(
                _build_xelatex_command(xelatex, tex_path.name),
                cwd=tmp_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_latex_render_timeout(),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PdfRenderError(
                "XeLaTeX PDF generation timed out. MiKTeX may still be downloading packages; "
                "try again after package installation finishes or increase KAOYAN_LATEX_TIMEOUT."
            ) from exc
        except OSError as exc:
            raise PdfRenderError(f"Unable to run XeLaTeX: {exc}") from exc
        if completed.returncode != 0 or not pdf_path.exists():
            log_path = tmp_path / "practice.log"
            log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else completed.stderr
            raise PdfRenderError("XeLaTeX PDF generation failed: " + _summarize_log(log_text))
        return pdf_path.read_bytes()


def ensure_latex_packages() -> dict[str, Any]:
    """Install the LaTeX packages needed by Kaoyan PDFs when MiKTeX is available."""
    xelatex = _resolve_xelatex()
    packages = _configured_latex_packages()
    result: dict[str, Any] = {
        "xelatex": xelatex,
        "auto_install": _latex_auto_install_enabled(),
        "packages": packages,
        "installed": [],
        "failed": [],
        "skipped": [],
    }
    if not result["auto_install"]:
        result["skipped"].append("KAOYAN_LATEX_AUTO_INSTALL is disabled")
        return result
    if not _is_miktex_xelatex(xelatex):
        result["skipped"].append("Automatic package installation is only supported for MiKTeX")
        return result
    mpm = _resolve_mpm(xelatex)
    if not mpm:
        result["skipped"].append("MiKTeX package manager (mpm) was not found")
        return result
    result["mpm"] = mpm
    for package in packages:
        try:
            completed = subprocess.run(
                [mpm, f"--install={package}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_latex_install_timeout(),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["failed"].append({"package": package, "error": str(exc)})
            continue
        if completed.returncode == 0:
            result["installed"].append(package)
        else:
            result["failed"].append({"package": package, "error": _summarize_process(completed)})
    return result


@lru_cache(maxsize=4)
def _prepare_latex_for_render(xelatex: str) -> None:
    if _latex_auto_install_enabled():
        ensure_latex_packages()


def _build_xelatex_command(xelatex: str, tex_name: str) -> list[str]:
    command = [xelatex]
    if _latex_auto_install_enabled() and _is_miktex_xelatex(xelatex):
        command.append("--enable-installer")
    command.extend(["-interaction=nonstopmode", "-halt-on-error", tex_name])
    return command


def _configured_latex_packages() -> list[str]:
    configured = os.environ.get("KAOYAN_LATEX_PACKAGES")
    if not configured:
        return list(_DEFAULT_LATEX_PACKAGES)
    return [item.strip() for item in configured.split(",") if item.strip()]


def _latex_auto_install_enabled() -> bool:
    value = os.environ.get("KAOYAN_LATEX_AUTO_INSTALL")
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _latex_render_timeout() -> int:
    return _positive_int_env("KAOYAN_LATEX_TIMEOUT", 180)


def _latex_install_timeout() -> int:
    return _positive_int_env("KAOYAN_LATEX_INSTALL_TIMEOUT", 300)


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


@lru_cache(maxsize=8)
def _is_miktex_xelatex(xelatex: str) -> bool:
    try:
        completed = subprocess.run(
            [xelatex, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    output = f"{completed.stdout}\n{completed.stderr}"
    return "MiKTeX" in output


def _resolve_mpm(xelatex: str) -> str | None:
    found = shutil.which("mpm")
    if found:
        return found
    xelatex_path = Path(xelatex)
    candidates = [xelatex_path.with_name("mpm.exe"), xelatex_path.with_name("mpm")]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _summarize_process(completed: subprocess.CompletedProcess[str]) -> str:
    text = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    return _summarize_log(text) or f"exit code {completed.returncode}"


def build_practice_tex(payload: dict[str, Any]) -> str:
    title = _latex_escape(str(payload.get("title") or "\u8003\u7814\u7ebf\u4e0b\u7ec3\u4e60\u9898\u5355"))
    label_total = "\u5171"
    label_questions = "\u9898\u76ee"
    label_answers = "\u53c2\u8003\u7b54\u6848\u4e0e\u89e3\u6790"
    label_question_count = "\u9898"
    label_difficulty = "\u96be\u5ea6"
    label_analysis = "\u89e3\u6790"
    no_questions = "\u6682\u65e0\u9898\u76ee"
    no_answer = "\u6682\u65e0\u7b54\u6848"
    questions = list(payload.get("questions") or [])
    question_blocks = []
    answer_blocks = []
    for index, question in enumerate(questions, start=1):
        qtype = _latex_escape(str(question.get("question_type") or ""))
        difficulty = _latex_escape(str(question.get("difficulty_level") or ""))
        stem = _markdown_to_tex(question.get("stem_without_options") or question.get("stem") or "")
        answer = _markdown_to_tex(question.get("answer") or "\u6682\u65e0\u7b54\u6848")
        analysis = _markdown_to_tex(question.get("analysis") or "")
        question_blocks.append(
            "\\item "
            f"\\textbf{{[{qtype}] {label_difficulty} {difficulty}}}\\\\[4pt]\n"
            f"{stem}\n"
        )
        answer_text = f"\\item {answer}"
        if analysis:
            answer_text += f"\\\\[4pt]\\textit{{{label_analysis}}}: {analysis}"
        answer_blocks.append(answer_text)
    questions_tex = "\n".join(question_blocks) or f"\\item {no_questions}"
    answers_tex = "\n".join(answer_blocks) or f"\\item {no_answer}"
    return f"""
\\documentclass[UTF8,a4paper,12pt]{{ctexart}}
\\usepackage{{geometry}}
\\usepackage{{enumitem}}
\\usepackage{{fontspec}}
\\usepackage{{iftex}}
\\usepackage{{amsmath}}
\\usepackage{{amssymb}}
\\usepackage{{mathtools}}
\\usepackage{{unicode-math}}
\\geometry{{left=2.2cm,right=2.2cm,top=2.2cm,bottom=2.2cm}}
\\IfFontExistsTF{{Microsoft YaHei}}{{\\setCJKmainfont{{Microsoft YaHei}}}}{{\\IfFontExistsTF{{SimSun}}{{\\setCJKmainfont{{SimSun}}}}{{\\IfFontExistsTF{{Noto Serif CJK SC}}{{\\setCJKmainfont{{Noto Serif CJK SC}}}}{{\\IfFontExistsTF{{FandolSong}}{{\\setCJKmainfont{{FandolSong}}}}{{}}}}}}}}
\\IfFontExistsTF{{Latin Modern Math}}{{\\setmathfont{{Latin Modern Math}}}}{{}}
\\setlist[enumerate]{{leftmargin=*, itemsep=1.1em}}
\\linespread{{1.18}}
\\pagestyle{{plain}}
\\begin{{document}}
\\begin{{center}}
  {{\\Large\\bfseries {title}}}\\\\[0.4em]
  {{\\small {label_total} {len(questions)} {label_question_count}}}
\\end{{center}}

\\section*{{{label_questions}}}
\\begin{{enumerate}}
{questions_tex}
\\end{{enumerate}}

\\newpage
\\section*{{{label_answers}}}
\\begin{{enumerate}}
{answers_tex}
\\end{{enumerate}}
\\end{{document}}
""".strip()


def _resolve_xelatex() -> str:
    configured = os.environ.get("KAOYAN_XELATEX_PATH")
    if configured:
        path = Path(configured)
        if path.exists():
            return str(path)
        raise PdfRenderError(f"KAOYAN_XELATEX_PATH does not exist: {configured}")
    found = shutil.which("xelatex")
    if not found:
        raise PdfRenderError("XeLaTeX was not found. Install MiKTeX or set KAOYAN_XELATEX_PATH.")
    return found


def _plain_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"```.*?```", lambda match: match.group(0).strip("`"), text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = re.sub(r"[*`#]+", "", text)
    text = _INVALID_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _markdown_to_tex(value: Any) -> str:
    text = _plain_text(value)
    if not text:
        return ""
    parts: list[str] = []
    cursor = 0
    for match in _MATH_RE.finditer(text):
        if match.start() > cursor:
            parts.append(_latex_escape_text(text[cursor : match.start()]))
        parts.append(_normalize_math_segment(match.group(0)))
        cursor = match.end()
    if cursor < len(text):
        parts.append(_latex_escape_text(text[cursor:]))
    return "".join(parts)


def _normalize_math_segment(segment: str) -> str:
    if segment.startswith("$$") and segment.endswith("$$"):
        body = segment[2:-2]
        return "\\[\n" + _normalize_math_body(body) + "\n\\]"
    if segment.startswith("\\[") and segment.endswith("\\]"):
        body = segment[2:-2]
        return "\\[\n" + _normalize_math_body(body) + "\n\\]"
    if segment.startswith("\\(") and segment.endswith("\\)"):
        body = segment[2:-2]
        return r"\(" + _normalize_math_body(body) + r"\)"
    if segment.startswith("$") and segment.endswith("$"):
        body = segment[1:-1]
        return "$" + _normalize_math_body(body) + "$"
    return _latex_escape_text(segment)


def _normalize_math_body(value: str) -> str:
    text = _INVALID_RE.sub("", _CONTROL_RE.sub("", str(value or "")))
    text = _normalize_blanks(text)
    for raw, replacement in _MATH_SYMBOLS.items():
        text = text.replace(raw, replacement)
    return text.strip()


def _latex_escape_text(value: str) -> str:
    value = _normalize_blanks(str(value or ""))
    parts: list[str] = []
    buffer: list[str] = []
    cursor = 0
    for match in re.finditer(re.escape(_BLANK_TEX), value):
        if match.start() > cursor:
            parts.append(_latex_escape_text_chunk(value[cursor : match.start()]))
        parts.append(_BLANK_TEX)
        cursor = match.end()
    if cursor < len(value):
        parts.append(_latex_escape_text_chunk(value[cursor:]))
    return "".join(parts)


def _latex_escape_text_chunk(value: str) -> str:
    parts: list[str] = []
    buffer: list[str] = []
    for char in str(value or ""):
        replacement = _TEXT_MATH_SYMBOLS.get(char)
        if replacement:
            if buffer:
                parts.append(_latex_escape("".join(buffer)))
                buffer = []
            parts.append(replacement)
        else:
            buffer.append(char)
    if buffer:
        parts.append(_latex_escape("".join(buffer)))
    return "".join(parts)


def _normalize_blanks(value: str) -> str:
    return _BLANK_RE.sub(lambda _match: _BLANK_TEX, str(value or ""))


def _latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    escaped = "".join(replacements.get(char, char) for char in value)
    return escaped.replace("\n", r"\\ " + "\n")


def _summarize_log(log_text: str) -> str:
    lines = [line.strip() for line in str(log_text or "").splitlines() if line.strip()]
    important = [line for line in lines if line.startswith("!") or "Error" in line or "not found" in line]
    selected = important[:6] or lines[-6:]
    return " ".join(selected)[:1200] or "unknown LaTeX error"
