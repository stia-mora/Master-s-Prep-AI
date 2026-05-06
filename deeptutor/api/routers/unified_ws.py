"""
Unified WebSocket Endpoint
==========================

Single ``/api/v1/ws`` endpoint for turn-based execution and replayable streaming.

Supported client message ``type`` values:

- ``message`` / ``start_turn`` — start a new turn from a payload.
- ``subscribe_turn`` — stream events of an existing turn (with ``after_seq``).
- ``subscribe_session`` — stream events of the active turn for a session.
- ``resume_from`` — resume an in-flight turn after reconnection.
- ``unsubscribe`` — stop a previously created subscription.
- ``cancel_turn`` — cancel a running turn.
- ``regenerate`` — re-run the last user message in the given session as a
  brand-new turn. Replaces the trailing assistant message (if any) and
  reuses the session's stored capability/tools/preferences. Optional
  ``overrides`` field accepts ``capability``, ``tools``, ``knowledge_bases``,
  ``language``, ``config``, `
otebook_references``, ``history_references``.
  Errors: ``regenerate_busy`` (another turn is running) and
  `
othing_to_regenerate`` (no prior user message).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws")
async def unified_websocket(ws: WebSocket) -> None:
    from deeptutor.auth import current_user_context, require_websocket_user

    user = await require_websocket_user(ws)
    if user is None:
        return
    closed = False
    subscription_tasks: dict[str, asyncio.Task[None]] = {}

    async def safe_send(data: dict[str, Any]) -> None:
        nonlocal closed
        if closed:
            return
        try:
            await ws.send_json(data)
        except Exception:
            closed = True

    async def stop_subscription(key: str) -> None:
        task = subscription_tasks.pop(key, None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def subscribe_turn(turn_id: str, after_seq: int = 0) -> None:
        from deeptutor.services.session import get_turn_runtime_manager

        async def _forward() -> None:
            runtime = get_turn_runtime_manager()
            async for event in runtime.subscribe_turn(turn_id, after_seq=after_seq):
                await safe_send(event)

        await stop_subscription(turn_id)
        with current_user_context(user.user_id):
            subscription_tasks[turn_id] = asyncio.create_task(_forward())

    async def subscribe_session(session_id: str, after_seq: int = 0) -> None:
        from deeptutor.services.session import get_turn_runtime_manager

        async def _forward() -> None:
            runtime = get_turn_runtime_manager()
            async for event in runtime.subscribe_session(session_id, after_seq=after_seq):
                await safe_send(event)

        key = f"session:{session_id}"
        await stop_subscription(key)
        with current_user_context(user.user_id):
            subscription_tasks[key] = asyncio.create_task(_forward())

    try:
        while not closed:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await safe_send({"type": "error", "content": "Invalid JSON."})
                continue

            msg_type = msg.get("type")

            if msg_type in {"message", "start_turn"}:
                from deeptutor.services.session import get_turn_runtime_manager

                runtime = get_turn_runtime_manager()
                try:
                    msg["user_id"] = user.user_id
                    with current_user_context(user.user_id):
                        _, turn = await runtime.start_turn(msg)
                except RuntimeError as exc:
                    await safe_send(
                        {
                            "type": "error",
                            "source": "unified_ws",
                            "stage": "",
                            "content": str(exc),
                            "metadata": {"turn_terminal": True, "status": "rejected"},
                            "session_id": str(msg.get("session_id") or ""),
                            "turn_id": "",
                            "seq": 0,
                        }
                    )
                    continue
                await subscribe_turn(turn["id"], after_seq=0)
                continue

            if msg_type == "subscribe_turn":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await safe_send({"type": "error", "content": "Missing turn_id."})
                    continue
                await subscribe_turn(turn_id, after_seq=int(msg.get("after_seq") or 0))
                continue

            if msg_type == "subscribe_session":
                session_id = str(msg.get("session_id") or "").strip()
                if not session_id:
                    await safe_send({"type": "error", "content": "Missing session_id."})
                    continue
                await subscribe_session(session_id, after_seq=int(msg.get("after_seq") or 0))
                continue

            if msg_type == "resume_from":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await safe_send({"type": "error", "content": "Missing turn_id."})
                    continue
                await subscribe_turn(turn_id, after_seq=int(msg.get("seq") or 0))
                continue

            if msg_type == "unsubscribe":
                turn_id = str(msg.get("turn_id") or "").strip()
                if turn_id:
                    await stop_subscription(turn_id)
                session_id = str(msg.get("session_id") or "").strip()
                if session_id:
                    await stop_subscription(f"session:{session_id}")
                continue

            if msg_type == "cancel_turn":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await safe_send({"type": "error", "content": "Missing turn_id."})
                    continue
                from deeptutor.services.session import get_turn_runtime_manager

                runtime = get_turn_runtime_manager()
                with current_user_context(user.user_id):
                    cancelled = await runtime.cancel_turn(turn_id)
                if not cancelled:
                    await safe_send({"type": "error", "content": f"Turn not found: {turn_id}"})
                continue

            if msg_type == "regenerate":
                session_id = str(msg.get("session_id") or "").strip()
                if not session_id:
                    await safe_send({"type": "error", "content": "Missing session_id."})
                    continue
                from deeptutor.services.session import get_turn_runtime_manager

                runtime = get_turn_runtime_manager()
                overrides = msg.get("overrides") if isinstance(msg.get("overrides"), dict) else None
                try:
                    if overrides is None:
                        overrides = {}
                    overrides["user_id"] = user.user_id
                    with current_user_context(user.user_id):
                        _, turn = await runtime.regenerate_last_turn(
                            session_id,
                            overrides=overrides,
                        )
                except RuntimeError as exc:
                    await safe_send(
                        {
                            "type": "error",
                            "source": "unified_ws",
                            "stage": "",
                            "content": str(exc),
                            "metadata": {
                                "turn_terminal": True,
                                "status": "rejected",
                                "reason": str(exc),
                            },
                            "session_id": session_id,
                            "turn_id": "",
                            "seq": 0,
                        }
                    )
                    continue
                await subscribe_turn(turn["id"], after_seq=0)
                continue

            await safe_send({"type": "error", "content": f"Unknown type: {msg_type}"})

    except WebSocketDisconnect:
        logger.debug("Client disconnected from /ws")
    except Exception as exc:
        logger.error("Unified WS error: %s", exc, exc_info=True)
        await safe_send({"type": "error", "content": str(exc)})
    finally:
        closed = True
        for key in list(subscription_tasks.keys()):
            await stop_subscription(key)
