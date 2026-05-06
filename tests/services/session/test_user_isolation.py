from __future__ import annotations

import asyncio
from pathlib import Path
import uuid

from deeptutor.auth import current_user_context
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def _runtime_db(name: str) -> Path:
    root = Path("tests") / "session_runtime"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{name}_{uuid.uuid4().hex}.sqlite"


def test_chat_sessions_are_filtered_by_current_user():
    store = SQLiteSessionStore(_runtime_db("chat"))

    with current_user_context("user-a"):
        session_a = asyncio.run(store.create_session(title="A"))
        asyncio.run(store.add_message(session_a["id"], "user", "hello from a"))

    with current_user_context("user-b"):
        session_b = asyncio.run(store.create_session(title="B"))
        asyncio.run(store.add_message(session_b["id"], "user", "hello from b"))
        assert asyncio.run(store.get_session(session_a["id"])) is None
        assert asyncio.run(store.get_messages(session_a["id"])) == []
        assert asyncio.run(store.delete_session(session_a["id"])) is False
        assert [item["id"] for item in asyncio.run(store.list_sessions())] == [session_b["id"]]

    with current_user_context("user-a"):
        assert asyncio.run(store.get_session(session_a["id"])) is not None
        assert asyncio.run(store.get_messages(session_a["id"]))[0]["content"] == "hello from a"
        assert [item["id"] for item in asyncio.run(store.list_sessions())] == [session_a["id"]]

def test_question_notebook_entries_and_categories_are_user_scoped():
    from deeptutor.services.session.turn_runtime import _build_question_bank_context

    store = SQLiteSessionStore(_runtime_db("question_bank"))

    with current_user_context("user-a"):
        session_a = asyncio.run(store.create_session(title="A notebook"))
        assert asyncio.run(
            store.upsert_notebook_entries(
                session_a["id"],
                [
                    {
                        "question_id": "q-1",
                        "question": "What is 2 + 2?",
                        "question_type": "single_choice",
                        "options": {"A": "3", "B": "4"},
                        "correct_answer": "B",
                        "explanation": "Basic arithmetic.",
                        "difficulty": "easy",
                        "bookmarked": True,
                    }
                ],
            )
        ) == 1
        entry_a = asyncio.run(store.find_notebook_entry(session_a["id"], "q-1"))
        assert entry_a is not None
        category_a = asyncio.run(store.create_category("Math"))
        assert asyncio.run(store.add_entry_to_category(entry_a["id"], category_a["id"])) is True
        assert asyncio.run(_build_question_bank_context(store, [entry_a["id"]]))

    with current_user_context("user-b"):
        session_b = asyncio.run(store.create_session(title="B notebook"))
        category_b = asyncio.run(store.create_category("Math"))

        listed = asyncio.run(store.list_notebook_entries())
        assert listed == {"items": [], "total": 0}
        assert asyncio.run(store.list_notebook_entries(category_id=category_a["id"])) == {"items": [], "total": 0}
        assert asyncio.run(store.get_notebook_entry(entry_a["id"])) is None
        assert asyncio.run(store.find_notebook_entry(session_a["id"], "q-1")) is None
        assert asyncio.run(store.update_notebook_entry(entry_a["id"], {"bookmarked": False})) is False
        assert asyncio.run(store.add_entry_to_category(entry_a["id"], category_b["id"])) is False
        assert asyncio.run(store.get_entry_categories(entry_a["id"])) == []
        assert asyncio.run(_build_question_bank_context(store, [entry_a["id"]])) == ""
        assert asyncio.run(store.delete_notebook_entry(entry_a["id"])) is False
        assert asyncio.run(store.list_categories())[0]["id"] == category_b["id"]

        assert asyncio.run(
            store.upsert_notebook_entries(
                session_b["id"],
                [{"question_id": "q-1", "question": "B's own question"}],
            )
        ) == 1

    with current_user_context("user-a"):
        assert asyncio.run(store.get_notebook_entry(entry_a["id"])) is not None
        assert asyncio.run(store.get_entry_categories(entry_a["id"])) == [
            {"id": category_a["id"], "name": "Math"}
        ]
        assert asyncio.run(store.delete_notebook_entry(entry_a["id"])) is True


def test_attachment_store_default_root_tracks_current_user(monkeypatch):
    from deeptutor.services.path_service import PathService
    from deeptutor.services.storage.attachment_store import LocalDiskAttachmentStore

    root = Path("tests") / "session_runtime" / f"attachments_{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    service = PathService.get_instance()
    old_project_root = service._project_root
    old_user_data_dir = service._user_data_dir
    monkeypatch.delenv("CHAT_ATTACHMENT_DIR", raising=False)
    service._project_root = root
    service._user_data_dir = (root / "data" / "user").resolve()
    store = LocalDiskAttachmentStore()
    try:
        with current_user_context("user-a"):
            url = asyncio.run(
                store.put(
                    session_id="session-1",
                    attachment_id="att-1",
                    filename="note.txt",
                    data=b"hello",
                )
            )
            assert url == "/api/attachments/session-1/att-1/note.txt"
            assert store.resolve_path(session_id="session-1", attachment_id="att-1", filename="note.txt").read_bytes() == b"hello"
            assert "user-a" in str(store.root)

        with current_user_context("user-b"):
            assert "user-b" in str(store.root)
            assert store.resolve_path(session_id="session-1", attachment_id="att-1", filename="note.txt") is None
    finally:
        service._project_root = old_project_root
        service._user_data_dir = old_user_data_dir

def test_legacy_notebook_categories_migrate_to_user_owned_schema():
    import sqlite3

    db_path = _runtime_db("legacy_categories")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL DEFAULT 'local-user', title TEXT NOT NULL DEFAULT 'New conversation', created_at REAL NOT NULL, updated_at REAL NOT NULL, compressed_summary TEXT DEFAULT '', summary_up_to_msg_id INTEGER DEFAULT 0, preferences_json TEXT DEFAULT '{}');
            CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', capability TEXT DEFAULT '', events_json TEXT DEFAULT '', attachments_json TEXT DEFAULT '', created_at REAL NOT NULL);
            CREATE TABLE turns (id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, capability TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'running', error TEXT DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL, finished_at REAL);
            CREATE TABLE turn_events (id INTEGER PRIMARY KEY AUTOINCREMENT, turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE, seq INTEGER NOT NULL, type TEXT NOT NULL, timestamp REAL NOT NULL, created_at REAL NOT NULL, UNIQUE(turn_id, seq));
            CREATE TABLE notebook_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, question_id TEXT NOT NULL, question TEXT NOT NULL, question_type TEXT DEFAULT '', options_json TEXT DEFAULT '{}', correct_answer TEXT DEFAULT '', explanation TEXT DEFAULT '', difficulty TEXT DEFAULT '', user_answer TEXT DEFAULT '', is_correct INTEGER DEFAULT 0, bookmarked INTEGER DEFAULT 0, followup_session_id TEXT DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL, UNIQUE(session_id, question_id));
            CREATE TABLE notebook_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, created_at REAL NOT NULL);
            CREATE TABLE notebook_entry_categories (entry_id INTEGER NOT NULL REFERENCES notebook_entries(id) ON DELETE CASCADE, category_id INTEGER NOT NULL REFERENCES notebook_categories(id) ON DELETE CASCADE, PRIMARY KEY (entry_id, category_id));
            INSERT INTO sessions (id, user_id, title, created_at, updated_at) VALUES ('s1', 'local-user', 's', 1, 1);
            INSERT INTO notebook_entries (id, session_id, question_id, question, created_at, updated_at) VALUES (1, 's1', 'q1', 'q', 1, 1);
            INSERT INTO notebook_categories (id, name, created_at) VALUES (1, 'Math', 1);
            INSERT INTO notebook_entry_categories (entry_id, category_id) VALUES (1, 1);
            """
        )

    SQLiteSessionStore(db_path)
    with sqlite3.connect(db_path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(notebook_categories)")]
        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        refs = conn.execute("PRAGMA foreign_key_list(notebook_entry_categories)").fetchall()
        owner = conn.execute("SELECT user_id FROM notebook_categories WHERE id = 1").fetchone()[0]

    assert "user_id" in columns
    assert owner == "local-user"
    assert foreign_key_errors == []
    assert any(row[2] == "notebook_categories" for row in refs)

def test_session_summary_and_preferences_writes_are_user_scoped():
    store = SQLiteSessionStore(_runtime_db("session_owner_writes"))

    with current_user_context("user-a"):
        session_a = asyncio.run(store.create_session(title="A"))
        assert asyncio.run(store.update_summary(session_a["id"], "summary-a", 1)) is True
        assert asyncio.run(
            store.update_session_preferences(session_a["id"], {"language": "zh"})
        ) is True

    with current_user_context("user-b"):
        assert asyncio.run(store.update_summary(session_a["id"], "summary-b", 2)) is False
        assert asyncio.run(
            store.update_session_preferences(session_a["id"], {"language": "en"})
        ) is False
        assert asyncio.run(store.get_session(session_a["id"])) is None

    with current_user_context("user-a"):
        session = asyncio.run(store.get_session(session_a["id"]))
        assert session is not None
        assert session["compressed_summary"] == "summary-a"
        assert session["summary_up_to_msg_id"] == 1
        assert session["preferences"]["language"] == "zh"