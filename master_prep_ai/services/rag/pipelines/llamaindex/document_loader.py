"""Document loading for the LlamaIndex RAG pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from llama_index.core import Document

from master_prep_ai.logging import get_logger
from master_prep_ai.services.rag.file_routing import FileTypeRouter


class LlamaIndexDocumentLoader:
    """Convert source files into LlamaIndex ``Document`` objects."""

    def __init__(self, logger=None) -> None:
        self.logger = logger or get_logger("LlamaIndexDocumentLoader")

    async def load(self, file_paths: Iterable[str]) -> list[Document]:
        documents: list[Document] = []
        classification = FileTypeRouter.classify_files(list(file_paths))

        for file_path_str in classification.parser_files:
            file_path = Path(file_path_str)
            self.logger.info(f"Parsing PDF: {file_path.name}")
            text = self._extract_pdf_text(file_path)
            self._append_if_nonempty(documents, file_path, text)

        for file_path_str in classification.text_files:
            file_path = Path(file_path_str)
            self.logger.info(f"Parsing text: {file_path.name}")
            text = await FileTypeRouter.read_text_file(str(file_path))
            self._append_if_nonempty(documents, file_path, text)

        for file_path_str in classification.unsupported:
            self.logger.warning(f"Skipped unsupported file: {Path(file_path_str).name}")

        return documents

    def _append_if_nonempty(
        self, documents: list[Document], file_path: Path, text: str
    ) -> None:
        if text.strip():
            documents.append(
                Document(
                    text=text,
                    metadata={
                        "file_name": file_path.name,
                        "file_path": str(file_path),
                    },
                )
            )
            self.logger.info(f"Loaded: {file_path.name} ({len(text)} chars)")
        else:
            self.logger.warning(f"Skipped empty document: {file_path.name}")

    def _extract_pdf_text(self, file_path: Path) -> str:
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(file_path)
            texts = [page.get_text() for page in doc]
            doc.close()
            return "\n\n".join(texts)
        except ImportError:
            self.logger.warning("PyMuPDF not installed. Cannot extract PDF text.")
            return ""
        except Exception as exc:
            self.logger.error(f"Failed to extract PDF text: {exc}")
            return ""
