"""
VPN Manager module for sub-deck.
Coordinates proxy cores (Xray-core + tun2socks), routing and subscription states.
"""

import os
import json
import subprocess
import tempfile
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

    def __init__(self, plugin_dir: str, settings_dir: str, logger=None):
        self.plugin_dir = plugin_dir
        self.settings_dir = settings_dir
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
        """Persists settings atomically using a temporary file."""
        tmp_file = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=self.settings_dir, delete=False, encoding="utf-8") as f:
                tmp_file = f.name
                json.dump(settings, f, indent=2)
            try:
                os.chmod(tmp_file, 0o666)
            except Exception:
                pass
            os.replace(tmp_file, self.settings_file)
            try:
                os.chmod(self.settings_file, 0o666)
            except Exception:
                pass
        except Exception as e:
            self.log(f"Failed to save settings: {e}")
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass

    def get_nodes(self) -> List[Dict[str, Any]]:
        """Returns cached proxy nodes, prepending the auto least-ping virtual node if multiple nodes exist."""
        nodes = []
        if os.path.exists(self.nodes_cache_path):
            try:
                with open(self.nodes_cache_path, "r", encoding="utf-8") as f:
                    raw_nodes = json.load(f)
                    for n in raw_nodes:
                        n["name"] = clean_node_name(n.get("name", ""))
                        nodes.append(n)
            except Exception:
                pass

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

    def save_nodes(self, nodes: List[Dict[str, Any]]) -> None:
        """Persists nodes list to disk atomically using a temporary file."""
        clean_nodes = [n for n in nodes if n.get("type") != "auto_balancer"]
        tmp_file = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=self.settings_dir, delete=False, encoding="utf-8") as f:
                tmp_file = f.name
                json.dump(clean_nodes, f)
            try:
                os.chmod(tmp_file, 0o666)
            except Exception:
                pass
            os.replace(tmp_file, self.nodes_cache_path)
            try:
                os.chmod(self.nodes_cache_path, 0o666)
            except Exception:
                pass
            self.log(f"Saved total of {len(clean_nodes)} nodes to cache.")
        except Exception as e:
            self.log(f"Failed to save nodes cache: {e}")
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass

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
        settings = self.load_settings()
        urls = settings.get("subscriptions", [])
        all_nodes: List[Dict[str, Any]] = []

        update_intervals = settings.setdefault("update_intervals", {})
        last_update_times = settings.setdefault("last_update_times", {})
        sub_metadata = settings.setdefault("subscription_metadata", {})

        self.log(f"Starting refresh of all subscriptions: {len(urls)} links")
        for url in urls:
            try:
                nodes, interval, meta = self.parse_subscription(url)
                all_nodes.extend(nodes)
                now_ts = int(time.time())
                last_update_times[url] = now_ts
                if interval is not None:
                    update_intervals[url] = int(interval)
                if meta:
                    existing_meta = sub_metadata.get(url, {})
                    existing_meta.update(meta)
                    existing_meta["last_updated"] = now_ts
                    sub_metadata[url] = existing_meta
            except Exception as e:
                self.log(f"Failed to parse subscription {url}: {e}")

        settings["update_intervals"] = update_intervals
        settings["last_update_times"] = last_update_times
        settings["subscription_metadata"] = sub_metadata
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
        """Removes a subscription URL and prunes associated nodes and metadata."""
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
        new_nodes, interval, meta = self.parse_subscription(url)

        current_nodes = self.load_nodes()
        # Retain nodes from other subscriptions
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
                        if resolved and resolved not in server_ips:
                            server_ips.append(resolved)
                for srv in settings.get("servers", []):
                    addr = srv.get("address")
                    if addr:
                        resolved = resolve_host(addr) or addr
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

            has_port_53_rule = any(r.get("port") in ("53", 53) for r in rules)
            if not has_port_53_rule:
                dns_outbound_tag = "proxy"
                for ob in config_data.get("outbounds", []):
                    tag = ob.get("tag")
                    net = ob.get("streamSettings", {}).get("network", "tcp")
                    if tag in ("proxy", "proxy-2", "direct") and net != "xhttp":
                        dns_outbound_tag = tag
                        break
                rules.insert(0, {
                    "type": "field",
                    "port": "53",
                    "outboundTag": dns_outbound_tag
                })

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

        # 2. Terminate child processes
        for proc in (self.tun_process, self.xray_process, self.singbox_process, self.process):
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
        for bin_path in (self.tun2socks_path, self.xray_path, self.singbox_path):
            try:
                subprocess.run(["pkill", "-f", bin_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
                subprocess.run(["pkill", "-f", bin_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

        settings = self.load_settings()
        if "_routing_state" in settings:
            settings.pop("_routing_state", None)
            settings["selected_node"] = None
            self.save_settings(settings)

    def is_running(self) -> bool:
        """Verifies if (xray OR sing-box) AND tun2socks processes are actively running."""
        # Fast path: check in-memory process objects first (zero subprocess overhead)
        tun_alive = self.tun_process is not None and self.tun_process.poll() is None
        core_alive = (
            (self.xray_process is not None and self.xray_process.poll() is None) or
            (self.singbox_process is not None and self.singbox_process.poll() is None)
        )
        if tun_alive and core_alive:
            return True

        # Fallback: check system processes if handles are not active or after plugin reload
        try:
            tun_check = subprocess.run(
                ["pgrep", "-f", "tun2socks"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=0.5,
            )
            if tun_check.returncode != 0:
                return False

            core_check = subprocess.run(
                ["pgrep", "-f", "xray|sing-box"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=0.5,
            )
            return core_check.returncode == 0
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
