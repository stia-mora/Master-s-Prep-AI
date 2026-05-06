from __future__ import annotations

from pathlib import Path
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import auth as auth_router
from deeptutor.auth import get_auth_store, reset_auth_store_cache


def _client(monkeypatch):
    root = Path("tests") / "auth_runtime"
    root.mkdir(parents=True, exist_ok=True)
    reset_auth_store_cache()
    monkeypatch.setenv("DEEPTUTOR_AUTH_DB", str(root / f"auth_{uuid.uuid4().hex}.sqlite"))
    reset_auth_store_cache()
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1/auth")
    return TestClient(app)


def test_first_admin_registers_once_and_login_cookie_roundtrip(monkeypatch):
    client = _client(monkeypatch)

    assert client.get("/api/v1/auth/bootstrap").json() == {"has_users": False}

    created = client.post(
        "/api/v1/auth/register-first-admin",
        json={"email": "Admin@Example.com", "password": "password123", "display_name": "Admin"},
    )
    assert created.status_code == 200
    assert created.json()["user"]["role"] == "admin"
    assert client.cookies.get("deeptutor_session")
    assert client.get("/api/v1/auth/bootstrap").json() == {"has_users": True}

    duplicate = client.post(
        "/api/v1/auth/register-first-admin",
        json={"email": "second@example.com", "password": "password123", "display_name": "Second"},
    )
    assert duplicate.status_code == 409

    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401

    bad_login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "wrongpass", "display_name": ""},
    )
    assert bad_login.status_code == 401

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password123", "display_name": ""},
    )
    assert login.status_code == 200
    assert client.get("/api/v1/auth/me").json()["user"]["email"] == "admin@example.com"


def test_auth_store_cache_is_keyed_by_db_path(monkeypatch):
    root = Path("tests") / "auth_runtime"
    root.mkdir(parents=True, exist_ok=True)

    first_db = root / f"auth_cache_{uuid.uuid4().hex}.sqlite"
    second_db = root / f"auth_cache_{uuid.uuid4().hex}.sqlite"

    reset_auth_store_cache()
    monkeypatch.setenv("DEEPTUTOR_AUTH_DB", str(first_db))
    first = get_auth_store()
    assert get_auth_store() is first

    monkeypatch.setenv("DEEPTUTOR_AUTH_DB", str(second_db))
    second = get_auth_store()
    assert second is not first

    reset_auth_store_cache()
    assert get_auth_store() is not second