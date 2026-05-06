from __future__ import annotations

from pathlib import Path
import uuid

from deeptutor.kaoyan.learning_store import KaoyanLearningStore


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