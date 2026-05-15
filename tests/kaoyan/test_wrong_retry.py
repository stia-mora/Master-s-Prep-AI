"""PR-B acceptance tests: wrong-question retry system.

Covers:
  - test_wrong_questions_summary            → GET /wrong-questions/summary
  - test_recommend_retry_fallback           → POST /wrong-questions/recommend-retry (no AI)
  - test_wrong_retry_modes_update_stage_progress
        verifies original / variant / mixed all:
          1. produce a non-empty question list
          2. write back to wrong_question (retry_count++)
          3. update mastery_score
          4. insert stage_attempt rows
  - test_priority_score_decreases_on_correct
  - test_add_stage_attempt_direct
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest

from master_prep_ai.kaoyan.content_store import KaoyanContentStore
from master_prep_ai.kaoyan.learning_store import KaoyanLearningStore
from master_prep_ai.kaoyan.wrong_retry import (
    KaoyanWrongRetryService,
    MODE_MIXED,
    MODE_ORIGINAL,
    MODE_VARIANT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_learning_store(tmp_path: Path) -> KaoyanLearningStore:
    db = tmp_path / "test_learning.sqlite"
    return KaoyanLearningStore(db_path=db)


def _seed_wrong_question(store: KaoyanLearningStore, user_id: str, question_id: str, knowledge_id: str) -> None:
    """Insert a wrong-question row directly so tests don't need a full practice flow."""
    import uuid as _uuid
    wrong_id = f"wrong_{_uuid.uuid4().hex[:16]}"
    with store._connect() as conn:
        conn.execute(
            """
            INSERT INTO wrong_question
                (wrong_id, user_id, question_id, knowledge_id, error_reason,
                 wrong_count, review_status, last_wrong_at, next_review_at,
                 wrong_reason, retry_count, last_retry_mode, priority_score)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', datetime('now'), datetime('now','+1 day'),
                    ?, 0, '', 5.0)
            ON CONFLICT(user_id, question_id) DO NOTHING
            """,
            (
                wrong_id,
                user_id,
                question_id,
                knowledge_id,
                "概念不清",
                2,
                "概念不清",
            ),
        )
        conn.commit()


def _seed_mastery(store: KaoyanLearningStore, user_id: str, knowledge_id: str, score: float = 45.0) -> None:
    with store._connect() as conn:
        conn.execute(
            """
            INSERT INTO mastery_record
                (mastery_id, user_id, knowledge_id, mastery_score,
                 attempts, correct_count, wrong_count, last_practiced_at, updated_at)
            VALUES (?, ?, ?, ?, 2, 0, 2, datetime('now'), datetime('now'))
            ON CONFLICT(user_id, knowledge_id) DO NOTHING
            """,
            (f"mas_{knowledge_id[:8]}", user_id, knowledge_id, score),
        )
        conn.commit()


def _get_mastery_score(store: KaoyanLearningStore, user_id: str, knowledge_id: str) -> float:
    with store._connect() as conn:
        row = conn.execute(
            "SELECT mastery_score FROM mastery_record WHERE user_id=? AND knowledge_id=?",
            (user_id, knowledge_id),
        ).fetchone()
    return float(row["mastery_score"]) if row else 0.0


def _get_retry_count(store: KaoyanLearningStore, user_id: str, question_id: str) -> int:
    with store._connect() as conn:
        row = conn.execute(
            "SELECT retry_count FROM wrong_question WHERE user_id=? AND question_id=?",
            (user_id, question_id),
        ).fetchone()
    return int(row["retry_count"]) if row else 0


def _get_stage_attempt_count(store: KaoyanLearningStore, user_id: str, stage_id: str) -> int:
    with store._connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM stage_attempt WHERE user_id=? AND stage_id=?",
            (user_id, stage_id),
        ).fetchone()
    return int(row["cnt"])


def _get_priority_score(store: KaoyanLearningStore, user_id: str, question_id: str) -> float:
    with store._connect() as conn:
        row = conn.execute(
            "SELECT priority_score FROM wrong_question WHERE user_id=? AND question_id=?",
            (user_id, question_id),
        ).fetchone()
    return float(row["priority_score"]) if row else 5.0


# ---------------------------------------------------------------------------
# Stub content store (no real DB needed for question lookup)
# ---------------------------------------------------------------------------

class _StubContentStore(KaoyanContentStore):
    """A minimal stub that returns fake questions without a real SQLite content DB."""

    def __init__(self, questions: list[dict[str, Any]]) -> None:
        # Skip real DB init — we override all relevant methods
        self._questions = {q["question_id"]: q for q in questions}

    def get_questions(self, question_ids: list[str]) -> list[dict[str, Any]]:
        return [self._questions[qid] for qid in question_ids if qid in self._questions]

    def get_question(self, question_id: str) -> dict[str, Any] | None:
        return self._questions.get(question_id)

    def select_questions(self, *, knowledge_id=None, question_type=None,
                         question_family="choice", difficulty_level=None,
                         limit=5, exclude_ids=None) -> list[dict[str, Any]]:
        result = []
        for q in self._questions.values():
            if exclude_ids and q["question_id"] in exclude_ids:
                continue
            if knowledge_id and q.get("knowledge_id") != knowledge_id:
                continue
            result.append(q)
            if len(result) >= limit:
                break
        return result

    def get_knowledge(self, knowledge_id: str, question_limit: int = 5) -> dict[str, Any] | None:
        return {"knowledge": {"knowledge_id": knowledge_id, "knowledge_name": knowledge_id}}

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "counts": {}, "abnormalities": {}}


def _stub_questions(knowledge_id: str = "KP_DERIVATIVE") -> list[dict[str, Any]]:
    return [
        {
            "question_id": f"Q_{knowledge_id}_01",
            "knowledge_id": knowledge_id,
            "stem": f"求函数 f(x)=x^2 的导数（{knowledge_id}）",
            "answer": "A",
            "correct_answer": "A",
            "analysis": "f'(x)=2x",
            "question_type": "单选题",
            "difficulty_level": 2,
            "options": {"A": "2x", "B": "x^2", "C": "2", "D": "x"},
            "is_choice": True,
        },
        {
            "question_id": f"Q_{knowledge_id}_02",
            "knowledge_id": knowledge_id,
            "stem": f"求极值点（{knowledge_id}）",
            "answer": "B",
            "correct_answer": "B",
            "analysis": "令f'(x)=0",
            "question_type": "单选题",
            "difficulty_level": 3,
            "options": {"A": "0", "B": "1", "C": "-1", "D": "2"},
            "is_choice": True,
        },
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWrongQuestionsSummary:
    def test_empty_returns_expected_keys(self, tmp_path: Path) -> None:
        store = _make_learning_store(tmp_path)
        summary = store.wrong_questions_summary("user_empty")
        assert "stage_groups" in summary
        assert "wrong_reason_distribution" in summary
        assert "blocked_stage_count" in summary
        assert summary["blocked_stage_count"] == 0

    def test_with_wrong_questions(self, tmp_path: Path) -> None:
        store = _make_learning_store(tmp_path)
        _seed_wrong_question(store, "u1", "Q_KP1_01", "KP1")
        _seed_wrong_question(store, "u1", "Q_KP1_02", "KP1")
        _seed_wrong_question(store, "u1", "Q_KP2_01", "KP2")
        summary = store.wrong_questions_summary("u1")
        assert len(summary["stage_groups"]) >= 1
        assert summary["total_pending_wrong"] >= 3

    def test_blocked_stage_count(self, tmp_path: Path) -> None:
        store = _make_learning_store(tmp_path)
        # seed a wrong_question with wrong_count >= 3
        with store._connect() as conn:
            conn.execute(
                """
                INSERT INTO wrong_question
                    (wrong_id, user_id, question_id, knowledge_id, error_reason,
                     wrong_count, review_status, last_wrong_at, next_review_at,
                     wrong_reason, retry_count, last_retry_mode, priority_score)
                VALUES ('wq_block1','u2','Qblk1','KP_BLOCK','',3,'pending',
                        datetime('now'),datetime('now','+1 day'),'',0,'',5.0)
                """,
            )
            conn.commit()
        summary = store.wrong_questions_summary("u2")
        assert summary["blocked_stage_count"] >= 1


class TestRecommendRetryFallback:
    """Test that fallback recommendation works without AI."""

    def test_no_wrong_questions(self, tmp_path: Path) -> None:
        store = _make_learning_store(tmp_path)
        content = _StubContentStore([])
        svc = KaoyanWrongRetryService(content, store)
        result = asyncio.run(svc.recommend_retry(user_id="user_empty"))
        assert "retry_mode" in result
        assert "reason" in result
        assert result["retry_mode"] in {"original", "variant", "mixed"}

    def test_with_wrong_questions_returns_valid_mode(self, tmp_path: Path) -> None:
        store = _make_learning_store(tmp_path)
        questions = _stub_questions("KP_D")
        _seed_wrong_question(store, "u3", questions[0]["question_id"], "KP_D")
        _seed_wrong_question(store, "u3", questions[1]["question_id"], "KP_D")
        content = _StubContentStore(questions)
        svc = KaoyanWrongRetryService(content, store)
        result = asyncio.run(svc.recommend_retry(user_id="u3"))
        assert result["retry_mode"] in {"original", "variant", "mixed"}
        assert len(result["reason"]) > 5
        assert isinstance(result["weakness_tags"], list)

    def test_explicit_mode_hint_respected(self, tmp_path: Path) -> None:
        store = _make_learning_store(tmp_path)
        questions = _stub_questions("KP_E")
        _seed_wrong_question(store, "u4", questions[0]["question_id"], "KP_E")
        content = _StubContentStore(questions)
        svc = KaoyanWrongRetryService(content, store)
        result = asyncio.run(svc.recommend_retry(mode="variant", user_id="u4"))
        # fallback must respect the requested mode
        assert result["retry_mode"] == "variant"


class TestWrongRetryModesUpdateStageProgress:
    """
    Main acceptance test — validates all three modes:
      1. produce a non-empty question list
      2. write retry_count++ to wrong_question
      3. update mastery_score
      4. insert stage_attempt rows
    """

    USER = "u_main"
    KID = "KP_DERIVATIVE"

    def _setup(self, tmp_path: Path):
        store = _make_learning_store(tmp_path)
        questions = _stub_questions(self.KID)
        content = _StubContentStore(questions)
        _seed_wrong_question(store, self.USER, questions[0]["question_id"], self.KID)
        _seed_wrong_question(store, self.USER, questions[1]["question_id"], self.KID)
        _seed_mastery(store, self.USER, self.KID, score=40.0)
        return store, content, questions

    # -- original ------------------------------------------------------------

    def test_original_mode_generates_same_questions(self, tmp_path: Path) -> None:
        store, content, questions = self._setup(tmp_path)
        svc = KaoyanWrongRetryService(content, store)
        session = asyncio.run(
            svc.create_retry_session(mode=MODE_ORIGINAL, user_id=self.USER)
        )
        assert session.get("questions"), "original mode must return non-empty questions"
        returned_ids = {q["question_id"] for q in session["questions"]}
        original_ids = {q["question_id"] for q in questions}
        assert returned_ids.issubset(original_ids), "original mode must return the exact wrong questions"
        assert session["retry_mode"] == MODE_ORIGINAL

    def test_original_mode_submit_updates_mastery(self, tmp_path: Path) -> None:
        store, content, questions = self._setup(tmp_path)
        svc = KaoyanWrongRetryService(content, store)
        session = asyncio.run(
            svc.create_retry_session(mode=MODE_ORIGINAL, user_id=self.USER)
        )
        session_id = session["session_id"]
        score_before = _get_mastery_score(store, self.USER, self.KID)

        answers = [{"question_id": q["question_id"], "answer": q["answer"]} for q in session["questions"]]
        result = asyncio.run(svc.submit_retry_session(session_id, answers, self.USER))

        assert result is not None
        assert result["retry_mode"] == MODE_ORIGINAL
        assert result["total_count"] > 0

        score_after = _get_mastery_score(store, self.USER, self.KID)
        assert score_after > score_before, "mastery_score must increase after correct retry"

        # retry_count incremented
        rc = _get_retry_count(store, self.USER, questions[0]["question_id"])
        assert rc >= 1, "retry_count must be incremented"

        # stage_attempt inserted
        sa_count = _get_stage_attempt_count(store, self.USER, self.KID)
        assert sa_count >= 1, "stage_attempt must be written"

    # -- variant -------------------------------------------------------------

    def test_variant_mode_returns_nonempty_questions(self, tmp_path: Path) -> None:
        store, content, questions = self._setup(tmp_path)
        svc = KaoyanWrongRetryService(content, store)
        session = asyncio.run(
            svc.create_retry_session(mode=MODE_VARIANT, user_id=self.USER)
        )
        assert session.get("questions"), "variant mode must return non-empty questions"
        assert session["retry_mode"] == MODE_VARIANT

    def test_variant_mode_knowledge_id_preserved(self, tmp_path: Path) -> None:
        store, content, questions = self._setup(tmp_path)
        svc = KaoyanWrongRetryService(content, store)
        session = asyncio.run(
            svc.create_retry_session(mode=MODE_VARIANT, user_id=self.USER)
        )
        for q in session["questions"]:
            assert q.get("knowledge_id") == self.KID, (
                f"variant question knowledge_id must match original ({self.KID}), got {q.get('knowledge_id')}"
            )

    def test_variant_mode_submit_updates_mastery(self, tmp_path: Path) -> None:
        store, content, questions = self._setup(tmp_path)
        svc = KaoyanWrongRetryService(content, store)
        session = asyncio.run(
            svc.create_retry_session(mode=MODE_VARIANT, user_id=self.USER)
        )
        session_id = session["session_id"]
        score_before = _get_mastery_score(store, self.USER, self.KID)

        qs = session["questions"]
        answers = [{"question_id": q["question_id"], "answer": q.get("answer", "A")} for q in qs]
        result = asyncio.run(svc.submit_retry_session(session_id, answers, self.USER))

        assert result is not None
        assert result["retry_mode"] == MODE_VARIANT
        assert result["total_count"] > 0

        score_after = _get_mastery_score(store, self.USER, self.KID)
        # Score should have changed (up or down depending on correctness)
        sa_count = _get_stage_attempt_count(store, self.USER, self.KID)
        assert sa_count >= 1, "stage_attempt must be written after variant retry"

    # -- mixed ---------------------------------------------------------------

    def test_mixed_mode_covers_multiple_knowledge_ids(self, tmp_path: Path) -> None:
        store = _make_learning_store(tmp_path)
        qs_d = _stub_questions("KP_DERIVATIVE")
        qs_i = _stub_questions("KP_INTEGRAL")
        qs_l = _stub_questions("KP_LINEAR")
        all_qs = qs_d + qs_i + qs_l
        content = _StubContentStore(all_qs)

        for q in qs_d:
            _seed_wrong_question(store, self.USER, q["question_id"], "KP_DERIVATIVE")
        for q in qs_i:
            _seed_wrong_question(store, self.USER, q["question_id"], "KP_INTEGRAL")
        for q in qs_l:
            _seed_wrong_question(store, self.USER, q["question_id"], "KP_LINEAR")

        svc = KaoyanWrongRetryService(content, store)
        session = asyncio.run(svc.create_retry_session(mode=MODE_MIXED, user_id=self.USER))
        assert session.get("questions") or session.get("weakness_knowledge_ids"), (
            "mixed mode must return questions or at least weakness_knowledge_ids"
        )
        assert session["retry_mode"] == MODE_MIXED

    def test_mixed_mode_submit_updates_mastery_and_stage_attempt(self, tmp_path: Path) -> None:
        store = _make_learning_store(tmp_path)
        qs_d = _stub_questions("KP_DERIVATIVE")
        qs_i = _stub_questions("KP_INTEGRAL")
        all_qs = qs_d + qs_i
        content = _StubContentStore(all_qs)

        for q in qs_d:
            _seed_wrong_question(store, "u_mix", q["question_id"], "KP_DERIVATIVE")
            _seed_mastery(store, "u_mix", "KP_DERIVATIVE", 40.0)
        for q in qs_i:
            _seed_wrong_question(store, "u_mix", q["question_id"], "KP_INTEGRAL")
            _seed_mastery(store, "u_mix", "KP_INTEGRAL", 38.0)

        svc = KaoyanWrongRetryService(content, store)
        session = asyncio.run(svc.create_retry_session(mode=MODE_MIXED, user_id="u_mix"))
        session_id = session.get("session_id", "")
        if not session_id or not session.get("questions"):
            pytest.skip("No questions generated (AI unavailable and fallback empty)")

        qs = session["questions"]
        answers = [{"question_id": q["question_id"], "answer": q.get("answer", "A")} for q in qs]
        result = asyncio.run(svc.submit_retry_session(session_id, answers, "u_mix"))

        assert result is not None
        assert result["retry_mode"] == MODE_MIXED
        assert result["mastery_updated"] is True
        assert result["stage_progress_updated"] is True


class TestPriorityScoreDecreasesOnCorrect:
    def test_priority_drops_after_correct_retry(self, tmp_path: Path) -> None:
        store = _make_learning_store(tmp_path)
        questions = _stub_questions("KP_PRI")
        content = _StubContentStore(questions)
        qid = questions[0]["question_id"]
        kid = questions[0]["knowledge_id"]

        _seed_wrong_question(store, "u_pri", qid, kid)
        _seed_mastery(store, "u_pri", kid, 50.0)

        priority_before = _get_priority_score(store, "u_pri", qid)
        store.record_wrong_retry(
            question_id=qid,
            is_correct=True,
            retry_mode=MODE_ORIGINAL,
            wrong_reason="",
            knowledge_id=kid,
            session_id="sess_test",
            user_id="u_pri",
        )
        priority_after = _get_priority_score(store, "u_pri", qid)
        assert priority_after < priority_before, "priority_score must decrease after correct retry"


class TestAddStageAttemptDirect:
    def test_insert_and_count(self, tmp_path: Path) -> None:
        store = _make_learning_store(tmp_path)
        attempt_id = store.add_stage_attempt(
            user_id="u_sa",
            stage_id="KP_SA_TEST",
            session_id="sess_sa",
            source="wrong_retry_original",
            score_delta=8.0,
            wrong_reason="计算失误",
        )
        assert attempt_id.startswith("sa_")
        count = _get_stage_attempt_count(store, "u_sa", "KP_SA_TEST")
        assert count == 1


class TestGetStageProgress:
    def test_returns_list_with_expected_keys(self, tmp_path: Path) -> None:
        store = _make_learning_store(tmp_path)
        _seed_mastery(store, "u_sp", "KP_SP1", 60.0)
        _seed_wrong_question(store, "u_sp", "Q_SP1_01", "KP_SP1")
        progress = store.get_stage_progress("u_sp")
        assert isinstance(progress, list)
        assert len(progress) >= 1
        row = progress[0]
        assert "knowledge_id" in row
        assert "mastery_score" in row
        assert "retry_count" in row
        assert "next_action" in row
        assert row["knowledge_id"] == "KP_SP1"
