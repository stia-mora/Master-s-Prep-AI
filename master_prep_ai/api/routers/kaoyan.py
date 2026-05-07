"""Kaoyan assistant MVP API."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from master_prep_ai.auth import AuthUser, require_current_user
from master_prep_ai.kaoyan.chat_context import KaoyanChatContextService
from master_prep_ai.kaoyan.content_store import get_content_store
from master_prep_ai.kaoyan.diagnostic import KaoyanDiagnosticService
from master_prep_ai.kaoyan.learning_store import get_learning_store
from master_prep_ai.kaoyan.planner import KaoyanPlanner
from master_prep_ai.kaoyan.practice import KaoyanPracticeService
from master_prep_ai.kaoyan.review import KaoyanReviewService

router = APIRouter()


class ProfileInitRequest(BaseModel):
    target_school: str = ""
    target_major: str = ""
    exam_date: str = ""
    daily_minutes: int = Field(default=120, ge=30, le=900)
    target_score: int = Field(default=120, ge=1, le=500)
    baseline_level: str = "待诊断"
    weak_modules: list[str] = Field(default_factory=list)


class DiagnosticSessionRequest(BaseModel):
    mode: Literal["light", "deep"] = "light"
    profile: dict[str, Any] | None = None


class PracticeSessionRequest(BaseModel):
    session_type: Literal["special", "wrong_retry", "similar"] = "special"
    knowledge_id: str | None = None
    source_question_id: str | None = None
    question_type: str | None = None
    difficulty_level: int | None = Field(default=None, ge=1, le=5)
    limit: int = Field(default=5, ge=1, le=20)


class AnswerItem(BaseModel):
    question_id: str
    answer: str = ""
    image_data_url: str | None = None


class PracticeSubmitRequest(BaseModel):
    answers: list[AnswerItem]


class DiagnosticSubmitRequest(BaseModel):
    answers: list[AnswerItem]


class TaskStatusRequest(BaseModel):
    status: Literal["pending", "in_progress", "completed", "skipped"]


class ReviewSubmitRequest(BaseModel):
    status: Literal["reviewed", "mastered", "failed"]


class ChatContextRequest(BaseModel):
    source_type: Literal["knowledge", "question"]
    source_id: str
    intent: str = "explain"

class PlanReorderRequest(BaseModel):
    trigger_reason: str = "manual"
    completion_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    mastery_scores: dict[str, float] = Field(default_factory=dict)
    remaining_days: int = Field(default=30, ge=0, le=1000)


class MaterialParseRequest(BaseModel):
    filename: str
    content_type: str = "pdf"


class RagQueryRequest(BaseModel):
    kb_name: str
    query: str


class ExamSimulationRequest(BaseModel):
    subject: str = "math"
    year: int | None = Field(default=None, ge=1987, le=2100)
    module: str = ""
    knowledge_id: str | None = None
    question_type: str | None = None
    difficulty_level: int | None = Field(default=None, ge=1, le=5)
    time_limit_minutes: int = Field(default=30, ge=5, le=180)
    limit: int = Field(default=8, ge=1, le=30)


class ExamSubmitRequest(BaseModel):
    answers: list[AnswerItem]
    elapsed_seconds: int | None = Field(default=None, ge=0)

def _content():
    return get_content_store()


def _learning():
    return get_learning_store()


@router.get("/content/health")
async def content_health() -> dict[str, Any]:
    return _content().health()


@router.get("/content/knowledge-tree")
async def get_knowledge_tree() -> list[dict[str, Any]]:
    return _content().knowledge_tree()


@router.get("/content/knowledge/{knowledge_id}")
async def get_knowledge(knowledge_id: str) -> dict[str, Any]:
    detail = _content().get_knowledge(knowledge_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Knowledge point not found")
    return detail


@router.post("/profile/init")
async def init_profile(request: ProfileInitRequest, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    return _learning().upsert_profile(request.model_dump(), user.user_id)


@router.get("/profile/me")
async def get_profile(user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    profile = _learning().get_profile(user.user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not initialized")
    return profile


@router.get("/dashboard/summary")
async def dashboard_summary(user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    summary = _learning().dashboard_summary(user.user_id)
    summary["profile"] = _learning().get_profile(user.user_id)
    return summary


@router.post("/plans/generate")
async def generate_plan(user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    planner = KaoyanPlanner(_content(), _learning())
    return await planner.generate_plan(user.user_id)


@router.get("/tasks/today")
async def today_tasks(user: AuthUser = Depends(require_current_user)) -> list[dict[str, Any]]:
    return _learning().list_today_tasks(user.user_id)


@router.patch("/tasks/{task_id}/status")
async def update_task_status(task_id: str, request: TaskStatusRequest, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    task = _learning().update_task_status(task_id, request.status, user.user_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/diagnostic/session")
async def create_diagnostic_session(request: DiagnosticSessionRequest, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    service = KaoyanDiagnosticService(_content(), _learning())
    session = await service.create_session(request.mode, request.profile, user.user_id)
    if not session.get("questions"):
        raise HTTPException(status_code=404, detail="No diagnostic questions available")
    return session


@router.post("/diagnostic/{session_id}/submit")
async def submit_diagnostic(session_id: str, request: DiagnosticSubmitRequest, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    service = KaoyanDiagnosticService(_content(), _learning())
    result = await service.submit_session(
        session_id,
        [item.model_dump() for item in request.answers],
        user.user_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Diagnostic session not found")
    session = _learning().get_practice_session(session_id, user.user_id) or {}
    answers = result.get("answers") or []
    total = len(answers)
    correct = sum(1 for item in answers if item.get("is_correct"))
    report = _learning().create_diagnostic_report(
        user_id=user.user_id,
        session_id=session_id,
        mode=str((session.get("ai_metadata") or {}).get("mode") or "light"),
        profile_snapshot=(session.get("ai_metadata") or {}).get("profile_seed") or _learning().get_profile(user.user_id) or {},
        answer_summary={"total": total, "correct": correct, "accuracy": correct / total if total else 0, "answers": answers},
        profile_draft=result.get("profile_draft") or {},
        summary=str(result.get("summary") or ""),
    )
    result["report"] = report
    return result


@router.get("/diagnostic/reports")
async def list_diagnostic_reports(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: AuthUser = Depends(require_current_user),
) -> dict[str, Any]:
    return {"reports": _learning().list_diagnostic_reports(user.user_id, limit, offset)}


@router.get("/diagnostic/reports/{report_id}")
async def get_diagnostic_report(report_id: str, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    report = _learning().get_diagnostic_report(report_id, user.user_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Diagnostic report not found")
    return report


@router.patch("/diagnostic/reports/{report_id}/confirm")
async def confirm_diagnostic_report(report_id: str, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    report = _learning().confirm_diagnostic_report(report_id, user.user_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Diagnostic report not found")
    draft = report.get("profile_draft") or {}
    current = _learning().get_profile(user.user_id) or {}
    profile_payload = {
        **current,
        "baseline_level": draft.get("baseline_level") or current.get("baseline_level") or "待诊断",
        "weak_modules": draft.get("weak_modules") or current.get("weak_modules") or [],
        "daily_minutes": draft.get("recommended_daily_minutes") or current.get("daily_minutes") or 120,
    }
    if profile_payload:
        _learning().upsert_profile(profile_payload, user.user_id)
    return report


@router.post("/chat-context")
async def create_chat_context(request: ChatContextRequest, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    service = KaoyanChatContextService(_content(), user_id=user.user_id)
    result = await service.build_context(request.source_type, request.source_id, request.intent)
    if result is None:
        raise HTTPException(status_code=404, detail="Kaoyan chat context source not found")
    return result


@router.post("/practice/session")
async def create_practice_session(request: PracticeSessionRequest, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    service = KaoyanPracticeService(_content(), _learning())
    session = service.create_session(
        session_type=request.session_type,
        knowledge_id=request.knowledge_id,
        source_question_id=request.source_question_id,
        question_type=request.question_type,
        difficulty_level=request.difficulty_level,
        limit=request.limit,
        user_id=user.user_id,
    )
    if not session.get("questions"):
        raise HTTPException(status_code=404, detail="No questions available for this practice request")
    return session


@router.post("/practice/{session_id}/submit")
async def submit_practice(session_id: str, request: PracticeSubmitRequest, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    service = KaoyanPracticeService(_content(), _learning())
    result = await service.submit_session(
        session_id,
        [item.model_dump() for item in request.answers],
        user.user_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Practice session not found")
    return result


@router.get("/wrong-questions")
async def wrong_questions(user: AuthUser = Depends(require_current_user)) -> list[dict[str, Any]]:
    rows = _learning().list_wrong_questions(user.user_id)
    question_rows = _content().get_questions([row["question_id"] for row in rows])
    questions = {item["question_id"]: item for item in question_rows}
    enriched = []
    for row in rows:
        item = dict(row)
        item["question"] = questions.get(row["question_id"])
        enriched.append(item)
    return enriched


@router.get("/reviews/today")
async def reviews_today(user: AuthUser = Depends(require_current_user)) -> list[dict[str, Any]]:
    return KaoyanReviewService(_content(), _learning()).list_today(user.user_id)


@router.post("/reviews/{review_id}/submit")
async def submit_review(review_id: str, request: ReviewSubmitRequest, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    review = KaoyanReviewService(_content(), _learning()).submit(review_id, request.status, user.user_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return review

@router.post("/plans/reorder")
async def reorder_plan(request: PlanReorderRequest, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    planner = KaoyanPlanner(_content(), _learning())
    result = await planner.reorder_plan(
        user.user_id,
        trigger_reason=request.trigger_reason,
        completion_rate=request.completion_rate,
        mastery_scores=request.mastery_scores,
        remaining_days=request.remaining_days,
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/materials/parse")
async def create_material_parse_task(request: MaterialParseRequest, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    return _content().create_material_parse_task(request.filename, request.content_type)


@router.get("/materials/tasks/{task_id}")
async def get_material_parse_task(task_id: str, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    task = _content().get_material_parse_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/rag/query")
async def query_kaoyan_rag(request: RagQueryRequest, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    service = KaoyanChatContextService(_content(), user_id=user.user_id)
    return await service.query_rag(request.kb_name, request.query)


@router.post("/exam/simulation")
async def create_exam_simulation(request: ExamSimulationRequest, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    service = KaoyanPracticeService(_content(), _learning())
    session = service.create_session(
        session_type="exam_simulation",
        knowledge_id=request.knowledge_id,
        question_type=request.question_type,
        difficulty_level=request.difficulty_level,
        limit=request.limit,
        user_id=user.user_id,
    )
    if not session.get("questions"):
        raise HTTPException(status_code=404, detail="No questions available for this simulation request")
    return {
        "simulation_id": session["session_id"],
        "status": "reserved",
        "subject": request.subject,
        "year": request.year,
        "module": request.module,
        "time_limit_minutes": request.time_limit_minutes,
        "practice_session": session,
        "questions": session["questions"],
        "score_report": "reserved",
    }


@router.post("/exam/{simulation_id}/submit")
async def submit_exam_simulation(simulation_id: str, request: ExamSubmitRequest, user: AuthUser = Depends(require_current_user)) -> dict[str, Any]:
    service = KaoyanPracticeService(_content(), _learning())
    result = await service.submit_session(
        simulation_id,
        [item.model_dump() for item in request.answers],
        user.user_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Exam simulation not found")
    return {
        "simulation_id": simulation_id,
        "elapsed_seconds": request.elapsed_seconds,
        "score_report": {
            "total_count": result["total_count"],
            "correct_count": result["correct_count"],
            "accuracy": result["accuracy"],
            "analysis_summary": result["analysis_summary"],
            "next_actions": result["next_actions"],
        },
        "practice_result": result,
    }


@router.get("/mastery/records")
async def mastery_records(
    knowledge_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: AuthUser = Depends(require_current_user),
) -> dict[str, Any]:
    records = _learning().list_mastery_records(
        user.user_id,
        knowledge_id=knowledge_id,
        limit=limit,
        offset=offset,
    )
    return {"records": records, "limit": limit, "offset": offset}
