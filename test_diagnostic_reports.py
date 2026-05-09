from __future__ import annotations

from pathlib import Path
import uuid

from master_prep_ai.kaoyan.learning_store import KaoyanLearningStore


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
