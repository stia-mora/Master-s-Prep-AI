from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import uuid

from fastapi.testclient import TestClient

from master_prep_ai.api import main as api_main
from master_prep_ai.auth import COOKIE_NAME, get_auth_store, reset_auth_store_cache


def _runtime_root() -> Path:
    root = Path("tests") / "outputs_runtime" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _set_runtime_roots(monkeypatch, root: Path) -> None:
    service = api_main.path_service
    monkeypatch.setattr(service, "_project_root", root)
    monkeypatch.setattr(service, "_user_data_dir", (root / "data" / "user").resolve())


def _create_logged_in_client(monkeypatch, root: Path):
    auth_db = root / f"auth_{uuid.uuid4().hex}.sqlite"
    reset_auth_store_cache()
    monkeypatch.setenv("MASTER_PREP_AI_AUTH_DB", str(auth_db))
    reset_auth_store_cache()
    store = get_auth_store()
    user = store.create_first_admin("owner@example.com", "password123", "Owner")
    token = store.create_session(user.user_id)
    client = TestClient(api_main.app)
    client.cookies.set(COOKIE_NAME, token)
    return client, user, store


def test_public_outputs_are_served_from_current_user_root(monkeypatch):
    root = _runtime_root()
    try:
        _set_runtime_roots(monkeypatch, root)
        client, user, _store = _create_logged_in_client(monkeypatch, root)

        artifact = (
            root
            / "data"
            / "users"
            / user.user_id
            / "workspace"
            / "chat"
            / "deep_solve"
            / "turn_1"
            / "artifacts"
            / "plot.png"
        )
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"png")

        response = client.get("/api/outputs/workspace/chat/deep_solve/turn_1/artifacts/plot.png")
        assert response.status_code == 200
        assert response.content == b"png"
        assert response.headers["cache-control"] == "private, max-age=0, must-revalidate"
    finally:
        reset_auth_store_cache()
        shutil.rmtree(root, ignore_errors=True)


def test_public_outputs_reject_private_files_other_users_and_anonymous(monkeypatch):
    root = _runtime_root()
    try:
        _set_runtime_roots(monkeypatch, root)
        client, user, store = _create_logged_in_client(monkeypatch, root)

        private_file = (
            root
            / "data"
            / "users"
            / user.user_id
            / "workspace"
            / "chat"
            / "deep_solve"
            / "turn_1"
            / "artifacts"
            / "trace.json"
        )
        private_file.parent.mkdir(parents=True, exist_ok=True)
        private_file.write_text("{}", encoding="utf-8")
        assert client.get("/api/outputs/workspace/chat/deep_solve/turn_1/artifacts/trace.json").status_code == 404

        user_b = f"user_{uuid.uuid4().hex}"
        now = "2026-01-01T00:00:00+00:00"
        with sqlite3.connect(store.db_path) as conn:
            conn.execute(
                """
                INSERT INTO app_user (user_id, email, display_name, password_hash, role, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'student', ?, ?)
                """,
                (user_b, "other@example.com", "Other", "unused", now, now),
            )
            conn.commit()
        token_b = store.create_session(user_b)
        client_b = TestClient(api_main.app)
        client_b.cookies.set(COOKIE_NAME, token_b)
        assert client_b.get("/api/outputs/workspace/chat/deep_solve/turn_1/artifacts/plot.png").status_code == 404

        assert TestClient(api_main.app).get(
            "/api/outputs/workspace/chat/deep_solve/turn_1/artifacts/plot.png"
        ).status_code == 401
    finally:
        reset_auth_store_cache()
        shutil.rmtree(root, ignore_errors=True)
