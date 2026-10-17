"""
Decky Loader Python Plugin entrypoint for sub-deck.
Acts as an asynchronous RPC bridge between the React frontend and core engine.
"""

import os
import sys
import re
import asyncio
import time
import decky

# Ensure plugin directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.constants import FREE_SUBSCRIPTIONS, PRESET_ROSCOMVPN
from core.system import get_user_home, read_system_clipboard, get_default_gateway
from core.server import SubDeckApiServer
from tray.desktop_integration import (
    set_autostart,
    get_desktop_integration_status,
    launch_tray_process,
    kill_tray_process,
)
from vpn_manager import VPNManager


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
        settings_dir = os.environ.get(
            "DECKY_PLUGIN_SETTINGS_DIR",
            os.path.join(get_user_home(), ".config", "sub-deck")
        )

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

        # Desktop tray integration (enabled by default on installation)
        settings = self.vpn.load_settings()
        tray_enabled = settings.get("desktop_tray_enabled", True)
        if "desktop_tray_enabled" not in settings:
            settings["desktop_tray_enabled"] = True
            self.vpn.save_settings(settings)

        if tray_enabled:
            try:
                await self.loop.run_in_executor(None, set_autostart, plugin_dir, True)
                await self.loop.run_in_executor(None, launch_tray_process, plugin_dir)
            except Exception as e:
                decky.logger.error(f"Failed to start desktop tray: {e}")


    # ────────────────────────────────────────────────
    # Frontend RPC API
    # ────────────────────────────────────────────────

    async def get_settings(self) -> dict:
        return self.vpn.load_settings()

    async def save_subscription_url(self, url: str) -> list:
        """Legacy method forwarding to add_subscription."""
        return await self.add_subscription(url)

    async def add_subscription(self, url: str) -> list:
        nodes = await self.loop.run_in_executor(None, self.vpn.add_subscription, url)
        return nodes

    async def add_free_subscriptions(self) -> list:
        nodes = await self.loop.run_in_executor(
            None, self.vpn.add_multiple_subscriptions, FREE_SUBSCRIPTIONS
        )
        return nodes

    async def remove_subscription(self, url: str) -> list:
        nodes = await self.loop.run_in_executor(None, self.vpn.remove_subscription, url)
        return nodes

    async def update_subscription(self, url: str) -> list:
        nodes = await self.loop.run_in_executor(None, self.vpn.update_subscription, url)
        return nodes

    async def save_preset(self, preset: str) -> bool:
        settings = self.vpn.load_settings()
        settings["selected_preset"] = preset
        self.vpn.save_settings(settings)
        if preset in (PRESET_ROSCOMVPN, "bypass_ru"):
            await self.loop.run_in_executor(None, self.vpn.update_geofiles, False)
        # If VPN is actively running, hot-restart with new preset routing rules
        if self.vpn.is_running():
            node = settings.get("selected_node")
            if node:
                await self.loop.run_in_executor(None, self.vpn.start, node)
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

    async def connect_node(self, node: dict) -> bool:
        success = await self.loop.run_in_executor(None, self.vpn.start, node)
        decky.logger.info(f"connect_node '{node.get('name')}': success={success}")
        return success

    async def disconnect(self) -> bool:
        await self.loop.run_in_executor(None, self.vpn.stop)
        return True

    async def is_connected(self) -> bool:
        return self.vpn.is_running()

    async def get_selected_node(self):
        settings = self.vpn.load_settings()
        return settings.get("selected_node")

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
        """Monitors system sleep/resume events and seamlessly restores VPN connectivity."""
        last_tick = time.monotonic()
        while True:
            try:
                await asyncio.sleep(3)
                now = time.monotonic()
                delta = now - last_tick
                last_tick = now

                # If loop interval exceeded 8 seconds, system was suspended/slept
                if delta > 8.0:
                    decky.logger.info(f"Steam Deck resume detected (suspend delta ~{delta:.1f}s)")
                    if self.vpn and self.vpn.is_running():
                        decky.logger.info("VPN was active before sleep. Waiting for Wi-Fi / network gateway...")
                        settings = self.vpn.load_settings()
                        node = settings.get("selected_node")

                        # Wait up to 10 seconds (20 iterations of 0.5s) for network gateway
                        gw, iface = None, None
                        for _ in range(20):
                            await asyncio.sleep(0.5)
                            gw, iface = get_default_gateway()
                            if gw and iface:
                                break

                        if node and gw and iface:
                            decky.logger.info(f"Network restored ({iface} via {gw}). Re-establishing tunnel...")
                            await self.loop.run_in_executor(None, self.vpn.start, node)
                        else:
                            decky.logger.warning("No network detected after resume. Tearing down stale tunnel to prevent routing lock.")
                            await self.loop.run_in_executor(None, self.vpn.stop)
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
            await self.loop.run_in_executor(None, kill_tray_process)
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
            await self.loop.run_in_executor(None, self.vpn.stop)
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
            kill_tray_process()
        except Exception:
            pass
        decky.logger.info("sub-deck uninstalled")

    async def _migration(self) -> None:
        pass

