"""Plan generation for the Kaoyan MVP."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .ai_service import KaoyanAIService
from .content_store import KaoyanContentStore
from .learning_store import DEFAULT_USER_ID, KaoyanLearningStore


class KaoyanPlanner:
    def __init__(self, content_store: KaoyanContentStore, learning_store: KaoyanLearningStore) -> None:
        self.content_store = content_store
        self.learning_store = learning_store
        self.ai = KaoyanAIService(learning_store)

    async def generate_plan(self, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
        profile = self.learning_store.get_profile(user_id)
        if not profile:
            profile = self.learning_store.upsert_profile({}, user_id)
        knowledge = self.content_store.sample_knowledge_for_plan(limit=8)
        prompt = self._build_plan_prompt(profile, knowledge)
        parsed, ai_meta = await self.ai.complete_json(
            action_type="plan_generate",
            system_prompt="你是考研数学规划师。只输出 JSON，不要输出 Markdown。",
            prompt=prompt,
            user_id=user_id,
        )
        tasks = self._tasks_from_ai(parsed, knowledge, profile) if parsed else []
        if not tasks:
            tasks = self._fallback_tasks(knowledge, profile)
        plan = self.learning_store.create_plan("高数 7 天学习闭环计划", tasks, ai_meta, user_id)
        plan["tasks"] = self.learning_store.list_today_tasks(user_id)
        plan["ai_metadata"] = ai_meta
        return plan

    def _build_plan_prompt(self, profile: dict[str, Any], knowledge: list[dict[str, Any]]) -> str:
        return (
            "请基于学生画像和高数知识点，生成今天开始的 7 天 MVP 学习任务。\n"
            "输出 JSON：{\"tasks\":[{\"task_type\":\"study|practice|review\",\"title\":\"...\","
            "\"description\":\"...\",\"estimated_minutes\":30,\"due_offset_days\":0,"
            "\"priority_score\":4.0,\"related_knowledge_ids\":[\"...\"]}]}。\n"
            f"学生画像：{profile}\n"
            f"可用知识点：{knowledge}\n"
        )

    def _tasks_from_ai(self, parsed: dict[str, Any] | None, knowledge: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(parsed, dict) or not isinstance(parsed.get("tasks"), list):
            return []
        known_ids = {item["knowledge_id"] for item in knowledge}
        tasks: list[dict[str, Any]] = []
        for raw in parsed["tasks"][:12]:
            if not isinstance(raw, dict):
                continue
            related = [str(item) for item in raw.get("related_knowledge_ids", []) if str(item) in known_ids]
            if not related and knowledge:
                related = [knowledge[len(tasks) % len(knowledge)]["knowledge_id"]]
            due = date.today() + timedelta(days=int(raw.get("due_offset_days") or 0))
            tasks.append(
                {
                    "task_type": str(raw.get("task_type") or "study"),
                    "title": str(raw.get("title") or "高数学习任务")[:120],
                    "description": str(raw.get("description") or "")[:800],
                    "estimated_minutes": int(raw.get("estimated_minutes") or 30),
                    "due_at": due.isoformat(),
                    "priority_score": float(raw.get("priority_score") or 3.0),
                    "related_knowledge_ids": related,
                }
            )
        return tasks

    def _fallback_tasks(self, knowledge: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
        daily = max(60, int(profile.get("daily_minutes") or 120))
        primary = knowledge[:3] or [{"knowledge_id": "", "knowledge_name": "高数基础"}]
        tasks: list[dict[str, Any]] = []
        for index, point in enumerate(primary):
            kid = point.get("knowledge_id", "")
            name = point.get("knowledge_name") or point.get("section") or "高数知识点"
            due = (date.today() + timedelta(days=index)).isoformat()
            tasks.extend(
                [
                    {
                        "task_type": "study",
                        "title": f"学习 {name}",
                        "description": "阅读知识点、公式和典型易错点，完成基础理解。",
                        "estimated_minutes": max(20, daily // 4),
                        "due_at": due,
                        "priority_score": 4.0,
                        "related_knowledge_ids": [kid] if kid else [],
                    },
                    {
                        "task_type": "practice",
                        "title": f"专项练习 {name}",
                        "description": "完成 5 道同知识点题目，提交后自动生成错题和复习项。",
                        "estimated_minutes": max(25, daily // 3),
                        "due_at": due,
                        "priority_score": 4.5,
                        "related_knowledge_ids": [kid] if kid else [],
                    },
                ]
            )
        tasks.append(
            {
                "task_type": "review",
                "title": "复习错题与公式卡",
                "description": "处理复习队列中的错题、公式和易错卡，更新掌握度。",
                "estimated_minutes": max(15, daily // 5),
                "due_at": date.today().isoformat(),
                "priority_score": 3.8,
                "related_knowledge_ids": [item.get("knowledge_id", "") for item in primary if item.get("knowledge_id")],
            }
        )
        return tasks
