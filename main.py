import os
import sys
import re
import asyncio
import decky

# Добавляем папку плагина в sys.path — Decky Loader не делает это автоматически
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vpn_manager import VPNManager


def get_user_home() -> str:
    """Надежно определяет домашнюю директорию пользователя, обходя root."""
    env_home = os.environ.get("DECKY_USER_HOME")
    if env_home and os.path.isdir(env_home):
        return env_home
        
    try:
        if hasattr(decky, "DECKY_USER_HOME") and decky.DECKY_USER_HOME:
            if os.path.isdir(decky.DECKY_USER_HOME):
                return decky.DECKY_USER_HOME
    except Exception:
        pass
        
    if os.path.isdir("/home/deck"):
        return "/home/deck"
        
    if os.path.isdir("/home"):
        try:
            for user in os.listdir("/home"):
                if user != "lost+found":
                    user_path = f"/home/{user}"
                    if os.path.isdir(user_path):
                        return user_path
        except Exception:
            pass
            
    return os.path.expanduser("~")


class Plugin:

    async def _main(self):
        """Вызывается Decky при загрузке плагина."""
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

    # ────────────────────────────────────────────────
    # API для фронтенда
    # ────────────────────────────────────────────────

    async def get_settings(self) -> dict:
        return self.vpn.load_settings()

    async def save_subscription_url(self, url: str) -> list:
        # Legacy-метод, теперь просто вызывает add_subscription
        return await self.add_subscription(url)

    async def add_subscription(self, url: str) -> list:
        nodes = await self.loop.run_in_executor(
            None, self.vpn.add_subscription, url
        )
        return nodes

    async def remove_subscription(self, url: str) -> list:
        nodes = await self.loop.run_in_executor(
            None, self.vpn.remove_subscription, url
        )
        return nodes

    async def update_subscription(self, url: str) -> list:
        nodes = await self.loop.run_in_executor(
            None, self.vpn.update_subscription, url
        )
        return nodes


    async def get_steam_language(self) -> str:
        """Считывает язык из Steam registry.vdf (как в warp-deck)"""
        paths = []
        if os.path.isdir("/home"):
            try:
                for user in os.listdir("/home"):
                    if user != "lost+found":
                        paths.append(f"/home/{user}/.steam/registry.vdf")
                        paths.append(f"/home/{user}/.steam/steam/registry.vdf")
            except Exception:
                pass
        
        paths.append(os.path.expanduser("~/.steam/registry.vdf"))
        paths.append(os.path.expanduser("~/.steam/steam/registry.vdf"))
        
        for path in paths:
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
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
        """Экспортирует объединенные логи в /home/deck/sub-deck.log и возвращает их."""
        def _export():
            plugin_log_path = "/home/deck/homebrew/logs/sub-deck/sub-deck.log"
            singbox_log_path = os.path.join(self.vpn.settings_dir, "sing-box.log")
            
            plugin_logs = "--- No sub-deck logs found ---"
            if os.path.exists(plugin_log_path):
                try:
                    with open(plugin_log_path, "r", errors="replace") as f:
                        lines = f.readlines()
                        plugin_logs = "".join(lines[-250:]) # Последние 250 строк
                except Exception as e:
                    plugin_logs = f"Error reading sub-deck logs: {e}"
            
            singbox_logs = "--- No sing-box logs found ---"
            if os.path.exists(singbox_log_path):
                try:
                    with open(singbox_log_path, "r", errors="replace") as f:
                        lines = f.readlines()
                        singbox_logs = "".join(lines[-250:]) # Последние 250 строк
                except Exception as e:
                    singbox_logs = f"Error reading sing-box logs: {e}"
            
            combined = (
                "=== SUB-DECK SYSTEM LOGS ===\n"
                f"{plugin_logs}\n\n"
                "=== SING-BOX CORE LOGS ===\n"
                f"{singbox_logs}\n"
            )
            
            # Сохраняем в доступное место на Steam Deck
            export_path = "/home/deck/sub-deck.log"
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
        success = await self.loop.run_in_executor(
            None, self.vpn.start, node
        )
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

    # ────────────────────────────────────────────────
    # Lifecycle
    # ────────────────────────────────────────────────

    async def _unload(self):
        if hasattr(self, "vpn"):
            self.vpn.stop()
        decky.logger.info("sub-deck unloaded")

    async def _uninstall(self):
        if hasattr(self, "vpn"):
            self.vpn.stop()
        decky.logger.info("sub-deck uninstalled")

    async def _migration(self):
        pass
