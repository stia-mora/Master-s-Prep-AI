from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sqlite3
import tempfile

import pytest

from master_prep_ai.kaoyan.chat_context import KaoyanChatContextService
from master_prep_ai.kaoyan.content_store import KaoyanContentStore


def test_kaoyan_content_store_health_advanced() -> None:
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    db_path = Path(path)
    try:
        conn = sqlite3.connect(db_path)
        tables = [
            "knowledge_points",
            "questions",
            "formulas",
            "mistakes",
            "review_cards",
            "lecture_knowledge_nodes",
            "lecture_chunks",
            "lecture_formulas",
            "lecture_mistakes",
            "lecture_review_cards",
            "worked_examples",
        ]
        for table in tables:
            if table == "knowledge_points":
                conn.execute(f"CREATE TABLE {table} (knowledge_id TEXT PRIMARY KEY, knowledge_name TEXT)")
            elif table == "questions":
                conn.execute(f"CREATE TABLE {table} (question_id TEXT PRIMARY KEY, knowledge_id TEXT, stem TEXT)")
            else:
                conn.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO knowledge_points (knowledge_id, knowledge_name) VALUES ('KP1', 'Test KP')")
        conn.execute("INSERT INTO questions (question_id, knowledge_id, stem) VALUES ('Q1', 'KP1', 'Stem 1')")
        conn.execute("INSERT INTO questions (question_id, knowledge_id, stem) VALUES ('Q2', 'KP_MISSING', 'Stem 2')")
        conn.commit()
        conn.close()

        store = KaoyanContentStore(db_path)
        health = store.health()

        assert health["status"] == "abnormal"
        assert health["abnormalities"]["orphaned_questions"] == 1
        assert health["counts"]["knowledge_points"] == 1
        assert health["counts"]["questions"] == 2
    finally:
        if db_path.exists():
            try:
                os.unlink(db_path)
            except PermissionError:
                pass


def test_kaoyan_content_store_material_parse_reserved() -> None:
    store = KaoyanContentStore()

    task = store.create_material_parse_task("test.pdf", "pdf")
    assert task["filename"] == "test.pdf"
    assert task["status"] == "pending"
    assert "task_id" in task
    assert "retry_count" in task
    assert "fail_reason" in task

    retrieved = store.get_material_parse_task(task["task_id"])
    assert retrieved is not None
    assert retrieved["task_id"] == task["task_id"]
    assert retrieved["status"] == "completed"
    assert "fail_reason" in retrieved


def test_kaoyan_chat_context_build_and_query() -> None:
    store = KaoyanContentStore()
    service = KaoyanChatContextService(store, user_id="test_user")

    tree = store.knowledge_tree()
    if not tree:
        pytest.skip("No knowledge tree available for testing")

    def find_leaf(nodes):
        for node in nodes:
            if not node.get("children"):
                return node
            leaf = find_leaf(node["children"])
            if leaf:
                return leaf
        return None

    leaf = find_leaf(tree)
    if not leaf:
        pytest.skip("No leaf knowledge point found")

    knowledge_id = leaf["knowledge_id"]
    context = asyncio.run(service.build_context("knowledge", knowledge_id))
    assert context is not None
    assert "title" in context
    assert "initial_message" in context
    assert "context_payload" in context
    assert context["context_payload"]["source_id"] == knowledge_id

    query_result = asyncio.run(service.query_rag("dummy_kb", "test query"))
    assert "kb_name" in query_result
    assert "results" in query_result
    assert "query" in query_result