"""
VPN Manager module for sub-deck.
Coordinates proxy cores (Xray-core + tun2socks), routing and subscription states.
"""

import os
import sys
import json
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Dict, List, Optional, Any

from core.constants import (
    DEFAULT_SOCKS_HOST,
    DEFAULT_SOCKS_PORT,
    TUN_INTERFACE,
    TUN_IP_CIDR,
    TUN_MTU,
    DNS_SERVERS,
    PRESET_DEFAULT,
    PRESET_BYPASS_RU,
    PRESET_GAMING,
    PRESET_ROSCOMVPN,
    STEAM_CDN_DOMAINS,
    RU_BYPASS_DOMAINS,
)
from core.system import (
    run_command,
    get_default_gateway,
    resolve_host,
    wait_for_port,
    wait_for_interface,
    get_clean_env,
    clean_node_name,
    get_user_home,
    get_target_uid_gid,
)
from core.binaries import ensure_xray_and_tun, ensure_singbox, update_geofiles
from core.parsers import parse_subscription_nodes
from core.singbox_config import build_singbox_config
from core.xray_config import (
    build_xray_config,
    build_auto_balancer_config,
    validate_xray_config,
)
from core.pinger import check_nodes_ping


class VPNManager:
    """High-level orchestrator for Xray and tun2socks management."""

    def __init__(self, plugin_dir: str, settings_dir: str, fallback_settings_dir: Optional[str] = None, logger=None):
        self.plugin_dir = plugin_dir
        self.settings_dir = settings_dir
        self.fallback_settings_dir = fallback_settings_dir
        self.bin_dir = os.path.join(self.settings_dir, "bin")
        self.xray_path = os.path.join(self.bin_dir, "xray")
        self.tun2socks_path = os.path.join(self.bin_dir, "tun2socks")
        self.singbox_path = os.path.join(self.bin_dir, "sing-box")
        self.singbox_config_path = os.path.join(self.settings_dir, "singbox-config.json")
        self.config_path = os.path.join(self.settings_dir, "xray-config.json")
        self.nodes_cache_path = os.path.join(self.settings_dir, "nodes.json")
        self.settings_file = os.path.join(self.settings_dir, "settings.json")
        self.xray_process: Optional[subprocess.Popen] = None
        self.singbox_process: Optional[subprocess.Popen] = None
        self.tun_process: Optional[subprocess.Popen] = None
        self.process = None  # Backward compatibility alias
        self._logger = logger
        self._last_server_ip: Optional[str] = None
        self._last_gw_ip: Optional[str] = None
        self._last_iface: Optional[str] = None
        self._settings_read_failed: bool = False
        self._storage_lock = threading.RLock()

        os.makedirs(self.bin_dir, exist_ok=True)
        os.makedirs(self.settings_dir, exist_ok=True)

    def log(self, msg: str) -> None:
        """Structured logging output via Decky logger or stdout."""
        if self._logger:
            self._logger.info(msg)
        else:
            print(msg)

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
        with self._storage_lock:
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
                                self._settings_read_failed = False
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
                                self._settings_read_failed = False
                                return settings
                    except Exception as e:
                        self.log(f"Error reading backup settings ({bak_file}): {e}")

            # If any settings file exists on disk but couldn't be decoded, flag the read failure
            if any(os.path.exists(os.path.join(d, "settings.json")) for d in dirs):
                self._settings_read_failed = True
            else:
                self._settings_read_failed = False

            return {"subscriptions": [], "selected_node": None}

    def save_settings(self, settings: Dict[str, Any]) -> None:
        """Persists settings atomically to both primary and fallback directories with fsync and .bak backup."""
        with self._storage_lock:
            dirs = self._get_target_dirs()
            for d in dirs:
                self._backup_file_if_valid(d, "settings.json", dict)
                self._atomic_write_file(d, "settings.json", settings)
            self._settings_read_failed = False

    def get_nodes(self) -> List[Dict[str, Any]]:
        """Returns cached proxy nodes, prepending the auto least-ping virtual node if multiple nodes exist."""
        with self._storage_lock:
            self._sync_dual_persistence("nodes.json")

            nodes = []
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

            if isinstance(raw_nodes, list):
                for n in raw_nodes:
                    if isinstance(n, dict):
                        n["name"] = clean_node_name(n.get("name", ""))
                        nodes.append(n)

            # Separate WARP nodes and other nodes to put WARP right at the top
            warp_nodes = [n for n in nodes if n.get("type") in ("warp", "wireguard") or n.get("subscription_url") == "cloudflare_warp"]
            other_nodes = [n for n in nodes if n.get("type") not in ("warp", "wireguard") and n.get("subscription_url") != "cloudflare_warp"]
            ordered_nodes = warp_nodes + other_nodes

            if len(ordered_nodes) > 1 and not any(n.get("type") == "auto_balancer" for n in ordered_nodes):
                auto_node = {
                    "type": "auto_balancer",
                    "name": "⚡ Авто-выбор лучшего",
                    "server": "auto",
                    "port": 0,
                    "ping": 1
                }
                return [auto_node] + ordered_nodes
            return ordered_nodes

    def load_nodes(self) -> List[Dict[str, Any]]:
        """Alias for get_nodes."""
        return self.get_nodes()

    def save_nodes(self, nodes: List[Dict[str, Any]], force: bool = False) -> None:
        """Persists nodes list to disk atomically to both primary and fallback directories with fsync and .bak backup. Never overwrites with empty unless force=True."""
        with self._storage_lock:
            clean_nodes = [n for n in nodes if n.get("type") != "auto_balancer"]

            # Prevent wiping existing cache with empty list unless explicitly forced
            if len(clean_nodes) == 0 and not force:
                existing = self.load_nodes()
                real_existing = [n for n in existing if n.get("type") != "auto_balancer"]
                if real_existing:
                    self.log("save_nodes: refusing to overwrite existing nodes with empty list without force=True. Preserving cached nodes.")
                    return

            dirs = self._get_target_dirs()
            for d in dirs:
                self._backup_file_if_valid(d, "nodes.json", list)
                self._atomic_write_file(d, "nodes.json", clean_nodes)
            self.log(f"Saved total of {len(clean_nodes)} nodes to cache across {len(dirs)} locations.")

    # ────────────────────────────────────────────────
    # Subscription Management
    # ────────────────────────────────────────────────

    def parse_subscription(self, url: str) -> tuple:
        """Fetches and parses a single subscription URL, returning (nodes, interval, metadata)."""
        if url == "cloudflare_warp":
            from core.warp_generator import generate_warp_identity
            res = generate_warp_identity(self.bin_dir, self.settings_dir, force=False, log_func=self.log)
            if res.get("success"):
                return [res["node"]], None, {"name": "Cloudflare WARP (WireGuard)"}
            return [], None, {"name": "Cloudflare WARP (WireGuard)"}

        res = parse_subscription_nodes(url, log_func=self.log)
        if len(res) == 3:
            return res
        return res[0], res[1], {}

    def parse_all_subscriptions(self) -> List[Dict[str, Any]]:
        """Refreshes all subscribed endpoints, updates metadata and aggregates nodes."""
        with self._storage_lock:
            settings = self.load_settings()
            urls = settings.get("subscriptions", [])
            current_cached_nodes = self.load_nodes()
            all_nodes: List[Dict[str, Any]] = []

            update_intervals = settings.setdefault("update_intervals", {})
            last_update_times = settings.setdefault("last_update_times", {})
            sub_metadata = settings.setdefault("subscription_metadata", {})

            self.log(f"Starting refresh of all subscriptions: {len(urls)} links")
            for url in urls:
                try:
                    nodes, interval, meta = self.parse_subscription(url)
                    now_ts = int(time.time())
                    last_update_times[url] = now_ts
                    if interval is not None:
                        update_intervals[url] = int(interval)
                    if meta:
                        existing_meta = sub_metadata.get(url, {})
                        existing_meta.update(meta)
                        existing_meta["last_updated"] = now_ts
                        sub_metadata[url] = existing_meta

                    if nodes:
                        all_nodes.extend(nodes)
                    else:
                        # Non-destructive caching: keep existing nodes for this URL if update returned empty
                        cached_for_url = [n for n in current_cached_nodes if n.get("subscription_url") == url]
                        if cached_for_url:
                            self.log(f"Subscription {url} returned 0 nodes, retaining {len(cached_for_url)} cached nodes.")
                            all_nodes.extend(cached_for_url)
                        else:
                            self.log(f"Subscription {url} returned 0 nodes and no previous cached nodes.")
                except Exception as e:
                    self.log(f"Failed to parse subscription {url}: {e}")
                    # Preserve cached nodes on exception as well
                    cached_for_url = [n for n in current_cached_nodes if n.get("subscription_url") == url]
                    if cached_for_url:
                        all_nodes.extend(cached_for_url)

            settings["update_intervals"] = update_intervals
            settings["last_update_times"] = last_update_times
            settings["subscription_metadata"] = sub_metadata
            self.save_settings(settings)
            # If user explicitly has zero subscriptions, allow wiping node cache via force=True
            force_save = (len(urls) == 0)
            self.save_nodes(all_nodes, force=force_save)

            return all_nodes

    def add_subscription(self, url: str) -> List[Dict[str, Any]]:
        """Adds a single subscription and updates the node pool."""
        with self._storage_lock:
            settings = self.load_settings()
            subscriptions = settings.get("subscriptions", [])
            if url not in subscriptions:
                subscriptions.append(url)
                settings["subscriptions"] = subscriptions
                self.save_settings(settings)
                self.log(f"Added subscription URL: {url}")
        return self.parse_all_subscriptions()

    def add_multiple_subscriptions(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Bulk adds subscriptions."""
        with self._storage_lock:
            settings = self.load_settings()
            subscriptions = settings.get("subscriptions", [])
            updated = False
            for url in urls:
                if url not in subscriptions:
                    subscriptions.append(url)
                    updated = True
            if updated:
                settings["subscriptions"] = subscriptions
                self.save_settings(settings)
                self.log(f"Added multiple subscriptions: {urls}")
        return self.parse_all_subscriptions()

    def remove_subscription(self, url: str) -> List[Dict[str, Any]]:
        """Removes a subscription URL and prunes associated nodes and metadata."""
        with self._storage_lock:
            settings = self.load_settings()
            subscriptions = settings.get("subscriptions", [])
            if url in subscriptions:
                subscriptions.remove(url)
                settings["subscriptions"] = subscriptions
                # Prune metadata and intervals
                if "subscription_metadata" in settings and url in settings["subscription_metadata"]:
                    del settings["subscription_metadata"][url]
                if "last_update_times" in settings and url in settings["last_update_times"]:
                    del settings["last_update_times"][url]
                if "update_intervals" in settings and url in settings["update_intervals"]:
                    del settings["update_intervals"][url]
                self.save_settings(settings)
                self.log(f"Removed subscription URL: {url}")
        return self.parse_all_subscriptions()

    def update_subscription(self, url: str) -> List[Dict[str, Any]]:
        """Updates a single subscription, updates metadata, and merges into current cache."""
        self.log(f"Updating single subscription: {url}")
        try:
            new_nodes, interval, meta = self.parse_subscription(url)
        except Exception as e:
            self.log(f"Error parsing subscription {url}: {e}")
            new_nodes, interval, meta = [], None, {}

        with self._storage_lock:
            current_nodes = self.load_nodes()
            # Non-destructive caching: if new_nodes is empty (network error, blocked, timeout),
            # do NOT wipe old nodes of this subscription!
            if not new_nodes:
                self.log(f"Warning: update_subscription for {url} returned 0 nodes. Preserving existing cached nodes.")
                merged_nodes = current_nodes
            else:
                # Retain nodes from other subscriptions and update nodes for this subscription
                merged_nodes = [n for n in current_nodes if n.get("subscription_url") != url]
                merged_nodes.extend(new_nodes)
                self.save_nodes(merged_nodes)

            settings = self.load_settings()
            last_updates = settings.setdefault("last_update_times", {})
            update_intervals = settings.setdefault("update_intervals", {})
            sub_metadata = settings.setdefault("subscription_metadata", {})

            now_ts = int(time.time())
            last_updates[url] = now_ts
            if interval is not None:
                update_intervals[url] = interval
            if meta:
                existing_meta = sub_metadata.get(url, {})
                existing_meta.update(meta)
                existing_meta["last_updated"] = now_ts
                sub_metadata[url] = existing_meta

            self.save_settings(settings)
            return merged_nodes

    def update_geofiles(self, force: bool = False) -> bool:
        """Downloads/updates GeoIP and Geosite databases for RoscomVPN preset."""
        settings = self.load_settings()
        if settings.get("selected_preset") != PRESET_ROSCOMVPN:
            return False
        return update_geofiles(
            self.plugin_dir,
            self.settings_dir,
            force=force,
            log_func=self.log
        )

    # ────────────────────────────────────────────────
    # Core Binaries
    # ────────────────────────────────────────────────

    def ensure_binaries(self) -> bool:
        """Checks and prepares Xray and tun2socks executables."""
        return ensure_xray_and_tun(
            self.plugin_dir,
            self.settings_dir,
            self.bin_dir,
            self.xray_path,
            self.tun2socks_path,
            log_func=self.log
        )

    def download_singbox(self) -> bool:
        """Backward compatibility alias."""
        return self.ensure_binaries()

    def _get_clean_env(self) -> Dict[str, str]:
        """Provides sanitized environment with XRAY asset location set."""
        return get_clean_env({"XRAY_LOCATION_ASSET": self.bin_dir})

    # ────────────────────────────────────────────────
    # Configuration Generation
    # ────────────────────────────────────────────────

    def generate_config(self, node: Dict[str, Any], iface: Optional[str] = None):
        """Generates and writes config for target node. Returns list of server IPs for bypass routing."""
        # 1. Virtual Auto-balancer node (leastPing observatory strategy)
        if node.get("type") == "auto_balancer":
            candidate_nodes = [n for n in self.load_nodes() if n.get("type") != "auto_balancer"]
            settings = self.load_settings()
            preset = settings.get("selected_preset", PRESET_DEFAULT)
            config_data, server_ips = build_auto_balancer_config(candidate_nodes, preset=preset, iface=iface)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)
            try:
                os.chmod(self.config_path, 0o666)
            except Exception:
                pass
            self.log(f"Auto-balancer config written to {self.config_path} with {len(server_ips)} endpoints")
            return server_ips

        # 2. Sing-box protocols (Hysteria 2 / TUIC v5 / WireGuard / WARP)
        if node.get("type") in ("hysteria2", "hy2", "tuic", "wireguard", "warp"):
            server_host = node.get("server", "")
            server_ip = resolve_host(server_host) or server_host
            settings = self.load_settings()
            preset = settings.get("selected_preset", PRESET_DEFAULT)
            config_data = build_singbox_config(node, server_ip, preset=preset, iface=iface)
            with open(self.singbox_config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)
            try:
                os.chmod(self.singbox_config_path, 0o666)
            except Exception:
                pass
            self.log(f"Sing-box config written to {self.singbox_config_path} for {server_host}")
            return [server_ip] if server_ip else []

        # 3. Raw Xray configurations (e.g. smart composite configs like #test)
        raw_config = node.get("raw_config")
        if raw_config:
            import copy
            config_data = copy.deepcopy(raw_config)
            config_data["inbounds"] = [
                {
                    "tag": "socks-in",
                    "port": DEFAULT_SOCKS_PORT,
                    "listen": DEFAULT_SOCKS_HOST,
                    "protocol": "socks",
                    "settings": {
                        "auth": "noauth",
                        "udp": True,
                    },
                    "sniffing": {
                        "enabled": True,
                        "destOverride": ["http", "tls", "quic"],
                    },
                }
            ]
            server_ips = []
            has_direct = False
            for ob in config_data.get("outbounds", []):
                if ob.get("tag") == "direct":
                    has_direct = True
                if iface and ob.get("protocol") in ("vless", "vmess", "trojan", "shadowsocks", "freedom"):
                    st = ob.setdefault("streamSettings", {})
                    so = st.setdefault("sockopt", {})
                    so["interface"] = iface

                settings = ob.get("settings", {})
                for vnext in settings.get("vnext", []):
                    addr = vnext.get("address")
                    if addr:
                        resolved = resolve_host(addr) or addr
                        vnext["address"] = resolved
                        if resolved and resolved not in server_ips:
                            server_ips.append(resolved)
                for srv in settings.get("servers", []):
                    addr = srv.get("address")
                    if addr:
                        resolved = resolve_host(addr) or addr
                        srv["address"] = resolved
                        if resolved and resolved not in server_ips:
                            server_ips.append(resolved)

            if not has_direct:
                direct_ob = {
                    "protocol": "freedom",
                    "tag": "direct",
                    "settings": {"domainStrategy": "UseIP"},
                }
                if iface:
                    direct_ob["streamSettings"] = {"sockopt": {"interface": iface}}
                config_data.setdefault("outbounds", []).append(direct_ob)

            if not server_ips and node.get("server"):
                s = node.get("server")
                res = resolve_host(s) or s
                if res:
                    server_ips.append(res)

            settings = self.load_settings()
            preset = settings.get("selected_preset", PRESET_DEFAULT)
            rules = config_data.setdefault("routing", {}).setdefault("rules", [])

            if preset == PRESET_GAMING:
                rules.insert(0, {
                    "type": "field",
                    "domain": STEAM_CDN_DOMAINS,
                    "outboundTag": "direct"
                })
            elif preset == PRESET_BYPASS_RU:
                rules.insert(0, {
                    "type": "field",
                    "ip": ["geoip:ru"],
                    "outboundTag": "direct"
                })
                rules.insert(0, {
                    "type": "field",
                    "domain": RU_BYPASS_DOMAINS + ["geosite:category-ru"],
                    "outboundTag": "direct"
                })

            has_private_rule = any("geoip:private" in r.get("ip", []) for r in rules)
            if not has_private_rule:
                rules.insert(0, {
                    "type": "field",
                    "ip": ["geoip:private"],
                    "outboundTag": "direct"
                })

            # Remove any existing port 53 rule to avoid loop or blocked UDP
            rules[:] = [r for r in rules if r.get("port") not in ("53", 53)]

            # Ensure dns-out outbound exists
            if not any(ob.get("tag") == "dns-out" for ob in config_data.get("outbounds", [])):
                config_data.setdefault("outbounds", []).append({
                    "tag": "dns-out",
                    "protocol": "dns"
                })

            # Route incoming DNS queries from socks-in to dns-out
            rules.insert(0, {
                "type": "field",
                "inboundTag": ["socks-in", "socks"],
                "port": "53",
                "outboundTag": "dns-out"
            })

            # Configure Xray DNS with remote DoH over TCP/TLS inside the proxy (direct IP bootstrap)
            config_data["dns"] = {
                "servers": [
                    "https://1.1.1.1/dns-query",
                    "https://1.0.0.1/dns-query",
                    "https://8.8.8.8/dns-query"
                ],
                "queryStrategy": "UseIPv4"
            }

            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)
            try:
                os.chmod(self.config_path, 0o666)
            except Exception:
                pass

            self.log(f"Raw Xray config written to {self.config_path} with {len(server_ips)} bypass endpoints: {server_ips}")
            return server_ips

        # 4. Standard Xray node configuration
        server_host = node["server"]
        server_ip = resolve_host(server_host) or server_host
        self.log(f"Generating Xray config for: {server_host} (resolved IP: {server_ip})")

        settings = self.load_settings()
        preset = settings.get("selected_preset", PRESET_DEFAULT)

        config_data = build_xray_config(node, server_ip, preset=preset, iface=iface)

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)
        try:
            os.chmod(self.config_path, 0o666)
        except Exception:
            pass

        self.log(f"Config written to {self.config_path}")
        return [server_ip] if server_ip else []

    # ────────────────────────────────────────────────
    # Process & Routing Lifecycle
    # ────────────────────────────────────────────────

    def start(self, node: Dict[str, Any]) -> bool:
        """
        Starts proxy core (Xray or sing-box) + tun2socks and configures full system TUN routing.
        Uses fast socket & interface polling instead of hardcoded sleeps.
        """
        self.stop()

        is_singbox = node.get("type") in ("hysteria2", "hy2", "tuic", "wireguard", "warp")
        if is_singbox:
            if not ensure_singbox(self.bin_dir, self.singbox_path, log_func=self.log, plugin_dir=self.plugin_dir):
                self.log("sing-box binary unavailable, aborting start.")
                return False
            if not ensure_xray_and_tun(self.plugin_dir, self.settings_dir, self.bin_dir, self.xray_path, self.tun2socks_path, log_func=self.log):
                self.log("tun2socks binary unavailable, aborting start.")
                return False
        else:
            if not self.ensure_binaries():
                self.log("Required binaries (xray/tun2socks) unavailable, aborting start.")
                return False

        gw_ip, iface = get_default_gateway()
        self.log(f"Detected default gateway: {gw_ip} via {iface}")

        server_ip = self.generate_config(node, iface=iface)
        server_ips = server_ip if isinstance(server_ip, list) else ([server_ip] if server_ip else [])

        if is_singbox:
            # Validate sing-box configuration
            try:
                chk = subprocess.run(
                    [self.singbox_path, "check", "-c", self.singbox_config_path],
                    capture_output=True,
                    text=True,
                    timeout=3.0,
                )
                if chk.returncode != 0:
                    self.log(f"sing-box config validation failed: {chk.stderr}")
                    return False
            except Exception as e:
                self.log(f"sing-box check error: {e}")
                return False

            # Start sing-box
            singbox_log_path = os.path.join(self.settings_dir, "singbox.log")
            try:
                sb_log = open(singbox_log_path, "w")
                try:
                    self.singbox_process = subprocess.Popen(
                        [self.singbox_path, "run", "-c", self.singbox_config_path],
                        stdout=sb_log,
                        stderr=sb_log,
                        env=self._get_clean_env(),
                        start_new_session=True,
                    )
                finally:
                    sb_log.close()
                self.log(f"sing-box started, PID={self.singbox_process.pid}")
            except Exception as e:
                self.log(f"Failed to spawn sing-box process: {e}")
                self.stop()
                return False
        else:
            # Validate config file syntax
            valid, err_msg = validate_xray_config(self.xray_path, self.config_path, self._get_clean_env())
            if not valid:
                self.log(f"Xray config validation failed: {err_msg}")
                return False

            # 1. Start Xray-core
            xray_log_path = os.path.join(self.settings_dir, "xray.log")
            try:
                xray_log = open(xray_log_path, "w")
                try:
                    self.xray_process = subprocess.Popen(
                        [self.xray_path, "-config", self.config_path],
                        stdout=xray_log,
                        stderr=xray_log,
                        env=self._get_clean_env(),
                        start_new_session=True,
                    )
                finally:
                    xray_log.close()
                self.log(f"Xray started, PID={self.xray_process.pid}")
            except Exception as e:
                self.log(f"Failed to spawn Xray process: {e}")
                self.stop()
                return False

        # Efficient poll for SOCKS port readiness (up to 2.5s, step 50ms)
        if not wait_for_port(DEFAULT_SOCKS_HOST, DEFAULT_SOCKS_PORT, timeout=2.5, interval=0.05):
            core_name = "sing-box" if is_singbox else "Xray"
            self.log(f"{core_name} failed to bind to {DEFAULT_SOCKS_HOST}:{DEFAULT_SOCKS_PORT} within timeout")
            self.stop()
            return False

        # 2. Start tun2socks
        tun_log_path = os.path.join(self.settings_dir, "tun2socks.log")
        try:
            tun_log = open(tun_log_path, "w")
            try:
                self.tun_process = subprocess.Popen(
                    [
                        self.tun2socks_path,
                        "-d", TUN_INTERFACE,
                        "-p", f"socks5://{DEFAULT_SOCKS_HOST}:{DEFAULT_SOCKS_PORT}",
                    ],
                    stdout=tun_log,
                    stderr=tun_log,
                    env=self._get_clean_env(),
                    start_new_session=True,
                )
            finally:
                tun_log.close()
            self.log(f"tun2socks started, PID={self.tun_process.pid}")
        except Exception as e:
            self.log(f"Failed to spawn tun2socks: {e}")
            self.stop()
            return False

        # Efficient poll for tun0 creation (up to 2.0s, step 50ms)
        if not wait_for_interface(TUN_INTERFACE, timeout=2.0, interval=0.05):
            self.log(f"Interface {TUN_INTERFACE} was not created in time")
            self.stop()
            return False

        # 3. Configure IP address, MTU and link state
        run_command(["ip", "addr", "add", TUN_IP_CIDR, "dev", TUN_INTERFACE])
        run_command(["ip", "link", "set", "dev", TUN_INTERFACE, "mtu", TUN_MTU, "up"])

        # Bypass route to VPN server(s) via real default gateway to prevent routing loop
        if gw_ip and iface:
            for sip in server_ips:
                run_command(["ip", "route", "replace", sip, "via", gw_ip, "dev", iface])

        # Route default traffic via TUN interface with top priority (metric 1)
        run_command(["ip", "route", "replace", "default", "dev", TUN_INTERFACE, "metric", "1"])

        # Configure systemd-resolved DNS for tun0
        run_command(["resolvectl", "dns", TUN_INTERFACE] + DNS_SERVERS)
        run_command(["resolvectl", "domain", TUN_INTERFACE, "~."])
        run_command(["resolvectl", "default-route", TUN_INTERFACE, "yes"])

        self._last_server_ip = server_ips
        self._last_gw_ip = gw_ip
        self._last_iface = iface

        settings = self.load_settings()
        settings["selected_node"] = node
        settings["_routing_state"] = {
            "server_ip": server_ips,
            "gw_ip": gw_ip,
            "iface": iface,
        }
        self.save_settings(settings)
        self.log(f"VPN connected successfully to: {node.get('name')}")
        return True

    def stop(self) -> None:
        """Tears down routing and terminates proxy processes safely."""
        self.log("Stopping VPN (xray/sing-box + tun2socks)...")

        settings = self.load_settings()
        routing_state = settings.get("_routing_state") or {}
        raw_ips = self._last_server_ip or routing_state.get("server_ip")
        if isinstance(raw_ips, str):
            server_ips = [raw_ips]
        elif isinstance(raw_ips, list):
            server_ips = raw_ips
        else:
            server_ips = []

        gw_ip = self._last_gw_ip or routing_state.get("gw_ip")
        iface = self._last_iface or routing_state.get("iface")

        # 1. Rollback system routing & DNS
        run_command(["resolvectl", "revert", TUN_INTERFACE])
        run_command(["ip", "route", "del", "default", "dev", TUN_INTERFACE, "metric", "1"])
        if gw_ip and iface:
            for sip in server_ips:
                run_command(["ip", "route", "del", sip, "via", gw_ip, "dev", iface])
        else:
            for sip in server_ips:
                run_command(["ip", "route", "del", sip])
        run_command(["ip", "link", "delete", TUN_INTERFACE])

        # 2. Terminate child processes cleanly and reap zombies
        for proc in (self.tun_process, self.xray_process, self.singbox_process, self.process):
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=0.3)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=0.2)
                    except Exception:
                        pass

        # 3. Targeted process cleanup (SIGTERM followed by SIGKILL for stubborn processes)
        for bin_path in (self.tun2socks_path, self.xray_path, self.singbox_path):
            try:
                subprocess.run(["pkill", "-15", "-f", bin_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
            except Exception:
                pass
            try:
                subprocess.run(["pkill", "-9", "-f", bin_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
            except Exception:
                pass

        self.tun_process = None
        self.xray_process = None
        self.singbox_process = None
        self.process = None
        self._last_server_ip = None
        self._last_gw_ip = None
        self._last_iface = None

        settings["selected_node"] = None
        settings.pop("_routing_state", None)
        self.save_settings(settings)
        self.log("VPN stopped cleanly.")

    def cleanup_stale(self) -> None:
        """Cleans up leftover interfaces, routes and processes from ungraceful shutdowns or reboot."""
        self.log("Cleaning up any stale VPN state...")
        try:
            run_command(["resolvectl", "revert", TUN_INTERFACE])
            run_command(["ip", "route", "del", "default", "dev", TUN_INTERFACE, "metric", "1"])
            run_command(["ip", "link", "delete", TUN_INTERFACE])
        except Exception:
            pass

        for bin_path in (self.tun2socks_path, self.xray_path, self.singbox_path):
            try:
                subprocess.run(["pkill", "-15", "-f", bin_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
            except Exception:
                pass
            try:
                subprocess.run(["pkill", "-9", "-f", bin_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
            except Exception:
                pass

        settings = self.load_settings()
        if "_routing_state" in settings:
            settings.pop("_routing_state", None)
            settings["selected_node"] = None
            self.save_settings(settings)

    def is_running(self) -> bool:
        """Verifies if VPN tunnel is actively running."""
        # 1. Interface check: if tun0 doesn't exist in kernel, VPN is definitely not active
        if not os.path.exists(f"/sys/class/net/{TUN_INTERFACE}"):
            return False

        # 2. Check process handles
        tun_alive = self.tun_process is not None and self.tun_process.poll() is None
        core_alive = (
            (self.xray_process is not None and self.xray_process.poll() is None) or
            (self.singbox_process is not None and self.singbox_process.poll() is None)
        )
        if tun_alive and core_alive:
            return True

        # 3. Fallback: check exact process names
        try:
            tun_check = subprocess.run(["pgrep", "-x", "tun2socks"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=0.5)
            xray_check = subprocess.run(["pgrep", "-x", "xray"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=0.5)
            sb_check = subprocess.run(["pgrep", "-x", "sing-box"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=0.5)
            return tun_check.returncode == 0 and (xray_check.returncode == 0 or sb_check.returncode == 0)
        except Exception:
            return False

    def get_singbox_log(self) -> str:
        """Returns logs from Xray, sing-box and tun2socks."""
        logs = []
        for name, fname in [("XRAY", "xray.log"), ("SINGBOX", "singbox.log"), ("TUN2SOCKS", "tun2socks.log")]:
            fpath = os.path.join(self.settings_dir, fname)
            if os.path.exists(fpath):
                try:
                    with open(fpath, "r", errors="replace", encoding="utf-8") as f:
                        lines = f.readlines()
                        logs.append(f"=== {name} LOGS ===\n" + "".join(lines[-30:]))
                except Exception as e:
                    logs.append(f"=== {name} LOGS ===\nError reading: {e}")
            else:
                logs.append(f"=== {name} LOGS ===\nNo log file found.")
        return "\n\n".join(logs)

    def update_routing_presets(self) -> Dict[str, Any]:
        """
        Downloads/updates Throne routing profiles and geo assets with atomic overwrite.
        Cleanly replaces all previous rules preventing duplicate entries.
        """
        from core.routing_updater import update_throne_routing
        res = update_throne_routing(self.settings_dir, self.bin_dir, log_func=self.log)
        if res.get("success"):
            settings = self.load_settings()
            settings["last_rules_update"] = int(time.time())
            self.save_settings(settings)
            # If actively connected, hot-restart with refreshed rules
            if self.is_running():
                node = settings.get("selected_node")
                if node:
                    self.start(node)
        return res

    def generate_warp_node(self, force: bool = True) -> Dict[str, Any]:
        """Registers Cloudflare WARP device and updates node cache."""
        from core.warp_generator import generate_warp_identity
        res = generate_warp_identity(self.bin_dir, self.settings_dir, force=force, log_func=self.log)
        if res.get("success"):
            warp_node = res["node"]
            settings = self.load_settings()
            subs = settings.get("subscriptions", [])
            if "cloudflare_warp" not in subs:
                subs.append("cloudflare_warp")
                settings["subscriptions"] = subs

            meta = settings.get("subscription_metadata", {})
            meta["cloudflare_warp"] = {
                "name": "Cloudflare WARP (WireGuard)",
                "upload": 0,
                "download": 0,
                "total": 0,
                "expire": 0,
                "last_updated": int(time.time()),
            }
            settings["subscription_metadata"] = meta
            self.save_settings(settings)

            # Insert or replace in nodes
            nodes = self.load_nodes()
            nodes = [n for n in nodes if n.get("subscription_url") != "cloudflare_warp"]
            nodes.append(warp_node)
            self.save_nodes(nodes)
            res["nodes"] = self.get_nodes()
            self.log("Cloudflare WARP node added to node cache.")
        return res
