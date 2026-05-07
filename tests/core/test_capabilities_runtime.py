"""Runtime tests for built-in capabilities under the unified framework."""

from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest

import master_prep_ai.agents.visualize.pipeline as visualize_pipeline
from master_prep_ai.capabilities.chat import ChatCapability
from master_prep_ai.capabilities.deep_question import DeepQuestionCapability
from master_prep_ai.capabilities.deep_research import DeepResearchCapability
from master_prep_ai.capabilities.deep_solve import DeepSolveCapability
from master_prep_ai.capabilities.visualize import VisualizeCapability
from master_prep_ai.core.context import Attachment, UnifiedContext
from master_prep_ai.core.stream import StreamEvent, StreamEventType
from master_prep_ai.core.stream_bus import StreamBus


def _install_module(
    monkeypatch: pytest.MonkeyPatch, fullname: str, **attrs: Any
) -> types.ModuleType:
    parts = fullname.split(".")
    for idx in range(1, len(parts)):
        pkg_name = ".".join(parts[:idx])
        if pkg_name not in sys.modules:
            pkg = types.ModuleType(pkg_name)
            pkg.__path__ = []  # type: ignore[attr-defined]
            monkeypatch.setitem(sys.modules, pkg_name, pkg)
            if idx > 1:
                parent = sys.modules[".".join(parts[: idx - 1])]
                setattr(parent, parts[idx - 1], pkg)

    module = types.ModuleType(fullname)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, fullname, module)
    if len(parts) > 1:
        parent = sys.modules[".".join(parts[:-1])]
        setattr(parent, parts[-1], module)
    return module


async def _collect_events(run_coro) -> list[StreamEvent]:
    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    await run_coro(bus)
    await asyncio.sleep(0)
    await bus.close()
    await consumer
    return events


@pytest.mark.asyncio
async def test_chat_capability_streams_content_and_geogebra_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakePipeline:
        def __init__(self, language: str = "en") -> None:
            captured["pipeline_init"] = {"language": language}

        async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
            captured["process"] = {
                "message": f"{context.user_message}\nGGB commands",
                "enabled_tools": list(context.enabled_tools or []),
            }
            await stream.tool_call(
                "geogebra_analysis",
                {"image_name": "img.png"},
                source="chat",
                stage="acting",
            )
            await stream.sources(
                [
                    {"type": "rag", "kb_name": "demo-kb", "content": "grounding"},
                    {"type": "web", "url": "https://example.com", "title": "Example"},
                ],
                source="chat",
                stage="responding",
            )
            await stream.content("assistant output", source="chat", stage="responding")

    monkeypatch.setattr("master_prep_ai.capabilities.chat.AgenticChatPipeline", FakePipeline)

    context = UnifiedContext(
        user_message="analyze triangle",
        enabled_tools=["rag", "web_search", "geogebra_analysis"],
        knowledge_bases=["demo-kb"],
        language="en",
        attachments=[Attachment(type="image", base64="ZmFrZQ==", filename="img.png")],
    )

    capability = ChatCapability()
    events = await _collect_events(lambda bus: capability.run(context, bus))

    assert any(event.type == StreamEventType.TOOL_CALL for event in events)
    assert any(event.type == StreamEventType.SOURCES for event in events)
    assert any(
        event.type == StreamEventType.CONTENT and "assistant output" in event.content
        for event in events
    )
    assert "GGB commands" in captured["process"]["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enabled_tools", "knowledge_bases", "expected_tools", "expected_kb", "expected_disable"),
    [
        (["rag", "code_execution"], ["algebra"], ["rag", "code_execution"], "algebra", False),
        (None, ["algebra"], list(DeepSolveCapability.manifest.tools_used), "algebra", False),
        ([], ["algebra"], [], None, True),
    ],
)
async def test_deep_solve_capability_bridges_solver_output(
    monkeypatch: pytest.MonkeyPatch,
    enabled_tools: list[str] | None,
    knowledge_bases: list[str],
    expected_tools: list[str],
    expected_kb: str | None,
    expected_disable: bool,
) -> None:
    captured: dict[str, Any] = {}

    class FakeMainSolver:
        def __init__(self, **kwargs: Any) -> None:
            captured["solver_init"] = kwargs
            self.logger = SimpleNamespace(
                logger=SimpleNamespace(addHandler=lambda *_: None, removeHandler=lambda *_: None)
            )

        async def ainit(self) -> None:
            captured["ainit"] = True

        async def solve(self, **kwargs: Any) -> dict[str, Any]:
            self._send_progress_update("reasoning", {"status": "solver-progress"})
            captured["solve"] = kwargs
            return {
                "final_answer": "final solution",
                "output_dir": "/tmp/solve",
                "metadata": {"steps": 2},
            }

    _install_module(monkeypatch, "master_prep_ai.agents.solve.main_solver", MainSolver=FakeMainSolver)
    _install_module(
        monkeypatch,
        "master_prep_ai.services.llm.config",
        get_llm_config=lambda: SimpleNamespace(api_key="k", base_url="u", api_version="v1"),
    )

    context = UnifiedContext(
        user_message="solve x^2=4",
        enabled_tools=enabled_tools,
        knowledge_bases=knowledge_bases,
        language="en",
        attachments=[Attachment(type="image", base64="ZmFrZQ==", filename="graph.png")],
    )
    capability = DeepSolveCapability()
    events = await _collect_events(lambda bus: capability.run(context, bus))

    assert captured["solver_init"]["enabled_tools"] == expected_tools
    assert captured["solver_init"]["kb_name"] == expected_kb
    assert captured["solver_init"]["disable_planner_retrieve"] is expected_disable
    assert captured["solve"]["attachments"][0].filename == "graph.png"
    assert any(
        event.type == StreamEventType.PROGRESS and event.content == "solver-progress"
        for event in events
    )
    assert any(
        event.type == StreamEventType.CONTENT and "final solution" in event.content
        for event in events
    )
    result_event = next(event for event in events if event.type == StreamEventType.RESULT)
    assert result_event.metadata["response"] == "final solution"


@pytest.mark.asyncio
async def test_deep_solve_capability_bridges_observation_and_retrieve_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMainSolver:
        def __init__(self, **_kwargs: Any) -> None:
            self._trace_callback = None
            self.logger = SimpleNamespace(
                logger=SimpleNamespace(addHandler=lambda *_: None, removeHandler=lambda *_: None)
            )

        async def ainit(self) -> None:
            return None

        def set_trace_callback(self, callback) -> None:
            self._trace_callback = callback

        async def solve(self, **_kwargs: Any) -> dict[str, Any]:
            assert self._trace_callback is not None
            await self._trace_callback(
                {
                    "event": "llm_observation",
                    "phase": "reasoning",
                    "response": "round summary",
                    "call_id": "solve-s1-round-1",
                    "trace_role": "observe",
                    "trace_group": "react_round",
                }
            )
            await self._trace_callback(
                {
                    "event": "tool_log",
                    "phase": "reasoning",
                    "message": "Retrieving from KB...",
                    "call_id": "solve-retrieve-1",
                    "call_kind": "rag_retrieval",
                    "trace_role": "retrieve",
                    "trace_group": "retrieve",
                    "trace_kind": "status",
                }
            )
            return {
                "final_answer": "final solution",
                "output_dir": "/tmp/solve",
                "metadata": {"steps": 1},
            }

    _install_module(monkeypatch, "master_prep_ai.agents.solve.main_solver", MainSolver=FakeMainSolver)
    _install_module(
        monkeypatch,
        "master_prep_ai.services.llm.config",
        get_llm_config=lambda: SimpleNamespace(api_key="k", base_url="u", api_version="v1"),
    )

    context = UnifiedContext(
        user_message="solve x^2=4",
        enabled_tools=["rag"],
        knowledge_bases=["algebra"],
        language="en",
    )
    capability = DeepSolveCapability()
    events = await _collect_events(lambda bus: capability.run(context, bus))

    observation_event = next(event for event in events if event.type == StreamEventType.OBSERVATION)
    assert observation_event.content == "round summary"
    assert observation_event.metadata["trace_role"] == "observe"

    retrieve_event = next(
        event
        for event in events
        if event.type == StreamEventType.PROGRESS and event.metadata.get("trace_role") == "retrieve"
    )
    assert retrieve_event.content == "Retrieving from KB..."
    assert retrieve_event.metadata["trace_group"] == "retrieve"


@pytest.mark.asyncio
async def test_deep_question_capability_uses_user_message_as_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeCoordinator:
        def __init__(self, **kwargs: Any) -> None:
            captured["init"] = kwargs
            self._callback = None

        def set_ws_callback(self, callback) -> None:
            self._callback = callback

        async def generate_from_topic(self, **kwargs: Any) -> dict[str, Any]:
            captured["topic_call"] = kwargs
            await self._callback({"type": "idea_round", "message": "ideas"})
            await self._callback({"type": "generating", "message": "writing"})
            return {
                "results": [
                    {
                        "qa_pair": {
                            "question": "What is a matrix?",
                            "options": {"A": "A table", "B": "A scalar"},
                            "correct_answer": "A",
                            "explanation": "A matrix is a table.",
                        }
                    }
                ]
            }

    _install_module(
        monkeypatch,
        "master_prep_ai.agents.question.coordinator",
        AgentCoordinator=FakeCoordinator,
    )
    _install_module(
        monkeypatch,
        "master_prep_ai.services.llm.config",
        get_llm_config=lambda: SimpleNamespace(api_key="k", base_url="u", api_version="v1"),
    )

    context = UnifiedContext(
        user_message="linear algebra fundamentals",
        config_overrides={},
        language="en",
        attachments=[Attachment(type="image", base64="ZmFrZQ==", filename="topic.png")],
    )
    capability = DeepQuestionCapability()
    events = await _collect_events(lambda bus: capability.run(context, bus))

    assert captured["topic_call"]["user_topic"] == "linear algebra fundamentals"
    assert captured["topic_call"]["attachments"][0].filename == "topic.png"
    assert any(
        event.type == StreamEventType.PROGRESS and event.stage == "ideation" for event in events
    )
    result_event = next(event for event in events if event.type == StreamEventType.RESULT)
    assert "Question 1" in result_event.metadata["response"]


@pytest.mark.asyncio
async def test_deep_question_mimic_uses_extracted_attachment_text_when_pdf_was_stripped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeCoordinator:
        def __init__(self, **_kwargs: Any) -> None:
            self._callback = None

        def set_ws_callback(self, callback) -> None:
            self._callback = callback

        async def generate_from_exam(self, **_kwargs: Any) -> dict[str, Any]:
            raise AssertionError("raw PDF path should not be required after document extraction")

        async def generate_from_topic(self, **kwargs: Any) -> dict[str, Any]:
            captured["topic_call"] = kwargs
            return {
                "results": [
                    {
                        "qa_pair": {
                            "question": "Question from attached paper?",
                            "correct_answer": "Yes",
                            "explanation": "The extracted document text was used.",
                        }
                    }
                ]
            }

    _install_module(
        monkeypatch,
        "master_prep_ai.agents.question.coordinator",
        AgentCoordinator=FakeCoordinator,
    )
    _install_module(
        monkeypatch,
        "master_prep_ai.services.llm.config",
        get_llm_config=lambda: SimpleNamespace(api_key="k", base_url="u", api_version="v1"),
    )

    context = UnifiedContext(
        user_message="[Attached Documents]\n[File: paper.pdf]\nExam text\n\n[User Question]\n",
        config_overrides={"mode": "mimic", "max_questions": 4},
        language="en",
        attachments=[
            Attachment(
                type="pdf",
                filename="paper.pdf",
                base64="",
                mime_type="application/pdf",
            )
        ],
    )

    capability = DeepQuestionCapability()
    events = await _collect_events(lambda bus: capability.run(context, bus))

    assert "Exam text" in captured["topic_call"]["user_topic"]
    assert captured["topic_call"]["num_questions"] == 4
    assert captured["topic_call"]["attachments"][0].filename == "paper.pdf"
    result_event = next(event for event in events if event.type == StreamEventType.RESULT)
    assert "Question 1" in result_event.metadata["response"]


@pytest.mark.asyncio
async def test_deep_question_capability_uses_single_call_followup_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeCoordinator:
        def __init__(self, **_kwargs: Any) -> None:
            raise AssertionError("Coordinator should not be constructed for follow-up mode")

    class FakeFollowupAgent:
        def __init__(self, **kwargs: Any) -> None:
            captured["init"] = kwargs
            self._trace_callback = None

        def set_trace_callback(self, callback) -> None:
            self._trace_callback = callback

        async def process(self, **kwargs: Any) -> str:
            captured["process"] = kwargs
            assert self._trace_callback is not None
            await self._trace_callback(
                {
                    "event": "llm_call",
                    "state": "running",
                    "label": "Answer follow-up for Question 3",
                    "phase": "generation",
                    "call_id": "quiz-followup-q_3",
                }
            )
            await self._trace_callback(
                {
                    "event": "llm_call",
                    "state": "complete",
                    "response": "You missed the key distinction between density and coverage.",
                    "phase": "generation",
                    "call_id": "quiz-followup-q_3",
                }
            )
            return "You missed the key distinction between density and coverage."

    _install_module(
        monkeypatch,
        "master_prep_ai.agents.question.coordinator",
        AgentCoordinator=FakeCoordinator,
    )
    _install_module(
        monkeypatch,
        "master_prep_ai.agents.question.agents.followup_agent",
        FollowupAgent=FakeFollowupAgent,
    )
    _install_module(
        monkeypatch,
        "master_prep_ai.services.llm.config",
        get_llm_config=lambda: SimpleNamespace(api_key="k", base_url="u", api_version="v1"),
    )

    context = UnifiedContext(
        user_message="Why was my answer wrong?",
        language="en",
        metadata={
            "conversation_context_text": "User previously asked for a simpler explanation.",
            "question_followup_context": {
                "question_id": "q_3",
                "question": "What does density mean in win-rate comparison?",
                "question_type": "written",
                "user_answer": "coverage",
                "correct_answer": "relevant information without redundancy",
                "is_correct": False,
                "explanation": "Density is about relevant content without redundancy.",
            },
        },
    )
    capability = DeepQuestionCapability()
    events = await _collect_events(lambda bus: capability.run(context, bus))

    assert captured["process"]["user_message"] == "Why was my answer wrong?"
    assert (
        captured["process"]["history_context"] == "User previously asked for a simpler explanation."
    )
    assert captured["process"]["question_context"]["question_id"] == "q_3"
    assert any(
        event.type == StreamEventType.CONTENT
        and "key distinction between density and coverage" in event.content
        for event in events
    )
    result_event = next(event for event in events if event.type == StreamEventType.RESULT)
    assert result_event.metadata["mode"] == "followup"
    assert result_event.metadata["question_id"] == "q_3"


def test_deep_question_capability_humanizes_question_progress_labels() -> None:
    assert DeepQuestionCapability._humanize_question_id("q_3") == "Question 3"
    assert (
        DeepQuestionCapability._format_bridge_message(
            "question_update",
            {"question_id": "q_3", "current": 3, "total": 3},
        )
        == "Generating Question 3 (3/3)"
    )
    assert (
        DeepQuestionCapability._format_bridge_message(
            "result",
            {
                "question_id": "q_3",
                "index": 2,
                "question": {"question_type": "coding", "difficulty": "hard"},
                "success": True,
            },
        )
        == "Question 3 done (#3, coding/hard, success=True)"
    )


@pytest.mark.asyncio
async def test_deep_research_capability_requires_explicit_config_and_streams_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import master_prep_ai.agents.research.request_config  # noqa: F401

    captured: dict[str, Any] = {}

    class FakeResearchPipeline:
        def __init__(self, **kwargs: Any) -> None:
            captured["pipeline_init"] = kwargs

        async def run(self, topic: str) -> dict[str, Any]:
            # progress_callback is fire-and-forget (sync) inside the
            # capability; just call it.
            captured["pipeline_init"]["progress_callback"](
                {"status": "gathering evidence", "stage": "researching", "block_id": "block_1"}
            )
            await captured["pipeline_init"]["trace_callback"](
                {
                    "event": "llm_call",
                    "state": "running",
                    "agent_name": "rephrase_agent",
                    "stage": "rephrase",
                }
            )
            await captured["pipeline_init"]["trace_callback"](
                {
                    "event": "tool_call",
                    "phase": "researching",
                    "tool_name": "web_search",
                    "tool_args": {"query": "agent-native tutoring"},
                    "label": "Use web_search",
                    "call_id": "research-tool-1",
                }
            )
            # Allow the scheduled progress task to flush onto the bus.
            await asyncio.sleep(0)
            return {"report": f"Report about {topic}", "metadata": {"citations": 3}}

    def fake_load_config_with_main(_: str) -> dict[str, Any]:
        return {
            "research": {
                "researching": {
                    "note_agent_mode": "auto",
                    "tool_timeout": 60,
                    "tool_max_retries": 2,
                    "paper_search_years_limit": 3,
                },
                "rag": {"default_mode": "hybrid"},
            },
            "tools": {"web_search": {"enabled": True}},
        }

    _install_module(
        monkeypatch,
        "master_prep_ai.agents.research.research_pipeline",
        ResearchPipeline=FakeResearchPipeline,
    )
    _install_module(
        monkeypatch,
        "master_prep_ai.services.config",
        load_config_with_main=fake_load_config_with_main,
    )
    _install_module(
        monkeypatch,
        "master_prep_ai.services.llm.config",
        get_llm_config=lambda: SimpleNamespace(api_key="k", base_url="u", api_version="v1"),
    )

    context = UnifiedContext(
        user_message="agent-native tutoring",
        enabled_tools=["rag", "web_search", "paper_search"],
        knowledge_bases=["research-kb"],
        attachments=[Attachment(type="image", base64="ZmFrZQ==", filename="brief.png")],
        config_overrides={
            "mode": "report",
            "depth": "standard",
            "sources": ["kb", "web", "papers"],
            # Provide a confirmed outline so the capability skips the
            # outline-preview short-circuit and runs the full pipeline.
            "confirmed_outline": [
                {"title": "Background", "overview": "Why this topic matters"},
                {"title": "Approaches", "overview": "How to do it"},
            ],
        },
        language="en",
    )
    capability = DeepResearchCapability()
    events = await _collect_events(lambda bus: capability.run(context, bus))

    config = captured["pipeline_init"]["config"]
    assert captured["pipeline_init"]["attachments"][0].filename == "brief.png"
    assert config["planning"]["decompose"]["mode"] == "auto"
    assert config["planning"]["decompose"]["auto_max_subtopics"] == 4
    assert config["researching"]["max_iterations"] == 3
    assert config["researching"]["enable_paper_search"] is True
    assert config["researching"]["enable_web_search"] is True
    assert config["reporting"]["style"] == "report"
    assert config["tools"]["web_search"]["enabled"] is True
    progress_event = next(
        event
        for event in events
        if event.type == StreamEventType.PROGRESS and event.content == "gathering evidence"
    )
    assert progress_event.metadata["research_stage_card"] == "evidence"
    tool_call_event = next(
        event
        for event in events
        if event.type == StreamEventType.TOOL_CALL and event.content == "web_search"
    )
    assert tool_call_event.metadata["research_stage_card"] == "evidence"
    result_event = next(event for event in events if event.type == StreamEventType.RESULT)
    assert result_event.metadata["response"] == "Report about agent-native tutoring"


@pytest.mark.asyncio
async def test_visualize_capability_passes_attachments_to_analysis_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeAnalysis:
        render_type = "svg"
        description = "A diagram"
        data_description = "diagram data"

        def model_dump(self) -> dict[str, Any]:
            return {
                "render_type": self.render_type,
                "description": self.description,
                "data_description": self.data_description,
            }

    class FakeReview:
        optimized_code = "<svg></svg>"
        changed = False
        review_notes = "ok"

        def model_dump(self) -> dict[str, Any]:
            return {
                "optimized_code": self.optimized_code,
                "changed": self.changed,
                "review_notes": self.review_notes,
            }

    class FakeVisualizePipeline:
        def __init__(self, **kwargs: Any) -> None:
            captured["init"] = kwargs

        async def run_analysis(self, **kwargs: Any) -> FakeAnalysis:
            captured["analysis"] = kwargs
            return FakeAnalysis()

        async def run_code_generation(self, **kwargs: Any) -> str:
            captured["code_generation"] = kwargs
            return "<svg></svg>"

        async def run_review(self, **kwargs: Any) -> FakeReview:
            captured["review"] = kwargs
            return FakeReview()

    monkeypatch.setattr(
        visualize_pipeline,
        "VisualizePipeline",
        FakeVisualizePipeline,
    )
    _install_module(
        monkeypatch,
        "master_prep_ai.services.llm.config",
        get_llm_config=lambda: SimpleNamespace(api_key="k", base_url="u", api_version="v1"),
    )

    context = UnifiedContext(
        user_message="make a figure",
        active_capability="visualize",
        config_overrides={"render_mode": "svg"},
        language="en",
        attachments=[Attachment(type="image", base64="ZmFrZQ==", filename="figure.png")],
    )

    capability = VisualizeCapability()
    events = await _collect_events(lambda bus: capability.run(context, bus))

    assert captured["analysis"]["attachments"][0].filename == "figure.png"
    result_event = next(event for event in events if event.type == StreamEventType.RESULT)
    assert result_event.metadata["render_type"] == "svg"
