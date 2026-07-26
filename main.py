import os
import sys
import re
import asyncio
import time
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

        # Запускаем фоновый цикл автообновления подписок и баз
        self.update_task = asyncio.create_task(self._auto_update_loop())

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

    async def add_free_subscriptions(self) -> list:
        urls = [
            "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
            "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/main/githubmirror/1.txt",
            "https://raw.githubusercontent.com/zieng2/wl/main/vless_universal.txt"
        ]
        nodes = await self.loop.run_in_executor(
            None, self.vpn.add_multiple_subscriptions, urls
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

    async def save_preset(self, preset: str) -> bool:
        settings = self.vpn.load_settings()
        settings["selected_preset"] = preset
        self.vpn.save_settings(settings)
        if preset == "roscomvpn":
            await self.loop.run_in_executor(None, self.vpn.update_geofiles, False)
        return True


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
                            plugin_logs = "".join(lines[-250:]) # Последние 250 строк
                            break
                    except Exception as e:
                        plugin_logs = f"Error reading sub-deck logs from {log_path}: {e}"

            singbox_log_path = os.path.join(self.vpn.settings_dir, "sing-box.log")
            singbox_logs = "--- No sing-box logs found ---"
            if os.path.exists(singbox_log_path):
                try:
                    with open(singbox_log_path, "r", errors="replace", encoding="utf-8") as f:
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

    async def get_clipboard(self) -> str:
        """Считывает содержимое системного буфера обмена Steam Deck (включая Игровой Режим / Gamescope)."""
        def _read_sys_clipboard():
            import ctypes
            import os
            import subprocess

            # 1. Чтение X11 / Gamescope буфера обмена от имени пользователя deck (Игровой режим Steam Deck)
            helper_script = """
import ctypes
x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
x11.XOpenDisplay.restype = ctypes.c_void_p
x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
x11.XInternAtom.restype = ctypes.c_ulong
x11.XCreateSimpleWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_ulong]
x11.XCreateSimpleWindow.restype = ctypes.c_ulong
x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
x11.XDefaultRootWindow.restype = ctypes.c_ulong
x11.XConvertSelection.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
x11.XConvertSelection.restype = ctypes.c_int
x11.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
x11.XNextEvent.restype = ctypes.c_int
x11.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_char_p)]
x11.XGetWindowProperty.restype = ctypes.c_int
x11.XFree.argtypes = [ctypes.c_void_p]
x11.XDestroyWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]

def get_x11_clipboard_text():
    display = x11.XOpenDisplay(b":0")
    if not display:
        return ""
    try:
        root = x11.XDefaultRootWindow(display)
        win = x11.XCreateSimpleWindow(display, root, 0, 0, 1, 1, 0, 0, 0)
        clipboard_atom = x11.XInternAtom(display, b"CLIPBOARD", False)
        utf8_atom = x11.XInternAtom(display, b"UTF8_STRING", False)
        prop_atom = x11.XInternAtom(display, b"SUBDECK_CLIP", False)
        x11.XConvertSelection(display, clipboard_atom, utf8_atom, prop_atom, win, 0)
        event_buf = (ctypes.c_char * 192)()
        x11.XNextEvent(display, event_buf)
        actual_type = ctypes.c_ulong()
        actual_format = ctypes.c_int()
        nitems = ctypes.c_ulong()
        bytes_after = ctypes.c_ulong()
        prop_val = ctypes.c_char_p()
        x11.XGetWindowProperty(
            display, win, prop_atom, 0, 1024*1024, False, 0,
            ctypes.byref(actual_type), ctypes.byref(actual_format),
            ctypes.byref(nitems), ctypes.byref(bytes_after),
            ctypes.byref(prop_val)
        )
        res_text = ""
        if prop_val.value:
            res_text = prop_val.value.decode("utf-8", errors="ignore")
            x11.XFree(prop_val)
        x11.XDestroyWindow(display, win)
        return res_text
    finally:
        x11.XCloseDisplay(display)

print(get_x11_clipboard_text())
"""
            try:
                res = subprocess.run(
                    ["sudo", "-u", "deck", "python3", "-c", helper_script],
                    capture_output=True, text=True, timeout=3
                )
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                pass

            # 2. Опросить KDE Klipper DBus (для Рабочего стола / Desktop Mode)
            env = dict(os.environ)
            if "DBUS_SESSION_BUS_ADDRESS" not in env:
                env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"

            for qdbus_bin in ["qdbus", "qdbus-qt5"]:
                try:
                    res = subprocess.run(
                        [qdbus_bin, "org.kde.klipper", "/klipper", "getClipboardContents"],
                        env=env, capture_output=True, text=True, timeout=2
                    )
                    if res.returncode == 0 and res.stdout.strip():
                        return res.stdout.strip()
                except Exception:
                    pass

            return ""

        loop = getattr(self, "loop", None) or asyncio.get_event_loop()
        return await loop.run_in_executor(None, _read_sys_clipboard)

    async def check_and_update_subscriptions(self):
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
                    nodes, interval = await self.loop.run_in_executor(
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

    async def _auto_update_loop(self):
        # Ожидаем 30 секунд после старта
        await asyncio.sleep(30)
        while True:
            try:
                await self.check_and_update_subscriptions()
                await self.loop.run_in_executor(None, self.vpn.update_geofiles)
            except Exception as e:
                decky.logger.error(f"Auto update loop error: {e}")
            await asyncio.sleep(900)

    # ────────────────────────────────────────────────
    # Lifecycle
    # ────────────────────────────────────────────────

    async def _unload(self):
        if hasattr(self, "update_task"):
            self.update_task.cancel()
        if hasattr(self, "vpn"):
            await self.loop.run_in_executor(None, self.vpn.stop)
        decky.logger.info("sub-deck unloaded")

    async def _uninstall(self):
        if hasattr(self, "vpn"):
            await self.loop.run_in_executor(None, self.vpn.stop)
        decky.logger.info("sub-deck uninstalled")

    async def _migration(self):
        pass
