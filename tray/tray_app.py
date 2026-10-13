#!/usr/bin/env python3
"""
Sub-Deck Desktop Tray Companion.
Provides a streamlined, always-in-tray system popup menu for managing
VPN connections, servers, subscriptions, and presets without opening Steam Big Picture.
"""

import sys
import os
import time
import threading
from typing import Optional, Dict, List, Any

# Ensure plugin root directory is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(SCRIPT_DIR)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

try:
    from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal, QObject
    from PyQt6.QtGui import (
        QIcon, QPixmap, QPainter, QColor, QFont, QAction, QCursor, QBrush, QPen,
        QPainterPath
    )
    from PyQt6.QtWidgets import (
        QApplication, QSystemTrayIcon, QMenu
    )
except ImportError:
    try:
        from PySide6.QtCore import Qt, QTimer, QPoint, Signal as pyqtSignal, QObject
        from PySide6.QtGui import (
            QIcon, QPixmap, QPainter, QColor, QFont, QAction, QCursor, QBrush, QPen,
            QPainterPath
        )
        from PySide6.QtWidgets import (
            QApplication, QSystemTrayIcon, QMenu
        )
    except ImportError:
        print("Error: Neither PyQt6 nor PySide6 is installed.")
        print("Please install python-pyqt6 (e.g.: sudo pacman -S python-pyqt6)")
        sys.exit(1)

from tray.api_client import SubDeckApiClient
from tray.desktop_integration import ensure_desktop_entry
from core.constants import PRESET_DEFAULT, PRESET_ROSCOMVPN


# ─────────────────────────────────────────────────────────────
# Localization
# ─────────────────────────────────────────────────────────────

STRINGS = {
    "ru": {
        "app_title": "Sub-Deck VPN",
        "status_connected": "Подключено: {name}",
        "status_disconnected": "Отключено",
        "status_offline": "Демон не отвечает",
        "action_connect": "🟢 Подключить VPN",
        "action_disconnect": "🔴 Отключить VPN",
        "menu_servers": "Серверы",
        "menu_subscriptions": "Подписки",
        "menu_preset": "Пресет маршрутизации",
        "btn_check_ping": "⚡ Проверить пинг",
        "btn_refresh_all": "🔄 Обновить все подписки",
        "preset_default": "Default (Весь трафик через VPN)",
        "preset_roscomvpn": "RoscomVPN (Анти-блокировка)",
        "notify_connected": "VPN подключен: {node}",
        "notify_disconnected": "VPN отключен",
        "no_servers": "Нет доступных серверов",
        "no_subscriptions": "Нет добавленных подписок",
    },
    "en": {
        "app_title": "Sub-Deck VPN",
        "status_connected": "Connected: {name}",
        "status_disconnected": "Disconnected",
        "status_offline": "Daemon Offline",
        "action_connect": "🟢 Connect VPN",
        "action_disconnect": "🔴 Disconnect VPN",
        "menu_servers": "Servers",
        "menu_subscriptions": "Subscriptions",
        "menu_preset": "Routing Preset",
        "btn_check_ping": "⚡ Check Ping",
        "btn_refresh_all": "🔄 Refresh All Subscriptions",
        "preset_default": "Default (All traffic via VPN)",
        "preset_roscomvpn": "RoscomVPN (Bypass Censorship)",
        "notify_connected": "VPN Connected: {node}",
        "notify_disconnected": "VPN Disconnected",
        "no_servers": "No available servers",
        "no_subscriptions": "No subscriptions added",
    }
}


def get_lang() -> str:
    lang = os.environ.get("LANG", "").lower()
    return "ru" if lang.startswith("ru") else "en"


def tr(key: str, **kwargs) -> str:
    lang = get_lang()
    text = STRINGS.get(lang, STRINGS["en"]).get(key, STRINGS["en"].get(key, key))
    if kwargs:
        return text.format(**kwargs)
    return text


# ─────────────────────────────────────────────────────────────
# Dynamic Tray Icon Generator
# ─────────────────────────────────────────────────────────────

def create_tray_pixmap(status: str = "disconnected", size: int = 64) -> QPixmap:
    """Generates crisp vector-like tray icon with status indicator."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Base shield
    shield_color = QColor(225, 230, 240)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(shield_color))

    margin = size * 0.12
    w = size - 2 * margin
    h = size - 2 * margin

    path = QPainterPath()
    path.moveTo(size / 2, margin)
    path.lineTo(size - margin, margin + h * 0.25)
    path.lineTo(size - margin, margin + h * 0.6)
    path.quadTo(size / 2, size - margin, size / 2, size - margin)
    path.quadTo(margin, margin + h * 0.6, margin, margin + h * 0.6)
    path.lineTo(margin, margin + h * 0.25)
    path.closeSubpath()
    painter.drawPath(path)

    # Inner cutout for shield accent
    inner_color = QColor(30, 35, 45)
    painter.setBrush(QBrush(inner_color))
    inner_path = QPainterPath()
    in_m = size * 0.22
    in_h = size - 2 * in_m
    inner_path.moveTo(size / 2, in_m)
    inner_path.lineTo(size - in_m, in_m + in_h * 0.25)
    inner_path.lineTo(size - in_m, in_m + in_h * 0.55)
    inner_path.quadTo(size / 2, size - in_m, size / 2, size - in_m)
    inner_path.quadTo(in_m, in_m + in_h * 0.55, in_m, in_m + in_h * 0.55)
    inner_path.lineTo(in_m, in_m + in_h * 0.25)
    inner_path.closeSubpath()
    painter.drawPath(inner_path)

    # Status Dot (bottom-right)
    dot_radius = size * 0.20
    dot_cx = size - dot_radius - 2
    dot_cy = size - dot_radius - 2

    if status == "connected":
        dot_color = QColor(16, 185, 129)  # Green
    elif status == "connecting":
        dot_color = QColor(245, 158, 11)  # Amber
    elif status == "offline":
        dot_color = QColor(239, 68, 68)   # Red
    else:
        dot_color = QColor(148, 163, 184) # Slate gray

    painter.setPen(QPen(QColor(26, 31, 41), 3))
    painter.setBrush(QBrush(dot_color))
    painter.drawEllipse(QPoint(int(dot_cx), int(dot_cy)), int(dot_radius), int(dot_radius))

    painter.end()
    return pixmap


MENU_STYLESHEET = """
QMenu {
    background-color: #1a1f29;
    color: #f1f5f9;
    border: 1px solid #2e384d;
    border-radius: 8px;
    padding: 6px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Ubuntu, sans-serif;
    font-size: 13px;
}
QMenu::item {
    padding: 8px 24px 8px 12px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: #2a3447;
    color: #38bdf8;
}
QMenu::item:disabled {
    color: #94a3b8;
    font-weight: bold;
}
QMenu::separator {
    height: 1px;
    background-color: #2e384d;
    margin: 5px 8px;
}
"""


# ─────────────────────────────────────────────────────────────
# Background State Signaler
# ─────────────────────────────────────────────────────────────

class StateBridge(QObject):
    state_updated = pyqtSignal(object, object, object)
    ping_updated = pyqtSignal(list)


# ─────────────────────────────────────────────────────────────
# Tray Application
# ─────────────────────────────────────────────────────────────

class SubDeckTrayApp(QObject):
    """Main System Tray controller managing icon and pop-up menu."""

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.client = SubDeckApiClient()
        self.bridge = StateBridge()

        self.last_connected_state: Optional[bool] = None
        self.nodes: List[Dict[str, Any]] = []
        self.settings: Dict[str, Any] = {}
        self.status: Optional[Dict[str, Any]] = None
        self.ping_map: Dict[str, int] = {}

        # Connect signals
        self.bridge.state_updated.connect(self._apply_state)
        self.bridge.ping_updated.connect(self._apply_ping_results)

        # Build menu
        self.menu = QMenu()
        self.menu.setStyleSheet(MENU_STYLESHEET)

        # Status item
        self.status_action = QAction(f"○ {tr('status_disconnected')}", self)
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)
        self.menu.addSeparator()

        # Connect/Disconnect Toggle
        self.toggle_action = QAction(tr("action_connect"), self)
        self.toggle_action.triggered.connect(self._toggle_vpn)
        self.menu.addAction(self.toggle_action)

        self.menu.addSeparator()

        # Servers Submenu
        self.servers_menu = self.menu.addMenu(tr("menu_servers"))

        # Subscriptions Submenu
        self.subscriptions_menu = self.menu.addMenu(tr("menu_subscriptions"))

        # Presets Submenu
        self.preset_menu = self.menu.addMenu(tr("menu_preset"))
        self.action_preset_def = QAction(tr("preset_default"), self)
        self.action_preset_def.triggered.connect(lambda: self._set_preset(PRESET_DEFAULT))
        self.action_preset_ros = QAction(tr("preset_roscomvpn"), self)
        self.action_preset_ros.triggered.connect(lambda: self._set_preset(PRESET_ROSCOMVPN))
        self.preset_menu.addAction(self.action_preset_def)
        self.preset_menu.addAction(self.action_preset_ros)

        # Create tray icon
        self.tray = QSystemTrayIcon(self)
        self._update_tray_icon("disconnected")
        self.tray.setToolTip(f"{tr('app_title')} - {tr('status_disconnected')}")
        self.tray.setContextMenu(self.menu)

        # Open menu on BOTH left click and right click!
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        # Background polling timer (every 2.5s)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_status_background)
        self.timer.start(2500)

        # Initial poll
        self._poll_status_background()

    def _update_tray_icon(self, status: str):
        pixmap = create_tray_pixmap(status, size=64)
        self.tray.setIcon(QIcon(pixmap))

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """Pops up the menu on left, right, or double click."""
        pos = QCursor.pos()
        self.menu.popup(pos)

    def _poll_status_background(self):
        """Runs in separate thread and emits result via Qt Signal."""
        def _worker():
            status = self.client.get_status()
            nodes = self.client.get_nodes() if status else []
            settings = self.client.get_settings() if status else {}
            # Thread-safe dispatch to GUI thread
            self.bridge.state_updated.emit(status, nodes, settings)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_state(self, status: Optional[Dict[str, Any]], nodes: List[Dict[str, Any]], settings: Dict[str, Any]):
        """Slot executed strictly on GUI thread."""
        self.status = status
        self.nodes = nodes
        self.settings = settings

        if not status:
            self._update_tray_icon("offline")
            self.tray.setToolTip(f"{tr('app_title')} - {tr('status_offline')}")
            self.status_action.setText(f"🔴 {tr('status_offline')}")
            self.toggle_action.setEnabled(False)
            return

        self.toggle_action.setEnabled(True)
        is_running = bool(status.get("running"))
        selected_node = status.get("selected_node")
        node_name = selected_node.get("name", "") if selected_node else ""

        # Notification on state transition
        if self.last_connected_state is not None and self.last_connected_state != is_running:
            if is_running:
                self.tray.showMessage(
                    tr("app_title"),
                    tr("notify_connected", node=node_name or "VPN"),
                    QSystemTrayIcon.MessageIcon.Information,
                    2500
                )
            else:
                self.tray.showMessage(
                    tr("app_title"),
                    tr("notify_disconnected"),
                    QSystemTrayIcon.MessageIcon.Information,
                    2000
                )
        self.last_connected_state = is_running

        if is_running:
            self._update_tray_icon("connected")
            tip = f"{tr('app_title')} - {tr('status_connected', name=node_name or 'Active')}"
            self.tray.setToolTip(tip)
            self.status_action.setText(f"🟢 {tr('status_connected', name=node_name[:26])}")
            self.toggle_action.setText(tr("action_disconnect"))
        else:
            self._update_tray_icon("disconnected")
            self.tray.setToolTip(f"{tr('app_title')} - {tr('status_disconnected')}")
            self.status_action.setText(f"⚪ {tr('status_disconnected')}")
            self.toggle_action.setText(tr("action_connect"))

        # ── Rebuild Servers Submenu ──
        self.servers_menu.clear()

        # Ping action
        ping_act = QAction(tr("btn_check_ping"), self)
        ping_act.triggered.connect(self._run_ping_check)
        self.servers_menu.addAction(ping_act)
        self.servers_menu.addSeparator()

        if not nodes:
            empty_act = QAction(tr("no_servers"), self)
            empty_act.setEnabled(False)
            self.servers_menu.addAction(empty_act)
        else:
            for node in nodes:
                name = node.get("name", "Server")
                proto = (node.get("type") or "vless").upper()
                key = f"{node.get('server')}:{node.get('port')}"
                ping_val = self.ping_map.get(key)

                label = f"{name} [{proto}]"
                if ping_val is not None:
                    label += f" • {ping_val}ms"

                action = QAction(label, self)
                action.setCheckable(True)
                is_current = bool(
                    selected_node and
                    node.get("server") == selected_node.get("server") and
                    node.get("port") == selected_node.get("port")
                )
                action.setChecked(is_current)
                if is_current:
                    action.setText(f"✔ {label}")

                action.triggered.connect(lambda checked, n=node: self._connect_node(n))
                self.servers_menu.addAction(action)

        # ── Rebuild Subscriptions Submenu ──
        self.subscriptions_menu.clear()
        subs = settings.get("subscriptions", [])
        if not subs:
            no_subs_act = QAction(tr("no_subscriptions"), self)
            no_subs_act.setEnabled(False)
            self.subscriptions_menu.addAction(no_subs_act)
        else:
            for url in subs:
                domain = url.split("://")[-1].split("/")[0] if "://" in url else url[:28]
                sub_act = QAction(f"🔗 {domain} ({url[:35]}...)", self)
                sub_act.setEnabled(False)
                self.subscriptions_menu.addAction(sub_act)

        self.subscriptions_menu.addSeparator()
        refresh_act = QAction(tr("btn_refresh_all"), self)
        refresh_act.triggered.connect(self._refresh_all_subscriptions)
        self.subscriptions_menu.addAction(refresh_act)

        # ── Update Preset Checks ──
        current_preset = status.get("selected_preset", PRESET_DEFAULT)
        self.action_preset_def.setText(f"{'✔ ' if current_preset == PRESET_DEFAULT else ''}{tr('preset_default')}")
        self.action_preset_ros.setText(f"{'✔ ' if current_preset == PRESET_ROSCOMVPN else ''}{tr('preset_roscomvpn')}")

    def _toggle_vpn(self):
        def _worker():
            if self.last_connected_state:
                self.client.disconnect()
            else:
                self.client.connect()
            time.sleep(0.4)
            self._poll_status_background()
        threading.Thread(target=_worker, daemon=True).start()

    def _connect_node(self, node: Dict[str, Any]):
        def _worker():
            self.client.connect(node)
            time.sleep(0.4)
            self._poll_status_background()
        threading.Thread(target=_worker, daemon=True).start()

    def _set_preset(self, preset: str):
        def _worker():
            self.client.set_preset(preset)
            time.sleep(0.3)
            self._poll_status_background()
        threading.Thread(target=_worker, daemon=True).start()

    def _refresh_all_subscriptions(self):
        def _worker():
            self.client.update_all_subscriptions()
            time.sleep(0.5)
            self._poll_status_background()
        threading.Thread(target=_worker, daemon=True).start()

    def _run_ping_check(self):
        def _worker():
            alive = self.client.ping_nodes()
            self.bridge.ping_updated.emit(alive)
        threading.Thread(target=_worker, daemon=True).start()

    def _apply_ping_results(self, alive_nodes: List[Dict[str, Any]]):
        self.ping_map = {f"{n.get('server')}:{n.get('port')}": n.get("ping") for n in alive_nodes}
        # Re-apply menu with fresh ping latencies
        self._apply_state(self.status, self.nodes, self.settings)


# ─────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────

def main():
    ensure_desktop_entry(PLUGIN_DIR)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("SubDeckTray")

    tray = SubDeckTrayApp(app)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
