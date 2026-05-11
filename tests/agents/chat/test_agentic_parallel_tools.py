from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from master_prep_ai.agents.chat.agentic_pipeline import AgenticChatPipeline
from master_prep_ai.core.context import UnifiedContext
from master_prep_ai.core.stream import StreamEvent, StreamEventType
from master_prep_ai.core.stream_bus import StreamBus
from master_prep_ai.core.tool_protocol import ToolResult
from master_prep_ai.core.trace import build_trace_metadata


async def _collect_bus_events(bus: StreamBus) -> tuple[list[StreamEvent], asyncio.Task[Any]]:
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    return events, consumer  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_native_tool_loop_executes_parallel_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "master_prep_ai.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )

    class FakeRegistry:
        def __init__(self) -> None:
            self.inflight = 0
            self.max_inflight = 0

        def build_openai_schemas(self, _enabled_tools):
            return [{"type": "function", "function": {"name": "web_search"}}]

        def build_prompt_text(self, enabled_tools, **_kwargs):
            return "\n".join(enabled_tools)

        def get_enabled(self, selected):
            return [SimpleNamespace(name=name) for name in selected]

        async def execute(self, name: str, **kwargs):
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
            await asyncio.sleep(0.05)
            self.inflight -= 1
            return ToolResult(
                content=f"{name} => {kwargs.get('query', '') or kwargs.get('context', '')}".strip(),
                sources=[{"tool": name}],
                metadata={"tool": name},
                success=True,
            )

    registry = FakeRegistry()
    monkeypatch.setattr(
        "master_prep_ai.agents.chat.agentic_pipeline.get_tool_registry", lambda: registry
    )

    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry

    class FakeCreate:
        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="",
                                tool_calls=[
                                    SimpleNamespace(
                                        id="tool-call-1",
                                        function=SimpleNamespace(
                                            name="web_search",
                                            arguments='{"query":"first"}',
                                        ),
                                    ),
                                    SimpleNamespace(
                                        id="tool-call-2",
                                        function=SimpleNamespace(
                                            name="reason",
                                            arguments='{"context":"second"}',
                                        ),
                                    ),
                                ],
                            )
                        )
                    ]
                )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="No more tools needed.",
                            tool_calls=[],
                        )
                    )
                ]
            )

    fake_create = FakeCreate()
    monkeypatch.setattr(
        pipeline,
        "_build_openai_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=fake_create),
            )
        ),
    )

    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)
    context = UnifiedContext(
        session_id="session-1",
        user_message="compare two sources",
        enabled_tools=["web_search", "reason"],
        language="en",
        metadata={"turn_id": "turn-1"},
    )

    traces = await pipeline._run_native_tool_loop(
        context=context,
        enabled_tools=["web_search", "reason"],
        thinking_text="Need outside evidence and a reasoning cross-check.",
        stream=bus,
    )
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    assert fake_create.calls == 1
    assert registry.max_inflight >= 2
    assert [trace.name for trace in traces] == ["web_search", "reason"]

    tool_result_events = [event for event in events if event.type.value == "tool_result"]
    assert len(tool_result_events) == 2
    assert tool_result_events[0].metadata["tool_call_id"] == "tool-call-1"
    assert tool_result_events[1].metadata["tool_call_id"] == "tool-call-2"
    assert tool_result_events[0].metadata["tool_index"] == 0
    assert tool_result_events[1].metadata["tool_index"] == 1
    acting_thinking_events = [
        event
        for event in events
        if event.type == StreamEventType.THINKING and event.stage == "acting"
    ]
    assert acting_thinking_events == []


@pytest.mark.asyncio
async def test_execute_tool_call_streams_retrieve_progress_for_rag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "master_prep_ai.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )

    class FakeRegistry:
        def get_enabled(self, selected):
            return [SimpleNamespace(name=name) for name in selected]

        async def execute(self, name: str, **kwargs):
            event_sink = kwargs.get("event_sink")
            if event_sink is not None:
                await event_sink(
                    "status", "Selecting provider: llamaindex", {"provider": "llamaindex"}
                )
                await event_sink("status", "Retrieving chunks...", {"mode": "hybrid"})
            return ToolResult(
                content=f"{name} => grounded answer",
                sources=[{"tool": name}],
                metadata={"tool": name},
                success=True,
            )

    registry = FakeRegistry()
    monkeypatch.setattr(
        "master_prep_ai.agents.chat.agentic_pipeline.get_tool_registry", lambda: registry
    )

    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry

    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)
    context = UnifiedContext(
        session_id="session-1",
        user_message="what is a transformer",
        enabled_tools=["rag"],
        knowledge_bases=["demo-kb"],
        language="en",
        metadata={"turn_id": "turn-1"},
    )
    trace_meta = build_trace_metadata(
        call_id="chat-react-1",
        phase="acting",
        label="Round 1",
        call_kind="react_round",
        trace_id="chat-react-1",
        trace_role="thought",
        trace_group="react_round",
        round=1,
    )
    retrieve_meta = pipeline._retrieve_trace_metadata(
        trace_meta,
        context=context,
        tool_call_id="tool-call-rag",
        tool_name="rag",
        tool_index=0,
        tool_args={"query": "transformer model", "kb_name": "demo-kb"},
    )

    result = await pipeline._execute_tool_call(
        "rag",
        {"query": "transformer model", "kb_name": "demo-kb"},
        stream=bus,
        retrieve_meta=retrieve_meta,
    )
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    assert result["success"] is True
    retrieve_events = [
        event
        for event in events
        if event.type == StreamEventType.PROGRESS and event.metadata.get("trace_role") == "retrieve"
    ]
    assert [event.content for event in retrieve_events] == [
        "Query: transformer model",
        "Selecting provider: llamaindex",
        "Retrieving chunks...",
        "Retrieve complete (22 chars)",
    ]


def test_rag_tool_args_replace_default_alias_with_selected_kb() -> None:
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    context = UnifiedContext(
        session_id="session-1",
        user_message="summarize the default knowledge base",
        enabled_tools=["rag"],
        knowledge_bases=["西方修辞思想史"],
        language="zh",
    )

    args = pipeline._augment_tool_kwargs(
        "rag",
        {"query": "Habermas public sphere", "kb_name": "default"},
        context,
        thinking_text="Use the selected knowledge base.",
    )

    assert args["kb_name"] == "西方修辞思想史"
    assert args["mode"] == "hybrid"


def test_rag_tool_args_replace_hallucinated_kb_with_selected_kb() -> None:
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    context = UnifiedContext(
        session_id="session-1",
        user_message="summarize the selected knowledge base",
        enabled_tools=["rag"],
        knowledge_bases=["demo-kb"],
        language="en",
    )

    args = pipeline._augment_tool_kwargs(
        "rag",
        {"query": "chapter summary", "kb_name": "made-up-kb"},
        context,
        thinking_text="Use RAG.",
    )

    assert args["kb_name"] == "demo-kb"


def test_rag_tool_args_ignore_llm_kb_name_and_use_current_selection() -> None:
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    context = UnifiedContext(
        session_id="session-1",
        user_message="use the current selected KB",
        enabled_tools=["rag"],
        knowledge_bases=["actual-kb", "default"],
        language="en",
    )

    args = pipeline._augment_tool_kwargs(
        "rag",
        {"query": "chapter summary", "kb_name": "default"},
        context,
        thinking_text="Use RAG.",
    )

    assert args["kb_name"] == "actual-kb"


def test_rag_tool_args_clear_old_kb_when_no_kb_selected() -> None:
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    context = UnifiedContext(
        session_id="session-1",
        user_message="answer without a knowledge base",
        enabled_tools=["rag"],
        knowledge_bases=[],
        language="en",
    )

    args = pipeline._augment_tool_kwargs(
        "rag",
        {"query": "chapter summary", "kb_name": "old-kb"},
        context,
        thinking_text="No selected KB is available.",
    )

    assert args["kb_name"] == ""
    assert args["mode"] == "hybrid"


def test_chat_messages_tell_llm_to_call_rag_without_kb_name() -> None:
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    pipeline.language = "en"
    context = UnifiedContext(
        session_id="session-1",
        user_message="use the current KB",
        conversation_history=[
            {"role": "user", "content": "Use knowledge base old-kb."},
            {"role": "assistant", "content": "Retrieved from old-kb."},
        ],
        enabled_tools=["rag"],
        knowledge_bases=["new-kb"],
        language="en",
    )

    messages = pipeline._build_messages(
        context=context,
        system_prompt="System prompt.",
        user_content="User prompt.",
    )

    system_content = messages[0]["content"]
    assert "call RAG with only a query" in system_content
    assert "currently selected knowledge base" in system_content
    assert "new-kb" not in system_content


def test_chat_rag_schema_exposes_only_query_to_llm() -> None:
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)

    class FakeRegistry:
        def build_openai_schemas(self, _enabled_tools):
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "rag",
                        "description": "Search the selected knowledge base.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "kb_name": {"type": "string"},
                            },
                            "required": ["query", "kb_name"],
                        },
                    },
                }
            ]

    pipeline.registry = FakeRegistry()

    [schema] = pipeline._build_llm_tool_schemas(["rag"])
    parameters = schema["function"]["parameters"]

    assert parameters["properties"] == {"query": {"type": "string"}}
    assert parameters["required"] == ["query"]
    assert parameters["additionalProperties"] is False


@pytest.mark.asyncio
async def test_native_rag_call_uses_system_selected_kb_not_llm_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "master_prep_ai.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )

    class FakeRegistry:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def build_openai_schemas(self, _enabled_tools):
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "rag",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "kb_name": {"type": "string"},
                            },
                            "required": ["query", "kb_name"],
                        },
                    },
                }
            ]

        def build_prompt_text(self, enabled_tools, **_kwargs):
            return "\n".join(enabled_tools)

        async def execute(self, name: str, **kwargs):
            self.calls.append({"name": name, **kwargs})
            return ToolResult(
                content="grounded result",
                sources=[{"tool": name, "kb_name": kwargs.get("kb_name")}],
                metadata={"tool": name},
                success=True,
            )

    registry = FakeRegistry()
    monkeypatch.setattr(
        "master_prep_ai.agents.chat.agentic_pipeline.get_tool_registry", lambda: registry
    )

    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry

    class FakeCreate:
        def __init__(self) -> None:
            self.tools: list[dict[str, Any]] = []

        async def __call__(self, **kwargs):
            self.tools = kwargs.get("tools") or []
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="",
                            tool_calls=[
                                SimpleNamespace(
                                    id="tool-call-rag",
                                    function=SimpleNamespace(
                                        name="rag",
                                        arguments='{"query":"chapter summary","kb_name":"old-kb"}',
                                    ),
                                )
                            ],
                        )
                    )
                ]
            )

    fake_create = FakeCreate()
    monkeypatch.setattr(
        pipeline,
        "_build_openai_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)),
        ),
    )

    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)
    context = UnifiedContext(
        session_id="session-1",
        user_message="summarize chapter 3",
        enabled_tools=["rag"],
        knowledge_bases=["current-kb"],
        language="en",
        metadata={"turn_id": "turn-1"},
    )

    traces = await pipeline._run_native_tool_loop(
        context=context,
        enabled_tools=["rag"],
        thinking_text="RAG would help.",
        stream=bus,
    )
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    rag_properties = fake_create.tools[0]["function"]["parameters"]["properties"]
    assert "kb_name" not in rag_properties
    assert registry.calls[0]["query"] == "chapter summary"
    assert registry.calls[0]["kb_name"] == "current-kb"
    assert traces[0].arguments == {"query": "chapter summary"}

    tool_call_events = [event for event in events if event.type == StreamEventType.TOOL_CALL]
    assert tool_call_events[0].metadata["tool_name"] == "rag"
    assert tool_call_events[0].metadata.get("args", {}) == {"query": "chapter summary"}
    assert tool_call_events[0].content


@pytest.mark.asyncio
async def test_native_tool_loop_caps_parallel_tool_calls_at_eight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "master_prep_ai.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )

    class FakeRegistry:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def build_openai_schemas(self, _enabled_tools):
            return [{"type": "function", "function": {"name": "web_search"}}]

        def build_prompt_text(self, enabled_tools, **_kwargs):
            return "\n".join(enabled_tools)

        def get_enabled(self, selected):
            return [SimpleNamespace(name=name) for name in selected]

        async def execute(self, name: str, **kwargs):
            self.calls.append(f"{name}:{kwargs.get('query', '')}")
            return ToolResult(
                content=f"{name} => {kwargs.get('query', '')}",
                sources=[{"tool": name}],
                metadata={"tool": name},
                success=True,
            )

    registry = FakeRegistry()
    monkeypatch.setattr(
        "master_prep_ai.agents.chat.agentic_pipeline.get_tool_registry", lambda: registry
    )

    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry

    tool_calls = [
        SimpleNamespace(
            id=f"tool-call-{index}",
            function=SimpleNamespace(
                name="web_search",
                arguments=f'{{"query":"q{index}"}}',
            ),
        )
        for index in range(10)
    ]

    async def fake_create(**_kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Use multiple tools in parallel.",
                        tool_calls=tool_calls,
                    )
                )
            ]
        )

    monkeypatch.setattr(
        pipeline,
        "_build_openai_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=fake_create),
            )
        ),
    )

    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)
    context = UnifiedContext(
        session_id="session-1",
        user_message="collect broad evidence",
        enabled_tools=["web_search"],
        language="en",
        metadata={"turn_id": "turn-1"},
    )

    traces = await pipeline._run_native_tool_loop(
        context=context,
        enabled_tools=["web_search"],
        thinking_text="Need multiple web sources.",
        stream=bus,
    )
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    assert len(traces) == 8
    assert len(registry.calls) == 8
    assert registry.calls[-1] == "web_search:q7"
    progress_events = [event.content for event in events if event.type == StreamEventType.PROGRESS]
    assert any("8 can run in parallel" in content for content in progress_events)
