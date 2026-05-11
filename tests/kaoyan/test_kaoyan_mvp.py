from __future__ import annotations

import asyncio
from pathlib import Path
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from master_prep_ai.api.routers import kaoyan as kaoyan_router
from master_prep_ai.auth import AuthUser
from master_prep_ai.kaoyan.content_store import KaoyanContentStore, default_content_db_path
from master_prep_ai.kaoyan.learning_store import KaoyanLearningStore
from master_prep_ai.kaoyan.practice import KaoyanPracticeService

CONTENT_DB = default_content_db_path()


def test_content_store_reads_high_math_package() -> None:
    store = KaoyanContentStore(CONTENT_DB)

    health = store.health()
    tree = store.knowledge_tree()
    questions = store.select_questions(limit=3)

    assert health["counts"]["knowledge_points"] >= 40
    assert health["counts"]["questions"] >= 1000
    assert tree
    assert len(questions) == 3
    assert questions[0]["question_id"].startswith("MATH_Q_")


def _runtime_db(name: str) -> Path:
    root = Path("tests") / "kaoyan_runtime"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{name}_{uuid.uuid4().hex}.sqlite"


def test_practice_submission_creates_wrong_question_and_review(monkeypatch) -> None:
    content = KaoyanContentStore(CONTENT_DB)
    learning = KaoyanLearningStore(_runtime_db("learning"))
    service = KaoyanPracticeService(content, learning)

    async def fake_text(**kwargs):
        return "错因：概念不清\n复盘建议：回看知识点并二刷。", {"message": "AI 已生成增强结果"}

    monkeypatch.setattr(service.ai, "complete_text", fake_text)

    session = service.create_session(knowledge_id="MATH_GS_CH_01_SEC_01", limit=1)
    result = asyncio.run(service.submit_session(
        session["session_id"],
        [{"question_id": session["questions"][0]["question_id"], "answer": "明显错误"}],
    ))

    assert result is not None
    assert result["total_count"] == 1
    assert result["wrong_question_ids"]
    assert learning.list_wrong_questions()
    assert learning.list_reviews_today()
    assert learning.dashboard_summary()["wrong_count"] == 1


def test_kaoyan_api_loop_uses_fallback_when_ai_fails(monkeypatch) -> None:
    content = KaoyanContentStore(CONTENT_DB)
    learning = KaoyanLearningStore(_runtime_db("api_learning"))

    monkeypatch.setattr(kaoyan_router, "get_content_store", lambda: content)
    monkeypatch.setattr(kaoyan_router, "get_learning_store", lambda: learning)

    from master_prep_ai.kaoyan import ai_service

    async def fail_complete(*args, **kwargs):
        raise RuntimeError("no model in test")

    monkeypatch.setattr(ai_service, "call_llm_complete", fail_complete)

    app = FastAPI()
    app.dependency_overrides[kaoyan_router.require_current_user] = lambda: AuthUser(
        user_id="test-user", email="student@example.com", display_name="Student", role="student"
    )
    app.include_router(kaoyan_router.router, prefix="/api/v1/kaoyan")
    client = TestClient(app)

    profile = client.post(
        "/api/v1/kaoyan/profile/init",
        json={
            "target_school": "测试大学",
            "target_major": "计算机",
            "exam_date": "2026-12-20",
            "daily_minutes": 120,
            "target_score": 120,
            "baseline_level": "基础",
            "weak_modules": ["极限"],
        },
    )
    assert profile.status_code == 200

    plan = client.post("/api/v1/kaoyan/plans/generate")
    assert plan.status_code == 200
    assert plan.json()["tasks"]
    assert plan.json()["ai_metadata"]["status"] == "fallback"

    tasks = client.get("/api/v1/kaoyan/tasks/today")
    assert tasks.status_code == 200
    assert tasks.json()

    practice = client.post(
        "/api/v1/kaoyan/practice/session",
        json={"knowledge_id": "MATH_GS_CH_01_SEC_01", "limit": 1},
    )
    assert practice.status_code == 200
    session = practice.json()

    submitted = client.post(
        f"/api/v1/kaoyan/practice/{session['session_id']}/submit",
        json={"answers": [{"question_id": session["questions"][0]["question_id"], "answer": "错误答案"}]},
    )
    assert submitted.status_code == 200
    assert submitted.json()["wrong_question_ids"]

    assert client.get("/api/v1/kaoyan/wrong-questions").json()
    assert client.get("/api/v1/kaoyan/reviews/today").json()
    assert client.get("/api/v1/kaoyan/dashboard/summary").json()["wrong_count"] == 1

def test_kaoyan_feedback_interfaces(monkeypatch) -> None:
    content = KaoyanContentStore(CONTENT_DB)
    learning = KaoyanLearningStore(_runtime_db("feedback_interfaces"))

    monkeypatch.setattr(kaoyan_router, "get_content_store", lambda: content)
    monkeypatch.setattr(kaoyan_router, "get_learning_store", lambda: learning)

    from master_prep_ai.kaoyan import ai_service

    async def fail_complete(*args, **kwargs):
        raise RuntimeError("no model in test")

    monkeypatch.setattr(ai_service, "call_llm_complete", fail_complete)

    app = FastAPI()
    app.dependency_overrides[kaoyan_router.require_current_user] = lambda: AuthUser(
        user_id="feedback-user", email="feedback@example.com", display_name="Feedback", role="student"
    )
    app.include_router(kaoyan_router.router, prefix="/api/v1/kaoyan")
    client = TestClient(app)

    profile = client.post(
        "/api/v1/kaoyan/profile/init",
        json={
            "target_school": "Test University",
            "target_major": "CS",
            "exam_date": "2026-12-20",
            "daily_minutes": 120,
            "target_score": 120,
            "baseline_level": "basic",
            "weak_modules": ["limit"],
        },
    )
    assert profile.status_code == 200

    plan = client.post("/api/v1/kaoyan/plans/generate")
    assert plan.status_code == 200
    assert plan.json()["tasks"]

    reorder = client.post(
        "/api/v1/kaoyan/plans/reorder",
        json={"trigger_reason": "test", "completion_rate": 0.2, "mastery_scores": {}, "remaining_days": 20},
    )
    assert reorder.status_code == 200
    assert reorder.json()["new_task_order"]

    material = client.post("/api/v1/kaoyan/materials/parse", json={"filename": "test.pdf", "content_type": "pdf"})
    assert material.status_code == 200
    task = client.get(f"/api/v1/kaoyan/materials/tasks/{material.json()['task_id']}")
    assert task.status_code == 200
    assert task.json()["status"] == "completed"

    rag = client.post("/api/v1/kaoyan/rag/query", json={"kb_name": "dummy_kb", "query": "test query"})
    assert rag.status_code == 200
    assert "results" in rag.json()

    practice = client.post(
        "/api/v1/kaoyan/practice/session",
        json={"knowledge_id": "MATH_GS_CH_01_SEC_01", "limit": 1},
    )
    assert practice.status_code == 200
    session = practice.json()

    submitted = client.post(
        f"/api/v1/kaoyan/practice/{session['session_id']}/submit",
        json={"answers": [{"question_id": session["questions"][0]["question_id"], "answer": "wrong"}]},
    )
    assert submitted.status_code == 200
    assert submitted.json()["wrong_question_ids"]

    similar = client.post(
        "/api/v1/kaoyan/practice/session",
        json={"session_type": "similar", "source_question_id": session["questions"][0]["question_id"], "limit": 1},
    )
    assert similar.status_code == 200
    assert similar.json()["questions"]

    reviews = client.get("/api/v1/kaoyan/reviews/today").json()
    assert reviews
    review = client.post(f"/api/v1/kaoyan/reviews/{reviews[0]['review_id']}/submit", json={"status": "mastered"})
    assert review.status_code == 200

    mastery = client.get("/api/v1/kaoyan/mastery/records")
    assert mastery.status_code == 200
    assert mastery.json()["records"]

    exam = client.post(
        "/api/v1/kaoyan/exam/simulation",
        json={"knowledge_id": "MATH_GS_CH_01_SEC_01", "limit": 1, "time_limit_minutes": 10},
    )
    assert exam.status_code == 200
    simulation = exam.json()
    assert simulation["simulation_id"]
    assert simulation["practice_session"]["questions"]

    exam_submit = client.post(
        f"/api/v1/kaoyan/exam/{simulation['simulation_id']}/submit",
        json={
            "elapsed_seconds": 120,
            "answers": [{"question_id": simulation["practice_session"]["questions"][0]["question_id"], "answer": "wrong"}],
        },
    )
    assert exam_submit.status_code == 200
    assert "score_report" in exam_submit.json()


def test_member_a_profile_diagnostic_plan_dashboard_api(monkeypatch) -> None:
    content = KaoyanContentStore(CONTENT_DB)
    learning = KaoyanLearningStore(_runtime_db("member_a_api"))

    monkeypatch.setattr(kaoyan_router, "get_content_store", lambda: content)
    monkeypatch.setattr(kaoyan_router, "get_learning_store", lambda: learning)

    from master_prep_ai.kaoyan import ai_service

    async def fail_complete(*args, **kwargs):
        raise RuntimeError("no model in test")

    monkeypatch.setattr(ai_service, "call_llm_complete", fail_complete)

    current_user = {"user_id": "member-a"}

    def auth_user():
        return AuthUser(
            user_id=current_user["user_id"],
            email=f"{current_user['user_id']}@example.com",
            display_name=current_user["user_id"],
            role="student",
        )

    app = FastAPI()
    app.dependency_overrides[kaoyan_router.require_current_user] = auth_user
    app.include_router(kaoyan_router.router, prefix="/api/v1/kaoyan")
    client = TestClient(app)

    assert client.get("/api/v1/kaoyan/profile/me").json() is None

    profile = client.post(
        "/api/v1/kaoyan/profile/init",
        json={
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
    )
    assert profile.status_code == 200
    assert profile.json()["subjects"] == ["math"]
    assert client.get("/api/v1/kaoyan/profile/me").json()["stage"] == "foundation"

    diagnostic = client.post("/api/v1/kaoyan/diagnostic/session", json={"mode": "light"})
    assert diagnostic.status_code == 200
    session = diagnostic.json()
    submitted = client.post(
        f"/api/v1/kaoyan/diagnostic/{session['session_id']}/submit",
        json={"answers": [{"question_id": session["questions"][0]["question_id"], "answer": "wrong"}]},
    )
    assert submitted.status_code == 200
    report = submitted.json()["report"]
    assert report["user_id"] == "member-a"
    assert "score_summary" in report
    assert "weak_knowledge_ids" in report

    reports = client.get("/api/v1/kaoyan/diagnostic/reports").json()["reports"]
    assert [item["report_id"] for item in reports] == [report["report_id"]]

    current_user["user_id"] = "member-b"
    assert client.get(f"/api/v1/kaoyan/diagnostic/reports/{report['report_id']}").status_code == 404
    assert client.patch(f"/api/v1/kaoyan/diagnostic/reports/{report['report_id']}/confirm").status_code == 404

    current_user["user_id"] = "member-a"
    confirmed = client.patch(f"/api/v1/kaoyan/diagnostic/reports/{report['report_id']}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["confirmed"] is True

    plan = client.post("/api/v1/kaoyan/plans/generate")
    assert plan.status_code == 200
    assert plan.json()["tasks"]
    assert plan.json()["ai_metadata"]["diagnostic_report_id"] == report["report_id"]
    task_id = plan.json()["tasks"][0]["task_id"]

    current_user["user_id"] = "member-b"
    assert client.patch(f"/api/v1/kaoyan/tasks/{task_id}/status", json={"status": "done"}).status_code == 404

    current_user["user_id"] = "member-a"
    task = client.patch(f"/api/v1/kaoyan/tasks/{task_id}/status", json={"status": "done"})
    assert task.status_code == 200
    assert task.json()["status"] == "completed"

    dashboard = client.get("/api/v1/kaoyan/dashboard/summary")
    assert dashboard.status_code == 200
    assert dashboard.json()["task_completed"] >= 1
    assert dashboard.json()["profile"]["user_id"] == "member-a"
    assert dashboard.json()["recent_diagnostic_report"]["report_id"] == report["report_id"]
