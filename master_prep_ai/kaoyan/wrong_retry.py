"""Wrong-question retry system — three modes (original / variant / mixed) + recommendation engine.

PR-B implementation:
  - GET  /wrong-questions/summary       → get_summary()
  - POST /wrong-questions/recommend-retry → recommend_retry()
  - POST /wrong-questions/retry          → create_retry_session()
  - POST /wrong-questions/retry/{id}/submit → submit_retry_session()
"""

from __future__ import annotations

import uuid
from typing import Any

from .ai_service import KaoyanAIService
from .content_store import KaoyanContentStore
from .learning_store import DEFAULT_USER_ID, KaoyanLearningStore

# ---------------------------------------------------------------------------
# Mode constants
# ---------------------------------------------------------------------------

MODE_ORIGINAL = "original"
MODE_VARIANT = "variant"
MODE_MIXED = "mixed"
VALID_MODES = {MODE_ORIGINAL, MODE_VARIANT, MODE_MIXED}

# ---------------------------------------------------------------------------
# AI prompt templates
# ---------------------------------------------------------------------------

_VARIANT_SYS = (
    "你是考研数学出题专家。基于原题生成一道知识点完全相同但题型/数字/问法有所变化的变式题。"
    "输出严格JSON（无Markdown）："
    '{"stem":"...","answer":"...","analysis":"...","question_type":"...","difficulty_level":3}'
)

_VARIANT_USER = (
    "原题题干：{stem}\n知识点ID：{knowledge_id}\n参考答案：{answer}\n题型：{question_type}\n"
    "要求：①知识点与原题一致 ②题型/数字/问法至少一处明显变化 ③难度相近。只输出JSON。"
)

_MIXED_SYS = (
    "你是考研数学综合题出题专家。根据多个薄弱知识点生成一道综合挑战题。"
    "输出严格JSON（无Markdown）："
    '{"stem":"...","answer":"...","analysis":"...","question_type":"综合题",'
    '"difficulty_level":4,"knowledge_ids":["id1","id2"]}'
)

_MIXED_USER = (
    "薄弱知识点：\n{knowledge_list}\n\n错因分布：\n{error_reasons}\n\n"
    "要求：①同时考察上述多个知识点 ②难度考研真题水准 ③侧重容易出错的知识点融合。只输出JSON。"
)

_RECOMMEND_SYS = (
    "你是考研学习路径优化专家。根据学生错题数据推荐最优重刷模式。"
    "输出严格JSON（无Markdown）："
    '{"retry_mode":"original|variant|mixed","reason":"...","related_stage":"...","weakness_tags":["..."]}'
)

_RECOMMEND_USER = (
    "错题总数:{wrong_count} 最频繁错因:{top_reasons} 平均掌握度:{avg_mastery:.1f} "
    "最近错题:{last_wrong_at} 薄弱知识点:{weakness_tags} 最高重复错误次数:{top_wrong_count}次\n"
    "请推荐最适合的重刷模式，只输出JSON。"
)


class KaoyanWrongRetryService:
    """Service for wrong-question retry system with three modes (PR-B)."""

    def __init__(
        self,
        content_store: KaoyanContentStore,
        learning_store: KaoyanLearningStore,
    ) -> None:
        self.cs = content_store
        self.ls = learning_store
        self.ai = KaoyanAIService(learning_store)

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------

    def get_summary(self, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
        """Return wrong-question statistics summary."""
        return self.ls.wrong_questions_summary(user_id)

    # -----------------------------------------------------------------------
    # Recommend retry
    # -----------------------------------------------------------------------

    async def recommend_retry(
        self,
        mode: str | None = None,
        user_id: str = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        """Recommend a retry mode with reason and weakness tags."""
        summary = self.ls.wrong_questions_summary(user_id)
        wrong_list = self.ls.list_wrong_questions(user_id)

        if not wrong_list:
            return {
                "retry_mode": mode or MODE_ORIGINAL,
                "reason": "暂无错题记录，请先完成一次练习。",
                "related_stage": "",
                "weakness_tags": [],
            }

        fallback = self._fallback_recommend(summary, wrong_list, mode)

        # Build AI prompt context
        top_reasons = [
            item["reason"] for item in summary.get("wrong_reason_distribution", [])[:3]
        ]
        weakness_tags = [
            item["knowledge_id"] for item in summary.get("stage_groups", [])[:5]
        ]
        mastery_records = self.ls.list_mastery_records(user_id, limit=200)
        avg_mastery = (
            sum(r.get("mastery_score", 50) for r in mastery_records) / len(mastery_records)
            if mastery_records
            else 50.0
        )
        last_wrong_at = wrong_list[0].get("last_wrong_at", "") if wrong_list else ""
        top_wrong_count = max((w.get("wrong_count", 0) for w in wrong_list), default=0)

        parsed, _meta = await self.ai.complete_json(
            action_type="wrong_retry_recommend",
            system_prompt=_RECOMMEND_SYS,
            prompt=_RECOMMEND_USER.format(
                wrong_count=len(wrong_list),
                top_reasons="、".join(top_reasons) or "暂无",
                avg_mastery=avg_mastery,
                last_wrong_at=last_wrong_at,
                weakness_tags="、".join(weakness_tags) or "暂无",
                top_wrong_count=top_wrong_count,
            ),
            user_id=user_id,
        )

        if isinstance(parsed, dict):
            result_mode = str(parsed.get("retry_mode") or fallback["retry_mode"])
            if result_mode not in VALID_MODES:
                result_mode = fallback["retry_mode"]
            return {
                "retry_mode": result_mode,
                "reason": str(parsed.get("reason") or fallback["reason"]),
                "related_stage": str(parsed.get("related_stage") or fallback["related_stage"]),
                "weakness_tags": list(parsed.get("weakness_tags") or fallback["weakness_tags"]),
            }

        return fallback

    def _fallback_recommend(
        self,
        summary: dict[str, Any],
        wrong_list: list[dict[str, Any]],
        requested_mode: str | None,
    ) -> dict[str, Any]:
        """Deterministic recommendation without AI."""
        if requested_mode and requested_mode in VALID_MODES:
            mode = requested_mode
        else:
            stage_groups = summary.get("stage_groups", [])
            high_repeat = sum(1 for w in wrong_list if w.get("wrong_count", 0) >= 3)
            if len(stage_groups) >= 3:
                mode = MODE_MIXED
            elif high_repeat >= 2:
                mode = MODE_VARIANT
            else:
                mode = MODE_ORIGINAL

        weakness_tags = [item["knowledge_id"] for item in summary.get("stage_groups", [])[:5]]
        top_wrong = max(wrong_list, key=lambda w: w.get("wrong_count", 0), default={})
        related_stage = str(top_wrong.get("knowledge_id") or "")
        tag_str = "、".join(weakness_tags[:3]) or "相关知识点"

        reason_map = {
            MODE_ORIGINAL: "检测记忆恢复，建议先原题重刷确认是否已掌握。",
            MODE_VARIANT: f"你在 {tag_str} 上存在重复错误，变式题可强化迁移能力。",
            MODE_MIXED: f"你在 {tag_str} 上均有薄弱，综合组合题可提升融合应用能力。",
        }
        return {
            "retry_mode": mode,
            "reason": reason_map.get(mode, "根据错题数据推荐重刷。"),
            "related_stage": related_stage,
            "weakness_tags": weakness_tags,
        }

    # -----------------------------------------------------------------------
    # Create retry session
    # -----------------------------------------------------------------------

    async def create_retry_session(
        self,
        mode: str,
        wrong_question_ids: list[str] | None = None,
        limit: int = 5,
        user_id: str = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        """Create a retry practice session in the given mode."""
        if mode not in VALID_MODES:
            raise ValueError(f"Invalid retry mode '{mode}'. Choose from {VALID_MODES}.")
        if mode == MODE_ORIGINAL:
            return self._session_original(wrong_question_ids, limit, user_id)
        if mode == MODE_VARIANT:
            return await self._session_variant(wrong_question_ids, limit, user_id)
        return await self._session_mixed(limit, user_id)

    # -- original ------------------------------------------------------------

    def _session_original(
        self,
        wrong_question_ids: list[str] | None,
        limit: int,
        user_id: str,
    ) -> dict[str, Any]:
        q_ids = (wrong_question_ids or self.ls.active_wrong_question_ids(user_id))[:limit]
        questions = self.cs.get_questions(q_ids) if q_ids else []
        session = self.ls.create_practice_session(
            session_type="wrong_retry",
            title="原题重刷",
            knowledge_id=questions[0].get("knowledge_id", "") if questions else "",
            question_ids=[q["question_id"] for q in questions],
            ai_meta={"retry_mode": MODE_ORIGINAL, "source": "wrong_retry",
                     "message": "原题重刷：检测记忆恢复"},
            user_id=user_id,
        )
        session["questions"] = questions
        session["retry_mode"] = MODE_ORIGINAL
        return session

    # -- variant -------------------------------------------------------------

    async def _session_variant(
        self,
        wrong_question_ids: list[str] | None,
        limit: int,
        user_id: str,
    ) -> dict[str, Any]:
        q_ids = (wrong_question_ids or self.ls.active_wrong_question_ids(user_id))[:limit]
        originals = self.cs.get_questions(q_ids) if q_ids else []
        variants: list[dict[str, Any]] = []

        for orig in originals:
            v = await self._generate_variant(orig, user_id)
            if v:
                variants.append(v)

        # Fallback: use content-store similar questions
        if not variants:
            for orig in originals:
                similar = self.cs.select_questions(
                    knowledge_id=orig.get("knowledge_id"),
                    question_family="choice",
                    limit=1,
                    exclude_ids=[orig["question_id"]],
                )
                variants.extend(similar)

        # Last resort: reuse originals
        if not variants:
            variants = originals

        pk_id = originals[0].get("knowledge_id", "") if originals else ""
        session = self.ls.create_practice_session(
            session_type="wrong_retry",
            title="变式重刷",
            knowledge_id=pk_id,
            question_ids=[q.get("question_id", str(uuid.uuid4())) for q in variants],
            ai_meta={"retry_mode": MODE_VARIANT, "source": "wrong_retry",
                     "generated_questions": variants,
                     "message": "变式重刷：知识点不变，题型/数字/问法变化"},
            user_id=user_id,
        )
        session["questions"] = variants
        session["retry_mode"] = MODE_VARIANT
        return session

    async def _generate_variant(
        self,
        original: dict[str, Any],
        user_id: str,
    ) -> dict[str, Any] | None:
        parsed, _meta = await self.ai.complete_json(
            action_type="variant_question_gen",
            system_prompt=_VARIANT_SYS,
            prompt=_VARIANT_USER.format(
                stem=original.get("stem", ""),
                knowledge_id=original.get("knowledge_id", ""),
                answer=original.get("answer", ""),
                question_type=original.get("question_type", ""),
            ),
            user_id=user_id,
        )
        if not isinstance(parsed, dict) or not parsed.get("stem"):
            return None
        return {
            "question_id": f"variant_{uuid.uuid4().hex[:12]}",
            "knowledge_id": original.get("knowledge_id", ""),
            "stem": str(parsed.get("stem", "")),
            "answer": str(parsed.get("answer", "")),
            "analysis": str(parsed.get("analysis", "")),
            "question_type": str(parsed.get("question_type") or original.get("question_type", "")),
            "difficulty_level": int(parsed.get("difficulty_level") or original.get("difficulty_level") or 3),
            "options": original.get("options"),
            "is_generated": True,
            "source_question_id": original["question_id"],
        }

    # -- mixed ---------------------------------------------------------------

    async def _session_mixed(
        self,
        limit: int,
        user_id: str,
    ) -> dict[str, Any]:
        wrong_list = self.ls.list_wrong_questions(user_id)
        if not wrong_list:
            return {"session_id": "", "questions": [], "retry_mode": MODE_MIXED,
                    "error": "无错题记录，请先完成一次练习。"}

        # Collect weak knowledge points and error reasons
        kid_counts: dict[str, int] = {}
        reasons: list[str] = []
        for w in wrong_list:
            kid = str(w.get("knowledge_id") or "")
            if kid:
                kid_counts[kid] = kid_counts.get(kid, 0) + int(w.get("wrong_count") or 1)
            r = str(w.get("wrong_reason") or w.get("error_reason") or "")
            if r:
                reasons.append(r)

        top_kids = [k for k, _ in sorted(kid_counts.items(), key=lambda x: x[1], reverse=True)[:5]]
        top_reasons = list(dict.fromkeys(reasons))[:5]

        # Build human-readable labels
        labels: list[str] = []
        for kid in top_kids:
            detail = self.cs.get_knowledge(kid, question_limit=0)
            if detail:
                name = detail.get("knowledge", {}).get("knowledge_name") or kid
                labels.append(f"{kid}（{name}）")
            else:
                labels.append(kid)

        mixed: list[dict[str, Any]] = []
        for _ in range(min(limit, 3)):
            parsed, _meta = await self.ai.complete_json(
                action_type="mixed_question_gen",
                system_prompt=_MIXED_SYS,
                prompt=_MIXED_USER.format(
                    knowledge_list="\n".join(f"- {lb}" for lb in labels),
                    error_reasons="\n".join(f"- {r}" for r in top_reasons) or "暂无",
                ),
                user_id=user_id,
            )
            if isinstance(parsed, dict) and parsed.get("stem"):
                mixed.append({
                    "question_id": f"mixed_{uuid.uuid4().hex[:12]}",
                    "knowledge_id": top_kids[0] if top_kids else "",
                    "knowledge_ids": list(parsed.get("knowledge_ids") or top_kids[:3]),
                    "stem": str(parsed.get("stem", "")),
                    "answer": str(parsed.get("answer", "")),
                    "analysis": str(parsed.get("analysis", "")),
                    "question_type": str(parsed.get("question_type") or "综合题"),
                    "difficulty_level": int(parsed.get("difficulty_level") or 4),
                    "is_generated": True,
                    "is_mixed": True,
                })

        # Fallback: pull real questions per weak knowledge point
        if not mixed:
            for kid in top_kids[:limit]:
                qs = self.cs.select_questions(knowledge_id=kid, question_family="choice", limit=1)
                mixed.extend(qs)

        pk_id = top_kids[0] if top_kids else ""
        session = self.ls.create_practice_session(
            session_type="wrong_retry",
            title="组合重刷（综合挑战）",
            knowledge_id=pk_id,
            question_ids=[q.get("question_id", str(uuid.uuid4())) for q in mixed],
            ai_meta={"retry_mode": MODE_MIXED, "source": "wrong_retry",
                     "generated_questions": mixed,
                     "weakness_knowledge_ids": top_kids,
                     "message": "组合重刷：多薄弱知识点综合挑战"},
            user_id=user_id,
        )
        session["questions"] = mixed
        session["retry_mode"] = MODE_MIXED
        session["weakness_knowledge_ids"] = top_kids
        return session

    # -----------------------------------------------------------------------
    # Submit retry and write-back
    # -----------------------------------------------------------------------

    async def submit_retry_session(
        self,
        session_id: str,
        answers: list[dict[str, Any]],
        user_id: str = DEFAULT_USER_ID,
    ) -> dict[str, Any] | None:
        """Grade retry answers and write back to wrong_question + mastery + stage_attempt."""
        session = self.ls.get_practice_session(session_id, user_id)
        if not session:
            return None

        retry_mode = (session.get("ai_metadata") or {}).get("retry_mode", MODE_ORIGINAL)
        generated = (session.get("ai_metadata") or {}).get("generated_questions") or []
        questions = generated if generated else self.cs.get_questions(
            session.get("question_ids") or []
        )

        # Grade using the practice service
        from .practice import KaoyanPracticeService
        svc = KaoyanPracticeService(self.cs, self.ls)
        answer_map = {str(a.get("question_id")): a for a in answers}
        results = await svc.grade_questions(questions, answer_map, user_id)

        # Write-back for every answer
        for item in results:
            self.ls.record_wrong_retry(
                question_id=item["question_id"],
                is_correct=bool(item.get("is_correct")),
                retry_mode=retry_mode,
                wrong_reason=item.get("error_reason", ""),
                knowledge_id=item.get("knowledge_id", ""),
                session_id=session_id,
                user_id=user_id,
            )

        total = len(results)
        correct = sum(1 for r in results if r.get("is_correct"))

        return {
            "session_id": session_id,
            "retry_mode": retry_mode,
            "total_count": total,
            "correct_count": correct,
            "accuracy": correct / total if total else 0.0,
            "answers": results,
            "wrong_question_ids": [r["question_id"] for r in results if not r.get("is_correct")],
            "mastery_updated": True,
            "stage_progress_updated": True,
        }
