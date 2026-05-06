"""Read-only access to the postgraduate math content SQLite database."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import re
import sqlite3
from typing import Any

DEFAULT_USER_ID = "local-user"

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


class KaoyanContentStore:
    """Query the prepared high-math content package without mutating it."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_content_db_path()

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Kaoyan content database not found: {self.db_path}")
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def health(self) -> dict[str, Any]:
        with self._connect() as conn:
            counts = {}
            for table in [
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
            ]:
                counts[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        return {"db_path": str(self.db_path), "counts": counts}

    def list_knowledge_points(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT knowledge_id, subject, module, chapter, section, knowledge_name,
                       parent_id, importance_level, is_core, raw_markdown
                FROM knowledge_points
                ORDER BY knowledge_id
                """
            ).fetchall()
        return _clean_rows(rows)

    def list_lecture_nodes(self) -> list[dict[str, Any]]:
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

    def knowledge_tree(self) -> list[dict[str, Any]]:
        """Return the student-facing lecture knowledge tree, not the question-bank grouping tree."""
        nodes = [node for node in self.list_lecture_nodes() if not self._is_noisy_lecture_node(node)]
        by_id: dict[str, dict[str, Any]] = {}
        for node in nodes:
            item = dict(node)
            item["children"] = []
            by_id[item["knowledge_id"]] = item

        roots: list[dict[str, Any]] = []
        for item in by_id.values():
            parent_id = item.get("parent_id")
            if parent_id and parent_id in by_id:
                by_id[parent_id]["children"].append(item)
            else:
                roots.append(item)
        return roots

    def get_knowledge(self, knowledge_id: str, question_limit: int = 8) -> dict[str, Any] | None:
        if knowledge_id.startswith("LECTURE_"):
            return self._get_lecture_knowledge(knowledge_id, question_limit)
        return self._get_question_group_knowledge(knowledge_id, question_limit)

    def get_question(self, question_id: str) -> dict[str, Any] | None:
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
        with self._connect() as conn:
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

    def _lecture_row_to_knowledge(self, row: dict[str, Any]) -> dict[str, Any]:
        full_path = str(row.get("full_path") or row.get("title") or "")
        path_parts = [part.strip() for part in full_path.split(">") if part.strip()]
        title = str(row.get("title") or "")
        node_type = str(row.get("node_type") or "")
        importance = 5 if node_type == "knowledge_point" else 4 if node_type in {"subsection", "section"} else 3
        return {
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