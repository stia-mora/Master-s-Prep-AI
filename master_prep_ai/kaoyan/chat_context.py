"""Build Master Prep AI chat/RAG context from kaoyan content records."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import logging
import re
from typing import Any, Literal

from master_prep_ai.auth import get_current_user_id
from master_prep_ai.knowledge.manager import KnowledgeBaseManager
from master_prep_ai.services.config import PROJECT_ROOT
from master_prep_ai.services.rag.service import RAGService
from master_prep_ai.services.session import get_sqlite_session_store

from .content_store import KaoyanContentStore

SourceType = Literal["knowledge", "question"]
KB_BASE_DIR = PROJECT_ROOT / "data" / "knowledge_bases"
QUESTION_BANK_SESSION_ID = "kaoyan_question_bank"
logger = logging.getLogger(__name__)


def _clip(value: Any, limit: int = 6000) -> str:
    text = "" if value is None else str(value).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...(truncated; ask for more if needed)"


def _compact_list(items: list[dict[str, Any]] | None, limit: int = 8) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for item in (items or [])[:limit]:
        compacted.append({key: _clip(value, 1200) if isinstance(value, str) else value for key, value in item.items()})
    return compacted


def _question_text(question: dict[str, Any]) -> str:
    parts = [f"type: {question.get('question_type') or 'unknown'}", f"difficulty: {question.get('difficulty_level') or '-'}"]
    stem = _markdown_text(question.get("stem") or question.get("stem_without_options"), 5000)
    if stem:
        parts.append(f"stem:\n{stem}")
    options = question.get("options") or []
    if options:
        option_text = "\n".join(f"{item.get('label')}. {_markdown_text(item.get('content'), 1200)}" for item in options)
        parts.append(f"options:\n{option_text}")
    answer = _markdown_text(question.get("answer"), 1200)
    if answer:
        parts.append(f"standard answer:\n{answer}")
    analysis = _markdown_text(question.get("analysis"), 2500)
    if analysis:
        parts.append(f"standard analysis:\n{analysis}")
    return "\n\n".join(parts)


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _markdown_text(value: Any, limit: int = 12000) -> str:
    """Normalize content extracted from SQLite/OCR into previewable Markdown."""
    text = _clip(value, limit)
    if not text:
        return ""
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\\\\([A-Za-z])", r"\\\1", text)
    text = text.replace("\\\\(", "\\(").replace("\\\\)", "\\)")
    text = text.replace("\\\\[", "\\[").replace("\\\\]", "\\]")
    return text.strip()


def _clean_display_text(value: Any, limit: int = 24) -> str:
    text = _markdown_text(value, 2000) if value is not None else ""
    if not text:
        return ""
    text = re.sub(r"#references\s*\"citation\"", " ", text)
    text = re.sub(r"\$+", " ", text)
    text = re.sub(r"\\(?:left|right|frac|sqrt|lim|sum|int|to|infty|cdots|operatorname|begin|end|mathrm|text)\b", " ", text)
    text = re.sub(r"[{}\[\]`*_>#|]", " ", text)
    text = re.sub(r"(?:^|\s)[\(\uFF08]?[A-D][\)\uFF09][\s\u3001.\uFF0E:\uFF1A]*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:^|\s)\d+[.\u3001\)\uFF09]\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:\uFF0C\u3002\uFF1B\uFF1A\u3001")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _knowledge_display_name(knowledge: dict[str, Any]) -> str:
    for key in ["knowledge_name", "section", "chapter", "full_path", "knowledge_id"]:
        value = _clean_display_text(knowledge.get(key), 24)
        if value:
            return value
    return "\u9ad8\u6570\u77e5\u8bc6\u70b9"


def _scoped_kb_display_metadata(payload: dict[str, Any], kb_name: str) -> dict[str, str]:
    source_type = _safe_text(payload.get("source_type"))
    source_id = _safe_text(payload.get("source_id"))
    knowledge = payload.get("knowledge") or {}
    if not isinstance(knowledge, dict):
        knowledge = {}
    knowledge_name = _knowledge_display_name(knowledge)
    if source_type == "question":
        question = payload.get("question") or {}
        if not isinstance(question, dict):
            question = {}
        stem = question.get("stem_without_options") or question.get("stem") or question.get("analysis") or source_id
        summary = _clean_display_text(stem, 24) or "\u8003\u7814\u6570\u5b66\u9898"
        display_name = f"\u9898\u76ee\uff5c{knowledge_name}\uff5c{summary}"
        return {
            "display_name": display_name,
            "short_name": summary,
            "source_label": "\u9898\u76ee\u89e3\u6790",
            "source_summary": summary,
            "debug_name": kb_name,
        }
    summary = knowledge_name
    return {
        "display_name": f"\u77e5\u8bc6\u70b9\uff5c{summary}",
        "short_name": summary,
        "source_label": "\u77e5\u8bc6\u70b9\u89e3\u6790",
        "source_summary": summary,
        "debug_name": kb_name,
    }

def _records_markdown(items: list[dict[str, Any]] | None, heading_key: str = "") -> str:
    lines: list[str] = []
    for index, item in enumerate(items or [], start=1):
        if not isinstance(item, dict):
            continue
        title = _safe_text(
            item.get(heading_key)
            or item.get("formula_name")
            or item.get("mistake_id")
            or item.get("card_id")
            or item.get("question_id")
            or f"item {index}"
        )
        lines.append(f"### {index}. {title}")
        for key, value in item.items():
            if value in (None, "", [], {}):
                continue
            if key == heading_key:
                continue
            label = key.replace("_", " ")
            if isinstance(value, str):
                lines.extend([f"**{label}**", _markdown_text(value, 2500), ""])
            else:
                lines.append(f"**{label}**: {value}")
        lines.append("")
    return "\n".join(lines).strip()


def _normalize_rag_search_result(
    *,
    kb_name: str,
    query: str,
    search_result: dict[str, Any],
) -> dict[str, Any]:
    answer = search_result.get("answer") or search_result.get("content") or ""
    raw_sources = search_result.get("sources") or search_result.get("results") or search_result.get("source_nodes") or []
    contexts: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for index, item in enumerate(raw_sources):
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("chunk_id") or item.get("id") or item.get("source") or f"source_{index + 1}")
        title = str(item.get("title") or item.get("file_name") or item.get("source") or source_id)
        snippet = _clip(item.get("content") or item.get("snippet") or item.get("text") or "", 700)
        score_raw = item.get("score")
        try:
            score = float(score_raw) if score_raw not in (None, "") else 0.0
        except (TypeError, ValueError):
            score = 0.0
        context = {
            "id": source_id,
            "title": title,
            "snippet": snippet,
            "score": score,
            "source_type": item.get("source_type") or "rag",
            "source_id": source_id,
            "metadata": {
                "source": item.get("source", ""),
                "page": item.get("page", ""),
                "kb_name": kb_name,
            },
        }
        contexts.append(context)
        sources.append(
            {
                "id": source_id,
                "title": title,
                "source_type": context["source_type"],
                "source_id": source_id,
                "score": score,
                "path": item.get("source") or "",
            }
        )
    status = "needs_reindex" if search_result.get("needs_reindex") else "success"
    if not answer and not contexts:
        status = "empty"
    return {
        "kb_name": kb_name,
        "query": query,
        "status": status,
        "answer": answer,
        "contexts": contexts,
        "sources": sources,
        "results": contexts,
        "raw": search_result,
    }


class KaoyanChatContextService:
    """Turn a kaoyan knowledge point or question into a scoped RAG chat entry."""

    def __init__(self, content_store: KaoyanContentStore, user_id: str | None = None) -> None:
        self.content_store = content_store
        self.user_id = str(user_id or get_current_user_id() or "local-user")
        safe_user = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in self.user_id)
        self.kb_base_dir = PROJECT_ROOT / "data" / "users" / safe_user / "knowledge_bases"

    async def build_context(self, source_type: SourceType, source_id: str, intent: str = "explain") -> dict[str, Any] | None:
        if source_type == "knowledge":
            result = self._knowledge_context(source_id, intent)
        elif source_type == "question":
            result = self._question_context(source_id, intent)
        else:
            return None
        if result is None:
            return None
        rag = await self._ensure_scoped_kb(result)
        result["rag"] = rag
        if source_type == "question":
            question_entry = await self._sync_question_bank_entry(result)
            if question_entry:
                result["question_entry"] = question_entry
        if rag.get("ready"):
            result["initial_message"] = self._rag_prompt(result["title"], result["context_payload"], str(rag["kb_name"]))
        return result

    async def query_rag(
        self,
        kb_name: str | None,
        query: str,
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        kb = str(kb_name or "").strip()
        if not kb:
            return self.content_store.query_rag(query, top_k=top_k, filters=filters)
        base = {"kb_name": kb, "query": str(query), "contexts": [], "sources": [], "results": []}
        try:
            search_result = await RAGService(kb_base_dir=str(self.kb_base_dir)).search(query=str(query), kb_name=kb, top_k=top_k)
        except Exception as exc:
            return {
                **base,
                "status": "fallback",
                "answer": "",
                "fallback": "RAG search is unavailable; use embedded kaoyan context instead.",
                "error": str(exc),
            }
        return _normalize_rag_search_result(kb_name=kb, query=str(query), search_result=search_result)

    def _knowledge_context(self, knowledge_id: str, intent: str) -> dict[str, Any] | None:
        detail = self.content_store.get_knowledge(knowledge_id, question_limit=8)
        if detail is None:
            return None
        knowledge = detail.get("knowledge") or {}
        title = f"Kaoyan knowledge explanation: {knowledge.get('knowledge_name') or knowledge_id}"
        payload = {
            "source_type": "knowledge",
            "source_id": knowledge_id,
            "intent": intent,
            "knowledge": knowledge,
            "lecture_markdown": _clip(knowledge.get("raw_markdown"), 12000),
            "formulas": _compact_list(detail.get("formulas"), 12),
            "mistakes": _compact_list(detail.get("mistakes"), 12),
            "review_cards": _compact_list(detail.get("review_cards"), 10),
            "sample_questions": _compact_list(detail.get("questions"), 8),
        }
        return {"title": title, "initial_message": self._embedded_knowledge_prompt(title, payload), "context_payload": payload}

    def _question_context(self, question_id: str, intent: str) -> dict[str, Any] | None:
        question = self.content_store.get_question(question_id)
        if question is None:
            return None
        knowledge_id = str(question.get("knowledge_id") or "")
        knowledge_detail = self.content_store.get_knowledge(knowledge_id, question_limit=4) if knowledge_id else None
        knowledge = (knowledge_detail or {}).get("knowledge") or {}
        payload = {
            "source_type": "question",
            "source_id": question_id,
            "intent": intent,
            "question": question,
            "knowledge": knowledge,
            "lecture_markdown": _clip(knowledge.get("raw_markdown"), 8000),
            "formulas": _compact_list((knowledge_detail or {}).get("formulas"), 10),
            "mistakes": _compact_list((knowledge_detail or {}).get("mistakes"), 10),
            "review_cards": _compact_list((knowledge_detail or {}).get("review_cards"), 6),
        }
        title = f"Kaoyan question explanation: {question_id}"
        return {"title": title, "initial_message": self._embedded_question_prompt(title, payload), "context_payload": payload}

    async def _ensure_question_bank_session(self, store: Any) -> str:
        """Create the virtual kaoyan question-bank chat session if needed."""
        session_id = QUESTION_BANK_SESSION_ID
        existing = await store.get_session(session_id, self.user_id)
        if existing:
            return session_id
        try:
            await store.create_session(title="\u8003\u7814\u52a9\u624b\u9898\u5e93", session_id=session_id, user_id=self.user_id)
            return session_id
        except Exception as exc:
            # Session ids are global in older local SQLite files. If another
            # user already owns the stable id, fall back to a deterministic
            # per-user id while keeping the visible title unchanged.
            fallback_id = f"{QUESTION_BANK_SESSION_ID}_{hashlib.sha1(self.user_id.encode('utf-8')).hexdigest()[:10]}"
            fallback_existing = await store.get_session(fallback_id, self.user_id)
            if fallback_existing:
                return fallback_id
            try:
                await store.create_session(title="\u8003\u7814\u52a9\u624b\u9898\u5e93", session_id=fallback_id, user_id=self.user_id)
                return fallback_id
            except Exception:
                logger.warning("Failed to create kaoyan question-bank session: %s", exc, exc_info=True)
                raise

    async def _sync_question_bank_entry(self, result: dict[str, Any]) -> dict[str, Any] | None:
        """Expose kaoyan questions in the existing chat question notebook."""
        payload = result.get("context_payload") or {}
        question = payload.get("question") or {}
        if not isinstance(question, dict):
            return None
        question_id = _safe_text(question.get("question_id") or payload.get("source_id"))
        if not question_id:
            return None
        options: dict[str, str] = {}
        for item in question.get("options") or []:
            if not isinstance(item, dict):
                continue
            label = _safe_text(item.get("label"))
            content = _safe_text(item.get("content"))
            if label or content:
                options[label or str(len(options) + 1)] = content
        entry_payload = {
            "session_id": QUESTION_BANK_SESSION_ID,
            "question_id": question_id,
            "question": _safe_text(question.get("stem_without_options") or question.get("stem")),
            "question_type": _safe_text(question.get("question_type")),
            "options": options,
            "correct_answer": _safe_text(question.get("answer")),
            "explanation": _safe_text(question.get("analysis")),
            "difficulty": _safe_text(question.get("difficulty_level")),
            "user_answer": "",
            "is_correct": False,
        }
        try:
            store = get_sqlite_session_store()
            session_id = await self._ensure_question_bank_session(store)
            entry_payload["session_id"] = session_id
            await store.upsert_notebook_entries(session_id, [entry_payload])
            entry = await store.find_notebook_entry(session_id, question_id)
            if not entry:
                return None
            return {"id": entry.get("id"), "question_id": entry.get("question_id")}
        except Exception as exc:
            logger.warning("Failed to sync kaoyan question into notebook: %s", exc, exc_info=True)
            return None

    def _write_scoped_kb_metadata(self, kb_name: str, result: dict[str, Any], display_meta: dict[str, str]) -> None:
        payload = result["context_payload"]
        source_type = _safe_text(payload.get("source_type"))
        source_id = _safe_text(payload.get("source_id"))
        kb_dir = self.kb_base_dir / kb_name
        kb_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = kb_dir / "metadata.json"
        existing: dict[str, Any] = {}
        if metadata_path.exists():
            try:
                loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing = loaded
            except Exception:
                existing = {}
        metadata = {
            **existing,
            "name": kb_name,
            "description": f"Kaoyan scoped RAG for {source_type}:{source_id}",
            "source_type": source_type,
            "source_id": source_id,
            "created_at": existing.get("created_at") or datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "rag_provider": existing.get("rag_provider") or "llamaindex",
            "needs_reindex": False,
            **display_meta,
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        self._sync_scoped_kb_config_metadata(kb_name, metadata)

    def _sync_scoped_kb_config_metadata(self, kb_name: str, metadata: dict[str, Any]) -> None:
        config_path = self.kb_base_dir / "kb_config.json"
        config: dict[str, Any] = {"knowledge_bases": {}}
        if config_path.exists():
            try:
                loaded = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    config = loaded
            except Exception:
                config = {"knowledge_bases": {}}
        knowledge_bases = config.setdefault("knowledge_bases", {})
        entry = knowledge_bases.setdefault(kb_name, {"path": kb_name})
        for key in [
            "description",
            "source_type",
            "source_id",
            "display_name",
            "short_name",
            "source_label",
            "source_summary",
            "debug_name",
            "created_at",
            "last_updated",
            "rag_provider",
            "needs_reindex",
        ]:
            if key in metadata and metadata[key] is not None:
                target_key = "updated_at" if key == "last_updated" else key
                entry[target_key] = metadata[key]
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _ensure_scoped_kb(self, result: dict[str, Any]) -> dict[str, Any]:
        payload = result["context_payload"]
        source_type = _safe_text(payload.get("source_type"))
        source_id = _safe_text(payload.get("source_id"))
        digest = hashlib.sha1(self._payload_markdown(result).encode("utf-8")).hexdigest()[:12]
        safe_user = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in self.user_id)[:24]
        kb_name = f"kaoyan_{safe_user}_{source_type}_{digest}"
        display_meta = _scoped_kb_display_metadata(payload, kb_name)
        rag_result = {
            "kb_name": kb_name,
            "display_name": display_meta.get("display_name"),
            "short_name": display_meta.get("short_name"),
        }
        manager = KnowledgeBaseManager(base_dir=str(self.kb_base_dir))
        status = manager.get_kb_status(kb_name)
        if status and status.get("status") == "ready":
            self._write_scoped_kb_metadata(kb_name, result, display_meta)
            return {**rag_result, "ready": True, "status": "ready", "message": "Reused scoped kaoyan RAG knowledge base"}

        kb_dir = self.kb_base_dir / kb_name
        raw_dir = kb_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        file_path = raw_dir / f"{source_type}_{source_id}.md"
        file_path.write_text(self._payload_markdown(result), encoding="utf-8")
        self._write_scoped_kb_metadata(kb_name, result, display_meta)
        manager.update_kb_status(kb_name, "initializing", {"stage": "initializing", "message": "Building kaoyan scoped RAG index", "percent": 10})
        try:
            success = await RAGService(kb_base_dir=str(self.kb_base_dir)).initialize(kb_name=kb_name, file_paths=[str(file_path)])
            if not success:
                raise RuntimeError("RAG pipeline returned failure")
            manager.update_kb_status(kb_name, "ready", {"stage": "completed", "message": "Kaoyan scoped RAG ready", "percent": 100, "timestamp": datetime.now().isoformat()})
            return {**rag_result, "ready": True, "status": "ready", "message": "Built scoped kaoyan RAG knowledge base"}
        except Exception as exc:
            manager.update_kb_status(kb_name, "error", {"stage": "error", "message": str(exc), "percent": 0, "timestamp": datetime.now().isoformat()})
            return {**rag_result, "ready": False, "status": "error", "message": f"RAG build failed; falling back to embedded context: {exc}"}

    def _payload_markdown(self, result: dict[str, Any]) -> str:
        payload = result["context_payload"]
        lines = [
            f"# {result['title']}",
            "",
            f"source_type: {payload.get('source_type')}",
            f"source_id: {payload.get('source_id')}",
            "",
        ]
        knowledge = payload.get("knowledge") or {}
        if isinstance(knowledge, dict) and knowledge:
            lines.append("## Knowledge point")
            for key in ["knowledge_id", "knowledge_name", "full_path", "chapter", "section", "importance_level", "is_core"]:
                value = knowledge.get(key)
                if value not in (None, ""):
                    lines.append(f"- **{key.replace('_', ' ')}**: {value}")
            lines.append("")
        question = payload.get("question")
        if isinstance(question, dict):
            lines.extend(["## Question", _question_text(question), ""])
        lecture = _markdown_text(payload.get("lecture_markdown"), 16000)
        if lecture:
            lines.extend(["## Lecture markdown", lecture, ""])
        for title, key, heading in [
            ("Formulas", "formulas", "formula_name"),
            ("Common mistakes", "mistakes", "mistake_id"),
            ("Review cards", "review_cards", "card_id"),
            ("Sample questions", "sample_questions", "question_id"),
        ]:
            block = _records_markdown(payload.get(key), heading)
            if block:
                lines.extend([f"## {title}", block, ""])
        return "\n".join(lines).strip() + "\n"

    def _rag_prompt(self, title: str, payload: dict[str, Any], kb_name: str) -> str:
        if payload.get("source_type") == "question":
            question = payload.get("question") or {}
            query = question.get("stem_without_options") or question.get("stem") or title
            return f"""Please answer in Chinese. I am working on this postgraduate entrance exam math question: {title}.
The current chat has selected the scoped RAG knowledge base named {kb_name}. Its material was generated from math_content.sqlite for exactly this question and its related knowledge point.
First use RAG retrieval on this selected knowledge base, then explain: 1. tested concept; 2. full solution; 3. common traps; 4. next review action; 5. one similar mini-question.
Suggested retrieval query: {query}
"""
        knowledge = payload.get("knowledge") or {}
        query = f"{knowledge.get('knowledge_name') or title} {knowledge.get('full_path') or ''}"
        return f"""Please answer in Chinese. I am reviewing this postgraduate entrance exam math knowledge point: {title}.
The current chat has selected the scoped RAG knowledge base named {kb_name}. Its material was generated from math_content.sqlite for exactly this knowledge point.
First use RAG retrieval on this selected knowledge base, then explain with Master Prep AI style: intuition first, then definition/formula, then typical problem patterns, then 2-3 self-check questions.
Suggested retrieval query: {query}
"""

    def _embedded_knowledge_prompt(self, title: str, payload: dict[str, Any]) -> str:
        knowledge = payload["knowledge"]
        return f"""Please answer in Chinese. Use the following material extracted from math_content.sqlite to explain this postgraduate entrance exam math knowledge point. If the extracted formulas contain obvious OCR or parsing errors, point them out and correct the math expression before teaching.

Task: {title}
Knowledge path: {knowledge.get('full_path') or knowledge.get('chapter') or ''}

Lecture material:
{payload.get('lecture_markdown') or 'No lecture slice available'}

Formulas:
{json.dumps(payload.get('formulas') or [], ensure_ascii=False, indent=2)}

Common mistakes:
{json.dumps(payload.get('mistakes') or [], ensure_ascii=False, indent=2)}
"""

    def _embedded_question_prompt(self, title: str, payload: dict[str, Any]) -> str:
        question = payload["question"]
        knowledge = payload.get("knowledge") or {}
        return f"""Please answer in Chinese. Use the following question and related knowledge-point material extracted from math_content.sqlite to provide an AI explanation. If the database formulas or analysis contain obvious extraction errors, correct them first and then teach.

Task: {title}
Knowledge point: {knowledge.get('knowledge_name') or question.get('knowledge_id') or 'unknown'}

Question material:
{_question_text(question)}

Related lecture material:
{payload.get('lecture_markdown') or 'No related lecture slice available'}
"""
