"""Local authentication and current-user context for Master Prep AI."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Iterator
import uuid

from fastapi import HTTPException, Request, Response, WebSocket, status

COOKIE_NAME = "master_prep_ai_session"
SESSION_DAYS = 14
PBKDF2_ITERATIONS = 240_000
_current_user_id: ContextVar[str | None] = ContextVar("master_prep_ai_current_user_id", default=None)


@dataclass(slots=True)
class AuthUser:
    user_id: str
    email: str
    display_name: str
    role: str

    def to_dict(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
        }


def auth_db_path() -> Path:
    configured = os.getenv("MASTER_PREP_AI_AUTH_DB")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / "data" / "user" / "auth.sqlite"


def get_current_user_id(default: str | None = None) -> str | None:
    return _current_user_id.get() or default


@contextmanager
def current_user_context(user_id: str | None) -> Iterator[None]:
    token = _current_user_id.set(user_id)
    try:
        yield
    finally:
        _current_user_id.reset(token)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def _validate_email(email: str) -> None:
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="Invalid email address")


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, digest = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(candidate.hex(), digest)
    except Exception:
        return False


class AuthStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else auth_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_user (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL DEFAULT '',
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'student',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                );

                CREATE TABLE IF NOT EXISTS auth_session (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_auth_session_user ON auth_session(user_id, expires_at);
                """
            )
            conn.commit()

    def has_users(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM app_user LIMIT 1").fetchone()
        return row is not None

    def create_first_admin(self, email: str, password: str, display_name: str = "") -> AuthUser:
        email = _normalize_email(email)
        _validate_email(email)
        if len(password or "") < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        now = _utc_now()
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM app_user LIMIT 1").fetchone() is not None:
                raise HTTPException(status_code=409, detail="First admin already exists")
            user_id = f"user_{uuid.uuid4().hex}"
            conn.execute(
                """
                INSERT INTO app_user (user_id, email, display_name, password_hash, role, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'admin', ?, ?)
                """,
                (user_id, email, display_name.strip() or email.split("@")[0], _hash_password(password), now, now),
            )
            conn.commit()
        self.assign_legacy_data(user_id)
        return AuthUser(user_id=user_id, email=email, display_name=display_name.strip() or email.split("@")[0], role="admin")

    def authenticate(self, email: str, password: str) -> AuthUser | None:
        email = _normalize_email(email)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, email, display_name, role, password_hash FROM app_user WHERE email = ?",
                (email,),
            ).fetchone()
            if row is None or not _verify_password(password, row["password_hash"]):
                return None
            conn.execute("UPDATE app_user SET last_login_at = ?, updated_at = ? WHERE user_id = ?", (_utc_now(), _utc_now(), row["user_id"]))
            conn.commit()
        return AuthUser(user_id=row["user_id"], email=row["email"], display_name=row["display_name"], role=row["role"])

    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=SESSION_DAYS)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO auth_session (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (_hash_token(token), user_id, expires.isoformat(), now.isoformat()),
            )
            conn.commit()
        return token

    def revoke_session(self, token: str) -> None:
        if not token:
            return
        with self._connect() as conn:
            conn.execute("UPDATE auth_session SET revoked_at = ? WHERE token_hash = ?", (_utc_now(), _hash_token(token)))
            conn.commit()

    def user_for_token(self, token: str | None) -> AuthUser | None:
        if not token:
            return None
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.user_id, u.email, u.display_name, u.role
                FROM auth_session s
                INNER JOIN app_user u ON u.user_id = s.user_id
                WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ?
                """,
                (_hash_token(token), now),
            ).fetchone()
        if row is None:
            return None
        return AuthUser(user_id=row["user_id"], email=row["email"], display_name=row["display_name"], role=row["role"])

    def change_password(self, user_id: str, current_password: str, new_password: str) -> None:
        if len(new_password or "") < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        with self._connect() as conn:
            row = conn.execute("SELECT password_hash FROM app_user WHERE user_id = ?", (user_id,)).fetchone()
            if row is None or not _verify_password(current_password, row["password_hash"]):
                raise HTTPException(status_code=400, detail="Current password is incorrect")
            conn.execute(
                "UPDATE app_user SET password_hash = ?, updated_at = ? WHERE user_id = ?",
                (_hash_password(new_password), _utc_now(), user_id),
            )
            conn.commit()

    def assign_legacy_data(self, user_id: str) -> None:
        root = Path(__file__).resolve().parents[1]
        for db_path in [root / "data" / "user" / "chat_history.db", root / "data" / "user" / "kaoyan_learning.sqlite"]:
            if not db_path.exists():
                continue
            try:
                with sqlite3.connect(db_path) as conn:
                    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                    if "sessions" in tables:
                        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
                        if "user_id" in cols:
                            conn.execute("UPDATE sessions SET user_id = ? WHERE user_id = '' OR user_id = 'local-user' OR user_id IS NULL", (user_id,))
                    if "notebook_categories" in tables:
                        cols = {row[1] for row in conn.execute("PRAGMA table_info(notebook_categories)").fetchall()}
                        if "user_id" in cols:
                            conn.execute("UPDATE notebook_categories SET user_id = ? WHERE user_id = '' OR user_id = 'local-user' OR user_id IS NULL", (user_id,))
                    for table in ["user_profile", "study_plan", "plan_task", "plan_task_version", "practice_session", "answer_record", "practice_record", "wrong_question", "review_queue", "mastery_record", "ai_action_log", "diagnostic_report"]:
                        if table not in tables:
                            continue
                        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                        if "user_id" in cols:
                            conn.execute(f"UPDATE {table} SET user_id = ? WHERE user_id = '' OR user_id = 'local-user' OR user_id IS NULL", (user_id,))
                    conn.commit()
            except Exception:
                pass


def issue_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


@lru_cache(maxsize=None)
def _get_auth_store_for_path(db_path: str) -> AuthStore:
    return AuthStore(db_path)


def get_auth_store() -> AuthStore:
    return _get_auth_store_for_path(str(auth_db_path().resolve()))


def reset_auth_store_cache() -> None:
    _get_auth_store_for_path.cache_clear()


def user_from_request(request: Request) -> AuthUser | None:
    return get_auth_store().user_for_token(request.cookies.get(COOKIE_NAME))


def user_from_websocket(ws: WebSocket) -> AuthUser | None:
    return get_auth_store().user_for_token(ws.cookies.get(COOKIE_NAME))


async def require_websocket_user(ws: WebSocket) -> AuthUser | None:
    """Accept a WebSocket only into an authenticated current-user context."""
    user = user_from_websocket(ws)
    await ws.accept()
    if user is None:
        await ws.send_json({"type": "error", "content": "Authentication required"})
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    _current_user_id.set(user.user_id)
    return user


def require_current_user(request: Request) -> AuthUser:
    user = user_from_request(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user