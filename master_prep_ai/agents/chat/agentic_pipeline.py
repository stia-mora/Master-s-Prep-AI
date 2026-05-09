"""Agentic chat pipeline with thinking, acting, observing, and responding."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import json
import logging
import os
from typing import Any

import httpx
from openai import AsyncAzureOpenAI, AsyncOpenAI

from master_prep_ai.core.context import UnifiedContext
from master_prep_ai.core.stream_bus import StreamBus
from master_prep_ai.core.trace import (
    build_trace_metadata,
    derive_trace_metadata,
    merge_trace_metadata,
    new_call_id,
)
from master_prep_ai.runtime.registry.tool_registry import get_tool_registry
from master_prep_ai.services.config import get_chat_params
from master_prep_ai.services.llm import (
    clean_thinking_tags,
    get_llm_config,
    get_token_limit_kwargs,
    prepare_multimodal_messages,
    supports_response_format,
    supports_tools,
)
from master_prep_ai.services.llm import (
    stream as llm_stream,
)
from master_prep_ai.services.prompt import get_prompt_manager
from master_prep_ai.tools.builtin import BUILTIN_TOOL_NAMES
from master_prep_ai.utils.json_parser import parse_json_response

logger = logging.getLogger(__name__)

CHAT_EXCLUDED_TOOLS = {"geogebra_analysis"}
CHAT_OPTIONAL_TOOLS = [name for name in BUILTIN_TOOL_NAMES if name not in CHAT_EXCLUDED_TOOLS]
MAX_PARALLEL_TOOL_CALLS = 8
MAX_TOOL_RESULT_CHARS = 4000

CHAT_STAGE_KEYS: tuple[str, ...] = (
    "responding",
    "answer_now",
    "thinking",
    "observing",
    "acting",
    "react_fallback",
)


@dataclass
class _ChatLimits:
    """Per-stage ``max_tokens`` resolved from ``capabilities.chat`` in agents.yaml."""

    responding: int
    answer_now: int
    thinking: int
    observing: int
    acting: int
    react_fallback: int

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "_ChatLimits":
        # Defaults below mirror DEFAULT_CHAT_PARAMS so the pipeline still works
        # if the YAML block is missing entirely (e.g. minimal/legacy installs).
        fallback = {
            "responding": 8000,
            "answer_now": 8000,
            "thinking": 2000,
            "observing": 2000,
            "acting": 2000,
            "react_fallback": 1500,
        }
        resolved: dict[str, int] = {}
        for key in CHAT_STAGE_KEYS:
            stage_cfg = cfg.get(key) if isinstance(cfg, dict) else None
            if isinstance(stage_cfg, dict):
                value = stage_cfg.get("max_tokens", fallback[key])
            else:
                value = fallback[key]
            try:
                resolved[key] = int(value)
            except (TypeError, ValueError):
                resolved[key] = fallback[key]
        return cls(**resolved)


@dataclass
class ToolTrace:
    name: str
    arguments: dict[str, Any]
    result: str
    success: bool
    sources: list[dict[str, Any]]
    metadata: dict[str, Any]


class AgenticChatPipeline:
    """Run chat as a 4-stage agentic pipeline."""

    def __init__(self, language: str = "en") -> None:
        self.language = "zh" if language.lower().startswith("zh") else "en"
        self.llm_config = get_llm_config()
        self.binding = getattr(self.llm_config, "binding", None) or "openai"
        self.model = getattr(self.llm_config, "model", None)
        self.api_key = getattr(self.llm_config, "api_key", None)
        self.base_url = getattr(self.llm_config, "base_url", None)
        self.api_version = getattr(self.llm_config, "api_version", None)
        self.registry = get_tool_registry()
        self._usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
        # capabilities.chat in agents.yaml drives token budgets and temperature
        # for every LLM call below; falls back to DEFAULT_CHAT_PARAMS if the
        # block is missing.
        try:
            chat_cfg = get_chat_params()
        except Exception as exc:
            logger.warning("Failed to load chat params, using defaults: %s", exc)
            chat_cfg = {}
        try:
            self._chat_temperature = float(chat_cfg.get("temperature", 0.2))
        except (TypeError, ValueError):
            self._chat_temperature = 0.2
        self._chat_limits = _ChatLimits.from_config(chat_cfg)
        # Prompts live in master_prep_ai/agents/chat/prompts/{zh,en}/agentic_chat.yaml
        # so all user-visible / LLM-facing copy is editable without touching code.
        try:
            self._prompts: dict[str, Any] = (
                get_prompt_manager().load_prompts(
                    module_name="chat",
                    agent_name="agentic_chat",
                    language=self.language,
                )
                or {}
            )
        except Exception as exc:
            logger.warning("Failed to load agentic_chat prompts: %s", exc)
            self._prompts = {}

    def _accumulate_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage:
            self._usage["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            self._usage["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
            self._usage["total_tokens"] += getattr(usage, "total_tokens", 0) or 0
            self._usage["calls"] += 1

    def _get_cost_summary(self) -> dict[str, Any] | None:
        if self._usage["calls"] == 0:
            return None
        return {
            "total_cost_usd": 0,
            "total_tokens": self._usage["total_tokens"],
            "total_calls": self._usage["calls"],
        }

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        answer_now_context = self._extract_answer_now_context(context)
        if answer_now_context is not None:
            final_response, trace_meta = await self._stage_answer_now(
                context=context,
                answer_now_context=answer_now_context,
                stream=stream,
            )
            result_payload: dict[str, Any] = {
                "response": final_response,
                "answer_now": True,
                "source_trace": trace_meta.get("label", "Answer now"),
            }
            cs = self._get_cost_summary()
            if cs:
                result_payload["metadata"] = {"cost_summary": cs}
            await stream.result(result_payload, source="chat")
            return

        requested_tools = self._normalize_enabled_tools(context.enabled_tools)
        enabled_tools = self._drop_rag_without_selected_kb(requested_tools, context)
        if "rag" in requested_tools and "rag" not in enabled_tools:
            await stream.progress(
                self._rag_without_kb_message(),
                source="chat",
                stage="thinking",
                metadata={"reason": "rag_without_kb"},
            )
        thinking_text = await self._stage_thinking(context, enabled_tools, stream)
        tool_traces = await self._stage_acting(
            context=context,
            enabled_tools=enabled_tools,
            thinking_text=thinking_text,
            stream=stream,
        )
        observation = await self._stage_observing(
            context=context,
            enabled_tools=enabled_tools,
            thinking_text=thinking_text,
            tool_traces=tool_traces,
            stream=stream,
        )
        final_response, responding_trace = await self._stage_responding(
            context=context,
            enabled_tools=enabled_tools,
            thinking_text=thinking_text,
            observation=observation,
            tool_traces=tool_traces,
            stream=stream,
        )

        all_sources: list[dict[str, Any]] = []
        for trace in tool_traces:
            all_sources.extend(trace.sources)
        if all_sources:
            await stream.sources(
                all_sources,
                source="chat",
                stage="responding",
                metadata=merge_trace_metadata(
                    responding_trace,
                    {"trace_kind": "sources"},
                ),
            )

        result_payload: dict[str, Any] = {
            "response": final_response,
            "observation": observation,
            "tool_traces": [asdict(trace) for trace in tool_traces],
        }
        cs = self._get_cost_summary()
        if cs:
            result_payload["metadata"] = {"cost_summary": cs}
        await stream.result(result_payload, source="chat")

    async def _stage_thinking(
        self,
        context: UnifiedContext,
        enabled_tools: list[str],
        stream: StreamBus,
    ) -> str:
        trace_meta = build_trace_metadata(
            call_id=new_call_id("chat-thinking"),
            phase="thinking",
            label=self._t("labels.reasoning", default="Reasoning"),
            call_kind="llm_reasoning",
            trace_id="chat-thinking",
            trace_role="thought",
            trace_group="stage",
        )
        async with stream.stage("thinking", source="chat", metadata=trace_meta):
            await stream.progress(
                trace_meta["label"],
                source="chat",
                stage="thinking",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "running"},
                ),
            )
            thinking_user = self._t(
                "thinking.user",
                user_message=context.user_message,
            )
            messages = self._build_messages(
                context=context,
                system_prompt=self._thinking_system_prompt(enabled_tools, context),
                user_content=thinking_user or context.user_message,
            )
            messages, images_stripped = self._prepare_messages_with_attachments(
                messages,
                context,
            )
            if images_stripped:
                await stream.thinking(
                    self._images_stripped_notice(),
                    source="chat",
                    stage="thinking",
                    metadata=merge_trace_metadata(trace_meta, {"trace_kind": "llm_chunk"}),
                )

            chunks: list[str] = []
            async for chunk in self._stream_messages(
                messages, max_tokens=self._chat_limits.thinking
            ):
                if not chunk:
                    continue
                chunks.append(chunk)
                await stream.thinking(
                    chunk,
                    source="chat",
                    stage="thinking",
                    metadata=merge_trace_metadata(trace_meta, {"trace_kind": "llm_chunk"}),
                )
            await stream.progress(
                "",
                source="chat",
                stage="thinking",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "complete"},
                ),
            )
            return clean_thinking_tags("".join(chunks), self.binding, self.model)

    async def _stage_acting(
        self,
        context: UnifiedContext,
        enabled_tools: list[str],
        thinking_text: str,
        stream: StreamBus,
    ) -> list[ToolTrace]:
        async with stream.stage("acting", source="chat"):
            if not enabled_tools:
                await stream.progress(
                    self._t("notices.no_tools_enabled"),
                    source="chat",
                    stage="acting",
                )
                return []

            if self._can_use_native_tool_calling():
                return await self._run_native_tool_loop(
                    context=context,
                    enabled_tools=enabled_tools,
                    thinking_text=thinking_text,
                    stream=stream,
                )

            await stream.progress(
                self._t("notices.react_fallback_switch"),
                source="chat",
                stage="acting",
            )
            return await self._run_react_fallback(
                context=context,
                enabled_tools=enabled_tools,
                thinking_text=thinking_text,
                stream=stream,
            )

    async def _stage_observing(
        self,
        context: UnifiedContext,
        enabled_tools: list[str],
        thinking_text: str,
        tool_traces: list[ToolTrace],
        stream: StreamBus,
    ) -> str:
        trace_meta = build_trace_metadata(
            call_id=new_call_id("chat-observing"),
            phase="observing",
            label=self._t("labels.observation", default="Observation"),
            call_kind="llm_observation",
            trace_id="chat-observing",
            trace_role="observe",
            trace_group="stage",
        )
        async with stream.stage("observing", source="chat", metadata=trace_meta):
            await stream.progress(
                trace_meta["label"],
                source="chat",
                stage="observing",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "running"},
                ),
            )
            observation_prompt = self._t("observing.user_intro")
            messages = self._build_messages(
                context=context,
                system_prompt=self._observing_system_prompt(enabled_tools),
                user_content=(
                    f"{observation_prompt}\n\n"
                    f"{self._labeled_block('Thinking', thinking_text)}\n\n"
                    f"{self._labeled_block('Tool Trace', self._format_tool_traces(tool_traces))}"
                ),
            )

            chunks: list[str] = []
            async for chunk in self._stream_messages(
                messages, max_tokens=self._chat_limits.observing
            ):
                if not chunk:
                    continue
                chunks.append(chunk)
                await stream.observation(
                    chunk,
                    source="chat",
                    stage="observing",
                    metadata=merge_trace_metadata(trace_meta, {"trace_kind": "observation"}),
                )
            await stream.progress(
                "",
                source="chat",
                stage="observing",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "complete"},
                ),
            )
            return clean_thinking_tags("".join(chunks), self.binding, self.model)

    async def _stage_responding(
        self,
        context: UnifiedContext,
        enabled_tools: list[str],
        thinking_text: str,
        observation: str,
        tool_traces: list[ToolTrace],
        stream: StreamBus,
    ) -> tuple[str, dict[str, Any]]:
        trace_meta = build_trace_metadata(
            call_id=new_call_id("chat-responding"),
            phase="responding",
            label=self._t("labels.final_response", default="Final response"),
            call_kind="llm_final_response",
            trace_id="chat-responding",
            trace_role="response",
            trace_group="stage",
        )
        async with stream.stage("responding", source="chat", metadata=trace_meta):
            await stream.progress(
                trace_meta["label"],
                source="chat",
                stage="responding",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "running"},
                ),
            )
            user_prompt = self._t(
                "responding.user",
                user_message=context.user_message,
                observation=observation.strip() if observation.strip() else "(empty)",
                tool_trace=self._format_tool_traces(tool_traces),
            )
            messages = self._build_messages(
                context=context,
                system_prompt=self._responding_system_prompt(enabled_tools),
                user_content=user_prompt,
            )
            messages, _ = self._prepare_messages_with_attachments(messages, context)

            chunks: list[str] = []
            async for chunk in self._stream_messages(
                messages, max_tokens=self._chat_limits.responding
            ):
                if not chunk:
                    continue
                chunks.append(chunk)
                await stream.content(
                    chunk,
                    source="chat",
                    stage="responding",
                    metadata=merge_trace_metadata(trace_meta, {"trace_kind": "llm_chunk"}),
                )
            await stream.progress(
                "",
                source="chat",
                stage="responding",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "complete"},
                ),
            )
            final_response = clean_thinking_tags("".join(chunks), self.binding, self.model)
            if not final_response.strip():
                # The provider returned an empty stream (zero non-empty chunks)
                # or only whitespace. This typically means: model hit a token
                # limit, was filtered, or treated the observation as the final
                # answer. Surface a non-terminal warning so the operator sees
                # the cause in logs and the UI can hint a Regenerate.
                prompt_chars = sum(len(str(m.get("content") or "")) for m in messages)
                logger.warning(
                    "[%s] responding stage returned empty response "
                    "(model=%s, chunks=%d, prompt_chars=%d, max_tokens=%d, observation_chars=%d)",
                    trace_meta.get("call_id"),
                    self.model,
                    len(chunks),
                    prompt_chars,
                    self._chat_limits.responding,
                    len(observation or ""),
                )
                await stream.error(
                    self._t(
                        "notices.empty_response",
                        default=(
                            "The model returned an empty response. "
                            "Try Regenerate or rephrase the question."
                        ),
                    ),
                    source="chat",
                    stage="responding",
                    metadata=merge_trace_metadata(
                        trace_meta,
                        {
                            "trace_kind": "warning",
                            "warning_kind": "empty_response",
                            "chunks": len(chunks),
                            "prompt_chars": prompt_chars,
                            "max_tokens": self._chat_limits.responding,
                            # Explicitly mark as non-terminal so the runtime
                            # does not flip the turn to ``failed``.
                            "turn_terminal": False,
                        },
                    ),
                )
            return final_response, trace_meta

    async def _stage_answer_now(
        self,
        context: UnifiedContext,
        answer_now_context: dict[str, Any],
        stream: StreamBus,
    ) -> tuple[str, dict[str, Any]]:
        trace_meta = build_trace_metadata(
            call_id=new_call_id("chat-answer-now"),
            phase="responding",
            label="Answer now",
            call_kind="llm_final_response",
            trace_id="chat-answer-now",
            trace_role="response",
            trace_group="stage",
        )
        async with stream.stage("responding", source="chat", metadata=trace_meta):
            await stream.progress(
                trace_meta["label"],
                source="chat",
                stage="responding",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "running"},
                ),
            )

            original_user_message = str(
                answer_now_context.get("original_user_message") or context.user_message
            ).strip()
            partial_response = str(answer_now_context.get("partial_response") or "").strip()
            trace_summary = self._format_answer_now_events(answer_now_context.get("events"))
            user_prompt = self._t(
                "answer_now.user",
                original_user_message=original_user_message,
                partial_response=partial_response.strip()
                if partial_response.strip()
                else "(empty)",
                trace_summary=trace_summary,
            )
            messages = self._build_messages(
                context=context,
                system_prompt=self._responding_system_prompt([]),
                user_content=user_prompt,
            )

            chunks: list[str] = []
            async for chunk in self._stream_messages(
                messages, max_tokens=self._chat_limits.answer_now
            ):
                if not chunk:
                    continue
                chunks.append(chunk)
                await stream.content(
                    chunk,
                    source="chat",
                    stage="responding",
                    metadata=merge_trace_metadata(trace_meta, {"trace_kind": "llm_chunk"}),
                )
            await stream.progress(
                "",
                source="chat",
                stage="responding",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "complete"},
                ),
            )
            return clean_thinking_tags("".join(chunks), self.binding, self.model), trace_meta

    async def _run_native_tool_loop(
        self,
        context: UnifiedContext,
        enabled_tools: list[str],
        thinking_text: str,
        stream: StreamBus,
    ) -> list[ToolTrace]:
        tool_schemas = self._build_llm_tool_schemas(enabled_tools)
        messages = self._build_messages(
            context=context,
            system_prompt=self._acting_system_prompt(enabled_tools, context),
            user_content=self._acting_user_prompt(context, thinking_text),
        )
        messages, _ = self._prepare_messages_with_attachments(messages, context)
        tool_traces: list[ToolTrace] = []
        client = self._build_openai_client()
        trace_meta = build_trace_metadata(
            call_id=new_call_id("chat-acting"),
            phase="acting",
            label=self._t("labels.tool_call", default="Tool call"),
            call_kind="tool_planning",
            trace_id="chat-acting",
            trace_role="tool",
            trace_group="tool_call",
        )
        await stream.progress(
            trace_meta["label"],
            source="chat",
            stage="acting",
            metadata=merge_trace_metadata(
                trace_meta,
                {"trace_kind": "call_status", "call_state": "running"},
            ),
        )
        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tool_schemas,
            tool_choice="auto",
            **self._completion_kwargs(max_tokens=self._chat_limits.acting),
        )
        self._accumulate_usage(response)
        if not response.choices:
            return tool_traces

        choice = response.choices[0]
        message = choice.message
        assistant_content = self._message_text(message.content)
        raw_tool_calls = list(message.tool_calls or [])

        if assistant_content:
            await stream.thinking(
                assistant_content,
                source="chat",
                stage="acting",
                metadata=merge_trace_metadata(trace_meta, {"trace_kind": "llm_output"}),
            )

        if not raw_tool_calls:
            await stream.progress(
                self._t("notices.no_tool_call_needed"),
                source="chat",
                stage="acting",
                metadata=merge_trace_metadata(trace_meta, {"trace_kind": "progress"}),
            )
            await stream.progress(
                "",
                source="chat",
                stage="acting",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "complete"},
                ),
            )
            return tool_traces

        pending_calls: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
        if len(raw_tool_calls) > MAX_PARALLEL_TOOL_CALLS:
            await stream.progress(
                self._t(
                    "notices.too_many_tool_calls",
                    requested=len(raw_tool_calls),
                    limit=MAX_PARALLEL_TOOL_CALLS,
                ),
                source="chat",
                stage="acting",
                metadata=merge_trace_metadata(trace_meta, {"trace_kind": "progress"}),
            )
        for tool_call in raw_tool_calls[:MAX_PARALLEL_TOOL_CALLS]:
            tool_name = tool_call.function.name
            tool_args = parse_json_response(
                tool_call.function.arguments or "{}",
                logger_instance=logger,
                fallback={},
            )
            if not isinstance(tool_args, dict):
                tool_args = {}
            display_args = self._llm_visible_tool_args(tool_name, tool_args)
            execution_args = self._augment_tool_kwargs(
                tool_name,
                display_args,
                context,
                thinking_text,
            )
            pending_calls.append((tool_call.id, tool_name, display_args, execution_args))

        for tool_index, (tool_call_id, tool_name, display_args, _execution_args) in enumerate(
            pending_calls
        ):
            await stream.tool_call(
                tool_name=tool_name,
                args=display_args,
                source="chat",
                stage="acting",
                metadata=self._tool_trace_metadata(
                    trace_meta,
                    context=context,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_index=tool_index,
                ),
            )

        tool_results = await asyncio.gather(
            *[
                self._execute_tool_call(
                    tool_name,
                    execution_args,
                    stream=stream,
                    retrieve_meta=self._retrieve_trace_metadata(
                        trace_meta,
                        context=context,
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        tool_index=tool_index,
                        tool_args=execution_args,
                    ),
                )
                for tool_index, (
                    tool_call_id,
                    tool_name,
                    _display_args,
                    execution_args,
                ) in enumerate(pending_calls)
            ]
        )

        for tool_index, (
            (tool_call_id, tool_name, display_args, _execution_args),
            tool_result,
        ) in enumerate(
            zip(pending_calls, tool_results, strict=False)
        ):
            result_text = tool_result["result_text"]
            success = bool(tool_result["success"])
            sources = tool_result["sources"]
            metadata = tool_result["metadata"]
            await stream.tool_result(
                tool_name=tool_name,
                result=result_text,
                source="chat",
                stage="acting",
                metadata=self._tool_trace_metadata(
                    trace_meta,
                    context=context,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_index=tool_index,
                    trace_kind="tool_result",
                ),
            )

            tool_traces.append(
                ToolTrace(
                    name=tool_name,
                    arguments=display_args,
                    result=result_text,
                    success=success,
                    sources=sources,
                    metadata=metadata,
                )
            )

        await stream.progress(
            "",
            source="chat",
            stage="acting",
            metadata=merge_trace_metadata(
                trace_meta,
                {"trace_kind": "call_status", "call_state": "complete"},
            ),
        )

        return tool_traces

    async def _run_react_fallback(
        self,
        context: UnifiedContext,
        enabled_tools: list[str],
        thinking_text: str,
        stream: StreamBus,
    ) -> list[ToolTrace]:
        tool_traces: list[ToolTrace] = []
        tool_table = self.registry.build_prompt_text(
            enabled_tools,
            format="table",
            language=self.language,
            control_actions=[
                {
                    "name": "done",
                    "when_to_use": self._t("react_fallback.done_when_to_use"),
                    "input_format": self._t("react_fallback.done_input_format"),
                }
            ],
        )

        trace_meta = build_trace_metadata(
            call_id=new_call_id("chat-react"),
            phase="acting",
            label=self._t("labels.tool_call", default="Tool call"),
            call_kind="tool_planning",
            trace_id="chat-react",
            trace_role="tool",
            trace_group="tool_call",
        )
        await stream.progress(
            trace_meta["label"],
            source="chat",
            stage="acting",
            metadata=merge_trace_metadata(
                trace_meta,
                {"trace_kind": "call_status", "call_state": "running"},
            ),
        )
        _fb_prompt = self._acting_user_prompt(context, thinking_text)
        _fb_system = self._react_fallback_system_prompt(tool_table)
        _chunks: list[str] = []
        async for _c in llm_stream(
            prompt=_fb_prompt,
            system_prompt=_fb_system,
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            binding=self.binding,
            response_format={"type": "json_object"}
            if supports_response_format(self.binding, self.model)
            else None,
            **self._completion_kwargs(max_tokens=self._chat_limits.react_fallback),
        ):
            _chunks.append(_c)
        response = "".join(_chunks)
        _fb_in = int((len(_fb_prompt) + len(_fb_system)) / 3.5)
        _fb_out = int(len(response) / 3.5)
        self._usage["prompt_tokens"] += _fb_in
        self._usage["completion_tokens"] += _fb_out
        self._usage["total_tokens"] += _fb_in + _fb_out
        self._usage["calls"] += 1

        payload = parse_json_response(response, logger_instance=logger, fallback={})
        if not isinstance(payload, dict):
            payload = {}

        action = str(payload.get("action") or "done").strip()
        action_input = payload.get("action_input") or {}
        if not isinstance(action_input, dict):
            action_input = {}

        if action == "done":
            if response:
                await stream.thinking(
                    response,
                    source="chat",
                    stage="acting",
                    metadata=merge_trace_metadata(trace_meta, {"trace_kind": "llm_output"}),
                )
            await stream.progress(
                self._t("notices.no_tool_call_needed"),
                source="chat",
                stage="acting",
                metadata=merge_trace_metadata(trace_meta, {"trace_kind": "progress"}),
            )
            await stream.progress(
                "",
                source="chat",
                stage="acting",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "complete"},
                ),
            )
            return tool_traces

        display_args = self._llm_visible_tool_args(action, action_input)
        tool_args = self._augment_tool_kwargs(action, display_args, context, thinking_text)
        if response:
            await stream.thinking(
                response,
                source="chat",
                stage="acting",
                metadata=merge_trace_metadata(trace_meta, {"trace_kind": "llm_output"}),
            )
        await stream.tool_call(
            tool_name=action,
            args=display_args,
            source="chat",
            stage="acting",
            metadata=merge_trace_metadata(
                trace_meta,
                {"trace_kind": "tool_call", "trace_role": "tool", "tool_name": action},
            ),
        )

        try:
            result = await self._execute_tool_call(
                action,
                tool_args,
                stream=stream,
                retrieve_meta=self._retrieve_trace_metadata(
                    trace_meta,
                    context=context,
                    tool_call_id="chat-react-tool",
                    tool_name=action,
                    tool_index=0,
                    tool_args=tool_args,
                ),
            )
            result_text = result["result_text"]
            success = result["success"]
            sources = result["sources"]
            metadata = result["metadata"]
        except Exception:
            logger.error("Fallback tool %s failed", action, exc_info=True)
            result_text = self._t("notices.tool_unknown_error", tool=action)
            success = False
            sources = []
            metadata = {"error": result_text}

        await stream.tool_result(
            tool_name=action,
            result=result_text,
            source="chat",
            stage="acting",
            metadata=merge_trace_metadata(
                trace_meta,
                {"trace_kind": "tool_result", "trace_role": "tool", "tool_name": action},
            ),
        )
        tool_traces.append(
            ToolTrace(
                name=action,
                arguments=display_args,
                result=result_text,
                success=success,
                sources=sources,
                metadata=metadata,
            )
        )
        await stream.progress(
            "",
            source="chat",
            stage="acting",
            metadata=merge_trace_metadata(
                trace_meta,
                {"trace_kind": "call_status", "call_state": "complete"},
            ),
        )

        return tool_traces

    def _build_messages(
        self,
        context: UnifiedContext,
        system_prompt: str,
        user_content: str,
    ) -> list[dict[str, Any]]:
        system_parts = [system_prompt]
        kb_note = self._current_kb_system_note(context)
        if kb_note:
            system_parts.append(kb_note)
        if context.memory_context:
            system_parts.append(context.memory_context)
        if context.skills_context:
            system_parts.append(context.skills_context)

        messages: list[dict[str, Any]] = [{"role": "system", "content": "\n\n".join(system_parts)}]
        for item in context.conversation_history:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, (str, list)):
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_content})
        return messages

    def _prepare_messages_with_attachments(
        self,
        messages: list[dict[str, Any]],
        context: UnifiedContext,
    ) -> tuple[list[dict[str, Any]], bool]:
        mm_result = prepare_multimodal_messages(
            messages,
            context.attachments,
            binding=self.binding,
            model=self.model,
        )
        return mm_result.messages, mm_result.images_stripped

    async def _stream_messages(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ):
        output_chars = 0
        async for chunk in llm_stream(
            prompt="",
            system_prompt="",
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            binding=self.binding,
            messages=messages,
            **self._completion_kwargs(max_tokens=max_tokens),
        ):
            output_chars += len(chunk)
            yield chunk
        input_chars = sum(len(str(m.get("content", ""))) for m in messages)
        est_input = int(input_chars / 3.5)
        est_output = int(output_chars / 3.5)
        self._usage["prompt_tokens"] += est_input
        self._usage["completion_tokens"] += est_output
        self._usage["total_tokens"] += est_input + est_output
        self._usage["calls"] += 1

    def _build_openai_client(self):
        http_client = None
        if os.getenv("DISABLE_SSL_VERIFY", "").lower() in ("true", "1", "yes"):
            http_client = httpx.AsyncClient(verify=False)  # nosec B501

        if self.binding == "azure_openai" or (self.binding == "openai" and self.api_version):
            return AsyncAzureOpenAI(
                api_key=self.api_key or "sk-no-key-required",
                azure_endpoint=self.base_url,
                api_version=self.api_version,
                http_client=http_client,
            )
        return AsyncOpenAI(
            api_key=self.api_key or "sk-no-key-required",
            base_url=self.base_url or None,
            http_client=http_client,
        )

    def _completion_kwargs(self, max_tokens: int) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"temperature": self._chat_temperature}
        if self.model:
            kwargs.update(get_token_limit_kwargs(self.model, max_tokens))
        return kwargs

    def _can_use_native_tool_calling(self) -> bool:
        if not supports_tools(self.binding, self.model):
            return False
        return self.binding not in {
            "anthropic",
            "claude",
            "ollama",
            "lm_studio",
            "vllm",
            "llama_cpp",
        }

    def _normalize_enabled_tools(self, enabled_tools: list[str] | None) -> list[str]:
        selected = enabled_tools or []
        return [
            tool.name
            for tool in self.registry.get_enabled(selected)
            if tool.name not in CHAT_EXCLUDED_TOOLS
        ]

    def _build_llm_tool_schemas(self, enabled_tools: list[str]) -> list[dict[str, Any]]:
        """Return tool schemas for the acting LLM.

        RAG's knowledge-base choice is a trusted UI/session value, not an LLM
        argument. The model only sees whether it can call ``rag`` and what
        retrieval query to send.
        """
        schemas = self.registry.build_openai_schemas(enabled_tools)
        for schema in schemas:
            function = schema.get("function") if isinstance(schema, dict) else None
            if not isinstance(function, dict) or function.get("name") != "rag":
                continue
            parameters = function.get("parameters")
            if not isinstance(parameters, dict):
                continue
            properties = parameters.get("properties")
            if isinstance(properties, dict):
                properties.pop("kb_name", None)
            required = parameters.get("required")
            if isinstance(required, list):
                parameters["required"] = [name for name in required if name != "kb_name"]
            parameters["additionalProperties"] = False
        return schemas

    @staticmethod
    def _llm_visible_tool_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_name != "rag":
            return dict(args)
        query = str(args.get("query") or "").strip()
        return {"query": query} if query else {}

    @staticmethod
    def _extract_answer_now_context(context: UnifiedContext) -> dict[str, Any] | None:
        # Delegate to the shared helper so every capability uses the
        # exact same gate (presence + non-empty original_user_message).
        from master_prep_ai.capabilities._answer_now import extract_answer_now_context

        return extract_answer_now_context(context)

    async def _execute_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        stream: StreamBus | None = None,
        retrieve_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async def _event_sink(
            event_type: str,
            message: str = "",
            metadata: dict[str, Any] | None = None,
        ) -> None:
            if stream is None or retrieve_meta is None or not message:
                return
            await stream.progress(
                message,
                source="chat",
                stage="acting",
                metadata=derive_trace_metadata(
                    retrieve_meta,
                    trace_kind=str(event_type or "tool_log"),
                    **(metadata or {}),
                ),
            )

        if tool_name == "rag" and not str(tool_args.get("kb_name") or "").strip():
            message = self._rag_without_kb_message()
            if stream is not None and retrieve_meta is not None:
                await stream.progress(
                    message,
                    source="chat",
                    stage="acting",
                    metadata=derive_trace_metadata(
                        retrieve_meta,
                        trace_kind="call_status",
                        call_state="skipped",
                        reason="no_kb_selected",
                    ),
                )
            return {
                "result_text": message,
                "success": True,
                "sources": [],
                "metadata": {"status": "skipped", "reason": "no_kb_selected"},
            }

        if stream is not None and retrieve_meta is not None:
            query = str(retrieve_meta.get("query") or tool_args.get("query") or "").strip()
            await stream.progress(
                f"Query: {query}" if query else self._t("notices.start_retrieval"),
                source="chat",
                stage="acting",
                metadata=derive_trace_metadata(
                    retrieve_meta,
                    trace_kind="call_status",
                    call_state="running",
                ),
            )
        try:
            result = await self.registry.execute(
                tool_name,
                event_sink=_event_sink if retrieve_meta is not None else None,
                **tool_args,
            )
            if stream is not None and retrieve_meta is not None:
                await stream.progress(
                    f"Retrieve complete ({len(result.content)} chars)",
                    source="chat",
                    stage="acting",
                    metadata=derive_trace_metadata(
                        retrieve_meta,
                        trace_kind="call_status",
                        call_state="complete",
                    ),
                )
            return {
                "result_text": result.content or self._t("notices.empty_tool_result"),
                "success": result.success,
                "sources": result.sources,
                "metadata": result.metadata,
            }
        except Exception as exc:
            logger.error("Tool %s failed", tool_name, exc_info=True)
            if stream is not None and retrieve_meta is not None:
                await stream.error(
                    f"Retrieve failed: {exc}",
                    source="chat",
                    stage="acting",
                    metadata=derive_trace_metadata(
                        retrieve_meta,
                        trace_kind="call_status",
                        call_state="error",
                        error=str(exc),
                    ),
                )
            return {
                "result_text": f"Error executing {tool_name}: {exc}",
                "success": False,
                "sources": [],
                "metadata": {"error": str(exc)},
            }

    def _tool_trace_metadata(
        self,
        trace_meta: dict[str, Any],
        *,
        context: UnifiedContext,
        tool_call_id: str,
        tool_name: str,
        tool_index: int,
        trace_kind: str = "tool_call",
    ) -> dict[str, Any]:
        return merge_trace_metadata(
            trace_meta,
            {
                "trace_kind": trace_kind,
                "trace_role": "tool",
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "tool_index": tool_index,
                "session_id": context.session_id,
                "turn_id": str(context.metadata.get("turn_id", "")),
            },
        )

    def _retrieve_trace_metadata(
        self,
        trace_meta: dict[str, Any],
        *,
        context: UnifiedContext,
        tool_call_id: str,
        tool_name: str,
        tool_index: int,
        tool_args: dict[str, Any],
    ) -> dict[str, Any] | None:
        if tool_name != "rag":
            return None
        return derive_trace_metadata(
            trace_meta,
            call_id=new_call_id(f"chat-retrieve-{tool_index + 1}"),
            label=self._t("labels.retrieve", default="Retrieve"),
            call_kind="rag_retrieval",
            trace_role="retrieve",
            trace_group="retrieve",
            trace_id=f"{trace_meta.get('trace_id', 'chat')}-retrieve-{tool_index + 1}",
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_index=tool_index,
            session_id=context.session_id,
            turn_id=str(context.metadata.get("turn_id", "")),
            query=str(tool_args.get("query", "") or ""),
        )

    def _augment_tool_kwargs(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: UnifiedContext,
        thinking_text: str,
    ) -> dict[str, Any]:
        from master_prep_ai.services.path_service import get_path_service

        kwargs = dict(args)
        turn_id = str(context.metadata.get("turn_id", "") or "").strip()
        task_dir = None
        if turn_id:
            task_dir = get_path_service().get_task_workspace("chat", turn_id)
        if tool_name == "rag":
            selected_kbs = self._selected_kbs(context)
            kwargs["kb_name"] = selected_kbs[0] if selected_kbs else ""
            kwargs.setdefault("mode", "hybrid")
        elif tool_name == "code_execution":
            kwargs.setdefault("intent", context.user_message)
            kwargs.setdefault("timeout", 30)
            kwargs.setdefault("feature", "chat")
            kwargs.setdefault("session_id", context.session_id)
            kwargs.setdefault("turn_id", turn_id)
            if task_dir is not None:
                kwargs.setdefault("workspace_dir", str(task_dir / "code_runs"))
        elif tool_name in {"reason", "brainstorm"}:
            kwargs.setdefault("context", thinking_text)
        elif tool_name == "paper_search":
            kwargs.setdefault("max_results", 3)
            kwargs.setdefault("years_limit", 3)
            kwargs.setdefault("sort_by", "relevance")
        elif tool_name == "web_search":
            kwargs.setdefault("query", context.user_message)
            if task_dir is not None:
                kwargs.setdefault("output_dir", str(task_dir / "web_search"))
        return kwargs

    def _acting_system_prompt(self, enabled_tools: list[str], context: UnifiedContext) -> str:
        kb_name = context.knowledge_bases[0] if context.knowledge_bases else ""
        tool_list = self.registry.build_prompt_text(
            enabled_tools,
            format="list",
            language=self.language,
            kb_name=kb_name,
        )
        tool_aliases = self.registry.build_prompt_text(
            enabled_tools,
            format="aliases",
            language=self.language,
        )
        return self._t(
            "acting.system",
            tool_list=tool_list or self._fallback_empty_tool_list(),
            tool_aliases=tool_aliases or self._fallback_empty_tool_list(),
            max_parallel_tools=MAX_PARALLEL_TOOL_CALLS,
        )

    def _react_fallback_system_prompt(self, tool_table: str) -> str:
        return self._t("react_fallback.system", tool_table=tool_table)

    def _thinking_system_prompt(self, enabled_tools: list[str], context: UnifiedContext) -> str:
        kb_name = context.knowledge_bases[0] if context.knowledge_bases else ""
        tool_list = self.registry.build_prompt_text(
            enabled_tools,
            format="list",
            language=self.language,
            kb_name=kb_name,
        )
        has_kb = "rag" in enabled_tools and bool(context.knowledge_bases)
        kb_hint = self._t("thinking.kb_hint") if has_kb else ""
        return self._t(
            "thinking.system",
            tool_list=tool_list or self._fallback_empty_tool_list(),
            kb_hint=kb_hint,
        )

    def _selected_kbs(self, context: UnifiedContext) -> list[str]:
        return [str(kb).strip() for kb in context.knowledge_bases if str(kb).strip()]

    def _drop_rag_without_selected_kb(
        self,
        enabled_tools: list[str],
        context: UnifiedContext,
    ) -> list[str]:
        if "rag" not in enabled_tools or self._selected_kbs(context):
            return enabled_tools
        return [tool for tool in enabled_tools if tool != "rag"]

    def _current_kb_system_note(self, context: UnifiedContext) -> str:
        if not self._selected_kbs(context):
            return ""
        if getattr(self, "language", "en") == "zh":
            return (
                "本轮已有系统态选中的知识库。如果需要知识库检索，只需调用 RAG 并提供 query；"
                "不要输出、猜测或沿用任何知识库名称。系统会把 query 发到当前选中的知识库。"
            )
        return (
            "A knowledge base is selected in system state for this turn. "
            "If retrieval is useful, call RAG with only a query; do not output, "
            "guess, or reuse any knowledge-base name. The system will route the "
            "query to the currently selected knowledge base."
        )

    def _rag_without_kb_message(self) -> str:
        if getattr(self, "language", "en") == "zh":
            return "已启用 RAG，但当前没有选择知识库；本轮将跳过知识库检索。"
        return (
            "RAG is enabled, but no knowledge base is selected; "
            "skipping KB retrieval for this turn."
        )

    def _observing_system_prompt(self, enabled_tools: list[str]) -> str:
        tool_list = self.registry.build_prompt_text(
            enabled_tools,
            format="list",
            language=self.language,
        )
        has_rag = "rag" in enabled_tools
        rag_hint = self._t("observing.rag_hint") if has_rag else ""
        return self._t(
            "observing.system",
            tool_list=tool_list or self._fallback_empty_tool_list(),
            rag_hint=rag_hint,
        )

    def _responding_system_prompt(self, enabled_tools: list[str]) -> str:
        tool_list = self.registry.build_prompt_text(
            enabled_tools,
            format="list",
            language=self.language,
        )
        has_rag = "rag" in enabled_tools
        rag_hint = self._t("responding.rag_hint") if has_rag else ""
        return self._t(
            "responding.system",
            tool_list=tool_list or self._fallback_empty_tool_list(),
            rag_hint=rag_hint,
        )

    def _acting_user_prompt(self, context: UnifiedContext, thinking_text: str) -> str:
        return self._t(
            "acting.user",
            user_message=context.user_message,
            thinking=thinking_text.strip() if thinking_text.strip() else "(empty)",
            max_parallel_tools=MAX_PARALLEL_TOOL_CALLS,
        )

    def _fallback_empty_tool_list(self) -> str:
        return "- 无" if self.language == "zh" else "- none"

    def _format_tool_traces(self, tool_traces: list[ToolTrace]) -> str:
        if not tool_traces:
            return self._t("empty.no_tool_traces")

        blocks: list[str] = []
        for idx, trace in enumerate(tool_traces, start=1):
            blocks.append(
                "\n".join(
                    [
                        f"{idx}. {trace.name}",
                        f"arguments: {json.dumps(trace.arguments, ensure_ascii=False)}",
                        f"success: {trace.success}",
                        f"result: {self._truncate_tool_result(trace.result)}",
                    ]
                )
            )
        return "\n\n".join(blocks)

    def _format_answer_now_events(self, events: Any) -> str:
        if not isinstance(events, list) or not events:
            return self._t("empty.no_intermediate_trace")

        lines: list[str] = []
        for index, event in enumerate(events, start=1):
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type") or "event").strip()
            stage = str(event.get("stage") or "").strip()
            content = str(event.get("content") or "").strip()
            metadata = event.get("metadata")
            label_parts = [event_type]
            if stage:
                label_parts.append(stage)
            line = f"{index}. {' / '.join(label_parts)}"
            if content:
                line += f": {self._truncate_tool_result(content, limit=1200)}"
            if isinstance(metadata, dict):
                tool_name = str(metadata.get("tool_name") or metadata.get("tool") or "").strip()
                if tool_name:
                    line += f" [tool={tool_name}]"
            lines.append(line)

        if not lines:
            return self._t("empty.no_intermediate_trace")
        return "\n".join(lines)

    @staticmethod
    def _message_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            return "\n".join(texts).strip()
        return str(content or "")

    @staticmethod
    def _truncate_tool_result(content: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
        cleaned = content.strip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3].rstrip() + "..."

    def _images_stripped_notice(self) -> str:
        return self._t("notices.images_stripped", model=self.model or "")

    @staticmethod
    def _labeled_block(label: str, content: str) -> str:
        return f"[{label}]\n{content.strip() if content.strip() else '(empty)'}"

    def _text(self, *, zh: str, en: str) -> str:
        return zh if self.language == "zh" else en

    def _t(self, key: str, default: str = "", **kwargs: Any) -> str:
        """Look up a YAML-loaded prompt by dotted key (e.g. ``thinking.system``).

        - Returns ``default`` if the key is missing or value is not a string.
        - When ``kwargs`` are passed, the string is rendered via ``str.format``;
          missing placeholders fall back to the unrendered template instead of
          crashing the pipeline.
        """
        value: Any = self._prompts
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        if not isinstance(value, str):
            return default
        if kwargs:
            try:
                return value.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return value
        return value
