"""LLM-assisted entry diagnostic tests for Kaoyan student profiling."""

from __future__ import annotations

from datetime import date
from typing import Any

from .ai_service import KaoyanAIService
from .content_store import KaoyanContentStore
from .learning_store import DEFAULT_USER_ID, KaoyanLearningStore
from .practice import KaoyanPracticeService

DIAGNOSTIC_SYSTEM_PROMPT = """
你是考研数学高数诊断测评命题老师。目标是用很短测验判断学生当前水平，而不是刷题训练。
命题要求：
1. 覆盖函数、极限、连续、导数/微分、不定积分、定积分中最能区分基础的知识点。
2. 轻度诊断 5 分钟：5 题，3 道选择题、1 道填空题、1 道简答/解答题，难度 1-3。
3. 重度诊断 30 分钟：12 题，4 道选择题、4 道填空题、4 道解答题，难度 1-5，覆盖概念、计算、综合应用。
4. 每道题必须有明确参考答案、简短解析、考察知识点 ID 或名称、预估耗时、区分度说明。
5. 不要出偏题怪题，不考超纲内容；题目应适合考研数学学生的真实画像评估。
6. 输出必须是 JSON，不要 Markdown。
JSON 格式：
{
  "title": "...",
  "diagnostic_goal": "...",
  "questions": [
    {
      "question_id": "diag_001",
      "knowledge_id": "LECTURE 或知识名称",
      "question_type": "选择题|填空题|解答题",
      "difficulty_level": 1,
      "stem": "题干，选择题不要把选项混在题干中",
      "options": [{"label":"A","content":"..."}],
      "answer": "...",
      "analysis": "...",
      "estimated_seconds": 60,
      "diagnostic_signal": "这道题能暴露什么问题"
    }
  ]
}
""".strip()


DIAGNOSTIC_USER_PROMPT = """
请为下面学生生成一套{minutes}分钟的高等数学入门诊断测验。

【学生基本信息】
{profile}

【考试日期】{exam_date}
【今天日期】{today}

【可用讲义知识点样例】
{knowledge}

【可参考题库题型样例】
{seed_questions}

请重点诊断：
- 是否理解基本概念，而不是只会套公式；
- 极限、导数、积分的基本计算是否稳定；
- 选择题是否能快速排除；
- 填空/解答题是否有规范表达和关键步骤。

模式：{mode}
只输出 JSON。
""".strip()


PROFILE_DRAFT_SYSTEM_PROMPT = """
你是考研数学学习画像诊断老师。请根据诊断答题记录生成一份可让学生确认的画像草案。
要求：
1. 不要夸大诊断结论，明确这是基于短测得到的初始画像。
2. baseline_level 只能是：待诊断、基础薄弱、基础、一般、强化、冲刺。
3. weak_modules 使用学生能理解的中文模块名，例如：函数、极限、连续、导数、不定积分、定积分。
4. module_scores 是对象，key 为模块名，value 为 0-100 分。
5. risk_flags 写具体风险，不要泛泛而谈。
6. plan_focus 给 3-5 条优先学习路径。
7. 输出必须是 JSON，不要 Markdown。
JSON 字段：
{"baseline_level":"...","weak_modules":["..."],"module_scores":{"极限":60},"strengths":["..."],"risk_flags":["..."],"recommended_daily_minutes":180,"plan_focus":["..."],"reasoning_summary":"..."}
""".strip()


PROFILE_DRAFT_PROMPT = """
【学生原始基本信息】
{profile}

【诊断模式】{mode}
【诊断结果】
{results}

【正确率】{accuracy}

请生成画像草案。该画像将展示给学生确认，确认后用于生成学习计划。
""".strip()


class KaoyanDiagnosticService:
    def __init__(self, content_store: KaoyanContentStore, learning_store: KaoyanLearningStore) -> None:
        self.content_store = content_store
        self.learning_store = learning_store
        self.ai = KaoyanAIService(learning_store)
        self.practice = KaoyanPracticeService(content_store, learning_store)

    async def create_session(self, mode: str = "light", profile: dict[str, Any] | None = None, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
        mode = "deep" if mode == "deep" else "light"
        minutes = 30 if mode == "deep" else 5
        limit = 12 if mode == "deep" else 5
        current_profile = profile or self.learning_store.get_profile(user_id) or {}
        knowledge = self.content_store.sample_knowledge_for_plan(limit=10)
        seed_questions = self.content_store.select_questions(limit=min(limit, 8))
        parsed, meta = await self.ai.complete_json(
            action_type=f"diagnostic_generate_{mode}",
            system_prompt=DIAGNOSTIC_SYSTEM_PROMPT,
            prompt=DIAGNOSTIC_USER_PROMPT.format(
                minutes=minutes,
                profile=current_profile,
                exam_date=current_profile.get("exam_date") or "未填写",
                today=date.today().isoformat(),
                knowledge=knowledge,
                seed_questions=[self._question_brief(q) for q in seed_questions],
                mode="轻度诊断" if mode == "light" else "重度诊断",
            ),
            user_id=user_id,
        )
        questions = self._normalize_generated_questions(parsed, mode, limit) if parsed else []
        if not questions:
            questions = seed_questions[:limit]
            meta = {**meta, "message": "AI 诊断生成失败，已使用题库基础诊断"}
        title = parsed.get("title") if isinstance(parsed, dict) and parsed.get("title") else f"高数{'30分钟' if mode == 'deep' else '5分钟'}诊断测验"
        session = self.learning_store.create_practice_session(
            session_type=f"diagnostic_{mode}",
            title=str(title),
            knowledge_id="diagnostic",
            question_ids=[item["question_id"] for item in questions],
            ai_meta={
                "message": meta.get("message", ""),
                "mode": mode,
                "minutes": minutes,
                "profile_seed": current_profile,
                "generated_questions": questions,
                "diagnostic_goal": parsed.get("diagnostic_goal", "") if isinstance(parsed, dict) else "",
            },
            user_id=user_id,
        )
        session["questions"] = questions
        session["mode"] = mode
        session["ai_metadata"] = {**(session.get("ai_metadata") or {}), "ai_used": meta.get("ai_used"), "status": meta.get("status")}
        return session

    async def submit_session(self, session_id: str, answers: list[dict[str, Any]], user_id: str = DEFAULT_USER_ID) -> dict[str, Any] | None:
        session = self.learning_store.get_practice_session(session_id, user_id)
        if not session:
            return None
        metadata = session.get("ai_metadata") or {}
        questions = metadata.get("generated_questions") or self.content_store.get_questions(session.get("question_ids") or [])
        answer_map = {str(item.get("question_id")): item for item in answers}
        results = await self.practice.grade_questions(questions, answer_map, user_id)
        summary = self._diagnostic_summary(results)
        next_actions = self._next_actions(results)
        record = self.learning_store.record_practice_submission(session, results, summary, next_actions, user_id)
        profile_seed = metadata.get("profile_seed") or self.learning_store.get_profile(user_id) or {}
        profile_draft, ai_meta = await self._profile_draft(profile_seed, metadata.get("mode", "light"), results)
        return {
            "session_id": session_id,
            "record_id": record["record_id"],
            "summary": summary,
            "profile_draft": profile_draft,
            "answers": results,
            "mastery_updates": self._mastery_updates(results),
            "ai_metadata": ai_meta,
        }

    async def _profile_draft(self, profile: dict[str, Any], mode: str, results: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        total = len(results)
        correct = sum(1 for item in results if item.get("is_correct"))
        accuracy = correct / total if total else 0.0
        fallback = self._fallback_profile_draft(profile, results, accuracy)
        parsed, meta = await self.ai.complete_json(
            action_type="diagnostic_profile_draft",
            system_prompt=PROFILE_DRAFT_SYSTEM_PROMPT,
            prompt=PROFILE_DRAFT_PROMPT.format(
                profile=profile,
                mode="轻度诊断" if mode == "light" else "重度诊断",
                results=results,
                accuracy=f"{accuracy:.0%}",
            ),
        )
        if isinstance(parsed, dict):
            return {**fallback, **self._normalize_profile_draft(parsed, fallback)}, meta
        return fallback, meta

    def _normalize_generated_questions(self, parsed: dict[str, Any] | None, mode: str, limit: int) -> list[dict[str, Any]]:
        if not isinstance(parsed, dict) or not isinstance(parsed.get("questions"), list):
            return []
        questions: list[dict[str, Any]] = []
        for index, raw in enumerate(parsed["questions"][:limit], start=1):
            if not isinstance(raw, dict):
                continue
            options = raw.get("options") if isinstance(raw.get("options"), list) else []
            qtype = str(raw.get("question_type") or ("选择题" if options else "解答题"))
            normalized_options = [
                {"label": str(item.get("label", "")).upper()[:1], "content": str(item.get("content", ""))}
                for item in options
                if isinstance(item, dict) and item.get("label") and item.get("content")
            ]
            questions.append(
                {
                    "question_id": str(raw.get("question_id") or f"diag_{mode}_{index:03d}"),
                    "knowledge_id": str(raw.get("knowledge_id") or "diagnostic"),
                    "question_type": qtype,
                    "difficulty_level": int(raw.get("difficulty_level") or 2),
                    "stem": str(raw.get("stem") or ""),
                    "stem_without_options": str(raw.get("stem") or ""),
                    "options": normalized_options,
                    "answer": str(raw.get("answer") or ""),
                    "analysis": str(raw.get("analysis") or raw.get("diagnostic_signal") or ""),
                    "source": "llm_diagnostic",
                    "source_type": "diagnostic",
                    "year": None,
                    "is_choice": "选择" in qtype or bool(normalized_options),
                    "diagnostic_signal": str(raw.get("diagnostic_signal") or ""),
                    "estimated_seconds": int(raw.get("estimated_seconds") or 60),
                }
            )
        return [item for item in questions if item["stem"] and item["answer"]]

    def _normalize_profile_draft(self, parsed: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        weak_modules = parsed.get("weak_modules") if isinstance(parsed.get("weak_modules"), list) else fallback["weak_modules"]
        strengths = parsed.get("strengths") if isinstance(parsed.get("strengths"), list) else fallback["strengths"]
        risk_flags = parsed.get("risk_flags") if isinstance(parsed.get("risk_flags"), list) else fallback["risk_flags"]
        plan_focus = parsed.get("plan_focus") if isinstance(parsed.get("plan_focus"), list) else fallback["plan_focus"]
        module_scores = parsed.get("module_scores") if isinstance(parsed.get("module_scores"), dict) else fallback["module_scores"]
        return {
            "baseline_level": str(parsed.get("baseline_level") or fallback["baseline_level"]),
            "weak_modules": [str(item) for item in weak_modules][:8],
            "module_scores": {str(key): max(0, min(100, int(value))) for key, value in module_scores.items()},
            "strengths": [str(item) for item in strengths][:6],
            "risk_flags": [str(item) for item in risk_flags][:6],
            "recommended_daily_minutes": int(parsed.get("recommended_daily_minutes") or fallback["recommended_daily_minutes"]),
            "plan_focus": [str(item) for item in plan_focus][:6],
            "reasoning_summary": str(parsed.get("reasoning_summary") or fallback["reasoning_summary"]),
        }

    def _fallback_profile_draft(self, profile: dict[str, Any], results: list[dict[str, Any]], accuracy: float) -> dict[str, Any]:
        wrong = [item for item in results if not item.get("is_correct")]
        weak = self._weak_modules(wrong) or ["极限", "导数"]
        baseline = "基础薄弱" if accuracy < 0.35 else "基础" if accuracy < 0.6 else "一般" if accuracy < 0.8 else "强化"
        daily = int(profile.get("daily_minutes") or 180)
        if accuracy < 0.5:
            daily = max(daily, 180)
        module_scores = {module: max(30, int(accuracy * 100) - 10) for module in weak}
        return {
            "baseline_level": baseline,
            "weak_modules": weak,
            "module_scores": module_scores,
            "strengths": ["已完成初始诊断", "可进入分模块学习闭环"] if accuracy >= 0.5 else ["愿意进行诊断", "需要先补核心概念"],
            "risk_flags": ["短测暴露基础不稳定，需要先抓概念和标准步骤"] if wrong else ["短测表现较稳，后续需用更高难度题继续校准"],
            "recommended_daily_minutes": daily,
            "plan_focus": [f"优先复盘{module}" for module in weak[:3]] + ["每天完成错题二刷和公式回顾"],
            "reasoning_summary": f"本次诊断正确率约 {accuracy:.0%}，画像为初始估计，建议结合后续练习动态修正。",
        }

    def _weak_modules(self, wrong: list[dict[str, Any]]) -> list[str]:
        modules: list[str] = []
        mapping = {
            "函数": "函数",
            "极限": "极限",
            "连续": "连续",
            "导数": "导数",
            "微分": "导数",
            "积分": "积分",
        }
        for item in wrong:
            text = f"{item.get('stem', '')} {item.get('knowledge_id', '')} {item.get('error_reason', '')}"
            for key, module in mapping.items():
                if key in text and module not in modules:
                    modules.append(module)
        return modules[:5]

    def _diagnostic_summary(self, results: list[dict[str, Any]]) -> str:
        total = len(results)
        correct = sum(1 for item in results if item.get("is_correct"))
        wrong = total - correct
        if not total:
            return "本次诊断没有收到有效作答。"
        return f"本次诊断共 {total} 题，答对 {correct} 题，答错 {wrong} 题。系统已根据短测结果生成初始画像草案，建议确认后生成计划。"

    def _next_actions(self, results: list[dict[str, Any]]) -> list[str]:
        if all(item.get("is_correct") for item in results):
            return ["确认画像", "生成强化阶段计划", "进入高阶专项练习"]
        return ["确认画像", "先补薄弱模块概念", "完成错题二刷", "生成今日计划"]

    def _mastery_updates(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "knowledge_id": item.get("knowledge_id", ""),
                "question_id": item.get("question_id", ""),
                "is_correct": bool(item.get("is_correct")),
                "error_reason": item.get("error_reason", ""),
            }
            for item in results
        ]

    def _question_brief(self, question: dict[str, Any]) -> dict[str, Any]:
        return {
            "question_type": question.get("question_type"),
            "difficulty_level": question.get("difficulty_level"),
            "knowledge_id": question.get("knowledge_id"),
            "stem": str(question.get("stem") or "")[:220],
            "options": question.get("options") or [],
        }