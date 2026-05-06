#!/usr/bin/env python
"""
Knowledge Base Manager

Manages multiple knowledge bases and provides utilities for accessing them.
"""

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from typing import Any

from deeptutor.logging import get_logger
from deeptutor.services.rag.factory import DEFAULT_PROVIDER
from deeptutor.services.rag.file_routing import FileTypeRouter

logger = get_logger("KnowledgeBaseManager")

SCOPED_METADATA_FIELDS = (
    "display_name",
    "short_name",
    "source_label",
    "source_summary",
    "source_type",
    "source_id",
    "debug_name",
)


def _read_kb_metadata_file(kb_dir: Path) -> dict[str, Any]:
    metadata_file = kb_dir / "metadata.json"
    if not metadata_file.exists():
        return {}
    try:
        with open(metadata_file, encoding="utf-8") as f:
            metadata = json.load(f)
        return metadata if isinstance(metadata, dict) else {}
    except Exception as exc:
        logger.warning(f"Failed to read metadata.json for '{kb_dir.name}': {exc}")
        return {}


def _merge_scoped_metadata(target: dict[str, Any], metadata: dict[str, Any]) -> bool:
    changed = False
    for key in SCOPED_METADATA_FIELDS:
        value = metadata.get(key)
        if value is not None and target.get(key) != value:
            target[key] = value
            changed = True
    return changed


def _clean_display_fragment(value: Any, limit: int = 24) -> str:
    text = str(value or "")
    text = re.sub(r"#references\s*\"citation\"", " ", text)
    text = re.sub(r"\$+", " ", text)
    text = re.sub(r"\\(?:left|right|frac|sqrt|lim|sum|int|to|infty|cdots|operatorname|begin|end|mathrm|text)\b", " ", text)
    text = re.sub(r"[{}\[\]`*_>#|]", " ", text)
    text = re.sub(r"(?:^|\s)[\(\uFF08]?[A-D][\)\uFF09][\s\u3001.\uFF0E:\uFF1A]*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:^|\s)\d+[.\u3001\)\uFF09]\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:\uFF0C\u3002\uFF1B\uFF1A\u3001")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


_GENERIC_KAOYAN_LABELS = {
    "\u8003\u7814\u6570\u5b66",
    "\u6570\u5b66",
    "\u9ad8\u7b49\u6570\u5b66",
    "\u9ad8\u6570",
    "\u8003\u7814\u6570\u5b66\u9898",
    "\u9ad8\u6570\u77e5\u8bc6\u70b9",
}


def _is_generic_kaoyan_display(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    normalized = re.sub(r"\s+", "", text)
    normalized = re.sub(r"^(?:\u9898\u76ee\u89e3\u6790|\u77e5\u8bc6\u70b9\u89e3\u6790|\u9898\u76ee|\u77e5\u8bc6\u70b9)\uff5c?", "", normalized)
    return normalized in _GENERIC_KAOYAN_LABELS


def _infer_kaoyan_scoped_metadata(kb_name: str, kb_dir: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    if not kb_name.startswith("kaoyan_") or not _is_generic_kaoyan_display(metadata.get("display_name")):
        return {}
    source_type = str(metadata.get("source_type") or "")
    if not source_type:
        if "question" in kb_name:
            source_type = "question"
        elif "knowledge" in kb_name:
            source_type = "knowledge"
    if source_type not in {"knowledge", "question"}:
        return {}
    raw_text = ""
    raw_dir = kb_dir / "raw"
    if raw_dir.exists():
        for file_path in raw_dir.glob("*.md"):
            try:
                raw_text = file_path.read_text(encoding="utf-8")[:20000]
                break
            except Exception:
                continue
    source_id_match = re.search(r"source_id:\s*([^\n]+)", raw_text, flags=re.IGNORECASE)
    source_id = metadata.get("source_id") or (source_id_match.group(1).strip() if source_id_match else None)
    knowledge_match = re.search(r'"knowledge_name"\s*:\s*"([^"]+)"', raw_text)
    if not knowledge_match:
        knowledge_match = re.search(r"\*\*knowledge name\*\*:\s*([^\n]+)", raw_text, flags=re.IGNORECASE)
    knowledge_name = _clean_display_fragment(knowledge_match.group(1) if knowledge_match else "", 24) or "\u9ad8\u6570\u77e5\u8bc6\u70b9"
    if source_type == "question":
        stem_match = re.search(r"stem:\s*\n(.+?)(?:\n\n|options:|standard answer:)", raw_text, flags=re.S | re.I)
        stem = stem_match.group(1) if stem_match else metadata.get("source_id") or kb_name
        summary = _clean_display_fragment(stem, 24) or "\u8003\u7814\u6570\u5b66\u9898"
        return {
            "display_name": f"\u9898\u76ee\uff5c{knowledge_name}\uff5c{summary}",
            "short_name": summary,
            "source_label": "\u9898\u76ee\u89e3\u6790",
            "source_summary": summary,
            "source_type": source_type,
            "source_id": source_id,
            "debug_name": kb_name,
        }
    return {
        "display_name": f"\u77e5\u8bc6\u70b9\uff5c{knowledge_name}",
        "short_name": knowledge_name,
        "source_label": "\u77e5\u8bc6\u70b9\u89e3\u6790",
        "source_summary": knowledge_name,
        "source_type": source_type,
        "source_id": metadata.get("source_id"),
        "debug_name": kb_name,
    }

# Cross-platform file locking
@contextmanager
def file_lock_shared(file_handle):
    """Acquire a shared (read) lock on a file - cross-platform."""
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(file_handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            file_handle.seek(0)
            msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(file_handle.fileno(), fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def file_lock_exclusive(file_handle):
    """Acquire an exclusive (write) lock on a file - cross-platform."""
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(file_handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            file_handle.seek(0)
            msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)


def _get_embedding_fingerprint() -> tuple[str, int] | None:
    """Return ``(model_name, dimension)`` of the active embedding config."""
    try:
        from deeptutor.services.embedding import get_embedding_config

        cfg = get_embedding_config()
        return (cfg.model, cfg.dim)
    except Exception:
        return None


def _reconcile_embedding_flags(knowledge_bases: dict, base_dir: Path | None = None) -> bool:
    """Reconcile per-KB embedding flags against the on-disk index versions.

    For each KB we check the flat ``version-N`` directories (plus legacy
    layouts) for a version matching the active embedding signature:

    * Match found → clear ``needs_reindex`` and ``embedding_mismatch`` (the
      user has switched back to a previously-indexed configuration).
    * No match, but the KB has a stored ``embedding_model`` that differs
      from the active fingerprint → set both flags so the UI surfaces a
      "Re-index" CTA.

    Returns ``True`` when any entry changed.
    """
    from deeptutor.services.rag.embedding_signature import signature_from_embedding_config
    from deeptutor.services.rag.index_versioning import (
        find_matching_version,
        list_kb_versions,
    )

    fp = _get_embedding_fingerprint()
    signature = signature_from_embedding_config()
    changed = False

    if signature is None and not fp:
        return False

    for kb_name, kb_entry in knowledge_bases.items():
        if not isinstance(kb_entry, dict):
            continue

        kb_dir = (base_dir / kb_name) if base_dir is not None else None
        matched = False
        if kb_dir is not None and signature is not None:
            matched = find_matching_version(kb_dir, signature) is not None

        if matched:
            mutated_local = False
            if kb_entry.get("needs_reindex"):
                kb_entry["needs_reindex"] = False
                mutated_local = True
            if kb_entry.get("embedding_mismatch"):
                kb_entry.pop("embedding_mismatch", None)
                mutated_local = True
            if mutated_local:
                changed = True
            # Refresh the surfaced version list either way so the UI sees
            # accurate state.
            if kb_dir is not None:
                kb_entry["index_versions"] = list_kb_versions(kb_dir)
            continue

        # No matching ready index version on disk.
        stored_model = kb_entry.get("embedding_model")
        # Empty/in-progress version dirs are created before indexing finishes.
        # They should not mark a brand-new KB as needing re-index.
        versions: list[dict] = []
        has_ready_version = False
        if kb_dir is not None:
            versions = list_kb_versions(kb_dir)
            has_ready_version = any(bool(version.get("ready")) for version in versions)
            kb_entry["index_versions"] = versions

        if not has_ready_version and not stored_model:
            continue

        current_model = fp[0] if fp else ""
        current_dim = fp[1] if fp else 0
        stored_dim = kb_entry.get("embedding_dim")
        mismatch = (stored_model and stored_model != current_model) or (
            stored_dim is not None and current_dim and stored_dim != current_dim
        )
        # If ready versions exist but none match active signature, that's also a mismatch.
        if has_ready_version:
            mismatch = True

        if mismatch and not kb_entry.get("embedding_mismatch"):
            kb_entry["embedding_mismatch"] = True
            if not kb_entry.get("needs_reindex"):
                kb_entry["needs_reindex"] = True
            changed = True
        elif not mismatch and kb_entry.get("embedding_mismatch"):
            kb_entry.pop("embedding_mismatch", None)
            changed = True

    return changed


class KnowledgeBaseManager:
    """Manager for knowledge bases"""

    def __init__(self, base_dir="./data/knowledge_bases"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Config file to track knowledge bases
        self.config_file = self.base_dir / "kb_config.json"
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Load knowledge base configuration from the canonical kb_config.json file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, encoding="utf-8") as f:
                    with file_lock_shared(f):
                        content = f.read()
                        if not content.strip():
                            # Empty file, return default
                            return {"knowledge_bases": {}}
                        config = json.loads(content)

                # Ensure knowledge_bases key exists
                if "knowledge_bases" not in config:
                    config["knowledge_bases"] = {}

                # Migration: remove old "default" field if present
                if "default" in config:
                    del config["default"]
                    # Note: Don't save during load to avoid recursion issues
                    # The next _save_config() call will persist this change

                # Migration: normalize legacy providers to llamaindex and
                # mark legacy index-only KBs as needs_reindex.
                from deeptutor.services.rag.index_versioning import list_kb_versions

                knowledge_bases = config.get("knowledge_bases", {})
                config_changed = False
                for kb_name, kb_entry in knowledge_bases.items():
                    if not isinstance(kb_entry, dict):
                        continue

                    raw_provider = kb_entry.get("rag_provider")
                    if kb_entry.get("rag_provider") != DEFAULT_PROVIDER:
                        kb_entry["rag_provider"] = DEFAULT_PROVIDER
                        config_changed = True

                    if isinstance(raw_provider, str) and raw_provider.strip().lower() not in {
                        "",
                        DEFAULT_PROVIDER,
                    }:
                        if not kb_entry.get("needs_reindex", False):
                            kb_entry["needs_reindex"] = True
                            config_changed = True

                    kb_dir = self.base_dir / kb_name
                    file_metadata = _read_kb_metadata_file(kb_dir)
                    inferred_metadata = _infer_kaoyan_scoped_metadata(kb_name, kb_dir, {**file_metadata, **kb_entry})
                    if _merge_scoped_metadata(kb_entry, file_metadata):
                        config_changed = True
                    if _merge_scoped_metadata(kb_entry, inferred_metadata):
                        config_changed = True
                    legacy_storage = kb_dir / "rag_storage"
                    has_llamaindex_index = any(
                        bool(version.get("ready")) for version in list_kb_versions(kb_dir)
                    )
                    if (
                        legacy_storage.exists()
                        and legacy_storage.is_dir()
                        and not has_llamaindex_index
                    ):
                        if not kb_entry.get("needs_reindex", False):
                            kb_entry["needs_reindex"] = True
                            config_changed = True

                if _reconcile_embedding_flags(knowledge_bases, self.base_dir):
                    config_changed = True

                if config_changed:
                    try:
                        with open(self.config_file, "w", encoding="utf-8") as f:
                            with file_lock_exclusive(f):
                                json.dump(config, f, indent=2, ensure_ascii=False)
                                f.flush()
                                os.fsync(f.fileno())
                    except Exception as save_err:
                        logger.warning(f"Failed to persist normalized KB config: {save_err}")

                return config
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Error loading config: {e}")
                return {"knowledge_bases": {}}
        return {"knowledge_bases": {}}

    def _save_config(self):
        """Save knowledge base configuration (thread-safe with file locking)"""
        # Use exclusive lock for writing
        with open(self.config_file, "w", encoding="utf-8") as f:
            with file_lock_exclusive(f):
                json.dump(self.config, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is written to disk

    def update_kb_status(
        self,
        name: str,
        status: str,
        progress: dict | None = None,
    ):
        """
        Update knowledge base status and progress in kb_config.json.

        Args:
            name: Knowledge base name
            status: Status string ("initializing", "processing", "ready", "error")
            progress: Optional progress dict with keys like:
                - stage: Current stage name
                - message: Human-readable message
                - percent: Progress percentage (0-100)
                - current: Current item number
                - total: Total items
                - file_name: Current file being processed
                - error: Error message (if status is "error")
        """
        # Reload config to get latest state
        self.config = self._load_config()

        if "knowledge_bases" not in self.config:
            self.config["knowledge_bases"] = {}

        if name not in self.config["knowledge_bases"]:
            # Auto-register if not exists
            self.config["knowledge_bases"][name] = {
                "path": name,
                "description": f"Knowledge base: {name}",
            }

        kb_config = self.config["knowledge_bases"][name]
        kb_config["status"] = status
        kb_config["updated_at"] = datetime.now().isoformat()

        if status == "ready":
            # Ready KBs should look like stable resources in the UI instead of
            # permanently carrying a "completed" progress banner.
            kb_config.pop("progress", None)
            if progress is not None:
                kb_config["last_completed_at"] = progress.get("timestamp") or datetime.now().isoformat()
        elif progress is not None:
            kb_config["progress"] = progress

        if status == "ready":
            fp = _get_embedding_fingerprint()
            if fp:
                kb_config["embedding_model"], kb_config["embedding_dim"] = fp
            # Record the active signature + the on-disk version registry so
            # the UI can render version chips without recomputing.
            try:
                from deeptutor.services.rag.embedding_signature import (
                    signature_from_embedding_config,
                )
                from deeptutor.services.rag.index_versioning import (
                    list_kb_versions,
                )

                sig = signature_from_embedding_config()
                if sig is not None:
                    kb_config["embedding_signature"] = sig.hash()
                kb_dir = self.base_dir / name
                if kb_dir.is_dir():
                    kb_config["index_versions"] = list_kb_versions(kb_dir)
            except Exception:  # pragma: no cover - best-effort metadata
                pass

        self._save_config()

    def get_kb_status(self, name: str) -> dict | None:
        """Get status and progress for a knowledge base."""
        self.config = self._load_config()
        kb_config = self.config.get("knowledge_bases", {}).get(name)
        if not kb_config:
            return None
        return {
            "status": kb_config.get("status", "unknown"),
            "progress": kb_config.get("progress"),
            "updated_at": kb_config.get("updated_at"),
        }

    def list_knowledge_bases(self) -> list[str]:
        """List all available knowledge bases.

        This method:
        1. Loads registered KBs from kb_config.json
        2. Scans the directory for existing KBs not yet registered
        3. Auto-registers discovered KBs with valid raw/index structure
        """
        # Always reload config from file to ensure we have the latest data
        self.config = self._load_config()

        # Read knowledge base list from config file
        config_kbs = self.config.get("knowledge_bases", {})
        kb_list = set(config_kbs.keys())

        # Also scan directory for KBs that may not be registered yet
        # This ensures backward compatibility and auto-discovery
        if self.base_dir.exists():
            config_changed = False
            for item in self.base_dir.iterdir():
                if not item.is_dir() or item.name.startswith(("__", ".")):
                    continue

                # Skip if already in config
                if item.name in kb_list:
                    continue

                # Check if this is a valid KB directory (flat versions or legacy stores)
                from deeptutor.services.rag.index_versioning import list_kb_versions

                rag_storage = item / "rag_storage"
                is_valid_kb = (
                    any(bool(version.get("ready")) for version in list_kb_versions(item))
                    or (rag_storage.exists() and rag_storage.is_dir())
                )

                if is_valid_kb:
                    # Auto-register this KB to kb_config.json
                    kb_list.add(item.name)
                    self._auto_register_kb(item.name)
                    config_changed = True

            # Save config if we registered new KBs
            if config_changed:
                self._save_config()

        return sorted(kb_list)

    def _auto_register_kb(self, name: str):
        """Auto-register an existing KB to kb_config.json.

        Reads info from metadata.json (if exists) for backward compatibility.
        """
        kb_dir = self.base_dir / name

        # Default values
        kb_entry: dict[str, Any] = {
            "path": name,
            "description": f"Knowledge base: {name}",
            "status": "ready",  # Existing KB with storage is considered ready
            "updated_at": datetime.now().isoformat(),
        }

        # Try to read metadata.json for existing info (backward compatibility)
        metadata = _read_kb_metadata_file(kb_dir)
        if metadata:
            if metadata.get("description"):
                kb_entry["description"] = metadata["description"]
            if metadata.get("rag_provider"):
                raw_provider = str(metadata["rag_provider"]).strip().lower()
                kb_entry["rag_provider"] = DEFAULT_PROVIDER
                if raw_provider not in {"", DEFAULT_PROVIDER}:
                    kb_entry["needs_reindex"] = True
            if metadata.get("created_at"):
                kb_entry["created_at"] = metadata["created_at"]
            if metadata.get("last_updated"):
                kb_entry["updated_at"] = metadata["last_updated"]
            _merge_scoped_metadata(kb_entry, metadata)

        # Detect rag_provider from storage type if not set
        if "rag_provider" not in kb_entry:
            from deeptutor.services.rag.index_versioning import list_kb_versions

            rag_storage = kb_dir / "rag_storage"
            if any(bool(version.get("ready")) for version in list_kb_versions(kb_dir)):
                kb_entry["rag_provider"] = DEFAULT_PROVIDER
            elif rag_storage.exists():
                kb_entry["rag_provider"] = DEFAULT_PROVIDER
                kb_entry["needs_reindex"] = True

        # Add to config
        if "knowledge_bases" not in self.config:
            self.config["knowledge_bases"] = {}
        self.config["knowledge_bases"][name] = kb_entry

        logger.info(f"Auto-registered KB '{name}' to kb_config.json")

    def register_knowledge_base(self, name: str, description: str = "", set_default: bool = False):
        """Register a knowledge base"""
        kb_dir = self.base_dir / name
        if not kb_dir.exists():
            raise ValueError(f"Knowledge base directory does not exist: {kb_dir}")

        if "knowledge_bases" not in self.config:
            self.config["knowledge_bases"] = {}

        self.config["knowledge_bases"][name] = {"path": name, "description": description}

        # Only set default if explicitly requested
        if set_default:
            self.set_default(name)

        self._save_config()

    def get_knowledge_base_path(self, name: str | None = None) -> Path:
        """Get path to a knowledge base"""
        if name is None:
            name = self.config.get("default")
            if name is None:
                raise ValueError("No default knowledge base set")

        kb_dir = self.base_dir / name
        if not kb_dir.exists():
            raise ValueError(f"Knowledge base not found: {name}")

        return kb_dir

    def get_rag_storage_path(self, name: str | None = None) -> Path:
        """Get active index storage path for a knowledge base."""
        kb_dir = self.get_knowledge_base_path(name)
        from deeptutor.services.rag.embedding_signature import signature_from_embedding_config
        from deeptutor.services.rag.index_versioning import (
            resolve_storage_dir_for_read,
        )

        active_storage = resolve_storage_dir_for_read(kb_dir, signature_from_embedding_config())
        legacy_storage = kb_dir / "rag_storage"
        if active_storage is not None:
            return active_storage
        if legacy_storage.exists():
            return legacy_storage
        raise ValueError(f"Index storage not found for knowledge base: {name or 'default'}")

    def get_images_path(self, name: str | None = None) -> Path:
        """Get images path for a knowledge base"""
        kb_dir = self.get_knowledge_base_path(name)
        return kb_dir / "images"

    def get_content_list_path(self, name: str | None = None) -> Path:
        """Get content list path for a knowledge base"""
        kb_dir = self.get_knowledge_base_path(name)
        return kb_dir / "content_list"

    def get_raw_path(self, name: str | None = None) -> Path:
        """Get raw documents path for a knowledge base"""
        kb_dir = self.get_knowledge_base_path(name)
        return kb_dir / "raw"

    def set_default(self, name: str):
        """Set default knowledge base using centralized config service."""
        if name not in self.list_knowledge_bases():
            raise ValueError(f"Knowledge base not found: {name}")

        # Persist default KB selection via the canonical KB config service.
        try:
            from deeptutor.services.config import get_kb_config_service

            kb_config_service = get_kb_config_service()
            kb_config_service.set_default_kb(name)
        except Exception as e:
            logger.warning(f"Failed to save default to centralized config: {e}")

    def get_default(self) -> str | None:
        """
        Get default knowledge base name.

        Priority:
        1. Canonical KB config service (`data/knowledge_bases/kb_config.json`)
        2. First knowledge base in the list (auto-fallback)
        """
        # Try centralized config first
        try:
            from deeptutor.services.config import get_kb_config_service

            kb_config_service = get_kb_config_service()
            default_kb = kb_config_service.get_default_kb()
            if default_kb and default_kb in self.list_knowledge_bases():
                return default_kb
        except Exception:
            pass

        # Fallback to first knowledge base in sorted list
        kb_list = self.list_knowledge_bases()
        if kb_list:
            return kb_list[0]

        return None

    @staticmethod
    def _embedding_fields(kb_config: dict) -> dict:
        """Extract embedding fingerprint fields from a KB config entry."""
        fields = {}
        for key in ("embedding_model", "embedding_dim"):
            val = kb_config.get(key)
            if val is not None:
                fields[key] = val
        if kb_config.get("embedding_mismatch"):
            fields["embedding_mismatch"] = True
        return fields

    def get_metadata(self, name: str | None = None) -> dict:
        """Get knowledge base metadata.

        Source:
        1. kb_config.json (authoritative source)
        """
        kb_name = name
        if kb_name is None:
            kb_name = self.get_default()
            if kb_name is None:
                return {}

        # First, try kb_config.json (authoritative source)
        self.config = self._load_config()
        kb_config = self.config.get("knowledge_bases", {}).get(kb_name, {})

        if kb_config:
            # Build metadata from config
            metadata = {
                "name": kb_name,
                "description": kb_config.get("description", f"Knowledge base: {kb_name}"),
                "rag_provider": DEFAULT_PROVIDER,
                "needs_reindex": bool(kb_config.get("needs_reindex", False)),
                "created_at": kb_config.get("created_at"),
                "last_updated": kb_config.get("updated_at"),
            }
            _merge_scoped_metadata(metadata, kb_config)
            if kb_name:
                file_metadata = _read_kb_metadata_file(self.base_dir / kb_name)
                inferred_metadata = _infer_kaoyan_scoped_metadata(kb_name, self.base_dir / kb_name, {**file_metadata, **metadata})
                _merge_scoped_metadata(metadata, file_metadata)
                _merge_scoped_metadata(metadata, inferred_metadata)
            metadata.update(self._embedding_fields(kb_config))
            # Remove None values
            metadata = {k: v for k, v in metadata.items() if v is not None}
            return metadata

        return {}

    def get_info(self, name: str | None = None) -> dict:
        """Get detailed information about a knowledge base.

        This method:
        1. Gets the KB name (from parameter or default)
        2. Reads all config from kb_config.json (authoritative source)
        3. Falls back to metadata.json for legacy KBs
        4. Collects statistics about files and RAG status
        """
        # Reload config to get latest status
        self.config = self._load_config()

        kb_name = name or self.get_default()
        if kb_name is None:
            raise ValueError("No knowledge base name provided and no default set")

        # Get knowledge base path
        kb_dir = self.base_dir / kb_name

        # Get config from kb_config.json (authoritative source)
        kb_config = self.config.get("knowledge_bases", {}).get(kb_name, {})
        status = kb_config.get("status")
        progress = kb_config.get("progress")
        description = kb_config.get("description", f"Knowledge base: {kb_name}")
        rag_provider = DEFAULT_PROVIDER
        needs_reindex = bool(kb_config.get("needs_reindex", False))
        created_at = kb_config.get("created_at")
        updated_at = kb_config.get("updated_at")

        live_status = status in {"initializing", "processing"}
        if live_status and isinstance(progress, dict):
            live_status = progress.get("stage") not in {"completed", "error"}
        effective_needs_reindex = needs_reindex and not live_status

        # KB might not have a directory yet if still initializing
        dir_exists = kb_dir.exists()
        index_versions: list[dict[str, Any]] = []
        has_ready_llamaindex = False
        if dir_exists:
            from deeptutor.services.rag.index_versioning import list_kb_versions

            index_versions = list_kb_versions(kb_dir)
            has_ready_llamaindex = any(
                bool(version.get("ready")) for version in index_versions
            )

        # For old KBs without status field, determine status from rag_storage
        if effective_needs_reindex:
            status = "needs_reindex"
        elif not status and dir_exists:
            rag_storage_dir = kb_dir / "rag_storage"
            if has_ready_llamaindex:
                status = "ready"
            elif rag_storage_dir.exists() and any(rag_storage_dir.iterdir()):
                status = "needs_reindex"
                needs_reindex = True
                effective_needs_reindex = True
            else:
                status = "unknown"
        elif not status:
            status = "unknown"

        # Build metadata from kb_config.json (authoritative source)
        metadata = {
            "name": kb_name,
            "description": description,
            "rag_provider": rag_provider,
            "needs_reindex": effective_needs_reindex,
        }
        if created_at:
            metadata["created_at"] = created_at
        if updated_at:
            metadata["last_updated"] = updated_at

        _merge_scoped_metadata(metadata, kb_config)
        file_metadata = _read_kb_metadata_file(kb_dir)
        inferred_metadata = _infer_kaoyan_scoped_metadata(kb_name, kb_dir, {**file_metadata, **metadata})
        _merge_scoped_metadata(metadata, file_metadata)
        _merge_scoped_metadata(metadata, inferred_metadata)
        metadata.update(self._embedding_fields(kb_config))

        # Remove None values
        metadata = {k: v for k, v in metadata.items() if v is not None}

        info = {
            "name": kb_name,
            "path": str(kb_dir),
            "is_default": kb_name == self.get_default(),
            "metadata": metadata,
            "status": status,
            "progress": progress,
        }

        # Count files - handle errors gracefully
        raw_dir = kb_dir / "raw" if dir_exists else None
        images_dir = kb_dir / "images" if dir_exists else None
        content_list_dir = kb_dir / "content_list" if dir_exists else None

        raw_count = 0
        images_count = 0
        content_lists_count = 0

        if dir_exists:
            try:
                raw_count = len([f for f in raw_dir.iterdir() if f.is_file()]) if raw_dir else 0
            except Exception:
                pass

            try:
                images_count = (
                    len([f for f in images_dir.iterdir() if f.is_file()]) if images_dir else 0
                )
            except Exception:
                pass

            try:
                content_lists_count = (
                    len(list(content_list_dir.glob("*.json"))) if content_list_dir else 0
                )
            except Exception:
                pass

        # Check rag_initialized: flat versions OR legacy single-store/nested stores.
        from deeptutor.services.rag.embedding_signature import signature_from_embedding_config
        from deeptutor.services.rag.index_versioning import (
            find_matching_version,
        )

        kb_dir = self.base_dir / kb_name if dir_exists else None
        rag_initialized = has_ready_llamaindex

        active_signature = signature_from_embedding_config()
        active_match = (
            find_matching_version(kb_dir, active_signature) is not None
            if (kb_dir and active_signature)
            else False
        )

        info["statistics"] = {
            "raw_documents": raw_count,
            "images": images_count,
            "content_lists": content_lists_count,
            "rag_initialized": rag_initialized,
            "rag_provider": rag_provider,
            "needs_reindex": effective_needs_reindex,
            "index_versions": index_versions,
            "active_signature": active_signature.hash() if active_signature else None,
            "active_match": active_match,
            # Include status and progress in statistics for backward compatibility
            "status": status,
            "progress": progress,
        }

        return info

    def delete_knowledge_base(self, name: str, confirm: bool = False) -> bool:
        """
        Delete a knowledge base

        Args:
            name: Knowledge base name
            confirm: If True, skip confirmation (use with caution!)

        Returns:
            True if deleted successfully
        """
        if name not in self.list_knowledge_bases():
            raise ValueError(f"Knowledge base not found: {name}")

        # Resolve the directory directly to stay idempotent: if the on-disk
        # folder was already removed (e.g. manually rm-rf'd) we still want to
        # purge the orphaned entry from kb_config.json instead of failing.
        kb_dir = self.base_dir / name
        dir_exists = kb_dir.exists()

        if not confirm:
            # Ask for confirmation in CLI
            print(f"⚠️  Warning: This will permanently delete the knowledge base '{name}'")
            print(f"   Path: {kb_dir}")
            response = input("Are you sure? Type 'yes' to confirm: ")
            if response.lower() != "yes":
                print("Deletion cancelled.")
                return False

        if dir_exists:

            def _on_rmtree_error(func, path, exc_info):
                exc = exc_info[1]
                if isinstance(exc, FileNotFoundError):
                    # Race: something else removed the entry between walk and unlink.
                    return
                # On Windows (and some bind-mounted filesystems) a read-only bit
                # or a stale handle from a failed RAG init can block removal.
                # Clear the read-only bit and retry once; if it still fails, log
                # and continue so the config entry gets cleaned up regardless —
                # leaving the KB stuck in the list is worse than orphan files on
                # disk (issue #370).
                try:
                    os.chmod(path, stat.S_IWRITE)
                    func(path)
                except Exception as retry_exc:
                    logger.warning(
                        f"Could not remove '{path}' while deleting KB '{name}': "
                        f"{retry_exc}. Continuing; orphan files may remain on disk."
                    )

            shutil.rmtree(kb_dir, onerror=_on_rmtree_error)
        else:
            logger.warning(
                f"KB directory '{kb_dir}' missing on disk; cleaning up orphaned config entry."
            )

        # Remove from config
        if name in self.config.get("knowledge_bases", {}):
            del self.config["knowledge_bases"][name]

        # Update default if this was the default
        if self.config.get("default") == name:
            remaining = [n for n in self.config.get("knowledge_bases", {}).keys() if n != name]
            self.config["default"] = sorted(remaining)[0] if remaining else None

        self._save_config()
        return True

    def clean_rag_storage(self, name: str | None = None, backup: bool = True) -> bool:
        """
        Clean (delete) index storage for a knowledge base.

        Args:
            name: Knowledge base name (default if not specified)
            backup: If True, backup storage before deleting

        Returns:
            True if cleaned successfully
        """
        kb_name = name or self.get_default()
        kb_dir = self.get_knowledge_base_path(kb_name)
        from deeptutor.services.rag.index_versioning import (
            LEGACY_VERSION_DIRNAME,
            VERSION_PREFIX,
        )

        legacy_llamaindex_storage_dir = kb_dir / "llamaindex_storage"
        legacy_versions_dir = kb_dir / LEGACY_VERSION_DIRNAME
        legacy_storage_dir = kb_dir / "rag_storage"

        flat_version_dirs = [
            path for path in kb_dir.iterdir()
            if path.is_dir() and path.name.startswith(VERSION_PREFIX)
        ]

        if (
            not flat_version_dirs
            and not legacy_versions_dir.exists()
            and not legacy_llamaindex_storage_dir.exists()
            and not legacy_storage_dir.exists()
        ):
            logger.info(f"Index storage does not exist for '{kb_name}'")
            return False

        targets = []
        for version_dir in flat_version_dirs:
            targets.append((version_dir.name, version_dir))
        if legacy_versions_dir.exists():
            targets.append((LEGACY_VERSION_DIRNAME, legacy_versions_dir))
        if legacy_llamaindex_storage_dir.exists():
            targets.append(("llamaindex_storage", legacy_llamaindex_storage_dir))
        if legacy_storage_dir.exists():
            targets.append(("rag_storage", legacy_storage_dir))

        for label, target in targets:
            if backup:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_dir = kb_dir / f"{label}_backup_{timestamp}"
                shutil.copytree(target, backup_dir)
                logger.info(f"Backed up {label} to: {backup_dir}")

            shutil.rmtree(target)
            logger.info(f"Cleaned {label} for '{kb_name}'")

        return True

    def link_folder(self, kb_name: str, folder_path: str) -> dict:
        """
        Link a local folder to a knowledge base.

        Args:
            kb_name: Knowledge base name
            folder_path: Path to local folder (supports ~, relative paths)

        Returns:
            Dict with folder info including id, path, and file count

        Raises:
            ValueError: If KB not found or folder doesn't exist
        """
        if kb_name not in self.list_knowledge_bases():
            raise ValueError(f"Knowledge base not found: {kb_name}")

        # Normalize path (cross-platform: handles ~, relative paths, etc.)
        folder = Path(folder_path).expanduser().resolve()

        if not folder.exists():
            raise ValueError(f"Folder does not exist: {folder}")
        if not folder.is_dir():
            raise ValueError(f"Path is not a directory: {folder}")

        files = FileTypeRouter.collect_supported_files(folder, recursive=True)

        # Generate folder ID

        folder_id = hashlib.md5(  # noqa: S324
            str(folder).encode(), usedforsecurity=False
        ).hexdigest()[:8]

        # Load existing linked folders from metadata
        kb_dir = self.base_dir / kb_name
        metadata_file = kb_dir / "metadata.json"
        metadata: dict = {}

        if metadata_file.exists():
            try:
                with open(metadata_file, encoding="utf-8") as fp:
                    metadata = json.load(fp)
            except Exception:
                metadata = {}

        if "linked_folders" not in metadata:
            metadata["linked_folders"] = []

        # Check if already linked
        existing_ids = [item["id"] for item in metadata.get("linked_folders", [])]
        if folder_id in existing_ids:
            # If already linked, treat as success (idempotent)
            # Find and return existing info
            for item in metadata.get("linked_folders", []):
                if item["id"] == folder_id:
                    return item

        # Add folder info
        folder_info = {
            "id": folder_id,
            "path": str(folder),
            "added_at": datetime.now().isoformat(),
            "file_count": len(files),
        }
        metadata["linked_folders"].append(folder_info)

        # Save metadata
        with open(metadata_file, "w", encoding="utf-8") as fp:
            json.dump(metadata, fp, indent=2, ensure_ascii=False)

        return folder_info

    def get_linked_folders(self, kb_name: str) -> list[dict]:
        """
        Get list of linked folders for a knowledge base.

        Args:
            kb_name: Knowledge base name

        Returns:
            List of linked folder info dicts
        """
        if kb_name not in self.list_knowledge_bases():
            raise ValueError(f"Knowledge base not found: {kb_name}")

        kb_dir = self.base_dir / kb_name
        metadata_file = kb_dir / "metadata.json"

        if not metadata_file.exists():
            return []

        try:
            with open(metadata_file, encoding="utf-8") as f:
                metadata = json.load(f)
                return metadata.get("linked_folders", [])
        except Exception:
            return []

    def unlink_folder(self, kb_name: str, folder_id: str) -> bool:
        """
        Unlink a folder from a knowledge base.

        Args:
            kb_name: Knowledge base name
            folder_id: Folder ID to unlink

        Returns:
            True if unlinked successfully, False if not found
        """
        if kb_name not in self.list_knowledge_bases():
            raise ValueError(f"Knowledge base not found: {kb_name}")

        kb_dir = self.base_dir / kb_name
        metadata_file = kb_dir / "metadata.json"

        if not metadata_file.exists():
            return False

        try:
            with open(metadata_file, encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception:
            return False

        linked = metadata.get("linked_folders", [])
        new_linked = [f for f in linked if f["id"] != folder_id]

        if len(new_linked) == len(linked):
            return False  # Not found

        metadata["linked_folders"] = new_linked

        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return True

    def scan_linked_folder(self, folder_path: str, provider: str = DEFAULT_PROVIDER) -> list[str]:
        """
        Scan a linked folder and return list of supported file paths.

        Args:
            folder_path: Path to folder
            provider: RAG provider to determine supported extensions (default: llamaindex)

        Returns:
            List of file paths (as strings)
        """
        folder = Path(folder_path).expanduser().resolve()

        if not folder.exists() or not folder.is_dir():
            return []

        files = [
            str(file_path)
            for file_path in FileTypeRouter.collect_supported_files(folder, recursive=True)
        ]

        return sorted(files)

    def detect_folder_changes(self, kb_name: str, folder_id: str) -> dict:
        """
        Detect new and modified files in a linked folder since last sync.

        This enables automatic sync of changes from local folders that may
        be synced with cloud services like SharePoint, Google Drive, etc.

        Args:
            kb_name: Knowledge base name
            folder_id: Folder ID to check for changes

        Returns:
            Dict with 'new_files', 'modified_files', and 'has_changes' keys
        """
        if kb_name not in self.list_knowledge_bases():
            raise ValueError(f"Knowledge base not found: {kb_name}")

        # Get folder info
        folders = self.get_linked_folders(kb_name)
        folder_info = next((f for f in folders if f["id"] == folder_id), None)

        if not folder_info:
            raise ValueError(f"Linked folder not found: {folder_id}")

        folder_path = Path(folder_info["path"]).expanduser().resolve()
        last_sync = folder_info.get("last_sync")
        synced_files = folder_info.get("synced_files", {})

        # Parse last sync timestamp
        last_sync_time = None
        if last_sync:
            try:
                last_sync_time = datetime.fromisoformat(last_sync)
            except Exception:
                pass

        new_files = []
        modified_files = []

        for file_path in FileTypeRouter.collect_supported_files(folder_path, recursive=True):
            file_str = str(file_path)
            file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)

            if file_str in synced_files:
                # Check if modified since last sync
                prev_mtime_str = synced_files[file_str]
                try:
                    prev_mtime = datetime.fromisoformat(prev_mtime_str)
                    if file_mtime > prev_mtime:
                        modified_files.append(file_str)
                except Exception:
                    modified_files.append(file_str)
            else:
                # New file (not in synced files)
                new_files.append(file_str)

        return {
            "new_files": sorted(new_files),
            "modified_files": sorted(modified_files),
            "has_changes": len(new_files) > 0 or len(modified_files) > 0,
            "new_count": len(new_files),
            "modified_count": len(modified_files),
        }

    def update_folder_sync_state(self, kb_name: str, folder_id: str, synced_files: list[str]):
        """
        Update the sync state for a linked folder after successful sync.

        Records which files were synced and their modification times,
        enabling future change detection.

        Args:
            kb_name: Knowledge base name
            folder_id: Folder ID
            synced_files: List of file paths that were successfully synced
        """
        if kb_name not in self.list_knowledge_bases():
            raise ValueError(f"Knowledge base not found: {kb_name}")

        kb_dir = self.base_dir / kb_name
        metadata_file = kb_dir / "metadata.json"

        if not metadata_file.exists():
            return

        try:
            with open(metadata_file, encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception:
            return

        linked = metadata.get("linked_folders", [])

        for folder in linked:
            if folder["id"] == folder_id:
                # Record sync timestamp
                folder["last_sync"] = datetime.now().isoformat()

                # Record file modification times
                file_states = folder.get("synced_files", {})
                for file_path in synced_files:
                    try:
                        p = Path(file_path)
                        if p.exists():
                            mtime = datetime.fromtimestamp(p.stat().st_mtime)
                            file_states[file_path] = mtime.isoformat()
                    except Exception:
                        pass

                folder["synced_files"] = file_states
                folder["file_count"] = len(file_states)
                break


def main():
    """Command-line interface for knowledge base manager"""
    import argparse

    parser = argparse.ArgumentParser(description="Knowledge Base Manager")
    parser.add_argument(
        "--base-dir", default="./knowledge_bases", help="Base directory for knowledge bases"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # List command
    subparsers.add_parser("list", help="List all knowledge bases")

    # Info command
    info_parser = subparsers.add_parser("info", help="Show knowledge base information")
    info_parser.add_argument(
        "name", nargs="?", help="Knowledge base name (default if not specified)"
    )

    # Set default command
    default_parser = subparsers.add_parser("set-default", help="Set default knowledge base")
    default_parser.add_argument("name", help="Knowledge base name")

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a knowledge base")
    delete_parser.add_argument("name", help="Knowledge base name")
    delete_parser.add_argument("--force", action="store_true", help="Skip confirmation")

    # Clean RAG command
    clean_parser = subparsers.add_parser(
        "clean-rag", help="Clean RAG storage (useful for corrupted data)"
    )
    clean_parser.add_argument(
        "name", nargs="?", help="Knowledge base name (default if not specified)"
    )
    clean_parser.add_argument(
        "--no-backup", action="store_true", help="Don't backup before cleaning"
    )

    args = parser.parse_args()

    manager = KnowledgeBaseManager(args.base_dir)

    if args.command == "list":
        kb_list = manager.list_knowledge_bases()
        default_kb = manager.get_default()

        print("\nAvailable Knowledge Bases:")
        print("=" * 60)
        if not kb_list:
            print("No knowledge bases found")
        else:
            for kb_name in kb_list:
                default_marker = " (default)" if kb_name == default_kb else ""
                print(f"  • {kb_name}{default_marker}")
        print()

    elif args.command == "info":
        try:
            info = manager.get_info(args.name)

            print("\nKnowledge Base Information:")
            print("=" * 60)
            print(f"Name: {info['name']}")
            print(f"Path: {info['path']}")
            print(f"Default: {'Yes' if info['is_default'] else 'No'}")

            if info.get("metadata"):
                print("\nMetadata:")
                for key, value in info["metadata"].items():
                    print(f"  {key}: {value}")

            print("\nStatistics:")
            stats = info["statistics"]
            print(f"  Raw documents: {stats['raw_documents']}")
            print(f"  Images: {stats['images']}")
            print(f"  Content lists: {stats['content_lists']}")
            print(f"  RAG initialized: {'Yes' if stats['rag_initialized'] else 'No'}")

            if "rag" in stats:
                print("\n  RAG Statistics:")
                for key, value in stats["rag"].items():
                    print(f"    {key}: {value}")

            print()
        except Exception as e:
            print(f"Error: {e!s}")

    elif args.command == "set-default":
        try:
            manager.set_default(args.name)
            print(f"✓ Set '{args.name}' as default knowledge base")
        except Exception as e:
            print(f"Error: {e!s}")

    elif args.command == "delete":
        try:
            success = manager.delete_knowledge_base(args.name, confirm=args.force)
            if success:
                print(f"✓ Deleted knowledge base '{args.name}'")
        except Exception as e:
            print(f"Error: {e!s}")

    elif args.command == "clean-rag":
        try:
            manager.clean_rag_storage(args.name, backup=not args.no_backup)
        except Exception as e:
            print(f"Error: {e!s}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
