"""Read-only access to the postgraduate math content SQLite database."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
from typing import Any

DEFAULT_USER_ID = "local-user"
_MATERIAL_PARSE_TASKS: dict[str, dict[str, Any]] = {}
_CONTENT_TABLES = [
    "knowledge_points",
    "questions",
    "formulas",
    "mistakes",
    "review_cards",
    "lecture_knowledge_nodes",
    "lecture_chunks",
    "lecture_formulas",
    "lecture_mistakes",
    "lecture_review_cards",
    "worked_examples",
]

_REFERENCE_PATTERNS = [
    re.compile(r"\{?#references\s+[\"'][^\"']+[\"']\}?", re.IGNORECASE),
    re.compile(r"\(#references\s+[\"'][^\"']+[\"']\)", re.IGNORECASE),
    re.compile(r"#references\s+[\"'][^\"']+[\"']", re.IGNORECASE),
]
_QUESTION_LIKE_MARKERS = (
    "下列",
    "求极限",
    "证明",
    "不可导点",
    "个数为",
    "填空",
    "选择",
    "______",
    "\\_\\_",
)

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_content_db_path() -> Path:
    configured = os.getenv("KAOYAN_CONTENT_DB")
    if configured:
        return Path(configured)
    return _repo_root().parent / "math_content.sqlite"


def clean_content(value: Any) -> Any:
    """Remove extraction artifacts before content reaches Markdown/LaTeX rendering."""
    if value is None or not isinstance(value, str):
        return value
    text = value
    for pattern in _REFERENCE_PATTERNS:
        text = pattern.sub("", text)
    text = text.replace("\\,{}", "\\,").replace("{}", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: clean_content(row[key]) for key in row.keys()}


def _clean_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [_row_to_dict(row) for row in rows]

_CHOICE_OPTION_RE = re.compile(
    r"(?:^|\n)\s*[\(（]([A-D])\s*[\)）]\s*(.*?)(?=(?:\n\s*[\(（][A-D]\s*[\)）])|\Z)",
    re.DOTALL,
)


def split_choice_options(stem: str | None) -> tuple[str, list[dict[str, str]]]:
    text = str(stem or "")
    options: list[dict[str, str]] = []
    for match in _CHOICE_OPTION_RE.finditer(text):
        label = match.group(1).upper()
        content = clean_content(match.group(2)) or ""
        if content:
            options.append({"label": label, "content": content})
    if not options:
        return text, []
    main = _CHOICE_OPTION_RE.sub("\n", text)
    main = re.sub(r"\n{3,}", "\n\n", main).strip()
    return main, options


def _question_row_to_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = _row_to_dict(row) if isinstance(row, sqlite3.Row) else {key: clean_content(value) for key, value in row.items()}
    stem = str(data.get("stem") or "")
    stem_main, options = split_choice_options(stem)
    data["stem"] = stem_main if options else stem
    data["stem_without_options"] = stem_main
    data["options"] = options
    data["is_choice"] = bool(options) or "选择" in str(data.get("question_type") or "")
    return data


def _question_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [_question_row_to_dict(row) for row in rows]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _compact_text(value: Any, limit: int = 500) -> str:
    text = clean_content(str(value or "")) or ""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _safe_slug(value: Any, fallback: str = "untitled") -> str:
    text = str(value or "").strip() or fallback
    text = re.sub(r"[\\/:*?\"<>|]+", "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text or fallback)[:80]


def _node_level(node: dict[str, Any]) -> int:
    explicit = node.get("level")
    if explicit not in (None, ""):
        return _as_int(explicit, 1)
    node_type = str(node.get("node_type") or node.get("module") or "").strip()
    if node_type == "chapter":
        return 1
    if node_type == "section":
        return 2
    if node_type == "subsection":
        return 3
    if node_type == "knowledge_point":
        return 4
    full_path = str(node.get("full_path") or "")
    if full_path:
        return max(1, len([part for part in full_path.split(">") if part.strip()]))
    if node.get("section"):
        return 3
    if node.get("chapter"):
        return 2
    return 1


def _source_refs_for_node(node: dict[str, Any]) -> list[dict[str, Any]]:
    source_id = str(node.get("knowledge_id") or node.get("id") or "").strip()
    if not source_id:
        return []
    return [
        {
            "id": source_id,
            "title": node.get("knowledge_name") or node.get("title") or source_id,
            "source_type": "content_db",
            "source": "math_content.sqlite",
            "path": node.get("full_path") or node.get("section") or node.get("chapter") or "",
        }
    ]


def _freeze_knowledge_node(node: dict[str, Any], *, include_children: bool = True) -> dict[str, Any]:
    item = dict(node)
    node_id = str(item.get("knowledge_id") or item.get("id") or "").strip()
    title = str(item.get("knowledge_name") or item.get("title") or node_id).strip()
    importance = _as_int(item.get("importance_level"), 3)
    item.setdefault("knowledge_id", node_id)
    item.setdefault("knowledge_name", title)
    item["id"] = str(item.get("id") or node_id)
    item["title"] = str(item.get("title") or title)
    item["level"] = _node_level(item)
    item["difficulty"] = _as_int(item.get("difficulty"), importance or 3)
    item["tags"] = _unique_strings(
        list(item.get("tags") or [])
        + [
            item.get("subject"),
            item.get("module"),
            item.get("chapter"),
            item.get("section"),
            item.get("node_type"),
            "core" if _as_int(item.get("is_core")) else "",
        ]
    )
    item["source_refs"] = list(item.get("source_refs") or _source_refs_for_node(item))
    if include_children:
        item["children"] = [
            _freeze_knowledge_node(child, include_children=True)
            for child in (item.get("children") or [])
            if isinstance(child, dict)
        ]
    else:
        item.pop("children", None)
    return item


def _detail_summary(knowledge: dict[str, Any], chunks: list[dict[str, Any]]) -> str:
    for value in [knowledge.get("raw_markdown"), *(chunk.get("raw_markdown") for chunk in chunks)]:
        summary = _compact_text(value, 600)
        if summary:
            return summary
    return _compact_text(knowledge.get("full_path") or knowledge.get("knowledge_name"), 300)


def _freeze_knowledge_detail(detail: dict[str, Any]) -> dict[str, Any]:
    result = dict(detail)
    knowledge = _freeze_knowledge_node(dict(result.get("knowledge") or {}), include_children=False)
    questions = list(result.get("questions") or [])
    formulas = list(result.get("formulas") or [])
    mistakes = list(result.get("mistakes") or [])
    review_cards = list(result.get("review_cards") or [])
    chunks = list(result.get("chunks") or [])
    question_ids = [
        str(item.get("question_id"))
        for item in questions
        if isinstance(item, dict) and item.get("question_id")
    ]
    source_refs = list(knowledge.get("source_refs") or [])
    for question in questions:
        if not isinstance(question, dict):
            continue
        qid = question.get("question_id")
        if qid:
            source_refs.append(
                {
                    "id": qid,
                    "title": _compact_text(question.get("stem_without_options") or question.get("stem"), 80) or str(qid),
                    "source_type": "question",
                    "source": question.get("source") or question.get("source_type") or "math_content.sqlite",
                    "path": question.get("knowledge_id") or knowledge.get("knowledge_id") or "",
                }
            )
    result.update(
        {
            "knowledge": knowledge,
            "questions": questions,
            "formulas": formulas,
            "mistakes": mistakes,
            "review_cards": review_cards,
            "chunks": chunks,
            "id": knowledge["id"],
            "title": knowledge["title"],
            "summary": _detail_summary(knowledge, chunks),
            "prerequisites": list(result.get("prerequisites") or []),
            "examples": [
                {
                    "question_id": item.get("question_id"),
                    "title": _compact_text(item.get("stem_without_options") or item.get("stem"), 120),
                    "difficulty": item.get("difficulty_level"),
                }
                for item in questions[:3]
                if isinstance(item, dict)
            ],
            "question_ids": question_ids,
            "source_refs": source_refs,
        }
    )
    return result


class KaoyanContentStore:
    """Query the prepared high-math content package without mutating it."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_content_db_path()

    def _connect(self):
        if not self.db_path.exists():
            raise FileNotFoundError(f"Kaoyan content database not found: {self.db_path}")
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return closing(conn)

    def health(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        abnormalities: dict[str, Any] = {"missing_tables": [], "orphaned_questions": 0}
        checked_at = _now_iso()
        for table in _CONTENT_TABLES:
            counts[table] = 0
        if not self.db_path.exists():
            return {
                "db_path": str(self.db_path),
                "db_exists": False,
                "status": "missing",
                "counts": counts,
                "abnormalities": abnormalities,
                "checked_at": checked_at,
            }
        try:
            conn_cm = self._connect()
        except Exception as exc:
            return {
                "db_path": str(self.db_path),
                "db_exists": True,
                "status": "error",
                "counts": counts,
                "abnormalities": {**abnormalities, "error": str(exc)},
                "checked_at": checked_at,
            }
        with conn_cm as conn:
            for table in _CONTENT_TABLES:
                try:
                    counts[table] = int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
                except sqlite3.Error:
                    abnormalities["missing_tables"].append(table)
            if not abnormalities["missing_tables"] or {"knowledge_points", "questions"}.isdisjoint(abnormalities["missing_tables"]):
                try:
                    abnormalities["orphaned_questions"] = int(
                        conn.execute(
                            """
                            SELECT count(*)
                            FROM questions q
                            LEFT JOIN knowledge_points kp ON kp.knowledge_id = q.knowledge_id
                            WHERE q.knowledge_id IS NOT NULL AND q.knowledge_id != '' AND kp.knowledge_id IS NULL
                            """
                        ).fetchone()[0]
                    )
                except sqlite3.Error:
                    abnormalities["orphaned_questions"] = 0
        status = "healthy" if not abnormalities["missing_tables"] and not abnormalities["orphaned_questions"] else "abnormal"
        return {
            "db_path": str(self.db_path),
            "db_exists": True,
            "status": status,
            "counts": counts,
            "abnormalities": abnormalities,
            "checked_at": checked_at,
        }

    def create_material_parse_task(
        self,
        filename: str,
        content_type: str = "pdf",
        *,
        user_id: str = DEFAULT_USER_ID,
        raw_text: str | None = None,
    ) -> dict[str, Any]:
        now = _now_iso()
        extracted_sections = self._extract_material_sections(raw_text or "", filename)
        status = "completed" if raw_text and extracted_sections else "pending"
        task = {
            "task_id": f"mat_{uuid.uuid4().hex[:12]}",
            "filename": str(filename),
            "content_type": str(content_type or "pdf"),
            "status": status,
            "progress": 100 if status == "completed" else 0,
            "retry_count": 0,
            "fail_reason": "",
            "extracted_sections": extracted_sections,
            "user_id": str(user_id or DEFAULT_USER_ID),
            "created_at": now,
            "updated_at": now,
        }
        _MATERIAL_PARSE_TASKS[task["task_id"]] = task
        return dict(task)

    def get_material_parse_task(self, task_id: str, *, user_id: str = DEFAULT_USER_ID) -> dict[str, Any] | None:
        task = _MATERIAL_PARSE_TASKS.get(str(task_id))
        if task is None:
            return None
        if str(task.get("user_id") or DEFAULT_USER_ID) != str(user_id or DEFAULT_USER_ID):
            return None
        if task.get("status") == "pending":
            task["status"] = "completed"
            task["progress"] = 100
            task["updated_at"] = _now_iso()
        return dict(task)

    def _extract_material_sections(self, raw_text: str, filename: str) -> list[dict[str, Any]]:
        text = clean_content(raw_text) if isinstance(raw_text, str) else ""
        if not text:
            return []
        sections: list[dict[str, Any]] = []
        current_title = Path(filename).stem or "material"
        current_lines: list[str] = []

        def flush() -> None:
            content = "\n".join(current_lines).strip()
            if not content:
                return
            order = len(sections) + 1
            sections.append(
                {
                    "section_id": f"sec_{order:03d}",
                    "title": current_title,
                    "content": content,
                    "order": order,
                    "word_count": len(content),
                }
            )

        for line in text.splitlines():
            heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
            if heading:
                flush()
                current_title = heading.group(1).strip()
                current_lines = []
                continue
            current_lines.append(line)
        flush()
        if not sections:
            sections.append(
                {
                    "section_id": "sec_001",
                    "title": Path(filename).stem or "material",
                    "content": text,
                    "order": 1,
                    "word_count": len(text),
                }
            )
        return sections[:50]

    def list_knowledge_points(self) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT knowledge_id, subject, module, chapter, section, knowledge_name,
                       parent_id, importance_level, is_core, raw_markdown
                FROM knowledge_points
                ORDER BY knowledge_id
                """
            ).fetchall()
        return [_freeze_knowledge_node(row, include_children=False) for row in _clean_rows(rows)]

    def list_lecture_nodes(self) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT lecture_knowledge_id, parent_id, node_type, chapter_no, section_no,
                       title, full_path, sort_order, raw_markdown, needs_review
                FROM lecture_knowledge_nodes
                ORDER BY sort_order, lecture_knowledge_id
                """
            ).fetchall()
        return [self._lecture_row_to_knowledge(_row_to_dict(row)) for row in rows]

    def knowledge_tree(self, subject: str | None = None) -> list[dict[str, Any]]:
        """Return the student-facing lecture knowledge tree, not the question-bank grouping tree."""
        if subject and subject != "math":
            return []
        nodes = [node for node in self.list_lecture_nodes() if not self._is_noisy_lecture_node(node)]
        by_id: dict[str, dict[str, Any]] = {}
        for node in nodes:
            item = _freeze_knowledge_node(dict(node), include_children=False)
            item["children"] = []
            by_id[item["knowledge_id"]] = item

        roots: list[dict[str, Any]] = []
        for item in by_id.values():
            parent_id = item.get("parent_id")
            if parent_id and parent_id in by_id:
                by_id[parent_id]["children"].append(item)
            else:
                roots.append(item)
        return [_freeze_knowledge_node(root, include_children=True) for root in roots]

    def get_knowledge(self, knowledge_id: str, question_limit: int = 8) -> dict[str, Any] | None:
        if not self.db_path.exists():
            return None
        if knowledge_id.startswith("LECTURE_"):
            detail = self._get_lecture_knowledge(knowledge_id, question_limit)
        else:
            detail = self._get_question_group_knowledge(knowledge_id, question_limit)
        return _freeze_knowledge_detail(detail) if detail is not None else None

    def get_question(self, question_id: str) -> dict[str, Any] | None:
        if not self.db_path.exists():
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT question_id, knowledge_id, question_type, difficulty_level, stem,
                       answer, analysis, source, source_type, year
                FROM questions
                WHERE question_id = ?
                """,
                (question_id,),
            ).fetchone()
        return _question_row_to_dict(row) if row else None

    def get_questions(self, question_ids: list[str]) -> list[dict[str, Any]]:
        if not question_ids:
            return []
        if not self.db_path.exists():
            return []
        placeholders = ",".join("?" for _ in question_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT question_id, knowledge_id, question_type, difficulty_level, stem,
                       answer, analysis, source, source_type, year
                FROM questions
                WHERE question_id IN ({placeholders})
                """,
                tuple(question_ids),
            ).fetchall()
        by_id = {_question_row_to_dict(row)["question_id"]: _question_row_to_dict(row) for row in rows}
        return [by_id[qid] for qid in question_ids if qid in by_id]

    def select_questions(
        self,
        *,
        knowledge_id: str | None = None,
        question_type: str | None = None,
        difficulty_level: int | None = None,
        limit: int = 5,
        exclude_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        clauses: list[str] = []
        params: list[Any] = []
        practice_knowledge_ids = self.resolve_practice_knowledge_ids(knowledge_id) if knowledge_id else []
        if practice_knowledge_ids:
            clauses.append("knowledge_id IN (" + ",".join("?" for _ in practice_knowledge_ids) + ")")
            params.extend(practice_knowledge_ids)
        elif knowledge_id:
            clauses.append("knowledge_id = ?")
            params.append(knowledge_id)
        if question_type:
            clauses.append("question_type = ?")
            params.append(question_type)
        if difficulty_level:
            clauses.append("difficulty_level BETWEEN ? AND ?")
            params.extend([max(1, difficulty_level - 1), min(5, difficulty_level + 1)])
        if exclude_ids:
            clauses.append("question_id NOT IN (" + ",".join("?" for _ in exclude_ids) + ")")
            params.extend(exclude_ids)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(limit, 30)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT question_id, knowledge_id, question_type, difficulty_level, stem,
                       answer, analysis, source, source_type, year
                FROM questions
                {where}
                ORDER BY RANDOM()
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return _question_rows(rows)

    def sample_knowledge_for_plan(self, limit: int = 8) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT lecture_knowledge_id, parent_id, node_type, chapter_no, section_no,
                       title, full_path, sort_order, raw_markdown, needs_review
                FROM lecture_knowledge_nodes
                WHERE node_type = 'knowledge_point'
                ORDER BY chapter_no, section_no, sort_order
                LIMIT ?
                """,
                (limit * 3,),
            ).fetchall()
        candidates = [self._lecture_row_to_knowledge(_row_to_dict(row)) for row in rows]
        return [item for item in candidates if not self._is_noisy_lecture_node(item)][:limit]

    def resolve_practice_knowledge_ids(self, knowledge_id: str | None, limit: int = 4) -> list[str]:
        if not knowledge_id:
            return []
        if not knowledge_id.startswith("LECTURE_"):
            return [knowledge_id]
        if not self.db_path.exists():
            return []
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    WITH RECURSIVE target(id) AS (
                        SELECT ?
                        UNION ALL
                        SELECT node.lecture_knowledge_id
                        FROM lecture_knowledge_nodes node
                        JOIN target ON node.parent_id = target.id
                    )
                    SELECT DISTINCT knowledge_id, max(confidence) AS score
                    FROM lecture_knowledge_mappings
                    WHERE lecture_knowledge_id IN (SELECT id FROM target)
                    GROUP BY knowledge_id
                    ORDER BY score DESC, knowledge_id
                    LIMIT ?
                    """,
                    (knowledge_id, limit),
                ).fetchall()
            except sqlite3.Error:
                return []
        return [str(row["knowledge_id"]) for row in rows]

    def _get_question_group_knowledge(self, knowledge_id: str, question_limit: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            point = conn.execute(
                """
                SELECT knowledge_id, subject, module, chapter, section, knowledge_name,
                       parent_id, importance_level, is_core, raw_markdown
                FROM knowledge_points
                WHERE knowledge_id = ?
                """,
                (knowledge_id,),
            ).fetchone()
            if point is None:
                return None
            questions = conn.execute(
                """
                SELECT question_id, knowledge_id, question_type, difficulty_level, stem,
                       answer, analysis, source, source_type, year
                FROM questions
                WHERE knowledge_id = ?
                ORDER BY difficulty_level, question_id
                LIMIT ?
                """,
                (knowledge_id, question_limit),
            ).fetchall()
        return {
            "knowledge": _row_to_dict(point),
            "questions": _question_rows(questions),
            "formulas": [],
            "mistakes": [],
            "review_cards": [],
        }

    def _get_lecture_knowledge(self, knowledge_id: str, question_limit: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            point = conn.execute(
                """
                SELECT lecture_knowledge_id, parent_id, node_type, chapter_no, section_no,
                       title, full_path, sort_order, raw_markdown, needs_review
                FROM lecture_knowledge_nodes
                WHERE lecture_knowledge_id = ?
                """,
                (knowledge_id,),
            ).fetchone()
            if point is None:
                return None
            descendant_rows = conn.execute(
                """
                WITH RECURSIVE target(id) AS (
                    SELECT ?
                    UNION ALL
                    SELECT node.lecture_knowledge_id
                    FROM lecture_knowledge_nodes node
                    JOIN target ON node.parent_id = target.id
                )
                SELECT id FROM target
                """,
                (knowledge_id,),
            ).fetchall()
            descendant_ids = [row["id"] for row in descendant_rows]
            placeholders = ",".join("?" for _ in descendant_ids)
            chunks = conn.execute(
                f"""
                SELECT chunk_id, lecture_knowledge_id, content_type, title, raw_markdown,
                       formula_count, image_count, table_count, needs_review
                FROM lecture_chunks
                WHERE lecture_knowledge_id IN ({placeholders})
                ORDER BY sort_order
                LIMIT 12
                """,
                tuple(descendant_ids),
            ).fetchall()
            formulas = conn.execute(
                f"""
                SELECT formula_id, formula_name, formula_content, conditions,
                       usage_scene, common_mistake, raw_markdown
                FROM lecture_formulas
                WHERE lecture_knowledge_id IN ({placeholders})
                ORDER BY formula_id
                LIMIT 12
                """,
                tuple(descendant_ids),
            ).fetchall()
            mistakes = conn.execute(
                f"""
                SELECT mistake_id, mistake_content, trigger_condition, correction_method, raw_markdown
                FROM lecture_mistakes
                WHERE lecture_knowledge_id IN ({placeholders})
                ORDER BY mistake_id
                LIMIT 12
                """,
                tuple(descendant_ids),
            ).fetchall()
            cards = conn.execute(
                f"""
                SELECT card_id, card_type, front_content, back_content, raw_markdown
                FROM lecture_review_cards
                WHERE lecture_knowledge_id IN ({placeholders})
                ORDER BY card_id
                LIMIT 12
                """,
                tuple(descendant_ids),
            ).fetchall()
        question_ids = self.resolve_practice_knowledge_ids(knowledge_id)
        questions: list[dict[str, Any]] = []
        if question_ids:
            questions = self.select_questions(knowledge_id=knowledge_id, limit=question_limit)
        knowledge = self._lecture_row_to_knowledge(_row_to_dict(point))
        chunk_dicts = _clean_rows(chunks)
        if chunk_dicts:
            knowledge["raw_markdown"] = "\n\n".join(item.get("raw_markdown", "") for item in chunk_dicts if item.get("raw_markdown"))
        return {
            "knowledge": knowledge,
            "questions": questions,
            "formulas": _clean_rows(formulas),
            "mistakes": _clean_rows(mistakes),
            "review_cards": _clean_rows(cards),
            "chunks": chunk_dicts,
        }

    def query_rag(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Lightweight local retrieval over the content SQLite package."""
        query_text = str(query or "").strip()
        limit = max(1, min(int(top_k or 5), 20))
        base = {
            "kb_name": "",
            "query": query_text,
            "answer": "",
            "contexts": [],
            "sources": [],
            "results": [],
            "status": "empty",
        }
        if not query_text:
            return {**base, "fallback": "Query is empty."}
        if not self.db_path.exists():
            return {**base, "status": "missing", "fallback": "Kaoyan content database is not available."}

        filters = filters or {}
        try:
            with self._connect() as conn:
                candidates = self._rag_candidates(conn, query_text, filters)
        except Exception as exc:
            return {**base, "status": "fallback", "fallback": "Kaoyan content retrieval is unavailable.", "error": str(exc)}

        tokens = self._query_tokens(query_text)
        scored: list[dict[str, Any]] = []
        for candidate in candidates:
            haystack = " ".join(
                str(candidate.get(key) or "")
                for key in ["title", "snippet", "content", "source_id", "source_type"]
            )
            score = self._score_candidate(query_text, tokens, haystack)
            if score <= 0:
                continue
            context = {
                "id": candidate["id"],
                "title": candidate["title"],
                "snippet": _compact_text(candidate.get("snippet") or candidate.get("content"), 700),
                "score": score,
                "source_type": candidate["source_type"],
                "source_id": candidate["source_id"],
                "metadata": candidate.get("metadata") or {},
            }
            scored.append(context)

        contexts = sorted(scored, key=lambda item: item["score"], reverse=True)[:limit]
        if not contexts:
            return {**base, "status": "empty", "fallback": "No grounded kaoyan content matched this query."}

        sources: list[dict[str, Any]] = []
        seen_sources: set[tuple[str, str]] = set()
        for context in contexts:
            key = (str(context["source_type"]), str(context["source_id"]))
            if key in seen_sources:
                continue
            seen_sources.add(key)
            sources.append(
                {
                    "id": context["id"],
                    "title": context["title"],
                    "source_type": context["source_type"],
                    "source_id": context["source_id"],
                    "score": context["score"],
                    "path": (context.get("metadata") or {}).get("path", ""),
                }
            )
        answer = "\n\n".join(f"### {item['title']}\n{item['snippet']}" for item in contexts)
        return {
            **base,
            "status": "success",
            "answer": answer,
            "contexts": contexts,
            "sources": sources,
            "results": contexts,
        }

    def _query_tokens(self, query: str) -> list[str]:
        tokens = [part.lower() for part in re.findall(r"[\w\u4e00-\u9fff]+", query) if len(part.strip()) >= 2]
        if not tokens and query.strip():
            tokens = [query.strip().lower()]
        return _unique_strings(tokens)

    def _score_candidate(self, query: str, tokens: list[str], haystack: str) -> float:
        text = haystack.lower()
        if not text:
            return 0.0
        score = 0.0
        query_norm = query.lower().strip()
        if query_norm and query_norm in text:
            score += 0.55
        matches = sum(1 for token in tokens if token in text)
        if matches:
            score += 0.25 + min(0.2, matches * 0.05)
        return round(min(score, 1.0), 4)

    def _rag_candidates(self, conn: sqlite3.Connection, query: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        tokens = self._query_tokens(query)[:5] or [query]
        source_type_filter = str(filters.get("source_type") or "").strip()

        def like_clause(columns: list[str]) -> tuple[str, list[str]]:
            clauses: list[str] = []
            params: list[str] = []
            for token in tokens:
                for column in columns:
                    clauses.append(f"COALESCE({column}, '') LIKE ?")
                    params.append(f"%{token}%")
            return " OR ".join(clauses) or "1=1", params

        if source_type_filter in {"", "lecture_chunk", "chunk"}:
            clause, params = like_clause(["title", "raw_markdown", "lecture_knowledge_id"])
            try:
                rows = conn.execute(
                    f"""
                    SELECT chunk_id, lecture_knowledge_id, content_type, title, raw_markdown
                    FROM lecture_chunks
                    WHERE {clause}
                    ORDER BY sort_order
                    LIMIT 80
                    """,
                    tuple(params),
                ).fetchall()
                for row in rows:
                    data = _row_to_dict(row)
                    candidates.append(
                        {
                            "id": data.get("chunk_id"),
                            "title": data.get("title") or data.get("lecture_knowledge_id") or "Lecture chunk",
                            "snippet": data.get("raw_markdown"),
                            "source_type": "lecture_chunk",
                            "source_id": data.get("lecture_knowledge_id") or data.get("chunk_id"),
                            "metadata": {"content_type": data.get("content_type"), "path": data.get("lecture_knowledge_id")},
                        }
                    )
            except sqlite3.Error:
                pass

        if source_type_filter in {"", "knowledge"}:
            clause, params = like_clause(["title", "full_path", "raw_markdown", "lecture_knowledge_id"])
            try:
                rows = conn.execute(
                    f"""
                    SELECT lecture_knowledge_id, node_type, title, full_path, raw_markdown
                    FROM lecture_knowledge_nodes
                    WHERE {clause}
                    ORDER BY sort_order
                    LIMIT 80
                    """,
                    tuple(params),
                ).fetchall()
                for row in rows:
                    data = _row_to_dict(row)
                    candidates.append(
                        {
                            "id": data.get("lecture_knowledge_id"),
                            "title": data.get("title") or data.get("lecture_knowledge_id") or "Knowledge",
                            "snippet": data.get("raw_markdown") or data.get("full_path"),
                            "source_type": "knowledge",
                            "source_id": data.get("lecture_knowledge_id"),
                            "metadata": {"node_type": data.get("node_type"), "path": data.get("full_path")},
                        }
                    )
            except sqlite3.Error:
                pass

        if source_type_filter in {"", "question"}:
            clause, params = like_clause(["stem", "analysis", "answer", "knowledge_id", "question_id"])
            extra = ""
            if filters.get("knowledge_id"):
                extra = " AND knowledge_id = ?"
                params.append(str(filters["knowledge_id"]))
            try:
                rows = conn.execute(
                    f"""
                    SELECT question_id, knowledge_id, question_type, difficulty_level, stem, answer, analysis, source, source_type, year
                    FROM questions
                    WHERE ({clause}){extra}
                    LIMIT 80
                    """,
                    tuple(params),
                ).fetchall()
                for row in rows:
                    data = _question_row_to_dict(row)
                    candidates.append(
                        {
                            "id": data.get("question_id"),
                            "title": _compact_text(data.get("stem_without_options") or data.get("stem"), 80) or data.get("question_id") or "Question",
                            "snippet": "\n\n".join(str(data.get(key) or "") for key in ["stem", "answer", "analysis"]),
                            "source_type": "question",
                            "source_id": data.get("question_id"),
                            "metadata": {"knowledge_id": data.get("knowledge_id"), "path": data.get("source") or ""},
                        }
                    )
            except sqlite3.Error:
                pass

        if source_type_filter in {"", "formula"}:
            clause, params = like_clause(["formula_name", "formula_content", "usage_scene", "common_mistake", "raw_markdown"])
            try:
                rows = conn.execute(
                    f"""
                    SELECT formula_id, lecture_knowledge_id, formula_name, formula_content, usage_scene, common_mistake, raw_markdown
                    FROM lecture_formulas
                    WHERE {clause}
                    LIMIT 80
                    """,
                    tuple(params),
                ).fetchall()
                for row in rows:
                    data = _row_to_dict(row)
                    candidates.append(
                        {
                            "id": data.get("formula_id"),
                            "title": data.get("formula_name") or data.get("formula_id") or "Formula",
                            "snippet": "\n\n".join(str(data.get(key) or "") for key in ["formula_content", "usage_scene", "common_mistake", "raw_markdown"]),
                            "source_type": "formula",
                            "source_id": data.get("formula_id"),
                            "metadata": {"knowledge_id": data.get("lecture_knowledge_id"), "path": data.get("lecture_knowledge_id")},
                        }
                    )
            except sqlite3.Error:
                pass

        return candidates

    def render_obsidian_export(
        self,
        source_type: str,
        source_id: str | None = None,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, str] | None:
        payload = payload or {}
        source_type = str(source_type or "").strip()
        if source_type == "knowledge":
            if not source_id:
                return None
            detail = self.get_knowledge(source_id)
            if detail is None:
                return None
            title = detail["title"]
            path = f"Kaoyan/Knowledge/{_safe_slug(title, source_id)}.md"
            return {"path": path, "markdown": self._knowledge_obsidian_markdown(detail)}
        if source_type == "question":
            if not source_id:
                return None
            question = self.get_question(source_id)
            if question is None:
                return None
            path = f"Kaoyan/Questions/{_safe_slug(source_id)}.md"
            return {"path": path, "markdown": self._question_obsidian_markdown(question)}
        if source_type == "wrong_question":
            question_id = str(source_id or payload.get("question_id") or "wrong-question")
            path = f"Kaoyan/Wrong Questions/{_safe_slug(question_id)}.md"
            return {"path": path, "markdown": self._wrong_question_obsidian_markdown(question_id, payload)}
        if source_type == "diagnostic_report":
            report_id = str(source_id or payload.get("report_id") or "diagnostic-report")
            path = f"Kaoyan/Diagnostics/{_safe_slug(report_id)}.md"
            return {"path": path, "markdown": self._diagnostic_obsidian_markdown(report_id, payload)}
        return None

    def _frontmatter(self, values: dict[str, Any]) -> str:
        lines = ["---"]
        for key, value in values.items():
            if value in (None, "", [], {}):
                continue
            if isinstance(value, list):
                rendered = "[" + ", ".join(json.dumps(str(item), ensure_ascii=False) for item in value) + "]"
            else:
                rendered = json.dumps(str(value), ensure_ascii=False)
            lines.append(f"{key}: {rendered}")
        lines.append("---")
        return "\n".join(lines)

    def _knowledge_obsidian_markdown(self, detail: dict[str, Any]) -> str:
        knowledge = detail.get("knowledge") or {}
        lines = [
            self._frontmatter(
                {
                    "type": "kaoyan_knowledge",
                    "id": detail.get("id"),
                    "title": detail.get("title"),
                    "tags": knowledge.get("tags") or [],
                }
            ),
            "",
            f"# {detail.get('title')}",
            "",
            "## Summary",
            detail.get("summary") or "",
            "",
        ]
        formulas = detail.get("formulas") or []
        if formulas:
            lines.extend(["## Formulas", ""])
            for formula in formulas:
                lines.append(f"- **{formula.get('formula_name') or formula.get('formula_id')}**: {formula.get('formula_content') or formula.get('raw_markdown') or ''}")
            lines.append("")
        mistakes = detail.get("mistakes") or []
        if mistakes:
            lines.extend(["## Common Mistakes", ""])
            for mistake in mistakes:
                lines.append(f"- {mistake.get('mistake_content') or mistake.get('raw_markdown') or mistake.get('mistake_id')}")
            lines.append("")
        if detail.get("question_ids"):
            lines.extend(["## Linked Questions", ""])
            lines.extend(f"- [[{qid}]]" for qid in detail["question_ids"])
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _question_obsidian_markdown(self, question: dict[str, Any]) -> str:
        lines = [
            self._frontmatter(
                {
                    "type": "kaoyan_question",
                    "id": question.get("question_id"),
                    "knowledge_id": question.get("knowledge_id"),
                    "difficulty": question.get("difficulty_level"),
                    "year": question.get("year"),
                }
            ),
            "",
            f"# {question.get('question_id')}",
            "",
            "## Stem",
            question.get("stem_without_options") or question.get("stem") or "",
            "",
        ]
        if question.get("options"):
            lines.extend(["## Options", ""])
            for option in question["options"]:
                lines.append(f"- {option.get('label')}. {option.get('content')}")
            lines.append("")
        lines.extend(["## Answer", str(question.get("answer") or ""), "", "## Analysis", str(question.get("analysis") or ""), ""])
        return "\n".join(lines).strip() + "\n"

    def _wrong_question_obsidian_markdown(self, question_id: str, payload: dict[str, Any]) -> str:
        question = payload.get("question") if isinstance(payload.get("question"), dict) else {}
        lines = [
            self._frontmatter(
                {
                    "type": "kaoyan_wrong_question",
                    "id": question_id,
                    "knowledge_id": payload.get("knowledge_id") or question.get("knowledge_id"),
                    "wrong_count": payload.get("wrong_count"),
                    "review_status": payload.get("review_status"),
                }
            ),
            "",
            f"# Wrong Question {question_id}",
            "",
            "## Question",
            question.get("stem_without_options") or question.get("stem") or payload.get("prompt") or "",
            "",
            "## Error Reason",
            str(payload.get("error_reason") or ""),
            "",
            "## Correction",
            str(payload.get("correction") or payload.get("analysis") or question.get("analysis") or ""),
        ]
        return "\n".join(lines).strip() + "\n"

    def _diagnostic_obsidian_markdown(self, report_id: str, payload: dict[str, Any]) -> str:
        draft = payload.get("profile_draft") if isinstance(payload.get("profile_draft"), dict) else {}
        weak_modules = draft.get("weak_modules") or payload.get("weak_modules") or []
        recommendations = payload.get("recommendations") or draft.get("plan_focus") or []
        lines = [
            self._frontmatter(
                {
                    "type": "kaoyan_diagnostic_report",
                    "id": report_id,
                    "mode": payload.get("mode"),
                    "tags": ["kaoyan", "diagnostic"],
                }
            ),
            "",
            f"# Diagnostic Report {report_id}",
            "",
            "## Summary",
            str(payload.get("summary") or draft.get("reasoning_summary") or ""),
            "",
            "## Weak Modules",
            "",
        ]
        lines.extend(f"- {item}" for item in weak_modules)
        lines.extend(["", "## Recommendations", ""])
        lines.extend(f"- {item}" for item in recommendations)
        return "\n".join(lines).strip() + "\n"

    def _lecture_row_to_knowledge(self, row: dict[str, Any]) -> dict[str, Any]:
        full_path = str(row.get("full_path") or row.get("title") or "")
        path_parts = [part.strip() for part in full_path.split(">") if part.strip()]
        title = str(row.get("title") or "")
        node_type = str(row.get("node_type") or "")
        importance = 5 if node_type == "knowledge_point" else 4 if node_type in {"subsection", "section"} else 3
        result = {
            "knowledge_id": row.get("lecture_knowledge_id"),
            "subject": "math",
            "module": node_type or "lecture",
            "chapter": path_parts[0] if path_parts else title,
            "section": " > ".join(path_parts[1:]) if len(path_parts) > 1 else "",
            "knowledge_name": title,
            "parent_id": row.get("parent_id"),
            "importance_level": importance,
            "is_core": 1 if node_type == "knowledge_point" else 0,
            "raw_markdown": clean_content(row.get("raw_markdown") or title),
            "node_type": node_type,
            "full_path": full_path,
            "sort_order": row.get("sort_order") or 0,
            "needs_review": row.get("needs_review") or 0,
        }
        return _freeze_knowledge_node(result, include_children=False)

    def _is_noisy_lecture_node(self, node: dict[str, Any]) -> bool:
        node_type = str(node.get("node_type") or "")
        title = str(node.get("knowledge_name") or "")
        raw = str(node.get("raw_markdown") or "")
        if node_type == "question_type":
            return True
        if node_type != "knowledge_point":
            return False
        if any(marker in title for marker in _QUESTION_LIKE_MARKERS) and (len(title) > 28 or "$" in title):
            return True
        if len(title) > 55 and not raw.lstrip().startswith("#"):
            return True
        return False


@lru_cache(maxsize=1)
def get_content_store() -> KaoyanContentStore:
    return KaoyanContentStore()
