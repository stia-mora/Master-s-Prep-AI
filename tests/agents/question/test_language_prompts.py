from __future__ import annotations

from types import SimpleNamespace

import pytest

from master_prep_ai.agents.question.agents.followup_agent import FollowupAgent
from master_prep_ai.agents.question.agents.generator import Generator
from master_prep_ai.agents.question.agents.idea_agent import IdeaAgent
from master_prep_ai.agents.question.models import QuestionTemplate


class CaptureIdeaAgent(IdeaAgent):
    def __init__(self, language: str = "zh") -> None:
        self.language = language
        self.prompts = {
            "system": "Idea agent system",
            "generate_ideas": (
                "Topic: {user_topic}\n"
                "Preference: {preference}\n"
                "Knowledge context:\n{knowledge_context}\n"
                "Existing concentrations:\n{existing_concentrations}\n"
                'Return JSON {{"ideas":[{{"idea_id":"idea_1","concentration":"基础概念","question_type":"written","difficulty":"medium","rationale":"覆盖核心知识点"}}]}}'
            ),
        }
        self.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
        self.captured_system_prompts: list[str] = []

    async def stream_llm(self, **kwargs):  # type: ignore[override]
        self.captured_system_prompts.append(str(kwargs["system_prompt"]))
        yield (
            '{"ideas":[{"idea_id":"idea_1","concentration":"基础概念",'
            '"question_type":"written","difficulty":"medium",'
            '"rationale":"覆盖核心知识点"}]}'
        )


class CaptureGenerator(Generator):
    def __init__(self, language: str = "zh") -> None:
        self.language = language
        self.prompts = {
            "system": "Generator system",
            "generate": (
                "QuestionTemplate:\n{template}\n"
                "User topic:\n{user_topic}\n"
                "User preference:\n{preference}\n"
                "Knowledge context:\n{knowledge_context}\n"
                "Tools:\n{available_tools}\n"
                "History:\n{history_context}\n"
                "Previous questions:\n{previous_questions}\n"
                'Return JSON {{"question_type":"written","question":"问题","options":null,"correct_answer":"答案","explanation":"解释"}}'
            ),
        }
        self.captured_system_prompts: list[str] = []

    async def stream_llm(self, **kwargs):  # type: ignore[override]
        self.captured_system_prompts.append(str(kwargs["system_prompt"]))
        yield (
            '{"question_type":"written","question":"问题",'
            '"options":null,"correct_answer":"答案","explanation":"解释"}'
        )


class CaptureFollowupAgent(FollowupAgent):
    def __init__(self, language: str = "zh") -> None:
        self.language = language
        self.prompts = {
            "system": "Followup system",
            "answer_followup": (
                "Question context:\n{question_context}\n\n"
                "Conversation history:\n{history_context}\n\n"
                "User follow-up:\n{user_message}\n"
            ),
        }
        self.captured_system_prompts: list[str] = []

    async def stream_llm(self, **kwargs):  # type: ignore[override]
        self.captured_system_prompts.append(str(kwargs["system_prompt"]))
        yield "已回答"


@pytest.mark.asyncio
async def test_idea_agent_appends_language_directive_to_system_prompt() -> None:
    agent = CaptureIdeaAgent(language="zh")

    templates = await agent._generate_templates(
        user_topic="线性代数",
        preference="请用中文出题",
        knowledge_context="矩阵和向量空间",
        num_ideas=1,
    )

    assert templates
    assert agent.captured_system_prompts
    assert "Idea agent system" in agent.captured_system_prompts[0]
    assert "请严格使用中文（简体）" in agent.captured_system_prompts[0]


@pytest.mark.asyncio
async def test_generator_appends_language_directive_to_generate_and_repair_prompts() -> None:
    agent = CaptureGenerator(language="zh")
    template = QuestionTemplate(
        question_id="q_1",
        concentration="矩阵乘法",
        question_type="written",
        difficulty="medium",
    )

    payload = await agent._generate_payload(
        template=template,
        user_topic="线性代数",
        preference="请使用中文",
        history_context="",
        knowledge_context="矩阵乘法的定义",
        available_tools="(no tools available)",
    )

    repaired = await agent._repair_payload(
        template=template,
        payload=payload,
        issues=["missing_explanation"],
        user_topic="线性代数",
        preference="请使用中文",
        history_context="",
        knowledge_context="矩阵乘法的定义",
        available_tools="(no tools available)",
    )

    assert repaired["question"] == "问题"
    assert len(agent.captured_system_prompts) == 2
    assert "Generator system" in agent.captured_system_prompts[0]
    assert "请严格使用中文（简体）" in agent.captured_system_prompts[0]
    assert "You fix malformed quiz payloads" in agent.captured_system_prompts[1]
    assert "请严格使用中文（简体）" in agent.captured_system_prompts[1]


@pytest.mark.asyncio
async def test_followup_agent_appends_language_directive_to_system_prompt() -> None:
    agent = CaptureFollowupAgent(language="zh")

    reply = await agent.process(
        user_message="为什么这题是这个答案？",
        question_context={
            "question_id": "q_1",
            "question_type": "choice",
            "question": "矩阵乘法什么时候有定义？",
            "correct_answer": "当内维度一致时。",
            "explanation": "矩阵 A 的列数必须等于矩阵 B 的行数。",
        },
        history_context="",
    )

    assert reply == "已回答"
    assert agent.captured_system_prompts
    assert "Followup system" in agent.captured_system_prompts[0]
    assert "请严格使用中文（简体）" in agent.captured_system_prompts[0]
