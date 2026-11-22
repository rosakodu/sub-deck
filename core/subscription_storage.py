"""JSON persistence for subscription settings and cached nodes."""

import json
import os
import shutil
import sys
import tempfile
import threading
from typing import Any, Callable, Dict, List, Optional

from core.system import get_target_uid_gid, get_user_home


class SubscriptionStorage:
    """Keeps the primary and fallback files under a shared transaction lock."""

    def __init__(self, settings_dir: str, fallback_settings_dir: Optional[str], log: Callable[[str], None]):
        self.settings_dir = settings_dir
        self.fallback_settings_dir = fallback_settings_dir
        self.log = log
        self.lock = threading.RLock()
        self.settings_read_failed = False

    def _get_target_dirs(self) -> List[str]:
        """Returns ordered list of directories for dual-persistence: primary settings dir and fallback user home dir."""
        dirs = [self.settings_dir]
        fallback_dir = self.fallback_settings_dir
        if fallback_dir is None and "unittest" not in sys.modules and "pytest" not in sys.modules:
            fallback_dir = os.path.join(get_user_home(), ".config", "sub-deck")

        if fallback_dir and os.path.abspath(fallback_dir) != os.path.abspath(self.settings_dir):
            dirs.append(fallback_dir)
        return dirs

    def _sync_dual_persistence(self, filename: str) -> None:
        """Synchronizes file and its .bak between all target dirs if one exists and the other is missing/empty."""
        dirs = self._get_target_dirs()
        if len(dirs) < 2:
            return

        for name in (filename, filename + ".bak"):
            # Find a directory that has a non-empty valid file
            source_file = None
            for d in dirs:
                fpath = os.path.join(d, name)
                if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
                    source_file = fpath
                    break

            if source_file:
                for d in dirs:
                    dest_file = os.path.join(d, name)
                    if not os.path.isfile(dest_file) or os.path.getsize(dest_file) == 0:
                        try:
                            os.makedirs(d, exist_ok=True)
                            self._ensure_file_permissions(d)
                            shutil.copy2(source_file, dest_file)
                            self._ensure_file_permissions(dest_file)
                            self.log(f"Recovered {dest_file} from {source_file}")
                        except Exception as e:
                            self.log(f"Failed to recover {dest_file} from {source_file}: {e}")

    def _ensure_file_permissions(self, path: str, mode: int = 0o666) -> None:
        """Sets safe permissions and ownership to user deck if running as root."""
        try:
            if os.path.isdir(path):
                os.chmod(path, 0o755)
            else:
                os.chmod(path, mode)
        except Exception:
            pass

        if os.geteuid() == 0:
            try:
                uid, gid = get_target_uid_gid()
                os.chown(path, uid, gid)
            except Exception:
                pass

    def _atomic_write_file(self, target_dir: str, filename: str, data: Any) -> bool:
        """Writes JSON data atomically with fsync and ensures permissions."""
        os.makedirs(target_dir, exist_ok=True)
        self._ensure_file_permissions(target_dir)

        target_file = os.path.join(target_dir, filename)
        tmp_file = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=target_dir, delete=False, encoding="utf-8") as f:
                tmp_file = f.name
                json.dump(data, f, indent=2 if isinstance(data, dict) else None)
                f.flush()
                os.fsync(f.fileno())
            self._ensure_file_permissions(tmp_file)
            os.replace(tmp_file, target_file)
            self._ensure_file_permissions(target_file)
            return True
        except Exception as e:
            self.log(f"Failed atomic write to {target_file}: {e}")
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass
            return False

    def _backup_file_if_valid(self, target_dir: str, filename: str, expected_type: type) -> None:
        """Copies target_file to .bak in target_dir if current file is valid JSON of expected_type."""
        target_file = os.path.join(target_dir, filename)
        bak_file = target_file + ".bak"
        if os.path.exists(target_file) and os.path.getsize(target_file) > 0:
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    content = json.load(f)
                if isinstance(content, expected_type):
                    shutil.copy2(target_file, bak_file)
                    self._ensure_file_permissions(bak_file)
                else:
                    self.log(f"Preserving existing {filename}.bak: primary JSON is not {expected_type.__name__}.")
            except Exception as e:
                self.log(f"Preserving existing {filename}.bak: primary file is invalid JSON: {e}")

    # ────────────────────────────────────────────────
    # Settings and cache persistence
    # ────────────────────────────────────────────────

    def load_settings(self) -> Dict[str, Any]:
        """Loads plugin configuration and migrates legacy keys if needed, with dual-persistence and .bak fallback."""
        with self.lock:
            # Sync across primary and fallback directories if needed
            self._sync_dual_persistence("settings.json")

            dirs = self._get_target_dirs()
            # 1. Try loading primary or fallback settings
            for d in dirs:
                s_file = os.path.join(d, "settings.json")
                if os.path.exists(s_file) and os.path.getsize(s_file) > 0:
                    try:
                        with open(s_file, "r", encoding="utf-8") as f:
                            settings = json.load(f)
                            if isinstance(settings, dict):
                                if "subscription_url" in settings and "subscriptions" not in settings:
                                    old_url = settings.get("subscription_url", "")
                                    settings["subscriptions"] = [old_url] if old_url else []
                                self.settings_read_failed = False
                                return settings
                    except Exception as e:
                        self.log(f"Error reading primary settings from {s_file}: {e}")

            # 2. Try loading backup file (.bak) from any target dir
            for d in dirs:
                bak_file = os.path.join(d, "settings.json.bak")
                if os.path.exists(bak_file) and os.path.getsize(bak_file) > 0:
                    try:
                        with open(bak_file, "r", encoding="utf-8") as f:
                            settings = json.load(f)
                            if isinstance(settings, dict):
                                if "subscription_url" in settings and "subscriptions" not in settings:
                                    old_url = settings.get("subscription_url", "")
                                    settings["subscriptions"] = [old_url] if old_url else []
                                self.log(f"Loaded settings from backup file ({bak_file}) due to primary failure.")
                                self.settings_read_failed = False
                                return settings
                    except Exception as e:
                        self.log(f"Error reading backup settings ({bak_file}): {e}")

            # If any settings file exists on disk but couldn't be decoded, flag the read failure
            if any(os.path.exists(os.path.join(d, "settings.json")) for d in dirs):
                self.settings_read_failed = True
            else:
                self.settings_read_failed = False

            return {"subscriptions": [], "selected_node": None}

    def save_settings(self, settings: Dict[str, Any]) -> None:
        """Persists settings atomically to both primary and fallback directories with fsync and .bak backup."""
        with self.lock:
            dirs = self._get_target_dirs()
            for d in dirs:
                self._backup_file_if_valid(d, "settings.json", dict)
                self._atomic_write_file(d, "settings.json", settings)
            self.settings_read_failed = False

    def load_nodes(self) -> List[Any]:
        """Reads the persisted node list, recovering from backups when needed."""
        with self.lock:
            self._sync_dual_persistence("nodes.json")

            raw_nodes = None
            dirs = self._get_target_dirs()

            for d in dirs:
                n_file = os.path.join(d, "nodes.json")
                if os.path.exists(n_file) and os.path.getsize(n_file) > 0:
                    try:
                        with open(n_file, "r", encoding="utf-8") as f:
                            raw_nodes = json.load(f)
                        if isinstance(raw_nodes, list):
                            break
                        else:
                            self.log(f"Nodes cache {n_file} is not a JSON list, trying next.")
                            raw_nodes = None
                    except Exception as e:
                        self.log(f"Error reading nodes cache from {n_file}: {e}")
                        raw_nodes = None

            if raw_nodes is None:
                for d in dirs:
                    bak_file = os.path.join(d, "nodes.json.bak")
                    if os.path.exists(bak_file) and os.path.getsize(bak_file) > 0:
                        try:
                            with open(bak_file, "r", encoding="utf-8") as f:
                                raw_nodes = json.load(f)
                            if isinstance(raw_nodes, list):
                                self.log(f"Loaded nodes from backup cache ({bak_file}) due to primary cache failure.")
                                break
                            else:
                                self.log(f"Backup nodes cache ({bak_file}) is not a JSON list.")
                                raw_nodes = None
                        except Exception as e:
                            self.log(f"Error reading backup nodes cache ({bak_file}): {e}")
                            raw_nodes = None

            return raw_nodes if raw_nodes is not None else []

    def save_nodes(self, nodes: List[Dict[str, Any]]) -> None:
        """Writes the node cache and backs up the previous valid contents."""
        with self.lock:
            dirs = self._get_target_dirs()
            for d in dirs:
                self._backup_file_if_valid(d, "nodes.json", list)
                self._atomic_write_file(d, "nodes.json", nodes)
            self.log(f"Saved total of {len(nodes)} nodes to cache across {len(dirs)} locations.")
