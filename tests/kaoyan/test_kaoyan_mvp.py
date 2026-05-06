from __future__ import annotations

import asyncio
from pathlib import Path
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import kaoyan as kaoyan_router
from deeptutor.auth import AuthUser
from deeptutor.kaoyan.content_store import KaoyanContentStore
from deeptutor.kaoyan.learning_store import KaoyanLearningStore
from deeptutor.kaoyan.practice import KaoyanPracticeService

CONTENT_DB = r"E:\Group-projects\Master's Prep AI\DeepTutor\math_content.sqlite"


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

    from deeptutor.kaoyan import ai_service

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
