from __future__ import annotations

from pathlib import Path
import sqlite3
from types import SimpleNamespace
import uuid

import pytest

from master_prep_ai.api.routers import kaoyan as kaoyan_router
from master_prep_ai.kaoyan.content_store import KaoyanContentStore
from master_prep_ai.kaoyan.learning_path import KaoyanLearningPathService
from master_prep_ai.kaoyan.learning_store import KaoyanLearningStore
from master_prep_ai.kaoyan.pdf_renderer import PdfRenderError, build_practice_tex, render_practice_pdf
from master_prep_ai.kaoyan.practice import KaoyanPracticeService


def _runtime_db(name: str) -> Path:
    root = Path("tests") / "kaoyan_runtime"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{name}_{uuid.uuid4().hex}.sqlite"


def test_diagnostic_reports_are_user_scoped():
    store = KaoyanLearningStore(_runtime_db("reports"))
    report_a = store.create_diagnostic_report(
        user_id="user-a",
        session_id="diag-a",
        mode="light",
        profile_snapshot={"target_school": "A"},
        answer_summary={"total": 2, "correct": 1, "accuracy": 0.5},
        profile_draft={"baseline_level": "basic", "weak_modules": ["limits"]},
        summary="A summary",
    )
    report_b = store.create_diagnostic_report(
        user_id="user-b",
        session_id="diag-b",
        mode="deep",
        profile_snapshot={"target_school": "B"},
        answer_summary={"total": 2, "correct": 2, "accuracy": 1.0},
        profile_draft={"baseline_level": "strong", "weak_modules": []},
        summary="B summary",
    )

    assert [item["report_id"] for item in store.list_diagnostic_reports("user-a")] == [report_a["report_id"]]
    assert store.get_diagnostic_report(report_b["report_id"], "user-a") is None
    assert store.confirm_diagnostic_report(report_b["report_id"], "user-a") is None
    confirmed = store.confirm_diagnostic_report(report_a["report_id"], "user-a")
    assert confirmed is not None
    assert confirmed["confirmed"] is True


def test_profile_plan_task_and_dashboard_are_user_scoped():
    store = KaoyanLearningStore(_runtime_db("member_a_store"))

    profile_a = store.upsert_profile(
        {
            "target_school": "A University",
            "target_major": "CS",
            "exam_date": "2026-12-20",
            "daily_minutes": 150,
            "target_score": 140,
            "baseline_level": "basic",
            "weak_modules": ["limits"],
            "subjects": ["math"],
            "stage": "foundation",
            "preferences": {"pace": "steady"},
        },
        user_id="user-a",
    )
    store.upsert_profile({"target_school": "B University"}, user_id="user-b")

    assert profile_a["subjects"] == ["math"]
    assert profile_a["stage"] == "foundation"
    assert profile_a["preferences"] == {"pace": "steady"}
    assert store.get_profile("user-b")["target_school"] == "B University"

    plan = store.create_plan(
        "Plan A",
        [
            {
                "task_type": "study",
                "title": "Study limits",
                "estimated_minutes": 30,
                "due_at": "2000-01-01",
                "related_knowledge_ids": ["K_LIMIT"],
            }
        ],
        {"status": "fallback"},
        user_id="user-a",
    )
    task = store.list_today_tasks("user-a")[0]

    assert task["plan_id"] == plan["plan_id"]
    assert task["knowledge_ids"] == ["K_LIMIT"]
    assert task["due_date"] == "2000-01-01"
    assert task["priority"] == task["priority_score"]
    assert store.update_task_status(task["task_id"], "done", "user-b") is None
    updated = store.update_task_status(task["task_id"], "done", "user-a")
    assert updated["status"] == "completed"
    deferred = store.update_task_status(task["task_id"], "deferred", "user-a")
    assert deferred["status"] == "skipped"

    summary_a = store.dashboard_summary("user-a")
    summary_b = store.dashboard_summary("user-b")
    assert summary_a["task_total"] == 1
    assert summary_a["today_tasks"][0]["task_id"] == task["task_id"]
    assert summary_a["today_tasks"][0]["knowledge_ids"] == ["K_LIMIT"]
    assert summary_a["active_plan"]["ai_metadata"]["status"] == "fallback"
    assert summary_b["task_total"] == 0


def test_diagnostic_report_compatibility_fields_are_derived():
    store = KaoyanLearningStore(_runtime_db("report_compat"))

    report = store.create_diagnostic_report(
        user_id="user-a",
        session_id="diag-a",
        mode="light",
        profile_snapshot={"target_school": "A"},
        answer_summary={
            "total": 2,
            "correct": 1,
            "accuracy": 0.5,
            "answers": [
                {"question_id": "q1", "knowledge_id": "K_LIMIT", "is_correct": False},
                {"question_id": "q2", "knowledge_id": "K_DERIVATIVE", "is_correct": True},
            ],
        },
        profile_draft={
            "baseline_level": "basic",
            "weak_modules": ["limits"],
            "plan_focus": ["Review limits first"],
        },
        summary="A summary",
    )

    assert report["weak_knowledge_ids"] == ["K_LIMIT"]
    assert report["score_summary"] == {"total": 2, "correct": 1, "wrong": 1, "accuracy": 0.5}
    assert report["recommendations"] == ["Review limits first"]
    assert report["subject"] == "math"

    confirmed = store.confirm_diagnostic_report(report["report_id"], "user-a")
    latest = store.get_latest_confirmed_diagnostic_report("user-a")
    assert confirmed["report_id"] == latest["report_id"]


def test_learning_path_refresh_from_diagnostic():
    content = KaoyanContentStore(_content_db("path_refresh_content"))
    store = KaoyanLearningStore(_runtime_db("path_refresh"))
    report = store.create_diagnostic_report(
        user_id="user-a",
        session_id="diag-a",
        mode="light",
        profile_snapshot={"target_school": "A"},
        answer_summary={
            "total": 1,
            "correct": 0,
            "accuracy": 0,
            "answers": [{"question_id": "q_choice", "knowledge_id": "K_LIMIT", "is_correct": False}],
        },
        profile_draft={"baseline_level": "basic", "weak_modules": ["limits"]},
        summary="A summary",
    )
    store.confirm_diagnostic_report(report["report_id"], "user-a")

    path = KaoyanLearningPathService(content, store).refresh_learning_path("user-a")

    assert path["status"] == "active"
    assert path["source_snapshot_id"] == report["report_id"]
    assert path["current_stage"]["progress"]["unlocked"] is True
    assert len(path["stages"]) >= 1


@pytest.mark.asyncio
async def test_stage_submit_mastery_gate():
    content = KaoyanContentStore(_content_db("stage_gate_content"))
    store = KaoyanLearningStore(_runtime_db("stage_gate"))
    service = KaoyanLearningPathService(content, store)
    path = service.refresh_learning_path("user-a")
    stage = path["current_stage"]

    low = await service.submit_stage(stage["stage_id"], {"answers": []}, "user-a")
    assert low is not None
    assert low["passed"] is False
    assert low["unlock_next_stage"] is False

    session = store.create_practice_session(
        "stage",
        "Stage practice",
        "K_LIMIT",
        [f"q_pass_{index}" for index in range(10)],
        user_id="user-a",
    )
    store.record_practice_submission(
        session,
        [
            {
                "question_id": f"q_pass_{index}",
                "knowledge_id": "K_LIMIT",
                "difficulty_level": 5,
                "user_answer": "A",
                "correct_answer": "A",
                "is_correct": True,
            }
            for index in range(10)
        ],
        "all correct",
        [],
        "user-a",
    )

    high = await service.submit_stage(stage["stage_id"], {"answers": []}, "user-a")
    assert high is not None
    assert high["mastery_score"] >= 90
    assert high["passed"] is True


def test_learning_path_fallback_without_llm_and_user_isolation():
    content = KaoyanContentStore(_content_db("path_isolation_content"))
    store = KaoyanLearningStore(_runtime_db("path_isolation"))
    service = KaoyanLearningPathService(content, store)

    path_a = service.refresh_learning_path("user-a")
    path_b = service.refresh_learning_path("user-b")

    assert path_a["path_id"] != path_b["path_id"]
    assert path_a["user_id"] == "user-a"
    assert path_b["user_id"] == "user-b"
    assert path_a["current_stage"]["progress"]["mastery_score"] >= 0
    assert path_a["current_stage"]["progress"]["last_reason"]["summary"]


@pytest.mark.asyncio
async def test_learning_path_updates_after_practice_wrong_review():
    content = KaoyanContentStore(_content_db("path_wrong_content"))
    store = KaoyanLearningStore(_runtime_db("path_wrong"))
    service = KaoyanLearningPathService(content, store)
    path = service.refresh_learning_path("user-a")
    stage = path["current_stage"]
    session = store.create_practice_session("stage", "Stage practice", "K_LIMIT", ["q_wrong"], user_id="user-a")
    store.record_practice_submission(
        session,
        [
            {
                "question_id": "q_wrong",
                "knowledge_id": "K_LIMIT",
                "difficulty_level": 3,
                "user_answer": "B",
                "correct_answer": "A",
                "is_correct": False,
                "error_reason": "concept confusion",
            }
        ],
        "wrong",
        [],
        "user-a",
    )

    result = await service.submit_stage(stage["stage_id"], {"answers": []}, "user-a")

    assert result is not None
    assert result["passed"] is False
    assert result["reason"]["blockers"]
    assert any(item["type"] == "wrong_question" and item["count"] >= 1 for item in result["evidence"])


def _content_db(name: str) -> Path:
    path = _runtime_db(name)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE knowledge_points (
                knowledge_id TEXT PRIMARY KEY,
                subject TEXT,
                module TEXT,
                chapter TEXT,
                section TEXT,
                knowledge_name TEXT,
                parent_id TEXT,
                importance_level INTEGER,
                is_core INTEGER,
                raw_markdown TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE questions (
                question_id TEXT PRIMARY KEY,
                knowledge_id TEXT,
                question_type TEXT,
                difficulty_level INTEGER,
                stem TEXT,
                answer TEXT,
                analysis TEXT,
                source TEXT,
                source_type TEXT,
                year INTEGER
            )
            """
        )
        conn.execute("INSERT INTO knowledge_points VALUES ('K_LIMIT', 'math', '高数', '极限', '函数极限', '函数极限', '', 5, 1, '')")
        rows = [
            ("q_choice", "K_LIMIT", "选择题", 1, "下列正确的是\n(A) A\n(B) B", "A", "choice analysis", "test", "unit", 2025),
            ("q_fill", "K_LIMIT", "填空题", 2, "求极限 ______", "1", "fill analysis", "test", "unit", 2025),
            ("q_solution", "K_LIMIT", "综合题", 3, "证明函数连续", "略", "solution analysis", "test", "unit", 2025),
        ]
        conn.executemany("INSERT INTO questions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        conn.commit()
    return path


def test_online_practice_defaults_to_choice_questions_and_pdf_uses_free_response():
    content = KaoyanContentStore(_content_db("question_family"))
    learning = KaoyanLearningStore(_runtime_db("question_family_learning"))
    service = KaoyanPracticeService(content, learning)

    session = service.create_session(knowledge_id="K_LIMIT", limit=5, user_id="user-a")
    assert session["questions"]
    assert all(question["is_choice"] for question in session["questions"])

    payload = service.create_pdf_payload(knowledge_id="K_LIMIT", limit=5, user_id="user-a")
    assert {question["question_id"] for question in payload["questions"]} == {"q_fill", "q_solution"}
    assert learning.get_practice_session(payload.get("session_id", ""), "user-a") is None

    fixed_payload = service.create_pdf_payload(question_ids=["q_choice", "q_fill"], limit=5, user_id="user-a")
    assert [question["question_id"] for question in fixed_payload["questions"]] == ["q_fill"]


def test_practice_tex_escapes_chinese_and_latex_special_chars():
    tex = build_practice_tex(
        {
            "title": "中文题单 & 100%",
            "questions": [
                {
                    "question_type": "填空题",
                    "difficulty_level": 2,
                    "stem": "求 f(x)=x_1 的极限 #1",
                    "answer": "1_0",
                    "analysis": "注意 50% 与 {集合}",
                }
            ],
        }
    )

    assert "\\documentclass[UTF8" in tex
    assert "中文题单 \\& 100\\%" in tex
    assert "x\\_1" in tex
    assert "参考答案与解析" in tex



def test_practice_tex_preserves_math_segments_and_normalizes_symbols():
    tex = build_practice_tex(
        {
            "title": "Math PDF",
            "questions": [
                {
                    "question_type": "填空题",
                    "difficulty_level": 3,
                    "stem": r"求 $\lim_{x\to0}\frac{x^2}{\sqrt{x+1}}$ ，并说明 x ≥ 0 且 x ≠ 1。",
                    "answer": r"$\frac{1}{2}$",
                    "analysis": "若 x≤1 ，则 $x^2 \\to 0$。\uffff",
                }
            ],
        }
    )

    assert r"$\lim_{x\to0}\frac{x^2}{\sqrt{x+1}}$" in tex
    assert r"x $\geq$ 0" in tex
    assert r"x $\ne$ 1" in tex
    assert r"x$\leq$1" in tex
    assert "\uffff" not in tex
    assert r"\textbackslash{}lim" not in tex


def test_practice_tex_converts_fill_blanks_without_touching_subscripts():
    tex = build_practice_tex(
        {
            "title": "Blank PDF",
            "questions": [
                {
                    "question_type": "填空题",
                    "difficulty_level": 3,
                    "stem": r"$x_1 + x_2$；普通变量 x_1；答案为 \_\_\_\_；定义域为 ____。",
                    "answer": r"$\_\_\_$",
                    "analysis": r"空线 \_\_\_ 不应显示反斜杠。",
                }
            ],
        }
    )

    assert tex.count(r"\underline{\hspace{2.8cm}}") == 4
    assert r"$x_1 + x_2$" in tex
    assert r"x\_1" in tex
    assert r"\_\_\_" not in tex
    assert "____" not in tex

def test_render_practice_pdf_reports_missing_xelatex(monkeypatch):
    monkeypatch.delenv("KAOYAN_XELATEX_PATH", raising=False)
    monkeypatch.setattr("master_prep_ai.kaoyan.pdf_renderer.shutil.which", lambda name: None)

    with pytest.raises(PdfRenderError, match="XeLaTeX was not found"):
        render_practice_pdf({"title": "PDF", "questions": []})


@pytest.mark.asyncio
async def test_practice_pdf_download_endpoint_returns_pdf(monkeypatch):
    class FakeService:
        def __init__(self, *_args, **_kwargs):
            pass

        def create_pdf_payload(self, **kwargs):
            assert kwargs["user_id"] == "user-a"
            assert kwargs["question_ids"] == ["q_fill"]
            return {
                "title": "PDF",
                "filename": "practice.pdf",
                "questions": [{"question_id": "q_fill", "question_type": "填空题", "stem": "题干"}],
            }

    monkeypatch.setattr(kaoyan_router, "KaoyanPracticeService", FakeService)
    monkeypatch.setattr(kaoyan_router, "render_practice_pdf", lambda payload: b"%PDF-1.7\nok")

    response = await kaoyan_router.download_practice_pdf(
        kaoyan_router.PracticePdfRequest(question_ids=["q_fill"], limit=1),
        SimpleNamespace(user_id="user-a"),
    )

    assert response.media_type == "application/pdf"
    assert response.body.startswith(b"%PDF")
    assert response.headers["content-disposition"] == 'attachment; filename="practice.pdf"'
