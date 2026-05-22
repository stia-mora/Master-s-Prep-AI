"""SQLite runtime store for the Kaoyan MVP learning loop."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import json
import os
from pathlib import Path
import sqlite3
from typing import Any
import uuid

DEFAULT_USER_ID = "local-user"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_learning_db_path() -> Path:
    configured = os.getenv("KAOYAN_APP_DB")
    if configured:
        return Path(configured)
    return _repo_root() / "data" / "user" / "kaoyan_learning.sqlite"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_iso() -> str:
    return date.today().isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = {key: row[key] for key in row.keys()}
    list_json_keys = {
        "weak_modules_json",
        "related_knowledge_ids_json",
        "question_ids_json",
        "subjects_json",
        "weak_knowledge_ids_json",
        "recommendations_json",
        "knowledge_ids_json",
        "evidence_json",
    }
    for key in [
        "weak_modules_json",
        "payload_json",
        "related_knowledge_ids_json",
        "question_ids_json",
        "ai_metadata_json",
        "subjects_json",
        "preferences_json",
        "weak_knowledge_ids_json",
        "score_summary_json",
        "recommendations_json",
        "knowledge_ids_json",
        "unlock_rule_json",
        "context_json",
        "portrait_summary_json",
        "evidence_json",
        "last_reason_json",
    ]:
        if key in data:
            data[key.replace("_json", "")] = _json_loads(
                data.pop(key), [] if key in list_json_keys else {}
            )
    if "related_knowledge_ids" in data:
        data["knowledge_ids"] = data["related_knowledge_ids"]
    if "due_at" in data:
        data["due_date"] = data["due_at"]
    if "priority_score" in data:
        data["priority"] = data["priority_score"]
    if "ai_generated" in data and "ai_status" in data:
        data["ai_metadata"] = {
            "ai_used": bool(data.get("ai_generated")),
            "status": data.get("ai_status", ""),
            "message": data.get("ai_message", ""),
        }
    return data


def _normalize_task_status(status: str) -> str:
    aliases = {
        "todo": "pending",
        "pending": "pending",
        "in_progress": "in_progress",
        "doing": "in_progress",
        "done": "completed",
        "completed": "completed",
        "skipped": "skipped",
        "deferred": "skipped",
    }
    return aliases.get(str(status or "").strip().lower(), "pending")


class KaoyanLearningStore:
    """Persist single-user MVP behavior, plans, mastery and review data."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_learning_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_profile (
                    user_id TEXT PRIMARY KEY,
                    target_school TEXT NOT NULL DEFAULT '',
                    target_major TEXT NOT NULL DEFAULT '',
                    exam_date TEXT NOT NULL DEFAULT '',
                    daily_minutes INTEGER NOT NULL DEFAULT 120,
                    target_score INTEGER NOT NULL DEFAULT 120,
                    baseline_level TEXT NOT NULL DEFAULT '基础',
                    weak_modules_json TEXT NOT NULL DEFAULT '[]',
                    subjects_json TEXT NOT NULL DEFAULT '[]',
                    stage TEXT NOT NULL DEFAULT '',
                    preferences_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS study_plan (
                    plan_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    ai_generated INTEGER NOT NULL DEFAULT 0,
                    ai_status TEXT NOT NULL DEFAULT 'fallback',
                    ai_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plan_task (
                    task_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    estimated_minutes INTEGER NOT NULL DEFAULT 30,
                    due_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    priority_score REAL NOT NULL DEFAULT 1,
                    related_knowledge_ids_json TEXT NOT NULL DEFAULT '[]',
                    source_ref TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plan_task_version (
                    version_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS practice_session (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    knowledge_id TEXT NOT NULL DEFAULT '',
                    question_ids_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active',
                    ai_metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    submitted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS answer_record (
                    answer_id TEXT PRIMARY KEY,
                    practice_session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    knowledge_id TEXT NOT NULL,
                    user_answer TEXT NOT NULL DEFAULT '',
                    correct_answer TEXT NOT NULL DEFAULT '',
                    is_correct INTEGER NOT NULL DEFAULT 0,
                    ai_analysis TEXT NOT NULL DEFAULT '',
                    error_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS practice_record (
                    record_id TEXT PRIMARY KEY,
                    practice_session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    total_count INTEGER NOT NULL,
                    correct_count INTEGER NOT NULL,
                    accuracy REAL NOT NULL,
                    analysis_summary TEXT NOT NULL DEFAULT '',
                    next_actions_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS wrong_question (
                    wrong_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    knowledge_id TEXT NOT NULL,
                    question_type TEXT NOT NULL DEFAULT '',
                    error_reason TEXT NOT NULL DEFAULT '',
                    wrong_count INTEGER NOT NULL DEFAULT 1,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    manual_wrong_reason TEXT NOT NULL DEFAULT '',
                    ai_wrong_reason TEXT NOT NULL DEFAULT '',
                    is_focus INTEGER NOT NULL DEFAULT 0,
                    last_retry_at TEXT,
                    last_result TEXT NOT NULL DEFAULT '',
                    review_status TEXT NOT NULL DEFAULT 'pending',
                    last_wrong_at TEXT NOT NULL,
                    next_review_at TEXT NOT NULL,
                    UNIQUE(user_id, question_id)
                );

                CREATE TABLE IF NOT EXISTS review_queue (
                    review_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    knowledge_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL DEFAULT '',
                    answer TEXT NOT NULL DEFAULT '',
                    priority_score REAL NOT NULL DEFAULT 1,
                    next_review_at TEXT NOT NULL,
                    review_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, source_type, source_id)
                );

                CREATE TABLE IF NOT EXISTS mastery_record (
                    mastery_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    knowledge_id TEXT NOT NULL,
                    mastery_score REAL NOT NULL DEFAULT 50,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    correct_count INTEGER NOT NULL DEFAULT 0,
                    wrong_count INTEGER NOT NULL DEFAULT 0,
                    last_practiced_at TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, knowledge_id)
                );

                CREATE TABLE IF NOT EXISTS diagnostic_report (
                    report_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'light',
                    profile_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    answer_summary_json TEXT NOT NULL DEFAULT '{}',
                    profile_draft_json TEXT NOT NULL DEFAULT '{}',
                    weak_knowledge_ids_json TEXT NOT NULL DEFAULT '[]',
                    score_summary_json TEXT NOT NULL DEFAULT '{}',
                    recommendations_json TEXT NOT NULL DEFAULT '[]',
                    summary TEXT NOT NULL DEFAULT '',
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_action_log (
                    log_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    response_text TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS learning_path (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    goal TEXT NOT NULL DEFAULT '',
                    source_snapshot_id TEXT NOT NULL DEFAULT '',
                    portrait_summary_json TEXT NOT NULL DEFAULT '{}',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS learning_stage (
                    id TEXT PRIMARY KEY,
                    path_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    knowledge_ids_json TEXT NOT NULL DEFAULT '[]',
                    title TEXT NOT NULL,
                    order_index INTEGER NOT NULL,
                    unlock_rule_json TEXT NOT NULL DEFAULT '{}',
                    pass_threshold REAL NOT NULL DEFAULT 90,
                    context_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS stage_progress (
                    user_id TEXT NOT NULL,
                    stage_id TEXT NOT NULL,
                    mastery_score REAL NOT NULL DEFAULT 0,
                    passed INTEGER NOT NULL DEFAULT 0,
                    unlocked INTEGER NOT NULL DEFAULT 0,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_reason_json TEXT NOT NULL DEFAULT '{}',
                    next_action TEXT NOT NULL DEFAULT '',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, stage_id)
                );

                CREATE INDEX IF NOT EXISTS idx_plan_task_due ON plan_task(user_id, due_at, status);
                CREATE INDEX IF NOT EXISTS idx_wrong_user ON wrong_question(user_id, review_status);
                CREATE INDEX IF NOT EXISTS idx_review_due ON review_queue(user_id, status, next_review_at, priority_score DESC);
                CREATE INDEX IF NOT EXISTS idx_mastery_user ON mastery_record(user_id, mastery_score);
                CREATE INDEX IF NOT EXISTS idx_diagnostic_report_user ON diagnostic_report(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_learning_path_user ON learning_path(user_id, status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_learning_stage_path ON learning_stage(user_id, path_id, order_index);
                """
            )
            self._ensure_column(conn, "user_profile", "subjects_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "user_profile", "stage", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "user_profile", "preferences_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(
                conn,
                "diagnostic_report",
                "weak_knowledge_ids_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(
                conn,
                "diagnostic_report",
                "score_summary_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                conn,
                "diagnostic_report",
                "recommendations_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(conn, "wrong_question", "question_type", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "wrong_question", "retry_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "wrong_question", "manual_wrong_reason", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "wrong_question", "ai_wrong_reason", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "wrong_question", "is_focus", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "wrong_question", "last_retry_at", "TEXT")
            self._ensure_column(conn, "wrong_question", "last_result", "TEXT NOT NULL DEFAULT ''")
            conn.commit()

    def _ensure_column(
        self, conn: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def upsert_profile(self, payload: dict[str, Any], user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
        now = utc_now()
        weak_modules = payload.get("weak_modules") or payload.get("weakModules") or []
        subjects = payload.get("subjects") or []
        preferences = payload.get("preferences") or {}
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_profile (
                    user_id, target_school, target_major, exam_date, daily_minutes,
                    target_score, baseline_level, weak_modules_json, subjects_json, stage,
                    preferences_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    target_school = excluded.target_school,
                    target_major = excluded.target_major,
                    exam_date = excluded.exam_date,
                    daily_minutes = excluded.daily_minutes,
                    target_score = excluded.target_score,
                    baseline_level = excluded.baseline_level,
                    weak_modules_json = excluded.weak_modules_json,
                    subjects_json = excluded.subjects_json,
                    stage = excluded.stage,
                    preferences_json = excluded.preferences_json,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    str(payload.get("target_school", "")),
                    str(payload.get("target_major", "")),
                    str(payload.get("exam_date", "")),
                    int(payload.get("daily_minutes") or 120),
                    int(payload.get("target_score") or 120),
                    str(payload.get("baseline_level", "基础")),
                    _json_dumps(weak_modules),
                    _json_dumps(subjects),
                    str(payload.get("stage", "")),
                    _json_dumps(preferences),
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get_profile(user_id) or {}

    def get_profile(self, user_id: str = DEFAULT_USER_ID) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM user_profile WHERE user_id = ?", (user_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def create_plan(self, title: str, tasks: list[dict[str, Any]], ai_meta: dict[str, Any], user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
        now = utc_now()
        plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        start = today_iso()
        end = (date.today() + timedelta(days=6)).isoformat()
        with self._connect() as conn:
            conn.execute("UPDATE study_plan SET status = 'archived', updated_at = ? WHERE user_id = ? AND status = 'active'", (now, user_id))
            conn.execute(
                """
                INSERT INTO study_plan (plan_id, user_id, title, start_date, end_date, status,
                    ai_generated, ai_status, ai_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    user_id,
                    title,
                    start,
                    end,
                    1 if ai_meta.get("ai_used") else 0,
                    str(ai_meta.get("status", "fallback")),
                    str(ai_meta.get("message", "")),
                    now,
                    now,
                ),
            )
            for task in tasks:
                conn.execute(
                    """
                    INSERT INTO plan_task (task_id, plan_id, user_id, task_type, title, description,
                        estimated_minutes, due_at, status, priority_score, related_knowledge_ids_json,
                        source_ref, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                    """,
                    (
                        f"task_{uuid.uuid4().hex[:12]}",
                        plan_id,
                        user_id,
                        str(task.get("task_type", "study")),
                        str(task.get("title", "高数学习任务")),
                        str(task.get("description", "")),
                        int(task.get("estimated_minutes") or 30),
                        str(task.get("due_at") or today_iso()),
                        float(task.get("priority_score") or 1),
                        _json_dumps(task.get("related_knowledge_ids") or []),
                        str(task.get("source_ref", "")),
                        now,
                        now,
                    ),
                )
            conn.commit()
        return self.get_active_plan(user_id) or {}

    def get_active_plan(self, user_id: str = DEFAULT_USER_ID) -> dict[str, Any] | None:
        with self._connect() as conn:
            plan = conn.execute(
                "SELECT * FROM study_plan WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return _row_to_dict(plan) if plan else None

    def list_today_tasks(self, user_id: str = DEFAULT_USER_ID) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM plan_task
                WHERE user_id = ? AND due_at <= date('now', '+1 day')
                ORDER BY status = 'completed', priority_score DESC, due_at, created_at
                """,
                (user_id,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def update_task_status(self, task_id: str, status: str, user_id: str = DEFAULT_USER_ID) -> dict[str, Any] | None:
        now = utc_now()
        normalized_status = _normalize_task_status(status)
        with self._connect() as conn:
            before = conn.execute("SELECT * FROM plan_task WHERE task_id = ? AND user_id = ?", (task_id, user_id)).fetchone()
            if before is None:
                return None
            before_dict = _row_to_dict(before)
            conn.execute("UPDATE plan_task SET status = ?, updated_at = ? WHERE task_id = ? AND user_id = ?", (normalized_status, now, task_id, user_id))
            after = conn.execute("SELECT * FROM plan_task WHERE task_id = ? AND user_id = ?", (task_id, user_id)).fetchone()
            conn.execute(
                "INSERT INTO plan_task_version (version_id, task_id, user_id, before_json, after_json, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"ver_{uuid.uuid4().hex[:12]}", task_id, user_id, _json_dumps(before_dict), _json_dumps(_row_to_dict(after)), "status_update", now),
            )
            conn.commit()
        return _row_to_dict(after) if after else None

    def reorder_plan_tasks(self, task_ids: list[str], reason: str, user_id: str = DEFAULT_USER_ID) -> list[dict[str, Any]]:
        ordered_ids = [str(task_id) for task_id in task_ids if str(task_id)]
        if not ordered_ids:
            return []
        now = utc_now()
        versions: list[dict[str, Any]] = []
        with self._connect() as conn:
            for index, task_id in enumerate(ordered_ids):
                before = conn.execute("SELECT * FROM plan_task WHERE task_id = ? AND user_id = ?", (task_id, user_id)).fetchone()
                if before is None:
                    continue
                before_dict = _row_to_dict(before)
                priority = float(len(ordered_ids) - index)
                conn.execute(
                    "UPDATE plan_task SET priority_score = ?, updated_at = ? WHERE task_id = ? AND user_id = ?",
                    (priority, now, task_id, user_id),
                )
                after = conn.execute("SELECT * FROM plan_task WHERE task_id = ? AND user_id = ?", (task_id, user_id)).fetchone()
                version = {
                    "version_id": f"ver_{uuid.uuid4().hex[:12]}",
                    "task_id": task_id,
                    "reason": reason,
                    "created_at": now,
                }
                conn.execute(
                    "INSERT INTO plan_task_version (version_id, task_id, user_id, before_json, after_json, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (version["version_id"], task_id, user_id, _json_dumps(before_dict), _json_dumps(_row_to_dict(after)), reason, now),
                )
                versions.append(version)
            conn.commit()
        return versions
    def create_practice_session(self, session_type: str, title: str, knowledge_id: str, question_ids: list[str], ai_meta: dict[str, Any] | None = None, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
        now = utc_now()
        session_id = f"prac_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO practice_session (session_id, user_id, session_type, title, knowledge_id,
                    question_ids_json, status, ai_metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (session_id, user_id, session_type, title, knowledge_id, _json_dumps(question_ids), _json_dumps(ai_meta or {}), now),
            )
            conn.commit()
        return self.get_practice_session(session_id, user_id) or {}

    def get_practice_session(self, session_id: str, user_id: str = DEFAULT_USER_ID) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM practice_session WHERE session_id = ? AND user_id = ?", (session_id, user_id)).fetchone()
        return _row_to_dict(row) if row else None

    def active_wrong_question_ids(self, user_id: str = DEFAULT_USER_ID) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT question_id FROM wrong_question WHERE user_id = ? AND review_status != 'mastered' ORDER BY wrong_count DESC, last_wrong_at DESC",
                (user_id,),
            ).fetchall()
        return [str(row["question_id"]) for row in rows]

    def wrong_questions_by_ids(
        self, wrong_ids: list[str], user_id: str = DEFAULT_USER_ID
    ) -> list[dict[str, Any]]:
        ids = [str(item) for item in wrong_ids if str(item)]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT wrong_question.*,
                       COALESCE(NULLIF(manual_wrong_reason, ''), NULLIF(ai_wrong_reason, ''), error_reason) AS wrong_reason,
                       CASE
                           WHEN is_focus = 1 THEN 'focus'
                           WHEN review_status = 'mastered' THEN 'mastered'
                           WHEN retry_count = 0 THEN 'pending_retry'
                           WHEN last_result = 'wrong' THEN 'retry_failed'
                           ELSE review_status
                       END AS wrong_status,
                       1 AS selected_supported
                FROM wrong_question
                WHERE user_id = ? AND wrong_id IN ({placeholders})
                """,
                tuple([user_id, *ids]),
            ).fetchall()
        by_id = {str(row["wrong_id"]): _row_to_dict(row) for row in rows}
        result = [by_id[item] for item in ids if item in by_id]
        for item in result:
            item["is_focus"] = bool(item.get("is_focus"))
            item["selected_supported"] = True
        return result

    def record_practice_submission(self, session: dict[str, Any], results: list[dict[str, Any]], summary: str, next_actions: list[str], user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
        now = utc_now()
        total = len(results)
        correct = sum(1 for item in results if item.get("is_correct"))
        accuracy = correct / total if total else 0.0
        with self._connect() as conn:
            for item in results:
                conn.execute(
                    """
                    INSERT INTO answer_record (answer_id, practice_session_id, user_id, question_id,
                        knowledge_id, user_answer, correct_answer, is_correct, ai_analysis, error_reason, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"ans_{uuid.uuid4().hex[:12]}",
                        session["session_id"],
                        user_id,
                        item["question_id"],
                        item["knowledge_id"],
                        item.get("user_answer", ""),
                        item.get("correct_answer", ""),
                        1 if item.get("is_correct") else 0,
                        item.get("ai_analysis", ""),
                        item.get("error_reason", ""),
                        now,
                    ),
                )
                self._update_mastery(conn, item["knowledge_id"], bool(item.get("is_correct")), user_id, now)
                if item.get("is_correct"):
                    conn.execute("UPDATE wrong_question SET review_status = 'mastered' WHERE user_id = ? AND question_id = ?", (user_id, item["question_id"]))
                else:
                    self._upsert_wrong_question(conn, item, user_id, now)
                if session.get("session_type") == "wrong_retry":
                    retry_meta = session.get("ai_metadata") or {}
                    counted_question_ids = set(retry_meta.get("retry_counted_question_ids") or [])
                    source_question_id = str(
                        (retry_meta.get("source_question_id_by_question_id") or {}).get(
                            str(item.get("question_id") or ""),
                            item.get("question_id") or "",
                        )
                    )
                    self._record_wrong_retry_result(
                        conn,
                        item,
                        user_id,
                        now,
                        source_question_id=source_question_id,
                        increment_retry=source_question_id not in counted_question_ids,
                    )
            record_id = f"rec_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO practice_record (record_id, practice_session_id, user_id, total_count,
                    correct_count, accuracy, analysis_summary, next_actions_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record_id, session["session_id"], user_id, total, correct, accuracy, summary, _json_dumps(next_actions), now),
            )
            conn.execute("UPDATE practice_session SET status = 'submitted', submitted_at = ? WHERE session_id = ? AND user_id = ?", (now, session["session_id"], user_id))
            conn.commit()
        return {
            "record_id": record_id,
            "practice_id": session["session_id"],
            "total_count": total,
            "correct_count": correct,
            "accuracy": accuracy,
            "analysis_summary": summary,
            "next_actions": next_actions,
        }

    def _update_mastery(self, conn: sqlite3.Connection, knowledge_id: str, is_correct: bool, user_id: str, now: str) -> None:
        row = conn.execute("SELECT * FROM mastery_record WHERE user_id = ? AND knowledge_id = ?", (user_id, knowledge_id)).fetchone()
        if row is None:
            base = 55.0 if is_correct else 40.0
            conn.execute(
                "INSERT INTO mastery_record (mastery_id, user_id, knowledge_id, mastery_score, attempts, correct_count, wrong_count, last_practiced_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)",
                (f"mas_{uuid.uuid4().hex[:12]}", user_id, knowledge_id, base, 1 if is_correct else 0, 0 if is_correct else 1, now, now),
            )
            return
        score = float(row["mastery_score"])
        score = min(100.0, score + 8.0) if is_correct else max(0.0, score - 12.0)
        conn.execute(
            """
            UPDATE mastery_record
            SET mastery_score = ?, attempts = attempts + 1,
                correct_count = correct_count + ?, wrong_count = wrong_count + ?,
                last_practiced_at = ?, updated_at = ?
            WHERE user_id = ? AND knowledge_id = ?
            """,
            (score, 1 if is_correct else 0, 0 if is_correct else 1, now, now, user_id, knowledge_id),
        )

    def _upsert_wrong_question(self, conn: sqlite3.Connection, item: dict[str, Any], user_id: str, now: str) -> None:
        next_review = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        error_reason = str(item.get("error_reason") or "")
        conn.execute(
            """
            INSERT INTO wrong_question (wrong_id, user_id, question_id, knowledge_id, question_type,
                error_reason, wrong_count, retry_count, manual_wrong_reason, ai_wrong_reason,
                is_focus, last_retry_at, last_result, review_status, last_wrong_at, next_review_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, 0, '', ?, 0, NULL, 'wrong', 'pending', ?, ?)
            ON CONFLICT(user_id, question_id) DO UPDATE SET
                question_type = excluded.question_type,
                error_reason = excluded.error_reason,
                ai_wrong_reason = excluded.ai_wrong_reason,
                wrong_count = wrong_count + 1,
                review_status = 'pending',
                last_wrong_at = excluded.last_wrong_at,
                next_review_at = excluded.next_review_at
            """,
            (
                f"wrong_{uuid.uuid4().hex[:12]}",
                user_id,
                item["question_id"],
                item["knowledge_id"],
                item.get("question_type", ""),
                error_reason,
                error_reason,
                now,
                next_review,
            ),
        )
        self.upsert_review_item(
            conn,
            user_id=user_id,
            source_type="wrong_question",
            source_id=item["question_id"],
            knowledge_id=item["knowledge_id"],
            title=f"错题二刷 {item['question_id']}",
            prompt=item.get("stem", ""),
            answer=item.get("correct_answer", ""),
            priority_score=4.5,
            next_review_at=next_review,
            now=now,
        )

    def _record_wrong_retry_result(
        self,
        conn: sqlite3.Connection,
        item: dict[str, Any],
        user_id: str,
        now: str,
        *,
        source_question_id: str,
        increment_retry: bool,
    ) -> None:
        last_result = "correct" if item.get("is_correct") else "wrong"
        conn.execute(
            f"""
            UPDATE wrong_question
            SET retry_count = retry_count + ?,
                last_retry_at = ?,
                last_result = ?,
                review_status = CASE WHEN ? = 'correct' THEN 'mastered' ELSE 'pending' END
            WHERE user_id = ? AND question_id = ?
            """,
            (
                1 if increment_retry else 0,
                now,
                last_result,
                last_result,
                user_id,
                source_question_id,
            ),
        )

    def upsert_review_item(self, conn: sqlite3.Connection, *, user_id: str, source_type: str, source_id: str, knowledge_id: str, title: str, prompt: str, answer: str, priority_score: float, next_review_at: str, now: str) -> None:
        conn.execute(
            """
            INSERT INTO review_queue (review_id, user_id, source_type, source_id, knowledge_id, title,
                prompt, answer, priority_score, next_review_at, review_count, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'pending', ?, ?)
            ON CONFLICT(user_id, source_type, source_id) DO UPDATE SET
                title = excluded.title,
                prompt = excluded.prompt,
                answer = excluded.answer,
                priority_score = max(review_queue.priority_score, excluded.priority_score),
                next_review_at = excluded.next_review_at,
                status = 'pending',
                updated_at = excluded.updated_at
            """,
            (f"rev_{uuid.uuid4().hex[:12]}", user_id, source_type, source_id, knowledge_id, title, prompt, answer, priority_score, next_review_at, now, now),
        )

    def list_wrong_questions(
        self,
        user_id: str = DEFAULT_USER_ID,
        *,
        knowledge_id: str | None = None,
        question_type: str | None = None,
        wrong_reason: str | None = None,
        status: str | None = None,
        sort: str = "default",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if knowledge_id:
            clauses.append("knowledge_id = ?")
            params.append(knowledge_id)
        if question_type:
            clauses.append("question_type = ?")
            params.append(question_type)
        if wrong_reason:
            clauses.append(
                "(manual_wrong_reason = ? OR ai_wrong_reason = ? OR error_reason = ?)"
            )
            params.extend([wrong_reason, wrong_reason, wrong_reason])
        if status:
            if status == "focus":
                clauses.append("is_focus = 1")
            elif status == "pending_retry":
                clauses.append("review_status != 'mastered' AND retry_count = 0")
            elif status == "retry_failed":
                clauses.append("last_result = 'wrong'")
            else:
                clauses.append("review_status = ?")
                params.append(status)
        order_by = {
            "wrong_count": "wrong_count DESC, last_wrong_at DESC",
            "recent": "last_wrong_at DESC, wrong_count DESC",
            "knowledge": "knowledge_id ASC, wrong_count DESC",
            "question_type": "question_type ASC, wrong_count DESC",
            "retry_count": "retry_count DESC, last_retry_at DESC",
            "status": "review_status ASC, wrong_count DESC",
        }.get(sort, "review_status = 'mastered', is_focus DESC, wrong_count DESC, last_wrong_at DESC")
        params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT wrong_question.*,
                       COALESCE(NULLIF(manual_wrong_reason, ''), NULLIF(ai_wrong_reason, ''), error_reason) AS wrong_reason,
                       CASE
                           WHEN is_focus = 1 THEN 'focus'
                           WHEN review_status = 'mastered' THEN 'mastered'
                           WHEN retry_count = 0 THEN 'pending_retry'
                           WHEN last_result = 'wrong' THEN 'retry_failed'
                           ELSE review_status
                       END AS wrong_status,
                       1 AS selected_supported
                FROM wrong_question
                WHERE {" AND ".join(clauses)}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
        result = [_row_to_dict(row) for row in rows]
        for item in result:
            item["is_focus"] = bool(item.get("is_focus"))
            item["selected_supported"] = True
        return result

    def wrong_question_summary(self, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
        rows = self.list_wrong_questions(user_id, limit=500)
        active = [item for item in rows if item.get("review_status") != "mastered"]

        def distribution(key: str) -> list[dict[str, Any]]:
            counts = Counter(str(item.get(key) or "未标注") for item in rows)
            return [
                {"key": key_value, "count": count}
                for key_value, count in counts.most_common()
            ]

        wrong_count_top = sorted(
            rows,
            key=lambda item: (int(item.get("wrong_count") or 0), str(item.get("last_wrong_at") or "")),
            reverse=True,
        )[:10]
        repeated = [
            item
            for item in rows
            if int(item.get("wrong_count") or 0) >= 2 or item.get("last_result") == "wrong"
        ][:10]
        return {
            "total": len(rows),
            "unmastered": len(active),
            "focus_count": sum(1 for item in rows if item.get("is_focus")),
            "pending_retry": sum(1 for item in rows if int(item.get("retry_count") or 0) == 0 and item.get("review_status") != "mastered"),
            "by_knowledge": distribution("knowledge_id"),
            "by_question_type": distribution("question_type"),
            "by_wrong_reason": distribution("wrong_reason"),
            "wrong_count_top10": wrong_count_top,
            "repeated_wrong_questions": repeated,
        }

    def register_wrong_retry(
        self,
        wrong_ids: list[str],
        user_id: str = DEFAULT_USER_ID,
        *,
        retry_mode: str = "original",
    ) -> list[dict[str, Any]]:
        rows = self.wrong_questions_by_ids(wrong_ids, user_id)
        if not rows:
            return []
        now = utc_now()
        ids = [str(item["wrong_id"]) for item in rows]
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE wrong_question
                SET retry_count = retry_count + 1,
                    last_retry_at = ?,
                    last_result = '',
                    review_status = CASE WHEN review_status = 'mastered' THEN 'reviewed' ELSE review_status END
                WHERE user_id = ? AND wrong_id IN ({placeholders})
                """,
                tuple([now, user_id, *ids]),
            )
            conn.commit()
        return self.wrong_questions_by_ids(ids, user_id)

    def update_wrong_reason(
        self,
        wrong_id: str,
        wrong_reason: str,
        user_id: str = DEFAULT_USER_ID,
        *,
        reason_source: str = "manual",
    ) -> dict[str, Any] | None:
        column = "ai_wrong_reason" if reason_source == "ai" else "manual_wrong_reason"
        with self._connect() as conn:
            row = conn.execute(
                "SELECT wrong_id FROM wrong_question WHERE user_id = ? AND wrong_id = ?",
                (user_id, wrong_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                f"UPDATE wrong_question SET {column} = ? WHERE user_id = ? AND wrong_id = ?",
                (wrong_reason.strip(), user_id, wrong_id),
            )
            conn.commit()
        rows = self.wrong_questions_by_ids([wrong_id], user_id)
        return rows[0] if rows else None

    def batch_update_wrong_questions(
        self,
        wrong_ids: list[str],
        action: str,
        user_id: str = DEFAULT_USER_ID,
        *,
        wrong_reason: str = "",
    ) -> dict[str, Any]:
        rows = self.wrong_questions_by_ids(wrong_ids, user_id)
        if not rows:
            return {"action": action, "affected_count": 0, "items": []}
        ids = [str(item["wrong_id"]) for item in rows]
        placeholders = ",".join("?" for _ in ids)
        now = utc_now()
        with self._connect() as conn:
            if action == "mark_focus":
                conn.execute(
                    f"UPDATE wrong_question SET is_focus = 1 WHERE user_id = ? AND wrong_id IN ({placeholders})",
                    tuple([user_id, *ids]),
                )
            elif action == "unmark_focus":
                conn.execute(
                    f"UPDATE wrong_question SET is_focus = 0 WHERE user_id = ? AND wrong_id IN ({placeholders})",
                    tuple([user_id, *ids]),
                )
            elif action == "set_reason":
                conn.execute(
                    f"UPDATE wrong_question SET manual_wrong_reason = ? WHERE user_id = ? AND wrong_id IN ({placeholders})",
                    tuple([wrong_reason.strip(), user_id, *ids]),
                )
            elif action == "add_to_review":
                next_review = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
                for item in rows:
                    self.upsert_review_item(
                        conn,
                        user_id=user_id,
                        source_type="wrong_question",
                        source_id=str(item.get("question_id") or ""),
                        knowledge_id=str(item.get("knowledge_id") or ""),
                        title=f"Wrong question retry {item.get('question_id')}",
                        prompt="",
                        answer="",
                        priority_score=5.0,
                        next_review_at=next_review,
                        now=now,
                    )
            conn.commit()
        updated = self.wrong_questions_by_ids(ids, user_id)
        return {"action": action, "affected_count": len(updated), "items": updated}

    def list_reviews_today(self, user_id: str = DEFAULT_USER_ID) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM review_queue
                WHERE user_id = ? AND status IN ('pending', 'failed')
                ORDER BY priority_score DESC, next_review_at ASC
                LIMIT 30
                """,
                (user_id,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def submit_review(self, review_id: str, status: str, user_id: str = DEFAULT_USER_ID) -> dict[str, Any] | None:
        now = utc_now()
        next_days = 3 if status == "mastered" else 1
        next_review = (datetime.now(timezone.utc) + timedelta(days=next_days)).isoformat()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM review_queue WHERE review_id = ? AND user_id = ?", (review_id, user_id)).fetchone()
            if row is None:
                return None
            final_status = "mastered" if status == "mastered" else "pending" if status == "reviewed" else "failed"
            conn.execute(
                "UPDATE review_queue SET status = ?, review_count = review_count + 1, next_review_at = ?, updated_at = ? WHERE review_id = ? AND user_id = ?",
                (final_status, next_review, now, review_id, user_id),
            )
            if final_status in {"mastered", "failed"} and row["knowledge_id"]:
                self._update_mastery(conn, row["knowledge_id"], final_status == "mastered", user_id, now)
            if row["source_type"] == "wrong_question" and final_status == "mastered":
                conn.execute("UPDATE wrong_question SET review_status = 'mastered' WHERE user_id = ? AND question_id = ?", (user_id, row["source_id"]))
            updated = conn.execute("SELECT * FROM review_queue WHERE review_id = ? AND user_id = ?", (review_id, user_id)).fetchone()
            conn.commit()
        return _row_to_dict(updated) if updated else None

    def list_mastery_records(
        self,
        user_id: str = DEFAULT_USER_ID,
        *,
        knowledge_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if knowledge_id:
            clauses.append("knowledge_id = ?")
            params.append(knowledge_id)
        params.extend([max(1, min(int(limit), 200)), max(0, int(offset))])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM mastery_record
                WHERE {" AND ".join(clauses)}
                ORDER BY mastery_score ASC, updated_at DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def replace_learning_path(
        self,
        *,
        user_id: str,
        goal: str,
        source_snapshot_id: str,
        portrait_summary: dict[str, Any],
        evidence: list[dict[str, Any]],
        stages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        now = utc_now()
        path_id = f"path_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                "UPDATE learning_path SET status = 'archived', updated_at = ? WHERE user_id = ? AND status = 'active'",
                (now, user_id),
            )
            conn.execute(
                """
                INSERT INTO learning_path (
                    id, user_id, status, goal, source_snapshot_id,
                    portrait_summary_json, evidence_json, created_at, updated_at
                ) VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?)
                """,
                (
                    path_id,
                    user_id,
                    goal,
                    source_snapshot_id,
                    _json_dumps(portrait_summary),
                    _json_dumps(evidence),
                    now,
                    now,
                ),
            )
            for index, stage in enumerate(stages):
                stage_id = f"stage_{uuid.uuid4().hex[:12]}"
                knowledge_ids = [str(item) for item in stage.get("knowledge_ids", []) if str(item)]
                conn.execute(
                    """
                    INSERT INTO learning_stage (
                        id, path_id, user_id, knowledge_ids_json, title, order_index,
                        unlock_rule_json, pass_threshold, context_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stage_id,
                        path_id,
                        user_id,
                        _json_dumps(knowledge_ids),
                        str(stage.get("title") or f"Stage {index + 1}"),
                        index,
                        _json_dumps(stage.get("unlock_rule") or {"previous_stage_passed": index > 0}),
                        float(stage.get("pass_threshold") or 90),
                        _json_dumps(stage.get("context") or {}),
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO stage_progress (
                        user_id, stage_id, mastery_score, passed, unlocked, attempt_count,
                        last_reason_json, next_action, evidence_json, updated_at
                    ) VALUES (?, ?, 0, 0, ?, 0, '{}', ?, '[]', ?)
                    """,
                    (user_id, stage_id, 1 if index == 0 else 0, "start_stage" if index == 0 else "locked", now),
                )
            conn.commit()
        return self.get_active_learning_path(user_id) or {}

    def get_active_learning_path(self, user_id: str = DEFAULT_USER_ID) -> dict[str, Any] | None:
        with self._connect() as conn:
            path = conn.execute(
                """
                SELECT *
                FROM learning_path
                WHERE user_id = ? AND status = 'active'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            if path is None:
                return None
            stages = conn.execute(
                """
                SELECT *
                FROM learning_stage
                WHERE user_id = ? AND path_id = ?
                ORDER BY order_index
                """,
                (user_id, path["id"]),
            ).fetchall()
            progress = conn.execute(
                """
                SELECT sp.*
                FROM stage_progress sp
                JOIN learning_stage ls ON ls.id = sp.stage_id
                WHERE sp.user_id = ? AND ls.path_id = ?
                """,
                (user_id, path["id"]),
            ).fetchall()
        progress_by_stage = {row["stage_id"]: self._stage_progress_row_to_dict(row) for row in progress}
        path_dict = _row_to_dict(path)
        path_dict["path_id"] = path_dict["id"]
        path_dict["stages"] = []
        for row in stages:
            stage = _row_to_dict(row)
            stage["stage_id"] = stage["id"]
            stage["progress"] = progress_by_stage.get(
                stage["id"],
                {
                    "user_id": user_id,
                    "stage_id": stage["id"],
                    "mastery_score": 0.0,
                    "passed": False,
                    "unlocked": False,
                    "attempt_count": 0,
                    "last_reason": {},
                    "next_action": "locked",
                    "evidence": [],
                },
            )
            path_dict["stages"].append(stage)
        path_dict["current_stage"] = self._current_stage(path_dict["stages"])
        return path_dict

    def get_learning_stage(self, stage_id: str, user_id: str = DEFAULT_USER_ID) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM learning_stage WHERE id = ? AND user_id = ?",
                (stage_id, user_id),
            ).fetchone()
            progress = conn.execute(
                "SELECT * FROM stage_progress WHERE stage_id = ? AND user_id = ?",
                (stage_id, user_id),
            ).fetchone()
        if row is None:
            return None
        stage = _row_to_dict(row)
        stage["stage_id"] = stage["id"]
        stage["progress"] = self._stage_progress_row_to_dict(progress) if progress else None
        return stage

    def update_stage_progress(
        self,
        *,
        user_id: str,
        stage_id: str,
        mastery_score: float,
        passed: bool,
        unlocked: bool,
        reason: dict[str, Any],
        next_action: str,
        evidence: list[dict[str, Any]],
        increment_attempt: bool = False,
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM learning_stage WHERE id = ? AND user_id = ?",
                (stage_id, user_id),
            ).fetchone()
            if exists is None:
                return None
            conn.execute(
                """
                INSERT INTO stage_progress (
                    user_id, stage_id, mastery_score, passed, unlocked, attempt_count,
                    last_reason_json, next_action, evidence_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, stage_id) DO UPDATE SET
                    mastery_score = excluded.mastery_score,
                    passed = excluded.passed,
                    unlocked = max(stage_progress.unlocked, excluded.unlocked),
                    attempt_count = stage_progress.attempt_count + ?,
                    last_reason_json = excluded.last_reason_json,
                    next_action = excluded.next_action,
                    evidence_json = excluded.evidence_json,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    stage_id,
                    max(0.0, min(100.0, float(mastery_score))),
                    1 if passed else 0,
                    1 if unlocked else 0,
                    1 if increment_attempt else 0,
                    _json_dumps(reason),
                    next_action,
                    _json_dumps(evidence),
                    now,
                    1 if increment_attempt else 0,
                ),
            )
            if passed:
                next_stage = conn.execute(
                    """
                    SELECT next.id
                    FROM learning_stage current
                    JOIN learning_stage next
                      ON next.path_id = current.path_id
                     AND next.user_id = current.user_id
                     AND next.order_index = current.order_index + 1
                    WHERE current.id = ? AND current.user_id = ?
                    """,
                    (stage_id, user_id),
                ).fetchone()
                if next_stage is not None:
                    conn.execute(
                        """
                        INSERT INTO stage_progress (
                            user_id, stage_id, mastery_score, passed, unlocked, attempt_count,
                            last_reason_json, next_action, evidence_json, updated_at
                        ) VALUES (?, ?, 0, 0, 1, 0, '{}', 'start_stage', '[]', ?)
                        ON CONFLICT(user_id, stage_id) DO UPDATE SET
                            unlocked = 1,
                            next_action = CASE
                                WHEN stage_progress.passed = 1 THEN stage_progress.next_action
                                ELSE 'start_stage'
                            END,
                            updated_at = excluded.updated_at
                        """,
                        (user_id, next_stage["id"], now),
                    )
            updated = conn.execute(
                "SELECT * FROM stage_progress WHERE user_id = ? AND stage_id = ?",
                (user_id, stage_id),
            ).fetchone()
            conn.commit()
        return self._stage_progress_row_to_dict(updated) if updated else None

    def collect_learning_path_signals(
        self,
        user_id: str = DEFAULT_USER_ID,
        *,
        knowledge_ids: list[str] | None = None,
        limit: int = 80,
    ) -> dict[str, Any]:
        params: list[Any] = [user_id]
        knowledge_clause = ""
        if knowledge_ids:
            filtered = [str(item) for item in knowledge_ids if str(item)]
            if filtered:
                knowledge_clause = "AND knowledge_id IN (" + ",".join("?" for _ in filtered) + ")"
                params.extend(filtered)
        with self._connect() as conn:
            answers = conn.execute(
                f"""
                SELECT *
                FROM answer_record
                WHERE user_id = ? {knowledge_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(params + [max(1, min(int(limit), 200))]),
            ).fetchall()
            wrongs = conn.execute(
                f"""
                SELECT *
                FROM wrong_question
                WHERE user_id = ? {knowledge_clause}
                ORDER BY review_status = 'mastered', wrong_count DESC, last_wrong_at DESC
                """,
                tuple(params),
            ).fetchall()
            reviews = conn.execute(
                f"""
                SELECT *
                FROM review_queue
                WHERE user_id = ? {knowledge_clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                tuple(params + [max(1, min(int(limit), 200))]),
            ).fetchall()
            mastery = conn.execute(
                f"""
                SELECT *
                FROM mastery_record
                WHERE user_id = ? {knowledge_clause}
                ORDER BY mastery_score ASC, updated_at DESC
                """,
                tuple(params),
            ).fetchall()
        return {
            "answers": [_row_to_dict(row) for row in answers],
            "wrong_questions": [_row_to_dict(row) for row in wrongs],
            "reviews": [_row_to_dict(row) for row in reviews],
            "mastery_records": [_row_to_dict(row) for row in mastery],
        }

    def _stage_progress_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["passed"] = bool(data.get("passed"))
        data["unlocked"] = bool(data.get("unlocked"))
        data["last_reason"] = _json_loads(data.pop("last_reason_json", "{}"), {})
        data["evidence"] = _json_loads(data.pop("evidence_json", "[]"), [])
        return data

    def _current_stage(self, stages: list[dict[str, Any]]) -> dict[str, Any] | None:
        for stage in stages:
            progress = stage.get("progress") or {}
            if progress.get("unlocked") and not progress.get("passed"):
                return stage
        for stage in reversed(stages):
            if (stage.get("progress") or {}).get("passed"):
                return stage
        return stages[0] if stages else None

    def dashboard_summary(self, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
        with self._connect() as conn:
            tasks = conn.execute("SELECT count(*) total, sum(status = 'completed') completed FROM plan_task WHERE user_id = ?", (user_id,)).fetchone()
            practice = conn.execute("SELECT count(*) sessions, avg(accuracy) avg_accuracy FROM practice_record WHERE user_id = ?", (user_id,)).fetchone()
            wrong_count = conn.execute("SELECT count(*) FROM wrong_question WHERE user_id = ? AND review_status != 'mastered'", (user_id,)).fetchone()[0]
            review_count = conn.execute("SELECT count(*) FROM review_queue WHERE user_id = ? AND status IN ('pending', 'failed')", (user_id,)).fetchone()[0]
            mastery_rows = conn.execute("SELECT mastery_score FROM mastery_record WHERE user_id = ?", (user_id,)).fetchall()
            weak_rows = conn.execute(
                """
                SELECT knowledge_id, wrong_count
                FROM wrong_question
                WHERE user_id = ? AND review_status != 'mastered'
                ORDER BY wrong_count DESC, last_wrong_at DESC
                LIMIT 8
                """,
                (user_id,),
            ).fetchall()
        total = int(tasks["total"] or 0)
        completed = int(tasks["completed"] or 0)
        scores = [float(row["mastery_score"]) for row in mastery_rows]
        today_tasks = self.list_today_tasks(user_id)
        profile = self.get_profile(user_id)
        latest_report = self.list_diagnostic_reports(user_id, limit=1, offset=0)
        active_plan = self.get_active_plan(user_id)
        return {
            "task_total": total,
            "task_completed": completed,
            "completion_rate": completed / total if total else 0.0,
            "practice_sessions": int(practice["sessions"] or 0),
            "accuracy": float(practice["avg_accuracy"] or 0.0),
            "wrong_count": int(wrong_count),
            "review_due_count": int(review_count),
            "mastery_average": sum(scores) / len(scores) if scores else 0.0,
            "mastery_distribution": {
                "low": sum(1 for score in scores if score < 50),
                "medium": sum(1 for score in scores if 50 <= score < 75),
                "high": sum(1 for score in scores if score >= 75),
            },
            "today_tasks": today_tasks,
            "weak_modules": (profile or {}).get("weak_modules", []),
            "weak_knowledge_ids": [str(row["knowledge_id"]) for row in weak_rows],
            "recent_diagnostic_report": latest_report[0] if latest_report else None,
            "active_plan": active_plan,
        }

    def create_diagnostic_report(
        self,
        *,
        user_id: str,
        session_id: str,
        mode: str,
        profile_snapshot: dict[str, Any],
        answer_summary: dict[str, Any],
        profile_draft: dict[str, Any],
        summary: str,
        weak_knowledge_ids: list[str] | None = None,
        score_summary: dict[str, Any] | None = None,
        recommendations: list[str] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        report_id = f"diagrep_{uuid.uuid4().hex[:12]}"
        report_weak_ids = weak_knowledge_ids or self._derive_weak_knowledge_ids(answer_summary)
        report_score_summary = score_summary or self._derive_score_summary(answer_summary)
        report_recommendations = recommendations or self._derive_recommendations(profile_draft)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO diagnostic_report (
                    report_id, user_id, session_id, mode, profile_snapshot_json,
                    answer_summary_json, profile_draft_json, weak_knowledge_ids_json,
                    score_summary_json, recommendations_json, summary, confirmed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    report_id,
                    user_id,
                    session_id,
                    mode,
                    _json_dumps(profile_snapshot),
                    _json_dumps(answer_summary),
                    _json_dumps(profile_draft),
                    _json_dumps(report_weak_ids),
                    _json_dumps(report_score_summary),
                    _json_dumps(report_recommendations),
                    summary,
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get_diagnostic_report(report_id, user_id) or {}

    def list_diagnostic_reports(self, user_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM diagnostic_report
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, int(limit), int(offset)),
            ).fetchall()
        return [self._diagnostic_report_row_to_dict(row) for row in rows]

    def get_diagnostic_report(self, report_id: str, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM diagnostic_report WHERE report_id = ? AND user_id = ?",
                (report_id, user_id),
            ).fetchone()
        return self._diagnostic_report_row_to_dict(row) if row else None

    def get_latest_confirmed_diagnostic_report(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM diagnostic_report
                WHERE user_id = ? AND confirmed = 1
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return self._diagnostic_report_row_to_dict(row) if row else None

    def confirm_diagnostic_report(self, report_id: str, user_id: str) -> dict[str, Any] | None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE diagnostic_report SET confirmed = 1, updated_at = ? WHERE report_id = ? AND user_id = ?",
                (now, report_id, user_id),
            )
            row = conn.execute(
                "SELECT * FROM diagnostic_report WHERE report_id = ? AND user_id = ?",
                (report_id, user_id),
            ).fetchone()
            conn.commit()
        return self._diagnostic_report_row_to_dict(row) if row else None

    def _diagnostic_report_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["profile_snapshot"] = _json_loads(data.pop("profile_snapshot_json", "{}"), {})
        data["answer_summary"] = _json_loads(data.pop("answer_summary_json", "{}"), {})
        data["profile_draft"] = _json_loads(data.pop("profile_draft_json", "{}"), {})
        data["weak_knowledge_ids"] = _json_loads(data.pop("weak_knowledge_ids_json", "[]"), [])
        data["score_summary"] = _json_loads(data.pop("score_summary_json", "{}"), {})
        data["recommendations"] = _json_loads(data.pop("recommendations_json", "[]"), [])
        data["confirmed"] = bool(data.get("confirmed"))
        subjects = data["profile_snapshot"].get("subjects") or []
        data["subject"] = data["profile_snapshot"].get("subject") or (subjects[0] if subjects else "math")
        return data

    def _derive_weak_knowledge_ids(self, answer_summary: dict[str, Any]) -> list[str]:
        weak_ids: list[str] = []
        for item in answer_summary.get("answers") or []:
            if not isinstance(item, dict) or item.get("is_correct"):
                continue
            knowledge_id = str(item.get("knowledge_id") or "")
            if knowledge_id and knowledge_id not in weak_ids:
                weak_ids.append(knowledge_id)
        return weak_ids[:12]

    def _derive_score_summary(self, answer_summary: dict[str, Any]) -> dict[str, Any]:
        total = int(answer_summary.get("total") or 0)
        correct = int(answer_summary.get("correct") or 0)
        accuracy = float(answer_summary.get("accuracy") or (correct / total if total else 0.0))
        return {
            "total": total,
            "correct": correct,
            "wrong": max(0, total - correct),
            "accuracy": accuracy,
        }

    def _derive_recommendations(self, profile_draft: dict[str, Any]) -> list[str]:
        plan_focus = profile_draft.get("plan_focus") if isinstance(profile_draft, dict) else []
        if isinstance(plan_focus, list) and plan_focus:
            return [str(item) for item in plan_focus[:6]]
        weak_modules = profile_draft.get("weak_modules") if isinstance(profile_draft, dict) else []
        if isinstance(weak_modules, list) and weak_modules:
            return [f"Prioritize review for {item}" for item in weak_modules[:6]]
        return []
    def log_ai_action(self, *, action_type: str, prompt: str, model: str = "", status: str, response_text: str = "", error_message: str = "", payload: dict[str, Any] | None = None, user_id: str = DEFAULT_USER_ID) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ai_action_log (log_id, user_id, action_type, prompt, model, status, response_text, error_message, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"ai_{uuid.uuid4().hex[:12]}", user_id, action_type, prompt, model, status, response_text, error_message, _json_dumps(payload or {}), utc_now()),
            )
            conn.commit()


@lru_cache(maxsize=1)
def get_learning_store() -> KaoyanLearningStore:
    return KaoyanLearningStore()
