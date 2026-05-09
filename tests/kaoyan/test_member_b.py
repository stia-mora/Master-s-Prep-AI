from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from pathlib import Path
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from master_prep_ai.api.routers import kaoyan as kaoyan_router
from master_prep_ai.auth import AuthUser
from master_prep_ai.kaoyan.chat_context import KaoyanChatContextService
from master_prep_ai.kaoyan.content_store import KaoyanContentStore


def _member_b_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    db_path = Path(path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE knowledge_points (
            knowledge_id TEXT PRIMARY KEY,
            subject TEXT,
            module TEXT,
            chapter TEXT,
            section TEXT,
            knowledge_name TEXT,
            parent_id TEXT,
            importance_level INTEGER,
            is_core INTEGER,
            raw_markdown TEXT
        );
        CREATE TABLE questions (
            question_id TEXT PRIMARY KEY,
            knowledge_id TEXT,
            question_type TEXT,
            difficulty_level INTEGER,
            stem TEXT,
            answer TEXT,
            analysis TEXT,
            source TEXT,
            source_type TEXT,
            year INTEGER
        );
        CREATE TABLE formulas (id TEXT PRIMARY KEY);
        CREATE TABLE mistakes (id TEXT PRIMARY KEY);
        CREATE TABLE review_cards (id TEXT PRIMARY KEY);
        CREATE TABLE lecture_knowledge_nodes (
            lecture_knowledge_id TEXT PRIMARY KEY,
            parent_id TEXT,
            node_type TEXT,
            chapter_no INTEGER,
            section_no INTEGER,
            title TEXT,
            full_path TEXT,
            sort_order INTEGER,
            raw_markdown TEXT,
            needs_review INTEGER
        );
        CREATE TABLE lecture_chunks (
            chunk_id TEXT PRIMARY KEY,
            lecture_knowledge_id TEXT,
            content_type TEXT,
            title TEXT,
            raw_markdown TEXT,
            formula_count INTEGER,
            image_count INTEGER,
            table_count INTEGER,
            needs_review INTEGER,
            sort_order INTEGER
        );
        CREATE TABLE lecture_formulas (
            formula_id TEXT PRIMARY KEY,
            lecture_knowledge_id TEXT,
            formula_name TEXT,
            formula_content TEXT,
            conditions TEXT,
            usage_scene TEXT,
            common_mistake TEXT,
            raw_markdown TEXT
        );
        CREATE TABLE lecture_mistakes (
            mistake_id TEXT PRIMARY KEY,
            lecture_knowledge_id TEXT,
            mistake_content TEXT,
            trigger_condition TEXT,
            correction_method TEXT,
            raw_markdown TEXT
        );
        CREATE TABLE lecture_review_cards (
            card_id TEXT PRIMARY KEY,
            lecture_knowledge_id TEXT,
            card_type TEXT,
            front_content TEXT,
            back_content TEXT,
            raw_markdown TEXT
        );
        CREATE TABLE lecture_knowledge_mappings (
            lecture_knowledge_id TEXT,
            knowledge_id TEXT,
            confidence REAL
        );
        CREATE TABLE worked_examples (id TEXT PRIMARY KEY);
        """
    )
    conn.execute(
        """
        INSERT INTO knowledge_points
        VALUES ('KP_LIMIT', 'math', 'calculus', 'Limits', 'Continuity', 'Limit Definition', NULL, 5, 1, 'Limit summary')
        """
    )
    conn.execute(
        """
        INSERT INTO questions
        VALUES ('Q_LIMIT_1', 'KP_LIMIT', 'choice', 3, 'Find the limit of sin x / x at 0', '1', 'Use standard limit.', 'mock', 'unit', 2026)
        """
    )
    conn.execute(
        """
        INSERT INTO lecture_knowledge_nodes
        VALUES ('LECTURE_ROOT', NULL, 'chapter', 1, 0, 'Calculus', 'Calculus', 1, '# Calculus', 0)
        """
    )
    conn.execute(
        """
        INSERT INTO lecture_knowledge_nodes
        VALUES ('LECTURE_LIMIT', 'LECTURE_ROOT', 'knowledge_point', 1, 1, 'Limit Definition', 'Calculus > Limits > Limit Definition', 2, '# Limit Definition', 0)
        """
    )
    conn.execute(
        """
        INSERT INTO lecture_chunks
        VALUES ('CHUNK_LIMIT', 'LECTURE_LIMIT', 'markdown', 'Limit intuition', 'Limit means approaching a stable value.', 0, 0, 0, 0, 1)
        """
    )
    conn.execute(
        """
        INSERT INTO lecture_formulas
        VALUES ('FORMULA_LIMIT', 'LECTURE_LIMIT', 'Standard limit', 'lim sin x / x = 1', 'x -> 0', 'limit problems', 'forget radians', 'Formula markdown')
        """
    )
    conn.execute(
        """
        INSERT INTO lecture_mistakes
        VALUES ('MISTAKE_LIMIT', 'LECTURE_LIMIT', 'Substituting too early', '0/0 form', 'transform first', 'Mistake markdown')
        """
    )
    conn.execute(
        """
        INSERT INTO lecture_review_cards
        VALUES ('CARD_LIMIT', 'LECTURE_LIMIT', 'qa', 'What is a limit?', 'Approaching value', 'Card markdown')
        """
    )
    conn.execute("INSERT INTO lecture_knowledge_mappings VALUES ('LECTURE_LIMIT', 'KP_LIMIT', 0.95)")
    conn.commit()
    conn.close()
    return db_path


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


def test_kaoyan_content_health_missing_db() -> None:
    missing = Path(tempfile.gettempdir()) / f"missing_{uuid.uuid4().hex}.sqlite"
    store = KaoyanContentStore(missing)

    health = store.health()

    assert health["status"] == "missing"
    assert health["db_exists"] is False
    assert "checked_at" in health


def test_knowledge_tree_and_detail_freeze_member_b_schema() -> None:
    db_path = _member_b_db()
    try:
        store = KaoyanContentStore(db_path)
        tree = store.knowledge_tree()
        assert tree
        root = tree[0]
        child = root["children"][0]

        assert child["knowledge_id"] == "LECTURE_LIMIT"
        assert child["id"] == "LECTURE_LIMIT"
        assert child["title"] == "Limit Definition"
        assert child["level"] >= 1
        assert "tags" in child
        assert child["source_refs"][0]["source_type"] == "content_db"

        detail = store.get_knowledge("LECTURE_LIMIT")
        assert detail is not None
        assert detail["id"] == "LECTURE_LIMIT"
        assert detail["knowledge"]["title"] == "Limit Definition"
        assert detail["summary"]
        assert detail["question_ids"] == ["Q_LIMIT_1"]
        assert detail["source_refs"]
        assert detail["examples"][0]["question_id"] == "Q_LIMIT_1"
    finally:
        db_path.unlink(missing_ok=True)


def test_material_parse_task_is_user_scoped_and_structures_sections() -> None:
    store = KaoyanContentStore()

    task = store.create_material_parse_task(
        "notes.md",
        "markdown",
        user_id="user-a",
        raw_text="# Limits\nLimit notes\n\n# Derivatives\nDerivative notes",
    )

    assert task["status"] == "completed"
    assert [item["title"] for item in task["extracted_sections"]] == ["Limits", "Derivatives"]
    assert store.get_material_parse_task(task["task_id"], user_id="user-b") is None
    assert store.get_material_parse_task(task["task_id"], user_id="user-a") is not None


def test_content_store_rag_query_returns_contexts_and_sources() -> None:
    db_path = _member_b_db()
    try:
        store = KaoyanContentStore(db_path)
        result = store.query_rag("limit", top_k=3)

        assert result["status"] == "success"
        assert result["contexts"]
        assert result["sources"]
        assert result["results"] == result["contexts"]
        assert "Limit" in result["answer"] or "limit" in result["answer"]
    finally:
        db_path.unlink(missing_ok=True)


def test_obsidian_export_preview_for_knowledge_and_payload_templates() -> None:
    db_path = _member_b_db()
    try:
        store = KaoyanContentStore(db_path)

        knowledge = store.render_obsidian_export("knowledge", "LECTURE_LIMIT")
        assert knowledge is not None
        assert knowledge["path"].endswith(".md")
        assert "kaoyan_knowledge" in knowledge["markdown"]
        assert "Limit Definition" in knowledge["markdown"]

        wrong = store.render_obsidian_export(
            "wrong_question",
            "Q_LIMIT_1",
            payload={"error_reason": "forgot standard limit", "knowledge_id": "KP_LIMIT"},
        )
        assert wrong is not None
        assert "Wrong Question Q_LIMIT_1" in wrong["markdown"]
        assert "forgot standard limit" in wrong["markdown"]
    finally:
        db_path.unlink(missing_ok=True)


def test_member_b_api_content_rag_materials_and_obsidian(monkeypatch) -> None:
    db_path = _member_b_db()
    store = KaoyanContentStore(db_path)
    monkeypatch.setattr(kaoyan_router, "get_content_store", lambda: store)

    app = FastAPI()
    app.dependency_overrides[kaoyan_router.require_current_user] = lambda: AuthUser(
        user_id="member-b-user", email="b@example.com", display_name="B", role="student"
    )
    app.include_router(kaoyan_router.router, prefix="/api/v1/kaoyan")
    client = TestClient(app)

    try:
        health = client.get("/api/v1/kaoyan/content/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"

        tree = client.get("/api/v1/kaoyan/content/knowledge-tree?subject=math")
        assert tree.status_code == 200
        assert tree.json()[0]["children"][0]["id"] == "LECTURE_LIMIT"

        detail = client.get("/api/v1/kaoyan/content/knowledge/LECTURE_LIMIT")
        assert detail.status_code == 200
        assert detail.json()["question_ids"] == ["Q_LIMIT_1"]

        task = client.post(
            "/api/v1/kaoyan/materials/parse",
            json={"filename": "notes.md", "content_type": "markdown", "raw_text": "# Limits\nNotes"},
        )
        assert task.status_code == 200
        task_body = task.json()
        assert task_body["user_id"] == "member-b-user"
        assert task_body["extracted_sections"]
        assert client.get(f"/api/v1/kaoyan/materials/tasks/{task_body['task_id']}").status_code == 200

        rag = client.post("/api/v1/kaoyan/rag/query", json={"query": "limit", "top_k": 2})
        assert rag.status_code == 200
        assert rag.json()["contexts"]
        assert rag.json()["sources"]

        export = client.post(
            "/api/v1/kaoyan/obsidian/export",
            json={"source_type": "knowledge", "source_id": "LECTURE_LIMIT"},
        )
        assert export.status_code == 200
        assert export.json()["path"].startswith("Kaoyan/Knowledge/")
        assert "markdown" in export.json()
    finally:
        db_path.unlink(missing_ok=True)


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
