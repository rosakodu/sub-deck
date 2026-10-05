"""
VPN Manager module for sub-deck.
Coordinates proxy cores (Xray-core + tun2socks), routing and subscription states.
"""

import os
import json
import subprocess
import time
from typing import Dict, List, Optional, Any

from core.constants import (
    DEFAULT_SOCKS_HOST,
    DEFAULT_SOCKS_PORT,
    TUN_INTERFACE,
    TUN_IP_CIDR,
    DNS_SERVERS,
    PRESET_DEFAULT,
    PRESET_ROSCOMVPN,
)
from core.system import (
    run_command,
    get_default_gateway,
    resolve_host,
    wait_for_port,
    wait_for_interface,
    get_clean_env,
)
from core.binaries import ensure_xray_and_tun, update_geofiles
from core.parsers import parse_subscription_nodes
from core.xray_config import build_xray_config, validate_xray_config
from core.pinger import tcp_ping, check_nodes_ping


class VPNManager:
    """High-level orchestrator for Xray and tun2socks management."""

    def __init__(self, plugin_dir: str, settings_dir: str, logger=None):
        self.plugin_dir = plugin_dir
        self.settings_dir = settings_dir
        self.bin_dir = os.path.join(self.settings_dir, "bin")
        self.xray_path = os.path.join(self.bin_dir, "xray")
        self.tun2socks_path = os.path.join(self.bin_dir, "tun2socks")
        self.singbox_path = self.xray_path  # Backward compatibility alias
        self.config_path = os.path.join(self.settings_dir, "xray-config.json")
        self.nodes_cache_path = os.path.join(self.settings_dir, "nodes.json")
        self.settings_file = os.path.join(self.settings_dir, "settings.json")
        self.xray_process: Optional[subprocess.Popen] = None
        self.tun_process: Optional[subprocess.Popen] = None
        self.process = None  # Backward compatibility alias
        self._logger = logger
        self._last_server_ip: Optional[str] = None
        self._last_gw_ip: Optional[str] = None
        self._last_iface: Optional[str] = None

        os.makedirs(self.bin_dir, exist_ok=True)
        os.makedirs(self.settings_dir, exist_ok=True)

    def log(self, msg: str) -> None:
        """Structured logging output via Decky logger or stdout."""
        if self._logger:
            self._logger.info(msg)
        else:
            print(msg)

    # ────────────────────────────────────────────────
    # Settings and cache persistence
    # ────────────────────────────────────────────────

    def load_settings(self) -> Dict[str, Any]:
        """Loads plugin configuration and migrates legacy keys if needed."""
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    # Migrate single subscription_url to subscriptions list
                    if "subscription_url" in settings and "subscriptions" not in settings:
                        old_url = settings.get("subscription_url", "")
                        settings["subscriptions"] = [old_url] if old_url else []
                    return settings
            except Exception as e:
                self.log(f"Error reading settings: {e}")
        return {"subscriptions": [], "selected_node": None}

    def save_settings(self, settings: Dict[str, Any]) -> None:
        """Persists settings atomically."""
        tmp_file = f"{self.settings_file}.tmp"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
            os.replace(tmp_file, self.settings_file)
        except Exception as e:
            self.log(f"Failed to save settings: {e}")
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass

    def get_nodes(self) -> List[Dict[str, Any]]:
        """Returns cached proxy nodes."""
        if os.path.exists(self.nodes_cache_path):
            try:
                with open(self.nodes_cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def load_nodes(self) -> List[Dict[str, Any]]:
        """Alias for get_nodes."""
        return self.get_nodes()

    def save_nodes(self, nodes: List[Dict[str, Any]]) -> None:
        """Persists nodes list to disk."""
        tmp_file = f"{self.nodes_cache_path}.tmp"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(nodes, f)
            os.replace(tmp_file, self.nodes_cache_path)
            self.log(f"Saved total of {len(nodes)} nodes to cache.")
        except Exception as e:
            self.log(f"Failed to save nodes cache: {e}")
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass

    # ────────────────────────────────────────────────
    # Subscription Management
    # ────────────────────────────────────────────────

    def parse_subscription(self, url: str) -> tuple:
        """Fetches and parses a single subscription URL."""
        return parse_subscription_nodes(url, log_func=self.log)

    def parse_all_subscriptions(self) -> List[Dict[str, Any]]:
        """Refreshes all subscribed endpoints and aggregates nodes."""
        settings = self.load_settings()
        urls = settings.get("subscriptions", [])
        all_nodes: List[Dict[str, Any]] = []

        update_intervals = settings.setdefault("update_intervals", {})
        last_update_times = settings.setdefault("last_update_times", {})

        self.log(f"Starting refresh of all subscriptions: {len(urls)} links")
        for url in urls:
            try:
                nodes, interval = self.parse_subscription(url)
                all_nodes.extend(nodes)
                last_update_times[url] = int(time.time())
                if interval is not None:
                    update_intervals[url] = int(interval)
            except Exception as e:
                self.log(f"Failed to parse subscription {url}: {e}")

        settings["update_intervals"] = update_intervals
        settings["last_update_times"] = last_update_times
        self.save_settings(settings)
        self.save_nodes(all_nodes)

        return all_nodes

    def add_subscription(self, url: str) -> List[Dict[str, Any]]:
        """Adds a single subscription and updates the node pool."""
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
        """Removes a subscription URL and prunes associated nodes."""
        settings = self.load_settings()
        subscriptions = settings.get("subscriptions", [])
        if url in subscriptions:
            subscriptions.remove(url)
            settings["subscriptions"] = subscriptions
            self.save_settings(settings)
            self.log(f"Removed subscription URL: {url}")
        return self.parse_all_subscriptions()

    def update_subscription(self, url: str) -> List[Dict[str, Any]]:
        """Updates a single subscription and merges into current cache."""
        self.log(f"Updating single subscription: {url}")
        new_nodes, interval = self.parse_subscription(url)

        current_nodes = self.load_nodes()
        # Retain nodes from other subscriptions
        merged_nodes = [n for n in current_nodes if n.get("subscription_url") != url]
        merged_nodes.extend(new_nodes)
        self.save_nodes(merged_nodes)

        settings = self.load_settings()
        last_updates = settings.setdefault("last_update_times", {})
        update_intervals = settings.setdefault("update_intervals", {})

        last_updates[url] = int(time.time())
        if interval is not None:
            update_intervals[url] = interval

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

    def generate_config(self, node: Dict[str, Any]) -> str:
        """Generates and writes xray-config.json for target node."""
        server_host = node["server"]
        server_ip = resolve_host(server_host) or server_host
        self.log(f"Generating Xray config for: {server_host} (resolved IP: {server_ip})")

        settings = self.load_settings()
        preset = settings.get("selected_preset", PRESET_DEFAULT)

        config_data = build_xray_config(node, server_ip, preset=preset)

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)

        self.log(f"Config written to {self.config_path}")
        return server_ip

    # ────────────────────────────────────────────────
    # Process & Routing Lifecycle
    # ────────────────────────────────────────────────

    def start(self, node: Dict[str, Any]) -> bool:
        """
        Starts Xray core + tun2socks and configures full system TUN routing.
        Uses fast socket & interface polling instead of hardcoded sleeps.
        """
        self.stop()

        if not self.ensure_binaries():
            self.log("Required binaries (xray/tun2socks) unavailable, aborting start.")
            return False

        gw_ip, iface = get_default_gateway()
        self.log(f"Detected default gateway: {gw_ip} via {iface}")

        server_ip = self.generate_config(node)

        # Validate config file syntax
        valid, err_msg = validate_xray_config(self.xray_path, self.config_path, self._get_clean_env())
        if not valid:
            self.log(f"Xray config validation failed: {err_msg}")
            return False

        # 1. Start Xray-core
        xray_log_path = os.path.join(self.settings_dir, "xray.log")
        try:
            xray_log = open(xray_log_path, "w")
            self.xray_process = subprocess.Popen(
                [self.xray_path, "-config", self.config_path],
                stdout=xray_log,
                stderr=xray_log,
                env=self._get_clean_env(),
                start_new_session=True,
            )
            xray_log.close()
            self.log(f"Xray started, PID={self.xray_process.pid}")
        except Exception as e:
            self.log(f"Failed to spawn Xray process: {e}")
            self.stop()
            return False

        # Efficient poll for SOCKS port readiness (up to 2.0s, step 50ms)
        if not wait_for_port(DEFAULT_SOCKS_HOST, DEFAULT_SOCKS_PORT, timeout=2.0, interval=0.05):
            self.log(f"Xray failed to bind to {DEFAULT_SOCKS_HOST}:{DEFAULT_SOCKS_PORT} within timeout")
            self.stop()
            return False

        # 2. Start tun2socks
        tun_log_path = os.path.join(self.settings_dir, "tun2socks.log")
        try:
            tun_log = open(tun_log_path, "w")
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

        # 3. Configure IP address and routing table
        run_command(["ip", "addr", "add", TUN_IP_CIDR, "dev", TUN_INTERFACE])
        run_command(["ip", "link", "set", "dev", TUN_INTERFACE, "up"])

        # Bypass route to VPN server via real default gateway to prevent routing loop
        if server_ip and gw_ip and iface:
            run_command(["ip", "route", "add", server_ip, "via", gw_ip, "dev", iface])

        # Route default traffic via TUN interface with top priority (metric 1)
        run_command(["ip", "route", "add", "default", "dev", TUN_INTERFACE, "metric", "1"])

        # Configure systemd-resolved DNS for tun0
        run_command(["resolvectl", "dns", TUN_INTERFACE] + DNS_SERVERS)
        run_command(["resolvectl", "domain", TUN_INTERFACE, "~."])
        run_command(["resolvectl", "default-route", TUN_INTERFACE, "yes"])

        self._last_server_ip = server_ip
        self._last_gw_ip = gw_ip
        self._last_iface = iface

        settings = self.load_settings()
        settings["selected_node"] = node
        settings["_routing_state"] = {
            "server_ip": server_ip,
            "gw_ip": gw_ip,
            "iface": iface,
        }
        self.save_settings(settings)
        self.log(f"VPN connected successfully to: {node.get('name')}")
        return True

    def stop(self) -> None:
        """Tears down routing and terminates proxy processes safely."""
        self.log("Stopping VPN (xray + tun2socks)...")

        settings = self.load_settings()
        routing_state = settings.get("_routing_state") or {}
        server_ip = self._last_server_ip or routing_state.get("server_ip")
        gw_ip = self._last_gw_ip or routing_state.get("gw_ip")
        iface = self._last_iface or routing_state.get("iface")

        # 1. Rollback system routing
        run_command(["ip", "route", "del", "default", "dev", TUN_INTERFACE, "metric", "1"])
        if server_ip and gw_ip and iface:
            run_command(["ip", "route", "del", server_ip, "via", gw_ip, "dev", iface])
        run_command(["resolvectl", "revert", TUN_INTERFACE])
        run_command(["ip", "link", "delete", TUN_INTERFACE])

        # 2. Terminate child processes
        for proc in (self.tun_process, self.xray_process, self.process):
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=0.3)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

        # 3. Targeted process cleanup
        for bin_path in (self.tun2socks_path, self.xray_path):
            try:
                subprocess.run(["pkill", "-f", bin_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

        self.tun_process = None
        self.xray_process = None
        self.process = None
        self._last_server_ip = None
        self._last_gw_ip = None
        self._last_iface = None

        settings["selected_node"] = None
        settings.pop("_routing_state", None)
        self.save_settings(settings)
        self.log("VPN stopped cleanly.")

    def is_running(self) -> bool:
        """Verifies if both xray and tun2socks processes are actively running."""
        try:
            res_xray = subprocess.run(["pgrep", "-f", self.xray_path], stdout=subprocess.PIPE)
            res_tun = subprocess.run(["pgrep", "-f", self.tun2socks_path], stdout=subprocess.PIPE)
            if res_xray.returncode == 0 and res_tun.returncode == 0:
                return True
            # Fallback to name check if binary paths were symlinked
            res_xray_name = subprocess.run(["pgrep", "-x", "xray"], stdout=subprocess.PIPE)
            res_tun_name = subprocess.run(["pgrep", "-x", "tun2socks"], stdout=subprocess.PIPE)
            return res_xray_name.returncode == 0 and res_tun_name.returncode == 0
        except Exception:
            return False

    def get_singbox_log(self) -> str:
        """Returns logs from Xray and tun2socks."""
        logs = []
        for name, fname in [("XRAY", "xray.log"), ("TUN2SOCKS", "tun2socks.log")]:
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
