from __future__ import annotations

from master_prep_ai.kaoyan import pdf_renderer


def test_xelatex_command_enables_miktex_installer(monkeypatch) -> None:
    monkeypatch.delenv("KAOYAN_LATEX_AUTO_INSTALL", raising=False)
    monkeypatch.setattr(pdf_renderer, "_is_miktex_xelatex", lambda _path: True)

    command = pdf_renderer._build_xelatex_command("xelatex", "practice.tex")

    assert command == [
        "xelatex",
        "--enable-installer",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "practice.tex",
    ]


def test_xelatex_command_respects_disabled_auto_install(monkeypatch) -> None:
    monkeypatch.setenv("KAOYAN_LATEX_AUTO_INSTALL", "false")
    monkeypatch.setattr(pdf_renderer, "_is_miktex_xelatex", lambda _path: True)

    command = pdf_renderer._build_xelatex_command("xelatex", "practice.tex")

    assert "--enable-installer" not in command


def test_latex_package_list_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("KAOYAN_LATEX_PACKAGES", "ctex, unicode-math,  mathtools ")

    assert pdf_renderer._configured_latex_packages() == ["ctex", "unicode-math", "mathtools"]


def test_latex_timeout_defaults_and_overrides(monkeypatch) -> None:
    monkeypatch.delenv("KAOYAN_LATEX_TIMEOUT", raising=False)
    assert pdf_renderer._latex_render_timeout() == 180

    monkeypatch.setenv("KAOYAN_LATEX_TIMEOUT", "240")
    assert pdf_renderer._latex_render_timeout() == 240