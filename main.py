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
from core.system import get_user_home, read_system_clipboard
from vpn_manager import VPNManager


class Plugin:
    """Decky plugin adapter class."""

    def __init__(self):
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.vpn: Optional[VPNManager] = None
        self.update_task: Optional[asyncio.Task] = None

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

        # Start background update daemon
        self.update_task = asyncio.create_task(self._auto_update_loop())

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
        if preset == PRESET_ROSCOMVPN:
            await self.loop.run_in_executor(None, self.vpn.update_geofiles, False)
        return True

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
            tun_log_path = os.path.join(self.vpn.settings_dir, "tun2socks.log")

            xray_logs = _read_tail(xray_log_path, "xray")
            tun_logs = _read_tail(tun_log_path, "tun2socks")

            combined = (
                "=== SUB-DECK SYSTEM LOGS ===\n"
                f"{plugin_logs}\n\n"
                "=== XRAY CORE LOGS ===\n"
                f"{xray_logs}\n\n"
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
                decky.logger.info(f"Auto-updating subscription: {url} (interval: {interval_hours}h)")
                try:
                    _, interval = await self.loop.run_in_executor(
                        None, self.vpn.parse_subscription, url
                    )
                    last_updates[url] = now
                    if interval is not None:
                        intervals[url] = int(interval)
                    updated_any = True
                except Exception as e:
                    decky.logger.error(f"Failed to auto-update subscription {url}: {e}")

        if updated_any:
            settings["last_update_times"] = last_updates
            settings["update_intervals"] = intervals
            self.vpn.save_settings(settings)
            await self.loop.run_in_executor(None, self.vpn.parse_all_subscriptions)
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

    # ────────────────────────────────────────────────
    # Lifecycle
    # ────────────────────────────────────────────────

    async def _unload(self) -> None:
        if self.update_task:
            self.update_task.cancel()
        if self.vpn:
            await self.loop.run_in_executor(None, self.vpn.stop)
        decky.logger.info("sub-deck unloaded")

    async def _uninstall(self) -> None:
        if self.vpn:
            await self.loop.run_in_executor(None, self.vpn.stop)
        decky.logger.info("sub-deck uninstalled")

    async def _migration(self) -> None:
        pass
