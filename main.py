"""
Decky Loader Python Plugin entrypoint for sub-deck.
Acts as an asynchronous RPC bridge between the React frontend and core engine.
"""

import os
import sys
import re
import shutil
import asyncio
import time
try:
    import decky
except ImportError:
    import types
    import logging
    decky = types.ModuleType("decky")
    decky.logger = logging.getLogger("sub-deck")

# Ensure plugin directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.system import get_user_home, read_system_clipboard, get_default_gateway, get_target_uid_gid
from core.server import SubDeckApiServer
from tray.desktop_integration import (
    set_autostart,
    ensure_desktop_autostart_and_service,
    get_desktop_integration_status,
    launch_tray_process,
    kill_tray_process,
)
from vpn_manager import VPNManager


def resolve_and_migrate_settings_dir(logger=None) -> str:
    """
    Resolves settings directory according to Decky standards and migrates
    legacy ~/.config/sub-deck files if necessary.
    """
    legacy_dir = os.path.join(get_user_home(), ".config", "sub-deck")
    target_dir = (
        getattr(decky, "DECKY_PLUGIN_SETTINGS_DIR", None)
        or os.environ.get("DECKY_PLUGIN_SETTINGS_DIR")
        or legacy_dir
    )
    os.makedirs(target_dir, exist_ok=True)

    # Migrate files from legacy directory if target_dir is different
    if os.path.abspath(target_dir) != os.path.abspath(legacy_dir) and os.path.isdir(legacy_dir):
        try:
            for item in os.listdir(legacy_dir):
                src = os.path.join(legacy_dir, item)
                dst = os.path.join(target_dir, item)
                if not os.path.exists(dst):
                    if os.path.isfile(src):
                        shutil.copy2(src, dst)
                        if logger:
                            logger.info(f"Migrated {item} from {legacy_dir} to {target_dir}")
                    elif os.path.isdir(src):
                        shutil.copytree(src, dst)
                        if logger:
                            logger.info(f"Migrated directory {item} from {legacy_dir} to {target_dir}")
        except Exception as e:
            if logger:
                logger.warning(f"Error migrating legacy settings from {legacy_dir}: {e}")

    return target_dir


class Plugin:
    """Decky plugin adapter class."""

    def __init__(self):
        self.loop = None
        self.vpn = None
        self.update_task = None
        self.sleep_task = None
        self.api_server = None

    async def _main(self):
        """Invoked by Decky Loader when the plugin is loaded."""
        self.loop = asyncio.get_running_loop()

        plugin_dir = os.environ.get(
            "DECKY_PLUGIN_DIR",
            os.path.dirname(os.path.abspath(__file__))
        )
        settings_dir = resolve_and_migrate_settings_dir(logger=decky.logger)

        self.vpn = VPNManager(plugin_dir, settings_dir, logger=decky.logger)
        decky.logger.info(f"sub-deck loaded. settings_dir={settings_dir}")

        # Clean up any stale interfaces or processes from ungraceful shutdown
        try:
            await self.loop.run_in_executor(None, self.vpn.cleanup_stale)
        except Exception as e:
            decky.logger.warning(f"Error during stale cleanup: {e}")

        try:
            bin_exts = {".sh", ""}
            for root, dirs, files in os.walk(plugin_dir):
                for d in dirs:
                    try:
                        os.chmod(os.path.join(root, d), 0o755)
                    except Exception:
                        pass
                for f in files:
                    fpath = os.path.join(root, f)
                    try:
                        _, ext = os.path.splitext(f)
                        if (ext in bin_exts and os.path.isfile(fpath)) or root.endswith("/bin"):
                            os.chmod(fpath, 0o755)
                        else:
                            os.chmod(fpath, 0o644)
                    except Exception:
                        pass
        except Exception:
            pass

        # Start background workers (subscription updates and sleep/wake monitor)
        self.update_task = asyncio.create_task(self._auto_update_loop())
        self.sleep_task = asyncio.create_task(self._sleep_monitor_loop())

        # Start local IPC API server for Desktop Mode tray integration
        self.api_server = SubDeckApiServer(self, logger=decky.logger)
        await self.api_server.start()

        # Desktop tray integration: ALWAYS ensure autostart .desktop and systemd user service exist
        try:
            await self.loop.run_in_executor(None, ensure_desktop_autostart_and_service, plugin_dir)
        except Exception as e:
            decky.logger.warning(f"Error ensuring desktop autostart and service: {e}")

        # Desktop tray process launch if enabled
        settings = self.vpn.load_settings()
        tray_enabled = settings.get("desktop_tray_enabled", True)
        if "desktop_tray_enabled" not in settings:
            if not getattr(self.vpn, "_settings_read_failed", False):
                settings["desktop_tray_enabled"] = True
                self.vpn.save_settings(settings)
            else:
                decky.logger.warning("Skipping automatic save_settings because settings load failed.")

        if tray_enabled:
            try:
                await self.loop.run_in_executor(None, launch_tray_process, plugin_dir)
            except Exception as e:
                decky.logger.error(f"Failed to start desktop tray: {e}")


    # ────────────────────────────────────────────────
    # Frontend RPC API
    # ────────────────────────────────────────────────

    async def get_settings(self) -> dict:
        settings = self.vpn.load_settings()
        if not settings.get("selected_node"):
            nodes = self.vpn.get_nodes()
            if nodes:
                settings["selected_node"] = nodes[0]
                with self.vpn._storage.lock:
                    self.vpn.save_settings(settings)
        return settings

    async def save_subscription_url(self, url: str) -> list:
        """Legacy method forwarding to add_subscription."""
        return await self.add_subscription(url)

    async def add_subscription(self, url: str) -> list:
        nodes = await self.loop.run_in_executor(None, self.vpn.add_subscription, url)
        return nodes

    async def remove_subscription(self, url: str) -> list:
        nodes = await self.loop.run_in_executor(None, self.vpn.remove_subscription, url)
        return nodes

    async def update_subscription(self, url: str) -> list:
        nodes = await self.loop.run_in_executor(None, self.vpn.update_subscription, url)
        return nodes

    async def save_preset(self, preset: str) -> bool:
        await self.loop.run_in_executor(None, self.vpn.save_preset, preset)
        return True

    async def update_routing_presets(self) -> dict:
        """Downloads and atomically updates Throne routing presets and geofiles."""
        return await self.loop.run_in_executor(None, self.vpn.update_routing_presets)

    async def generate_warp_node(self) -> dict:
        """Registers/generates Cloudflare WARP WireGuard profile."""
        return await self.loop.run_in_executor(None, self.vpn.generate_warp_node, True)

    async def get_steam_language(self) -> str:
        """Discovers active Steam language from registry.vdf."""
        user_home = get_user_home()
        candidate_paths = [
            os.path.join(user_home, ".steam", "registry.vdf"),
            os.path.join(user_home, ".steam", "steam", "registry.vdf"),
            os.path.join(user_home, ".local", "share", "Steam", "registry.vdf"),
            "/home/deck/.steam/registry.vdf",
            "/home/deck/.steam/steam/registry.vdf",
        ]

        for path in candidate_paths:
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    match = re.search(r'"language"\s+"([^"]+)"', content, re.IGNORECASE)
                    if match:
                        lang = match.group(1).lower().strip()
                        decky.logger.info(f"Steam language detected: {lang}")
                        return lang
                except Exception as e:
                    decky.logger.error(f"Error reading Steam language from {path}: {e}")

        decky.logger.info("Steam language not found, defaulting to english")
        return "english"

    async def export_logs(self) -> str:
        """Aggregates sub-deck, Xray and tun2socks logs to ~/sub-deck.log."""
        def _export():
            user_home = get_user_home()
            possible_log_paths = [
                os.path.join(user_home, ".homebrew", "logs", "sub-deck", "main.log"),
                os.path.join(user_home, "homebrew", "logs", "sub-deck", "main.log"),
                os.path.join(user_home, ".local", "share", "decky-loader", "logs", "sub-deck", "main.log"),
                "/home/deck/.homebrew/logs/sub-deck/main.log",
                "/home/deck/homebrew/logs/sub-deck/main.log",
            ]

            plugin_logs = "--- No sub-deck logs found ---"
            for log_path in possible_log_paths:
                if os.path.exists(log_path):
                    try:
                        with open(log_path, "r", errors="replace", encoding="utf-8") as f:
                            lines = f.readlines()
                            plugin_logs = "".join(lines[-250:])
                            break
                    except Exception as e:
                        plugin_logs = f"Error reading sub-deck logs from {log_path}: {e}"

            def _read_tail(fpath: str, label: str) -> str:
                if os.path.exists(fpath):
                    try:
                        with open(fpath, "r", errors="replace", encoding="utf-8") as f:
                            return "".join(f.readlines()[-250:])
                    except Exception as e:
                        return f"Error reading {label} logs: {e}"
                return f"--- No {label} logs found ---"

            xray_log_path = os.path.join(self.vpn.settings_dir, "xray.log")
            singbox_log_path = os.path.join(self.vpn.settings_dir, "singbox.log")
            tun_log_path = os.path.join(self.vpn.settings_dir, "tun2socks.log")

            xray_logs = _read_tail(xray_log_path, "xray")
            singbox_logs = _read_tail(singbox_log_path, "singbox")
            tun_logs = _read_tail(tun_log_path, "tun2socks")

            combined = (
                "=== SUB-DECK SYSTEM LOGS ===\n"
                f"{plugin_logs}\n\n"
                "=== XRAY CORE LOGS ===\n"
                f"{xray_logs}\n\n"
                "=== SING-BOX CORE LOGS ===\n"
                f"{singbox_logs}\n\n"
                "=== TUN2SOCKS LOGS ===\n"
                f"{tun_logs}\n"
            )

            export_path = os.path.join(user_home, "sub-deck.log")
            try:
                with open(export_path, "w", encoding="utf-8") as f:
                    f.write(combined)
            except Exception as e:
                decky.logger.error(f"Failed to write exported logs to {export_path}: {e}")

            return combined

        return await self.loop.run_in_executor(None, _export)

    async def get_nodes(self) -> list:
        return self.vpn.get_nodes()

    async def ping_nodes(self, subscription_url: str = None) -> list:
        """
        Pings nodes in parallel (Throne method).
        If subscription_url is provided, only nodes from that subscription are tested.
        Updates cached nodes with new ping values and returns updated nodes.
        """
        from core.pinger import ping_all_nodes
        nodes = self.vpn.load_nodes()
        real_nodes = [n for n in nodes if n.get("type") != "auto_balancer"]

        if subscription_url:
            target_nodes = [n for n in real_nodes if n.get("subscription_url") == subscription_url]
        else:
            target_nodes = real_nodes

        if not target_nodes:
            return self.vpn.get_nodes()

        if subscription_url:
            from core.speedtest import speedtest_nodes
            xray_path = getattr(self.vpn, "xray_path", None)
            singbox_path = getattr(self.vpn, "singbox_path", None)
            updated_targets = await self.loop.run_in_executor(
                None,
                lambda: speedtest_nodes(
                    target_nodes,
                    xray_path=xray_path,
                    singbox_path=singbox_path,
                    max_workers=4,
                    timeout=5.0,
                ),
            )
            target_map = {
                (n.get("name"), n.get("server"), n.get("port")): n
                for n in updated_targets
            }
            for n in real_nodes:
                key = (n.get("name"), n.get("server"), n.get("port"))
                if key in target_map:
                    upd = target_map[key]
                    n["ping"] = upd.get("ping")
                    n["speed_down"] = upd.get("speed_down")
                    n["speed_up"] = upd.get("speed_up")
                    n["country_flag"] = upd.get("country_flag")
        else:
            updated_targets = await self.loop.run_in_executor(
                None, lambda: ping_all_nodes(target_nodes, timeout=2.0)
            )
            target_map = {
                (n.get("name"), n.get("server"), n.get("port")): n.get("ping")
                for n in updated_targets
            }
            for n in real_nodes:
                key = (n.get("name"), n.get("server"), n.get("port"))
                if key in target_map:
                    n["ping"] = target_map[key]

        await self.loop.run_in_executor(
            None, lambda: self.vpn.save_nodes(real_nodes, force=True)
        )
        return self.vpn.get_nodes()

    async def get_real_delay(self) -> dict:
        """Measures real end-to-end HTTP 204 latency through current connection (active TUN)."""
        from core.pinger import http_url_test
        delay = await self.loop.run_in_executor(
            None, lambda: http_url_test(timeout=3.0)
        )
        return {"success": delay is not None, "delay_ms": int(delay) if delay else None}

    async def auto_select_best_node(self) -> dict:
        """
        Finds the best responsive node with lowest latency among available working nodes,
        configures the leastPing auto-balancer or connects to it,
        and returns the chosen node details (name, ping, success).
        """
        from core.pinger import find_best_node
        from core.system import clean_node_name

        nodes = self.vpn.load_nodes()
        candidate_nodes = [n for n in nodes if n.get("type") != "auto_balancer"]
        if not candidate_nodes:
            return {"success": False, "error": "No nodes available"}

        best_node = await self.loop.run_in_executor(
            None, lambda: find_best_node(candidate_nodes, timeout=1.5, log_func=self.vpn.log)
        )
        if not best_node:
            best_node = candidate_nodes[0]

        best_ping = best_node.get("ping")
        # Update cached ping in vpn if ping was measured
        if best_ping:
            try:
                for n in candidate_nodes:
                    if n.get("server") == best_node.get("server") and n.get("port") == best_node.get("port"):
                        n["ping"] = best_ping
                await self.loop.run_in_executor(
                    None, lambda: self.vpn.save_nodes(candidate_nodes, force=True)
                )
            except Exception as e:
                decky.logger.warning(f"Failed to update ping cache: {e}")

        # Construct auto balancer node
        auto_node = {
            "type": "auto_balancer",
            "name": "Авто-выбор сервера",
            "server": "auto",
            "port": 0,
            "ping": best_ping or 1,
            "uuid": "auto-balancer",
            "best_node": best_node
        }

        # Check if best_node is a Sing-box node or Xray node
        is_singbox_best = best_node.get("type") in ("awg", "hysteria2", "hy2", "tuic", "wireguard", "warp")

        # Check if candidate_nodes have any Xray-compatible nodes
        xray_candidates = [
            n for n in candidate_nodes
            if n.get("type") in ("vless", "vmess", "trojan", "shadowsocks", "balancer")
        ]

        if not is_singbox_best and xray_candidates:
            target_to_start = auto_node
        else:
            # If best node is Sing-box (AWG / Hysteria 2 / WARP) or no Xray nodes exist, connect to best_node
            target_to_start = best_node

        success = await self.loop.run_in_executor(None, self.vpn.start, target_to_start)
        clean_name = clean_node_name(best_node.get("name", ""))
        decky.logger.info(f"auto_select_best_node selected '{clean_name}' (ping: {best_ping}ms): success={success}")

        return {
            "success": bool(success),
            "node_name": clean_name,
            "ping": int(best_ping) if best_ping else None,
            "server": best_node.get("server"),
            "best_node": best_node,
        }

    async def connect_node(self, node: dict) -> bool:
        success = await self.loop.run_in_executor(None, self.vpn.start, node)
        decky.logger.info(f"connect_node '{node.get('name')}': success={success}")
        return success

    async def disconnect(self) -> bool:
        return await self.loop.run_in_executor(None, self.vpn.stop)

    async def is_connected(self) -> bool:
        return self.vpn.is_running()

    async def get_selected_node(self):
        settings = self.vpn.load_settings()
        node = settings.get("selected_node")
        if not node:
            nodes = self.vpn.get_nodes()
            if nodes:
                node = nodes[0]
                with self.vpn._storage.lock:
                    settings["selected_node"] = node
                    self.vpn.save_settings(settings)
        return node

    async def get_clipboard(self) -> str:
        """Reads system clipboard (X11 / Gamescope and KDE Klipper)."""
        return await self.loop.run_in_executor(None, read_system_clipboard)

    async def check_and_update_subscriptions(self) -> None:
        """Checks update intervals and refreshes subscriptions when expired."""
        settings = self.vpn.load_settings()
        urls = settings.get("subscriptions", [])
        intervals = settings.get("update_intervals", {})
        last_updates = settings.get("last_update_times", {})

        now = int(time.time())
        updated_any = False

        for url in urls:
            interval_hours = intervals.get(url)
            if not interval_hours:
                continue

            last_update = last_updates.get(url, 0)
            if now - last_update >= interval_hours * 3600:
                try:
                    await self.loop.run_in_executor(
                        None, self.vpn.update_subscription, url
                    )
                    updated_any = True
                except Exception as e:
                    decky.logger.error(f"Failed to auto-update subscription {url}: {e}")

        if updated_any:
            decky.logger.info("Subscriptions auto-updated successfully.")

    async def _auto_update_loop(self) -> None:
        """Periodic background worker for subscriptions and geofiles."""
        await asyncio.sleep(30)
        while True:
            try:
                await self.check_and_update_subscriptions()
                await self.loop.run_in_executor(None, self.vpn.update_geofiles)
            except asyncio.CancelledError:
                break
            except Exception as e:
                decky.logger.error(f"Auto update loop error: {e}")
            await asyncio.sleep(900)

    async def _sleep_monitor_loop(self) -> None:
        """Detects Linux suspend time and reconnects when the physical network returns."""
        last_suspend_time = time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()
        while True:
            try:
                await asyncio.sleep(3)
                suspend_time = time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()
                suspended_for = suspend_time - last_suspend_time
                last_suspend_time = suspend_time
                if suspended_for < 0.5 or not self.vpn:
                    continue

                decky.logger.info(f"Steam Deck resumed after {suspended_for:.1f}s asleep")
                vpn = self.vpn
                generation = await self.loop.run_in_executor(None, vpn.resume_generation)
                if generation is None:
                    continue

                network_ready = False
                deadline = self.loop.time() + 10.0
                while self.loop.time() < deadline:
                    gw, iface = await self.loop.run_in_executor(None, get_default_gateway)
                    if gw and iface:
                        network_ready = True
                        break
                    await asyncio.sleep(0.5)

                if not network_ready:
                    decky.logger.warning("No network after resume. Clearing the stale VPN tunnel.")
                await self.loop.run_in_executor(None, vpn.recover_after_resume, generation, network_ready)
            except asyncio.CancelledError:
                break
            except Exception as e:
                decky.logger.error(f"Error in sleep monitor: {e}")

    async def get_desktop_status(self) -> dict:
        """Returns desktop tray integration status."""
        settings = self.vpn.load_settings()
        enabled = settings.get("desktop_tray_enabled", True)
        return {"enabled": enabled}

    async def set_desktop_autostart(self, enable: bool) -> bool:
        """Toggles desktop tray companion auto-run and active process."""
        settings = self.vpn.load_settings()
        settings["desktop_tray_enabled"] = enable
        self.vpn.save_settings(settings)

        plugin_dir = self.vpn.plugin_dir if self.vpn else os.path.dirname(os.path.abspath(__file__))
        if enable:
            await self.loop.run_in_executor(None, set_autostart, plugin_dir, True)
            await self.loop.run_in_executor(None, launch_tray_process, plugin_dir)
        else:
            await self.loop.run_in_executor(None, set_autostart, plugin_dir, False)
            await self.loop.run_in_executor(None, kill_tray_process, plugin_dir)
        return True

    async def launch_desktop_tray(self) -> bool:
        """Launches the desktop tray widget in the active graphical desktop session."""
        plugin_dir = self.vpn.plugin_dir if self.vpn else os.path.dirname(os.path.abspath(__file__))
        return await self.loop.run_in_executor(None, launch_tray_process, plugin_dir)

    # ────────────────────────────────────────────────
    # Lifecycle
    # ────────────────────────────────────────────────

    async def _unload(self) -> None:
        if self.api_server:
            try:
                await self.api_server.stop()
            except Exception as e:
                decky.logger.error(f"Error stopping API server: {e}")
        if self.update_task:
            self.update_task.cancel()
        if self.sleep_task:
            self.sleep_task.cancel()
        if self.vpn:
            if self.loop:
                await self.loop.run_in_executor(None, self.vpn.stop)
            else:
                self.vpn.stop()
        try:
            plugin_dir = self.vpn.plugin_dir if self.vpn else os.path.dirname(os.path.abspath(__file__))
            if self.loop:
                await self.loop.run_in_executor(None, kill_tray_process, plugin_dir)
            else:
                kill_tray_process(plugin_dir)
        except Exception as e:
            decky.logger.warning(f"Error killing tray process in _unload: {e}")
        decky.logger.info("sub-deck unloaded")

    async def _uninstall(self) -> None:
        if self.api_server:
            try:
                await self.api_server.stop()
            except Exception as e:
                pass
        if self.update_task:
            self.update_task.cancel()
        if self.sleep_task:
            self.sleep_task.cancel()
        if self.vpn:
            await self.loop.run_in_executor(None, self.vpn.stop)
        # Also remove autostart and kill tray process when uninstalled
        try:
            plugin_dir = self.vpn.plugin_dir if self.vpn else os.path.dirname(os.path.abspath(__file__))
            set_autostart(plugin_dir, False)
            kill_tray_process(plugin_dir)
        except Exception:
            pass
        decky.logger.info("sub-deck uninstalled")

    async def _migration(self) -> None:
        pass

