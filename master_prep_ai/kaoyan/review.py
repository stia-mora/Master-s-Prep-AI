"""Review helpers for the Kaoyan MVP."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .content_store import KaoyanContentStore
from .learning_store import DEFAULT_USER_ID, KaoyanLearningStore, utc_now
from .practice import KaoyanPracticeService, is_correct_answer


class KaoyanReviewService:
    def __init__(self, content_store: KaoyanContentStore, learning_store: KaoyanLearningStore) -> None:
        self.content_store = content_store
        self.learning_store = learning_store

    def seed_from_knowledge(self, knowledge_id: str, user_id: str = DEFAULT_USER_ID) -> int:
        detail = self.content_store.get_knowledge(knowledge_id, question_limit=0)
        if not detail:
            return 0
        cards = detail.get("review_cards", [])
        now = utc_now()
        next_review = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        count = 0
        with self.learning_store._connect() as conn:  # Small domain helper; store owns schema.
            for card in cards[:5]:
                self.learning_store.upsert_review_item(
                    conn,
                    user_id=user_id,
                    source_type="review_card",
                    source_id=card["card_id"],
                    knowledge_id=knowledge_id,
                    title=f"{card.get('card_type') or '复习卡'}：{detail['knowledge']['knowledge_name']}",
                    prompt=card.get("front_content", ""),
                    answer=card.get("back_content", ""),
                    priority_score=3.0,
                    next_review_at=next_review,
                    now=now,
                )
                count += 1
            conn.commit()
        return count

    def list_today(self, user_id: str = DEFAULT_USER_ID) -> list[dict[str, Any]]:
        return self.learning_store.list_reviews_today(user_id)

    def calendar(
        self,
        user_id: str = DEFAULT_USER_ID,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        return self.learning_store.list_review_calendar(user_id, start_date=start_date, end_date=end_date)

    def start_test(self, review_id: str, user_id: str = DEFAULT_USER_ID) -> dict[str, Any] | None:
        review = self.learning_store.get_review(review_id, user_id)
        if not review:
            return None
        question = self._review_question(review)
        if question:
            question = self._hide_question_answer(question)
        return {
            "review_id": review["review_id"],
            "source_type": review["source_type"],
            "source_id": review["source_id"],
            "stage_id": review.get("stage_id") or review.get("knowledge_id") or review.get("source_id") or "",
            "knowledge_id": review.get("knowledge_id") or "",
            "title": review.get("title") or "",
            "prompt": review.get("prompt") or "",
            "question": question,
            "answer_hidden": True,
            "status": review.get("status") or "pending",
            "next_review_at": review.get("next_review_at") or "",
        }

    async def submit_test(
        self,
        review_id: str,
        payload: dict[str, Any],
        user_id: str = DEFAULT_USER_ID,
    ) -> dict[str, Any] | None:
        review = self.learning_store.get_review(review_id, user_id)
        if not review:
            return None
        answer_payload = self._answer_payload(review, payload)
        question = self._review_question(review)
        if question:
            practice = KaoyanPracticeService(self.content_store, self.learning_store)
            results = await practice.grade_questions([question], {question["question_id"]: answer_payload}, user_id)
            grading = results[0] if results else {}
            passed = bool(grading.get("is_correct"))
        else:
            user_answer = str(answer_payload.get("answer") or "")
            expected = str(review.get("answer") or "")
            passed = is_correct_answer(user_answer, expected)
            grading = {
                "question_id": review.get("source_id") or review_id,
                "knowledge_id": review.get("knowledge_id") or "",
                "user_answer": user_answer,
                "correct_answer": expected,
                "is_correct": passed,
                "ai_analysis": "Review card answer matched by rule." if passed else "Review card answer did not match the stored answer.",
                "error_reason": "" if passed else "review_answer_mismatch",
                "grading_method": "rule_review_card",
            }
        updated = self.learning_store.submit_review_result(
            review_id,
            passed,
            user_id=user_id,
            user_answer=str(answer_payload.get("answer") or ""),
            grading=grading,
        )
        if updated is None:
            return None
        updated["answer_hidden"] = True
        updated["result"] = grading
        updated.pop("answer", None)
        return updated

    def submit(self, review_id: str, status: str, user_id: str = DEFAULT_USER_ID) -> dict[str, Any] | None:
        return self.learning_store.submit_review(review_id, status, user_id)

    def daily_export_payload(
        self,
        target_date: str,
        *,
        include_answers: bool = False,
        user_id: str = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        reviews = self.learning_store.list_reviews_for_date(target_date, user_id, limit=200)
        self.learning_store.mark_reviews_printed([item["review_id"] for item in reviews], user_id)
        items: list[dict[str, Any]] = []
        for review in reviews:
            question = self._review_question(review)
            prompt = str((question or {}).get("stem_without_options") or (question or {}).get("stem") or review.get("prompt") or "")
            items.append(
                {
                    "review_id": review["review_id"],
                    "stage_id": review.get("stage_id") or review.get("knowledge_id") or review.get("source_id") or "",
                    "knowledge_id": review.get("knowledge_id") or "",
                    "title": review.get("title") or "",
                    "prompt": prompt,
                    "question_type": (question or {}).get("question_type") or review.get("source_type") or "",
                    "status": review.get("status") or "",
                    "next_action": review.get("next_action") or "",
                    "answer": (question or {}).get("answer") or review.get("answer") or "",
                }
            )
        return {
            "title": f"Kaoyan review sheet {target_date}",
            "filename": f"kaoyan-review-{target_date}-{'answers' if include_answers else 'student'}.pdf",
            "date": target_date,
            "include_answers": include_answers,
            "items": items,
        }

    def _review_question(self, review: dict[str, Any]) -> dict[str, Any] | None:
        if review.get("source_type") == "wrong_question":
            question = self.content_store.get_question(str(review.get("source_id") or ""))
            if question:
                return question
        return None

    def _hide_question_answer(self, question: dict[str, Any]) -> dict[str, Any]:
        public_question = dict(question)
        public_question.pop("answer", None)
        public_question.pop("analysis", None)
        return public_question

    def _answer_payload(self, review: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        answers = payload.get("answers")
        if isinstance(answers, list) and answers:
            first = answers[0]
            if isinstance(first, dict):
                return first
        return {
            "question_id": review.get("source_id") or review.get("review_id"),
            "answer": payload.get("answer", ""),
            "image_data_url": payload.get("image_data_url") or payload.get("imageDataUrl") or "",
        }
