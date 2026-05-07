"""Practice assembly, answer grading, and submission logic for Kaoyan MVP."""

from __future__ import annotations

import re
from typing import Any

from .ai_service import KaoyanAIService
from .content_store import KaoyanContentStore
from .learning_store import DEFAULT_USER_ID, KaoyanLearningStore

_OPTION_RE = re.compile(r"[A-DＡ-Ｄ]")
_OPTION_TRANSLATION = str.maketrans("ＡＢＣＤａｂｃｄ", "ABCDabcd")


FREE_RESPONSE_GRADING_SYSTEM_PROMPT = """
你是考研数学阅卷与诊断老师。你的任务不是鼓励式聊天，而是做可信的学习诊断。
判分原则：
1. 选择题严格按选项判定。
2. 填空题允许等价形式，例如等价分式、符号变形、常数合并；但不能把关键条件缺失判为正确。
3. 解答题按思路给分：结论正确但过程缺关键步骤，不能满分；过程正确但小计算错，可给部分正确。
4. 如果学生上传图片且当前模型能读取图片，请结合图片中的书写过程；如果无法读取图片，只依据文字答案，并在 analysis 中说明图片未被实际解析。
5. 输出必须是 JSON，不要 Markdown，不要额外解释。
JSON 字段：
{"is_correct": true|false, "score": 0到1的小数, "error_reason": "一句话错因", "analysis": "2-4句解析与复盘建议"}
""".strip()


FREE_RESPONSE_GRADING_PROMPT = """
请判定下面这道考研数学题的学生作答是否正确。

【题目】
{stem}

【题型】{question_type}
【知识点ID】{knowledge_id}
【参考答案】
{correct_answer}

【标准解析】
{analysis}

【学生文字答案】
{user_answer}

【图片答案】{image_note}

请根据考研数学阅卷口径判断：
- 填空题关注最终结果是否等价；
- 解答题关注关键步骤、方法选择、结论是否成立；
- 如果答案不足以判断，判为 false，并说明缺失什么。
只输出 JSON。
""".strip()


def normalize_answer(value: str | None) -> str:
    text = str(value or "").strip().translate(_OPTION_TRANSLATION)
    if not text:
        return ""
    option = _OPTION_RE.search(text.upper())
    if option:
        return option.group(0).upper()
    return re.sub(r"\s+", "", text).strip("。；;,")


def is_correct_answer(user_answer: str, correct_answer: str) -> bool:
    user = normalize_answer(user_answer)
    correct = normalize_answer(correct_answer)
    if not user or not correct:
        return False
    return user == correct or user in correct or correct in user


def is_choice_question(question: dict[str, Any]) -> bool:
    qtype = str(question.get("question_type") or "")
    return bool(question.get("is_choice")) or "选择" in qtype or bool(question.get("options"))


class KaoyanPracticeService:
    def __init__(self, content_store: KaoyanContentStore, learning_store: KaoyanLearningStore) -> None:
        self.content_store = content_store
        self.learning_store = learning_store
        self.ai = KaoyanAIService(learning_store)

    def create_session(
        self,
        *,
        session_type: str = "special",
        knowledge_id: str | None = None,
        source_question_id: str | None = None,
        question_type: str | None = None,
        difficulty_level: int | None = None,
        limit: int = 5,
        user_id: str = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        questions: list[dict[str, Any]]
        if session_type == "wrong_retry":
            wrong_ids = self.learning_store.active_wrong_question_ids(user_id)[: max(1, limit)]
            questions = self.content_store.get_questions(wrong_ids)
        elif session_type == "similar":
            source_question = self._resolve_similar_source_question(
                source_question_id=source_question_id,
                knowledge_id=knowledge_id,
                user_id=user_id,
            )
            exclude_ids = [source_question["question_id"]] if source_question else []
            resolved_knowledge_id = knowledge_id or (source_question or {}).get("knowledge_id")
            resolved_question_type = question_type or (source_question or {}).get("question_type")
            resolved_difficulty = difficulty_level or (source_question or {}).get("difficulty_level")
            questions = self.content_store.select_questions(
                knowledge_id=resolved_knowledge_id,
                question_type=resolved_question_type,
                difficulty_level=resolved_difficulty,
                limit=limit,
                exclude_ids=exclude_ids,
            )
            if not questions and resolved_knowledge_id:
                questions = self.content_store.select_questions(knowledge_id=resolved_knowledge_id, limit=limit, exclude_ids=exclude_ids)
            if not questions:
                questions = self.content_store.select_questions(limit=limit, exclude_ids=exclude_ids)
            knowledge_id = resolved_knowledge_id
        elif session_type == "exam_simulation":
            questions = self.content_store.select_questions(
                knowledge_id=knowledge_id,
                question_type=question_type,
                difficulty_level=difficulty_level,
                limit=limit,
            )
            if not questions:
                questions = self.content_store.select_questions(limit=limit)
        else:
            questions = self.content_store.select_questions(
                knowledge_id=knowledge_id,
                question_type=question_type,
                difficulty_level=difficulty_level,
                limit=limit,
            )
            if not questions and knowledge_id:
                questions = self.content_store.select_questions(knowledge_id=knowledge_id, limit=limit)
            if not questions:
                questions = self.content_store.select_questions(limit=limit)
        title_map = {
            "wrong_retry": "Wrong question retry",
            "similar": "Similar question practice",
            "exam_simulation": "Exam simulation",
        }
        title = title_map.get(session_type, "Kaoyan practice")
        if knowledge_id:
            detail = self.content_store.get_knowledge(knowledge_id, question_limit=1)
            if detail:
                prefix = title_map.get(session_type, "Practice")
                title = f"{prefix}: {detail['knowledge']['knowledge_name']}"
        session = self.learning_store.create_practice_session(
            session_type=session_type,
            title=title,
            knowledge_id=knowledge_id or (questions[0]["knowledge_id"] if questions else ""),
            question_ids=[item["question_id"] for item in questions],
            ai_meta={"message": "Practice questions were generated by filters.", "session_type": session_type},
            user_id=user_id,
        )
        session["questions"] = questions
        return session

    def _resolve_similar_source_question(
        self,
        *,
        source_question_id: str | None,
        knowledge_id: str | None,
        user_id: str,
    ) -> dict[str, Any] | None:
        if source_question_id:
            return self.content_store.get_question(source_question_id)
        for wrong in self.learning_store.list_wrong_questions(user_id):
            if knowledge_id and wrong.get("knowledge_id") != knowledge_id:
                continue
            question = self.content_store.get_question(str(wrong.get("question_id") or ""))
            if question:
                return question
        return None

    async def submit_session(
        self,
        session_id: str,
        answers: list[dict[str, Any]],
        user_id: str = DEFAULT_USER_ID,
    ) -> dict[str, Any] | None:
        session = self.learning_store.get_practice_session(session_id, user_id)
        if not session:
            return None
        answer_map = {str(item.get("question_id")): item for item in answers}
        generated = (session.get("ai_metadata") or {}).get("generated_questions") or []
        questions = generated if generated else self.content_store.get_questions(session.get("question_ids") or [])
        results = await self.grade_questions(questions, answer_map, user_id)

        summary = self._summary(results)
        ai_messages = [item.get("ai_message", "") for item in results if item.get("ai_message")]
        if any(not item["is_correct"] for item in results):
            ai_summary, meta = await self.ai.complete_text(
                action_type="practice_summary",
                system_prompt="你是考研数学训练反馈教练。用中文给出简洁可执行建议。",
                prompt=f"本次练习结果：{results}\n请总结薄弱点和下一步行动，不超过 150 字。",
                fallback=summary,
                user_id=user_id,
            )
            summary = ai_summary
            ai_messages.append(meta.get("message", ""))
        next_actions = self._next_actions(results)
        record = self.learning_store.record_practice_submission(session, results, summary, next_actions, user_id)
        record["answers"] = results
        record["wrong_question_ids"] = [item["question_id"] for item in results if not item["is_correct"]]
        ai_success = any(message == "AI 已生成增强结果" for message in ai_messages)
        record["ai_metadata"] = {
            "ai_used": ai_success,
            "message": "AI 已生成增强结果" if ai_success else "AI 增强失败，已使用基础策略" if ai_messages else "选择题已用规则判分",
        }
        return record

    async def grade_questions(
        self,
        questions: list[dict[str, Any]],
        answer_map: dict[str, dict[str, Any]],
        user_id: str = DEFAULT_USER_ID,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for question in questions:
            qid = str(question["question_id"])
            answer_payload = answer_map.get(qid, {})
            user_answer = str(answer_payload.get("answer", ""))
            image_data_url = str(answer_payload.get("image_data_url") or answer_payload.get("imageDataUrl") or "")
            correct_answer = str(question.get("answer") or "")
            ai_message = ""
            if is_choice_question(question):
                correct = is_correct_answer(user_answer, correct_answer)
                error_reason = "已掌握" if correct else self._fallback_error_reason(user_answer, correct_answer)
                ai_analysis = self._fallback_analysis(question, correct, error_reason)
                grading_method = "rule_choice"
                if not correct:
                    ai_text, ai_meta = await self.ai.complete_text(
                        action_type="wrong_reason",
                        system_prompt="你是考研数学错因分析老师。用中文输出简洁错因和复盘建议。",
                        prompt=(
                            f"题目：{question.get('stem')}\n参考答案：{correct_answer}\n"
                            f"标准解析：{question.get('analysis') or ''}\n学生答案：{user_answer}\n"
                            "请按：错因：...\n复盘建议：... 输出。"
                        ),
                        fallback=ai_analysis,
                        user_id=user_id,
                    )
                    ai_analysis = ai_text
                    error_reason = self._extract_reason(ai_text) or error_reason
                    ai_message = ai_meta.get("message", "")
            else:
                grading = await self._grade_free_response(question, user_answer, image_data_url, user_id)
                correct = grading["is_correct"]
                ai_analysis = grading["analysis"]
                error_reason = grading["error_reason"]
                grading_method = grading["grading_method"]
                ai_message = grading["ai_message"]

            results.append(
                {
                    "question_id": qid,
                    "knowledge_id": question.get("knowledge_id", ""),
                    "stem": question.get("stem", ""),
                    "question_type": question.get("question_type", ""),
                    "difficulty_level": question.get("difficulty_level", 1),
                    "user_answer": user_answer,
                    "correct_answer": correct_answer,
                    "is_correct": bool(correct),
                    "ai_analysis": ai_analysis,
                    "error_reason": error_reason,
                    "grading_method": grading_method,
                    "has_image_answer": bool(image_data_url),
                    "ai_message": ai_message,
                }
            )
        return results

    async def _grade_free_response(self, question: dict[str, Any], user_answer: str, image_data_url: str, user_id: str) -> dict[str, Any]:
        correct_answer = str(question.get("answer") or "")
        fallback_correct = is_correct_answer(user_answer, correct_answer)
        fallback_reason = "已掌握" if fallback_correct else self._fallback_error_reason(user_answer, correct_answer)
        fallback_analysis = self._fallback_analysis(question, fallback_correct, fallback_reason)
        image_note = "无图片答案"
        if image_data_url:
            image_note = "学生上传了图片答案；当前 API 已接收 data URL。若底层模型支持视觉，请结合图片；若不支持，请说明未解析图片。"
        parsed, meta = await self.ai.complete_json(
            action_type="free_response_grade",
            system_prompt=FREE_RESPONSE_GRADING_SYSTEM_PROMPT,
            prompt=FREE_RESPONSE_GRADING_PROMPT.format(
                stem=question.get("stem", ""),
                question_type=question.get("question_type", ""),
                knowledge_id=question.get("knowledge_id", ""),
                correct_answer=correct_answer,
                analysis=question.get("analysis") or "",
                user_answer=user_answer or "（未填写文字答案）",
                image_note=image_note,
            ),
            user_id=user_id,
            image_data=image_data_url or None,
        )
        if isinstance(parsed, dict):
            score = float(parsed.get("score") or 0)
            return {
                "is_correct": bool(parsed.get("is_correct")) or score >= 0.75,
                "error_reason": str(parsed.get("error_reason") or fallback_reason)[:100],
                "analysis": str(parsed.get("analysis") or fallback_analysis),
                "grading_method": "llm_free_response",
                "ai_message": meta.get("message", ""),
            }
        return {
            "is_correct": fallback_correct,
            "error_reason": fallback_reason,
            "analysis": fallback_analysis,
            "grading_method": "fallback_free_response",
            "ai_message": meta.get("message", ""),
        }

    def _fallback_error_reason(self, user_answer: str, correct_answer: str) -> str:
        if not str(user_answer or "").strip():
            return "步骤缺失"
        if normalize_answer(user_answer) and normalize_answer(correct_answer):
            return "概念不清或公式误用"
        return "计算失误"

    def _fallback_analysis(self, question: dict[str, Any], correct: bool, reason: str) -> str:
        if correct:
            return "回答正确。建议记录本题涉及的核心公式和解题入口。"
        analysis = str(question.get("analysis") or "").strip()
        return f"错因：{reason}\n复盘建议：回到知识点 {question.get('knowledge_id')}，重看标准解析并在 24 小时内二刷。\n{analysis[:500]}"

    def _extract_reason(self, text: str) -> str:
        for line in text.splitlines():
            cleaned = line.strip().lstrip("- ")
            if cleaned.startswith("错因"):
                return cleaned.split("：", 1)[-1].split(":", 1)[-1].strip()[:80]
        return ""

    def _summary(self, results: list[dict[str, Any]]) -> str:
        total = len(results)
        wrong = [item for item in results if not item["is_correct"]]
        if not total:
            return "本次练习没有提交题目。"
        if not wrong:
            return "本次练习全部正确，可以进入更高难度或相邻知识点训练。"
        reasons = "、".join(sorted({item["error_reason"] for item in wrong if item.get("error_reason")}))
        return f"本次共 {total} 题，错 {len(wrong)} 题。主要问题：{reasons or '基础掌握不稳定'}。错题已进入二刷和复习队列。"

    def _next_actions(self, results: list[dict[str, Any]]) -> list[str]:
        wrong = [item for item in results if not item["is_correct"]]
        if not wrong:
            return ["继续完成相邻知识点专项练习", "将本组题中用到的公式加入今日复习"]
        return ["完成错题二刷", "回看相关知识点讲义", "明天优先复习本次错题"]