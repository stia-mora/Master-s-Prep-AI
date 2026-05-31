"""Practice assembly, answer grading, and submission logic for Kaoyan MVP."""

from __future__ import annotations

import re
from typing import Any
import uuid

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

QUESTION_GENERATION_SYSTEM_PROMPT = """
你是考研数学关卡练习出题老师。只输出 JSON，不要 Markdown。
JSON 结构必须是 {"questions": [...]}。每道题必须包含：
question_id, knowledge_id, question_type, difficulty_level, stem, options, answer, analysis。
选择题 options 必须是 [{"label":"A","content":"..."}, ...]，answer 必须是 A/B/C/D。
题目必须严格围绕给定 knowledge_id，不要混入无关知识点。
""".strip()


QUESTION_GENERATION_PROMPT = """
请围绕下面的关卡上下文生成 {limit} 道 {kind_label}。
允许的 knowledge_id: {knowledge_ids}
关卡标题: {stage_title}
来源: {source_label}
题型: {question_family}
难度目标: {difficulty_hint}
要求：题干清晰、答案唯一、解析能说明关键步骤，避免与已有题干重复。
""".strip()


EXPLAIN_AGAIN_SYSTEM_PROMPT = """
你是考研数学闯关学习导师。用中文解释，直接给学生可执行的理解路径。
不要泛泛鼓励，不要输出 JSON。
""".strip()


QUESTION_KIND_LABELS = {
    "basic": "基础题",
    "variant": "变式题",
    "challenge": "挑战题",
}

SOURCE_LABELS = {
    "stage": "关卡练习",
    "wrong_retry": "错题重刷",
    "knowledge": "知识点新增题",
    "diagnostic": "诊断推荐",
}

EXPLAIN_MODE_LABELS = {
    "basic": "从基础讲",
    "example": "举例讲",
    "visual": "用图像直觉讲",
    "mistake_based": "针对错因讲",
    "analogy": "换个类比讲",
}


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

    async def generate_practice(
        self,
        *,
        source: str = "knowledge",
        stage_id: str | None = None,
        origin_id: str | None = None,
        tab_id: str | None = None,
        knowledge_id: str | None = None,
        source_question_id: str | None = None,
        question_type: str | None = None,
        question_family: str = "choice",
        question_kind: str = "basic",
        difficulty_level: int | None = None,
        limit: int = 5,
        user_id: str = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        source = source if source in SOURCE_LABELS else "knowledge"
        question_kind = question_kind if question_kind in QUESTION_KIND_LABELS else "basic"
        question_family = "free_response" if question_family == "free_response" else "choice"
        stage_context = self.learning_store.get_stage_context(stage_id or "", user_id) if stage_id else None
        if stage_id and stage_context is None:
            return {}
        allowed_knowledge_ids = self._resolve_generation_knowledge_ids(
            source=source,
            stage_context=stage_context,
            knowledge_id=knowledge_id,
            origin_id=origin_id,
            source_question_id=source_question_id,
            user_id=user_id,
        )
        difficulty = difficulty_level or self._difficulty_for_kind(question_kind)
        source_label = SOURCE_LABELS[source]
        title = self._practice_title(source_label, question_kind, stage_context, knowledge_id)
        generated_questions, ai_meta = await self._try_generate_questions(
            allowed_knowledge_ids=allowed_knowledge_ids,
            stage_context=stage_context,
            source=source,
            source_label=source_label,
            question_family=question_family,
            question_kind=question_kind,
            difficulty_level=difficulty,
            limit=limit,
            user_id=user_id,
        )
        questions = generated_questions
        if not questions:
            questions = self._select_questions_for_knowledge_ids(
                allowed_knowledge_ids,
                question_family=question_family,
                question_type=question_type,
                difficulty_level=difficulty,
                limit=limit,
            )
            if not questions and source == "wrong_retry":
                questions = self.create_session(
                    session_type="wrong_retry",
                    question_family=question_family,
                    difficulty_level=difficulty,
                    limit=limit,
                    user_id=user_id,
                    source=source,
                    source_label=source_label,
                    origin_id=origin_id or source_question_id or "",
                    stage_id=stage_id or "",
                    tab_id=tab_id or "",
                ).get("questions", [])
            if not questions and source != "stage":
                fallback_attempts = [
                    {"question_type": question_type, "question_family": question_family, "difficulty_level": difficulty},
                    {"question_type": question_type, "question_family": question_family},
                    {"question_family": question_family, "difficulty_level": difficulty},
                    {"question_family": question_family},
                ]
                for filters in fallback_attempts:
                    filters = {key: value for key, value in filters.items() if value is not None}
                    questions = self.content_store.select_questions(limit=limit, **filters)
                    if questions:
                        break
        question_ids = [str(item["question_id"]) for item in questions]
        session = self.learning_store.create_practice_session(
            session_type="stage_practice" if source == "stage" else source,
            title=title,
            knowledge_id=(allowed_knowledge_ids[0] if allowed_knowledge_ids else knowledge_id or ""),
            question_ids=question_ids,
            ai_meta={
                "message": ai_meta.get("message") or "Practice questions were selected by stage filters.",
                "source": source,
                "source_label": source_label,
                "origin_id": origin_id or source_question_id or "",
                "stage_id": stage_id or "",
                "tab_id": tab_id or "",
                "question_kind": question_kind,
                "generated_questions": generated_questions,
                "allowed_knowledge_ids": allowed_knowledge_ids,
                "stage_context": stage_context or {},
            },
            user_id=user_id,
            source=source,
            source_label=source_label,
            origin_id=origin_id or source_question_id or "",
            stage_id=stage_id or "",
            tab_id=tab_id or "",
        )
        session["questions"] = questions
        return session

    async def explain_again(
        self,
        *,
        stage_id: str,
        mode: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> dict[str, Any] | None:
        mode = mode if mode in EXPLAIN_MODE_LABELS else "basic"
        stage_context = self.learning_store.get_stage_context(stage_id, user_id)
        if stage_context is None:
            return None
        knowledge_ids = [str(item) for item in stage_context.get("knowledge_ids") or [] if str(item)]
        primary_knowledge_id = knowledge_ids[0] if knowledge_ids else ""
        knowledge_detail = self.content_store.get_knowledge(primary_knowledge_id, question_limit=3) if primary_knowledge_id else None
        examples = (knowledge_detail or {}).get("questions") or []
        example_question = examples[0] if examples else {}
        fallback = self._fallback_explanation(stage_context, knowledge_detail, mode, example_question)
        prompt = (
            f"关卡：{stage_context.get('title')}\n"
            f"知识点：{knowledge_ids}\n"
            f"讲法模式：{EXPLAIN_MODE_LABELS[mode]}\n"
            f"知识材料：{((knowledge_detail or {}).get('knowledge') or {}).get('raw_markdown', '')[:1200]}\n"
            f"例题：{example_question.get('stem', '')[:800]}\n"
            "请换一种讲法，最后给出一个下一步练习建议。"
        )
        content, meta = await self.ai.complete_text(
            action_type="explanation_variant",
            system_prompt=EXPLAIN_AGAIN_SYSTEM_PROMPT,
            prompt=prompt,
            fallback=fallback,
            user_id=user_id,
        )
        variant = self.learning_store.record_explanation_variant(
            user_id=user_id,
            stage_id=stage_id,
            mode=mode,
            content=content,
            example_question=example_question,
        )
        variant["ai_metadata"] = meta
        return {
            "stage_context": stage_context,
            "explanation_variant": variant,
            "history": self.learning_store.list_explanation_variants(stage_id, user_id),
        }

    def create_session(
        self,
        *,
        session_type: str = "special",
        knowledge_id: str | None = None,
        source_question_id: str | None = None,
        question_type: str | None = None,
        question_family: str = "choice",
        difficulty_level: int | None = None,
        limit: int = 5,
        user_id: str = DEFAULT_USER_ID,
        source: str = "knowledge",
        source_label: str = "",
        origin_id: str = "",
        stage_id: str = "",
        tab_id: str = "",
    ) -> dict[str, Any]:
        question_family = "free_response" if question_family == "free_response" else "choice"
        questions: list[dict[str, Any]]
        if session_type == "wrong_retry":
            wrong_ids = self.learning_store.active_wrong_question_ids(user_id)[: max(1, limit)]
            questions = [item for item in self.content_store.get_questions(wrong_ids) if is_choice_question(item)]
            if len(questions) < limit:
                exclude_ids = [item["question_id"] for item in questions]
                questions.extend(
                    self.content_store.select_questions(
                        question_family=question_family,
                        limit=max(1, limit - len(questions)),
                        exclude_ids=exclude_ids,
                    )
                )
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
                question_family=question_family,
                difficulty_level=resolved_difficulty,
                limit=limit,
                exclude_ids=exclude_ids,
            )
            if not questions and resolved_knowledge_id:
                questions = self.content_store.select_questions(knowledge_id=resolved_knowledge_id, question_family=question_family, limit=limit, exclude_ids=exclude_ids)
            if not questions:
                questions = self.content_store.select_questions(question_family=question_family, limit=limit, exclude_ids=exclude_ids)
            knowledge_id = resolved_knowledge_id
        elif session_type == "exam_simulation":
            questions = self.content_store.select_questions(
                knowledge_id=knowledge_id,
                question_type=question_type,
                question_family=question_family,
                difficulty_level=difficulty_level,
                limit=limit,
            )
            if not questions:
                questions = self.content_store.select_questions(question_family=question_family, limit=limit)
        else:
            questions = self.content_store.select_questions(
                knowledge_id=knowledge_id,
                question_type=question_type,
                question_family=question_family,
                difficulty_level=difficulty_level,
                limit=limit,
            )
            if not questions and knowledge_id:
                questions = self.content_store.select_questions(knowledge_id=knowledge_id, question_family=question_family, limit=limit)
            if not questions:
                questions = self.content_store.select_questions(question_family=question_family, limit=limit)
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
            ai_meta={
                "message": "Practice questions were generated by filters.",
                "session_type": session_type,
                "question_family": question_family,
                "source": source,
                "source_label": source_label or SOURCE_LABELS.get(source, "知识点新增题"),
                "origin_id": origin_id,
                "stage_id": stage_id,
                "tab_id": tab_id,
            },
            user_id=user_id,
            source=source,
            source_label=source_label or SOURCE_LABELS.get(source, "知识点新增题"),
            origin_id=origin_id,
            stage_id=stage_id,
            tab_id=tab_id,
        )
        session["questions"] = questions
        return session

    def _resolve_generation_knowledge_ids(
        self,
        *,
        source: str,
        stage_context: dict[str, Any] | None,
        knowledge_id: str | None,
        origin_id: str | None,
        source_question_id: str | None,
        user_id: str,
    ) -> list[str]:
        candidates: list[str] = []
        if stage_context:
            candidates.extend(str(item) for item in stage_context.get("knowledge_ids") or [] if str(item))
        if knowledge_id:
            candidates.append(knowledge_id)
        source_qid = source_question_id or origin_id
        if source_qid:
            source_question = self.content_store.get_question(source_qid)
            if source_question and source_question.get("knowledge_id"):
                candidates.append(str(source_question["knowledge_id"]))
        if source == "diagnostic" and not candidates:
            dashboard = self.learning_store.dashboard_summary(user_id)
            candidates.extend(str(item) for item in dashboard.get("weak_knowledge_ids") or [] if str(item))
        resolved: list[str] = []
        for candidate in candidates:
            mapped = self.content_store.resolve_practice_knowledge_ids(candidate)
            resolved.extend(mapped or [candidate])
        seen: set[str] = set()
        unique = []
        for item in resolved:
            if item and item not in seen:
                seen.add(item)
                unique.append(item)
        return unique

    def _difficulty_for_kind(self, question_kind: str) -> int:
        if question_kind == "challenge":
            return 4
        if question_kind == "variant":
            return 3
        return 2

    def _practice_title(
        self,
        source_label: str,
        question_kind: str,
        stage_context: dict[str, Any] | None,
        knowledge_id: str | None,
    ) -> str:
        base = stage_context.get("title") if stage_context else ""
        if not base and knowledge_id:
            detail = self.content_store.get_knowledge(knowledge_id, question_limit=1)
            base = ((detail or {}).get("knowledge") or {}).get("knowledge_name", "")
        return f"{source_label} · {QUESTION_KIND_LABELS.get(question_kind, '基础题')}{f'：{base}' if base else ''}"

    def _select_questions_for_knowledge_ids(
        self,
        knowledge_ids: list[str],
        *,
        question_family: str,
        question_type: str | None,
        difficulty_level: int | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        questions: list[dict[str, Any]] = []
        seen: set[str] = set()
        for knowledge_id in knowledge_ids:
            if len(questions) >= limit:
                break
            batch = self.content_store.select_questions(
                knowledge_id=knowledge_id,
                question_type=question_type,
                question_family=question_family,
                difficulty_level=difficulty_level,
                limit=max(1, limit - len(questions)),
            )
            if len(batch) < max(1, limit - len(questions)):
                batch.extend(
                    self.content_store.select_questions(
                        knowledge_id=knowledge_id,
                        question_type=question_type,
                        question_family=question_family,
                        limit=max(1, limit - len(questions) - len(batch)),
                        exclude_ids=[item["question_id"] for item in batch],
                    )
                )
            for question in batch:
                question_id = str(question.get("question_id") or "")
                if question_id and question_id not in seen:
                    seen.add(question_id)
                    questions.append(question)
                if len(questions) >= limit:
                    break
        return questions

    async def _try_generate_questions(
        self,
        *,
        allowed_knowledge_ids: list[str],
        stage_context: dict[str, Any] | None,
        source: str,
        source_label: str,
        question_family: str,
        question_kind: str,
        difficulty_level: int,
        limit: int,
        user_id: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not allowed_knowledge_ids:
            return [], {"ai_used": False, "status": "fallback", "message": "缺少可映射知识点，已跳过生成题"}
        parsed, meta = await self.ai.complete_json(
            action_type="stage_question_generate",
            system_prompt=QUESTION_GENERATION_SYSTEM_PROMPT,
            prompt=QUESTION_GENERATION_PROMPT.format(
                limit=max(1, min(limit, 10)),
                kind_label=QUESTION_KIND_LABELS[question_kind],
                knowledge_ids=", ".join(allowed_knowledge_ids),
                stage_title=(stage_context or {}).get("title", ""),
                source_label=source_label,
                question_family=question_family,
                difficulty_hint=difficulty_level,
            ),
            user_id=user_id,
        )
        raw_questions = parsed.get("questions") if isinstance(parsed, dict) else None
        if not isinstance(raw_questions, list):
            return [], meta
        valid: list[dict[str, Any]] = []
        seen_stems: set[str] = set()
        for raw in raw_questions:
            question = self._validate_generated_question(
                raw,
                allowed_knowledge_ids=allowed_knowledge_ids,
                question_family=question_family,
                question_kind=question_kind,
                source=source,
                stage_id=str((stage_context or {}).get("stage_id") or ""),
                difficulty_level=difficulty_level,
            )
            if question is None:
                continue
            stem_key = re.sub(r"\s+", "", str(question.get("stem") or ""))[:120]
            if stem_key in seen_stems:
                continue
            seen_stems.add(stem_key)
            valid.append(question)
            if len(valid) >= limit:
                break
        if valid:
            self.learning_store.record_generated_questions(
                valid,
                user_id=user_id,
                stage_id=str((stage_context or {}).get("stage_id") or ""),
                source=source,
                question_kind=question_kind,
            )
        return valid, meta

    def _validate_generated_question(
        self,
        raw: Any,
        *,
        allowed_knowledge_ids: list[str],
        question_family: str,
        question_kind: str,
        source: str,
        stage_id: str,
        difficulty_level: int,
    ) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        knowledge_id = str(raw.get("knowledge_id") or "")
        if knowledge_id not in set(allowed_knowledge_ids):
            return None
        stem = str(raw.get("stem") or "").strip()
        answer = normalize_answer(str(raw.get("answer") or ""))
        analysis = str(raw.get("analysis") or "").strip()
        if not stem or not answer or not analysis:
            return None
        options = self._normalize_options(raw.get("options"))
        if question_family == "choice":
            labels = {item["label"] for item in options}
            if len(options) < 4 or answer not in labels:
                return None
        question_id = str(raw.get("question_id") or f"gen_{uuid.uuid4().hex[:12]}")
        return {
            "question_id": question_id,
            "knowledge_id": knowledge_id,
            "stage_id": stage_id,
            "question_kind": question_kind,
            "source": source,
            "question_type": str(raw.get("question_type") or ("閫夋嫨题" if question_family == "choice" else "解答题")),
            "difficulty_level": max(1, min(int(raw.get("difficulty_level") or difficulty_level), 5)),
            "stem": stem,
            "stem_without_options": stem,
            "options": options,
            "is_choice": question_family == "choice",
            "answer": answer,
            "analysis": analysis,
            "source_type": "generated",
            "year": None,
        }

    def _normalize_options(self, options: Any) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        if not isinstance(options, list):
            return normalized
        fallback_labels = ["A", "B", "C", "D", "E", "F"]
        for index, option in enumerate(options[:6]):
            if isinstance(option, dict):
                label = str(option.get("label") or fallback_labels[index]).strip().upper()[:1]
                content = str(option.get("content") or option.get("text") or "").strip()
            else:
                label = fallback_labels[index]
                content = str(option).strip()
            if label and content:
                normalized.append({"label": label, "content": content})
        return normalized

    def _fallback_explanation(
        self,
        stage_context: dict[str, Any],
        knowledge_detail: dict[str, Any] | None,
        mode: str,
        example_question: dict[str, Any],
    ) -> str:
        title = str(stage_context.get("title") or "当前关卡")
        knowledge = (knowledge_detail or {}).get("knowledge") or {}
        knowledge_name = knowledge.get("knowledge_name") or title
        if mode == "example" and example_question:
            return f"我们用例题来理解 {knowledge_name}：先识别题干中的关键条件，再把它翻译成对应公式。例题入口是：{example_question.get('stem', '')[:200]}。下一步先做一道基础题，再做一道同知识点变式。"
        if mode == "visual":
            return f"{knowledge_name} 可以先从图像直觉理解：关注函数走势、极限靠近方式或几何含义，再回到符号推导。下一步把图像变化和公式中的变量变化一一对应。"
        if mode == "mistake_based":
            reason = (stage_context.get("progress") or {}).get("last_reason") or "概念与变式稳定性不足"
            return f"这次针对错因讲：你主要卡在 {reason}。先把定义条件补全，再检查公式适用范围，最后用一道变式题验证是否真正迁移。"
        if mode == "analogy":
            return f"把 {knowledge_name} 想成一道分拣流程：先判断题目属于哪类，再选择工具，最后检查条件是否满足。不要一上来套公式，先分型再计算。"
        return f"{title} 的基础理解顺序是：先看定义，再看典型题入口，最后练习同知识点变式。掌握目标不是记住答案，而是能解释为什么这一步可以这样变形。"

    def create_pdf_payload(
        self,
        *,
        session_type: str = "special",
        knowledge_id: str | None = None,
        source_question_id: str | None = None,
        question_ids: list[str] | None = None,
        difficulty_level: int | None = None,
        limit: int = 8,
        user_id: str = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        source_question = self.content_store.get_question(source_question_id) if source_question_id else None
        resolved_knowledge_id = knowledge_id or (source_question or {}).get("knowledge_id")
        exclude_ids = [source_question["question_id"]] if source_question else []
        if question_ids:
            questions = [item for item in self.content_store.get_questions(question_ids[:limit]) if not is_choice_question(item)]
        else:
            questions = self.content_store.select_questions(
                knowledge_id=resolved_knowledge_id,
                question_family="free_response",
                difficulty_level=difficulty_level or (source_question or {}).get("difficulty_level"),
                limit=limit,
                exclude_ids=exclude_ids,
            )
            if not questions:
                questions = self.content_store.select_questions(
                    question_family="free_response",
                    difficulty_level=difficulty_level,
                    limit=limit,
                    exclude_ids=exclude_ids,
                )
        title = "填空与综合题线下练习"
        if resolved_knowledge_id:
            detail = self.content_store.get_knowledge(resolved_knowledge_id, question_limit=1)
            if detail:
                title = f"填空与综合题：{detail['knowledge']['knowledge_name']}"
        return {
            "title": title,
            "filename": f"kaoyan-free-response-{resolved_knowledge_id or session_type}.pdf",
            "questions": questions,
            "session_type": session_type,
            "knowledge_id": resolved_knowledge_id or "",
            "question_family": "free_response",
            "user_id": user_id,
        }

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
