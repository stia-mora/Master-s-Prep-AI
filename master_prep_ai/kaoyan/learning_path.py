"""Learning path and mastery gate service for the Kaoyan loop."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .content_store import KaoyanContentStore
from .learning_store import DEFAULT_USER_ID, KaoyanLearningStore
from .practice import KaoyanPracticeService

DEFAULT_PASS_THRESHOLD = 90.0


class KaoyanLearningPathService:
    def __init__(self, content_store: KaoyanContentStore, learning_store: KaoyanLearningStore) -> None:
        self.content_store = content_store
        self.learning_store = learning_store
        self.practice = KaoyanPracticeService(content_store, learning_store)

    def get_learning_path(self, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
        path = self.learning_store.get_active_learning_path(user_id)
        if path is None:
            path = self.refresh_learning_path(user_id)
        return self._with_stage_summaries(path, user_id)

    def refresh_learning_path(self, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
        profile = self.learning_store.get_profile(user_id) or {}
        report = self.learning_store.get_latest_confirmed_diagnostic_report(user_id)
        signals = self.learning_store.collect_learning_path_signals(user_id)
        knowledge = self._select_knowledge_sequence(profile, report, signals)
        portrait_summary = self._portrait_summary(profile, report, signals)
        evidence = self._path_evidence(report, signals)
        stages = [
            {
                "knowledge_ids": [item["knowledge_id"]],
                "title": self._stage_title(index, item),
                "pass_threshold": DEFAULT_PASS_THRESHOLD,
                "unlock_rule": {"previous_stage_passed": index > 0, "pass_threshold": DEFAULT_PASS_THRESHOLD},
                "context": {
                    "stage_context": self._stage_context(item, profile, report, signals),
                    "weakness_tags": self._weakness_tags(item["knowledge_id"], report, signals),
                    "portrait_summary": portrait_summary,
                },
            }
            for index, item in enumerate(knowledge)
        ]
        path = self.learning_store.replace_learning_path(
            user_id=user_id,
            goal=str(profile.get("target_major") or profile.get("target_school") or "kaoyan-math"),
            source_snapshot_id=str((report or {}).get("report_id") or "fallback_snapshot"),
            portrait_summary=portrait_summary,
            evidence=evidence,
            stages=stages,
        )
        for stage in path.get("stages", []):
            self._recalculate_stage(stage, user_id, increment_attempt=False)
        refreshed = self.learning_store.get_active_learning_path(user_id) or path
        return self._with_stage_summaries(refreshed, user_id)

    def start_stage(self, stage_id: str, user_id: str = DEFAULT_USER_ID) -> dict[str, Any] | None:
        stage = self.learning_store.get_learning_stage(stage_id, user_id)
        if stage is None:
            return None
        progress = stage.get("progress") or {}
        if not progress.get("unlocked"):
            return {"stage": stage, "error": "stage_locked"}
        knowledge_id = (stage.get("knowledge_ids") or [""])[0]
        questions = self.content_store.select_questions(
            knowledge_id=knowledge_id,
            question_family="choice",
            limit=5,
        )
        if not questions and knowledge_id:
            questions = self.content_store.select_questions(question_family="choice", limit=5)
        session = self.learning_store.create_practice_session(
            session_type="stage",
            title=f"Stage practice: {stage.get('title') or stage_id}",
            knowledge_id=knowledge_id,
            question_ids=[item["question_id"] for item in questions],
            ai_meta={
                "source": "learning_stage",
                "stage_id": stage_id,
                "path_id": stage.get("path_id"),
                "knowledge_ids": stage.get("knowledge_ids") or [],
            },
            user_id=user_id,
        )
        session["questions"] = questions
        return {"stage": stage, "practice_session": session}

    async def submit_stage(
        self,
        stage_id: str,
        payload: dict[str, Any],
        user_id: str = DEFAULT_USER_ID,
    ) -> dict[str, Any] | None:
        stage = self.learning_store.get_learning_stage(stage_id, user_id)
        if stage is None:
            return None
        practice_result = None
        session_id = str(payload.get("practice_session_id") or payload.get("session_id") or "")
        answers = payload.get("answers") or []
        if session_id and answers:
            practice_result = await self.practice.submit_session(session_id, answers, user_id)
        elif isinstance(answers, list) and answers and all("is_correct" in item for item in answers if isinstance(item, dict)):
            practice_result = {
                "answers": answers,
                "total_count": len(answers),
                "correct_count": sum(1 for item in answers if item.get("is_correct")),
            }
        progress = self._recalculate_stage(stage, user_id, increment_attempt=True)
        if progress is None:
            return None
        next_stage_unlocked = False
        path = self.learning_store.get_active_learning_path(user_id)
        if path:
            stages = path.get("stages") or []
            for index, item in enumerate(stages):
                if item.get("stage_id") == stage_id and index + 1 < len(stages):
                    next_stage_unlocked = bool((stages[index + 1].get("progress") or {}).get("unlocked"))
                    break
        return {
            "stage_id": stage_id,
            "mastery_score": progress["mastery_score"],
            "passed": progress["passed"],
            "unlock_next_stage": next_stage_unlocked,
            "next_action": progress["next_action"],
            "reason": progress["last_reason"],
            "evidence": progress["evidence"],
            "practice_result": practice_result,
        }

    def _recalculate_stage(
        self,
        stage: dict[str, Any],
        user_id: str,
        *,
        increment_attempt: bool,
    ) -> dict[str, Any] | None:
        knowledge_ids = [str(item) for item in stage.get("knowledge_ids") or [] if str(item)]
        metrics, evidence = self._stage_metrics(knowledge_ids, user_id)
        score = (
            metrics["recent_accuracy"] * 25
            + metrics["difficulty_weight"] * 15
            + metrics["variant_stability"] * 20
            + metrics["wrong_reason_reduction"] * 15
            + metrics["review_retention"] * 15
            + metrics["process_quality"] * 10
        )
        threshold = float(stage.get("pass_threshold") or DEFAULT_PASS_THRESHOLD)
        passed = score >= threshold
        reason = self._reason(metrics, score, threshold)
        next_action = self._next_action(metrics, passed)
        progress = self.learning_store.update_stage_progress(
            user_id=user_id,
            stage_id=str(stage.get("stage_id") or stage.get("id")),
            mastery_score=score,
            passed=passed,
            unlocked=bool((stage.get("progress") or {}).get("unlocked", True)),
            reason=reason,
            next_action=next_action,
            evidence=evidence,
            increment_attempt=increment_attempt,
        )
        return progress

    def _select_knowledge_sequence(
        self,
        profile: dict[str, Any],
        report: dict[str, Any] | None,
        signals: dict[str, Any],
    ) -> list[dict[str, Any]]:
        ordered_ids: list[str] = []
        if report:
            ordered_ids.extend(str(item) for item in report.get("weak_knowledge_ids") or [] if str(item))
        ordered_ids.extend(
            str(item.get("knowledge_id"))
            for item in signals.get("wrong_questions", [])
            if item.get("knowledge_id")
        )
        ordered_ids.extend(
            str(item.get("knowledge_id"))
            for item in signals.get("mastery_records", [])
            if item.get("knowledge_id") and float(item.get("mastery_score") or 0) < 75
        )
        sample = self._sample_knowledge(limit=12)
        ordered_ids.extend(str(item.get("knowledge_id")) for item in sample if item.get("knowledge_id"))
        unique_ids: list[str] = []
        for knowledge_id in ordered_ids:
            if knowledge_id and knowledge_id not in unique_ids:
                unique_ids.append(knowledge_id)
        selected: list[dict[str, Any]] = []
        for knowledge_id in unique_ids[:8]:
            selected.append(self._knowledge_brief(knowledge_id))
            if len(selected) >= 3:
                break
        while len(selected) < 3 and sample:
            candidate = self._knowledge_brief(str(sample[len(selected) % len(sample)].get("knowledge_id") or ""))
            if candidate["knowledge_id"] not in {item["knowledge_id"] for item in selected}:
                selected.append(candidate)
            else:
                break
        if not selected:
            selected = [
                {"knowledge_id": "diagnostic", "knowledge_name": "Diagnostic foundation", "full_path": "Diagnostic foundation"}
            ]
        return selected

    def _sample_knowledge(self, limit: int) -> list[dict[str, Any]]:
        try:
            return self.content_store.sample_knowledge_for_plan(limit=limit)
        except Exception:
            try:
                return self.content_store.list_knowledge_points()[:limit]
            except Exception:
                return []

    def _knowledge_brief(self, knowledge_id: str) -> dict[str, Any]:
        try:
            detail = self.content_store.get_knowledge(knowledge_id, question_limit=1)
        except Exception:
            detail = None
        if detail and detail.get("knowledge"):
            knowledge = detail["knowledge"]
            return {
                "knowledge_id": str(knowledge.get("knowledge_id") or knowledge_id),
                "knowledge_name": str(knowledge.get("knowledge_name") or knowledge_id),
                "full_path": str(knowledge.get("full_path") or knowledge.get("section") or knowledge.get("chapter") or ""),
            }
        return {"knowledge_id": knowledge_id, "knowledge_name": knowledge_id, "full_path": knowledge_id}

    def _stage_metrics(self, knowledge_ids: list[str], user_id: str) -> tuple[dict[str, float], list[dict[str, Any]]]:
        signals = self.learning_store.collect_learning_path_signals(user_id, knowledge_ids=knowledge_ids)
        answers = signals["answers"]
        wrongs = [item for item in signals["wrong_questions"] if item.get("review_status") != "mastered"]
        reviews = signals["reviews"]
        mastery = signals["mastery_records"]

        recent_accuracy = self._ratio(sum(1 for item in answers[:10] if item.get("is_correct")), min(len(answers), 10), 0.6)
        correct_difficulties = [float(item.get("difficulty_level") or 3.5) for item in answers if item.get("is_correct")]
        difficulty_weight = min(1.0, (sum(correct_difficulties) / len(correct_difficulties)) / 5) if correct_difficulties else 0.6
        unique_correct = {str(item.get("question_id")) for item in answers if item.get("is_correct")}
        variant_stability = self._ratio(len(unique_correct), max(3, len({str(item.get("question_id")) for item in answers})), 0.6)
        wrong_reason_reduction = max(0.25, 0.85 - min(0.6, len(wrongs) * 0.12))
        if reviews:
            mastered_reviews = sum(1 for item in reviews if item.get("status") == "mastered")
            failed_reviews = sum(1 for item in reviews if item.get("status") == "failed")
            review_retention = max(0.25, min(1.0, 0.55 + mastered_reviews * 0.18 - failed_reviews * 0.22))
        else:
            review_retention = 0.85 if len(answers) >= 8 and recent_accuracy >= 0.9 else 0.6
        process_quality = recent_accuracy
        if mastery:
            mastery_score = sum(float(item.get("mastery_score") or 0) for item in mastery) / len(mastery) / 100
            recent_accuracy = (recent_accuracy + mastery_score) / 2
        metrics = {
            "recent_accuracy": recent_accuracy,
            "difficulty_weight": difficulty_weight,
            "variant_stability": variant_stability,
            "wrong_reason_reduction": wrong_reason_reduction,
            "review_retention": review_retention,
            "process_quality": process_quality,
        }
        evidence = [
            {"type": "answer_record", "count": len(answers), "knowledge_ids": knowledge_ids},
            {"type": "wrong_question", "count": len(wrongs), "top_reasons": self._top_reasons(wrongs)},
            {"type": "review_queue", "count": len(reviews), "failed": sum(1 for item in reviews if item.get("status") == "failed")},
            {"type": "mastery_record", "count": len(mastery)},
        ]
        return metrics, evidence

    def _reason(self, metrics: dict[str, float], score: float, threshold: float) -> dict[str, Any]:
        blockers: list[str] = []
        blocker_labels = {
            "recent_accuracy_low": "???????",
            "variant_stability_low": "????????",
            "wrong_reason_still_active": "????????",
            "review_retention_low": "???????",
        }
        if metrics["recent_accuracy"] < 0.8:
            blockers.append("recent_accuracy_low")
        if metrics["variant_stability"] < 0.8:
            blockers.append("variant_stability_low")
        if metrics["wrong_reason_reduction"] < 0.75:
            blockers.append("wrong_reason_still_active")
        if metrics["review_retention"] < 0.75:
            blockers.append("review_retention_low")
        if score >= threshold:
            summary = "???????,????????"
        elif blockers:
            summary = "????????:" + "?".join(blocker_labels.get(item, item) for item in blockers)
        else:
            summary = "????????:?????????,???????????????"
        return {
            "summary": summary,
            "blockers": blockers,
            "metrics": {key: round(value, 3) for key, value in metrics.items()},
            "threshold": threshold,
        }

    def _localize_reason_summary(self, reason: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(reason, dict):
            return reason
        summary = str(reason.get("summary") or "")
        blocker_labels = {
            "recent_accuracy_low": "???????",
            "variant_stability_low": "????????",
            "wrong_reason_still_active": "????????",
            "review_retention_low": "???????",
        }
        if summary == "Mastery gate passed. Next stage is unlocked.":
            reason["summary"] = "???????,????????"
        elif summary == "Mastery gate not passed: complete more stage practice for stronger evidence.":
            reason["summary"] = "????????:?????????,???????????????"
        elif summary.startswith("Mastery gate not passed: "):
            raw_blockers = summary.replace("Mastery gate not passed: ", "").split(",")
            labels = [blocker_labels.get(item.strip(), item.strip()) for item in raw_blockers if item.strip()]
            reason["summary"] = "????????:" + "?".join(labels)
        return reason

    def _next_action(self, metrics: dict[str, float], passed: bool) -> str:
        if passed:
            return "unlock_next_stage"
        if metrics["recent_accuracy"] < 0.8:
            return "foundation_practice"
        if metrics["variant_stability"] < 0.8:
            return "variant_practice"
        if metrics["review_retention"] < 0.75:
            return "review_foundation"
        return "complete_more_stage_questions"

    def _portrait_summary(
        self,
        profile: dict[str, Any],
        report: dict[str, Any] | None,
        signals: dict[str, Any],
    ) -> dict[str, Any]:
        weak_tags = list(profile.get("weak_modules") or [])
        if report:
            weak_tags.extend(str(item) for item in report.get("weak_knowledge_ids") or [])
        return {
            "baseline_level": profile.get("baseline_level") or "unknown",
            "daily_minutes": profile.get("daily_minutes") or 120,
            "weakness_tags": list(dict.fromkeys(str(item) for item in weak_tags if str(item)))[:8],
            "wrong_question_count": len(signals.get("wrong_questions") or []),
            "low_mastery_count": sum(
                1 for item in signals.get("mastery_records") or [] if float(item.get("mastery_score") or 0) < 75
            ),
        }

    def _path_evidence(self, report: dict[str, Any] | None, signals: dict[str, Any]) -> list[dict[str, Any]]:
        evidence = [
            {"type": "diagnostic_report", "id": (report or {}).get("report_id"), "confirmed": bool(report)},
            {"type": "wrong_questions", "count": len(signals.get("wrong_questions") or [])},
            {"type": "mastery_records", "count": len(signals.get("mastery_records") or [])},
            {"type": "review_queue", "count": len(signals.get("reviews") or [])},
        ]
        return evidence

    def _stage_context(
        self,
        item: dict[str, Any],
        profile: dict[str, Any],
        report: dict[str, Any] | None,
        signals: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "knowledge_id": item["knowledge_id"],
            "knowledge_name": item["knowledge_name"],
            "full_path": item.get("full_path", ""),
            "diagnostic_report_id": (report or {}).get("report_id"),
            "target_score": profile.get("target_score"),
            "recent_wrong_count": sum(
                1 for wrong in signals.get("wrong_questions", []) if wrong.get("knowledge_id") == item["knowledge_id"]
            ),
        }

    def _weakness_tags(
        self,
        knowledge_id: str,
        report: dict[str, Any] | None,
        signals: dict[str, Any],
    ) -> list[str]:
        tags = []
        if report and knowledge_id in set(str(item) for item in report.get("weak_knowledge_ids") or []):
            tags.append("diagnostic_weakness")
        if any(item.get("knowledge_id") == knowledge_id for item in signals.get("wrong_questions", [])):
            tags.append("wrong_question_hotspot")
        if any(
            item.get("knowledge_id") == knowledge_id and float(item.get("mastery_score") or 0) < 75
            for item in signals.get("mastery_records", [])
        ):
            tags.append("low_mastery")
        return tags or ["path_foundation"]

    def _with_stage_summaries(self, path: dict[str, Any], user_id: str) -> dict[str, Any]:
        stages = path.get("stages") or []
        for stage in stages:
            progress = stage.get("progress") or {}
            if progress.get("last_reason"):
                progress["last_reason"] = self._localize_reason_summary(progress["last_reason"])
        path["current_stage"] = next(
            (stage for stage in stages if (stage.get("progress") or {}).get("unlocked") and not (stage.get("progress") or {}).get("passed")),
            stages[0] if stages else None,
        )
        path["unlocked_stages"] = [stage for stage in stages if (stage.get("progress") or {}).get("unlocked")]
        path["portrait_summary"] = path.get("portrait_summary") or {}
        return path

    def _stage_title(self, index: int, item: dict[str, Any]) -> str:
        return f"Stage {index + 1}: {item.get('knowledge_name') or item.get('knowledge_id')}"

    def _top_reasons(self, wrongs: list[dict[str, Any]]) -> list[str]:
        counts = Counter(str(item.get("error_reason") or "unknown") for item in wrongs)
        return [reason for reason, _count in counts.most_common(3)]

    def _ratio(self, numerator: int, denominator: int, default: float) -> float:
        if denominator <= 0:
            return default
        return max(0.0, min(1.0, numerator / denominator))
