#!/usr/bin/env python3
"""
Sub-Deck Desktop Tray Companion.
Provides a modern system tray icon and pop-up widget for managing VPN
connections, servers, subscriptions, and presets without opening Steam Big Picture.
"""

import sys
import os
import time
import subprocess
import threading
from typing import Optional, Dict, List, Any

# Ensure plugin root directory is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(SCRIPT_DIR)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

try:
    from PyQt6.QtCore import Qt, QTimer, QPoint, QSize, pyqtSignal, QObject
    from PyQt6.QtGui import (
        QIcon, QPixmap, QPainter, QColor, QFont, QAction, QCursor, QBrush, QPen,
        QLinearGradient
    )
    from PyQt6.QtWidgets import (
        QApplication, QSystemTrayIcon, QMenu, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QComboBox, QLineEdit, QListWidget, QListWidgetItem,
        QTabWidget, QCheckBox, QFrame, QScrollArea, QMessageBox, QGraphicsDropShadowEffect
    )
except ImportError:
    try:
        from PySide6.QtCore import Qt, QTimer, QPoint, QSize, Signal as pyqtSignal, QObject
        from PySide6.QtGui import (
            QIcon, QPixmap, QPainter, QColor, QFont, QAction, QCursor, QBrush, QPen,
            QLinearGradient
        )
        from PySide6.QtWidgets import (
            QApplication, QSystemTrayIcon, QMenu, QWidget, QVBoxLayout, QHBoxLayout,
            QLabel, QPushButton, QComboBox, QLineEdit, QListWidget, QListWidgetItem,
            QTabWidget, QCheckBox, QFrame, QScrollArea, QMessageBox, QGraphicsDropShadowEffect
        )
    except ImportError:
        print("Error: Neither PyQt6 nor PySide6 is installed.")
        print("Please install python-pyqt6 (e.g. via pacman: sudo pacman -S python-pyqt6)")
        sys.exit(1)

from tray.api_client import SubDeckApiClient
from tray.desktop_integration import set_autostart, get_desktop_integration_status, ensure_desktop_entry
from core.constants import PRESET_DEFAULT, PRESET_ROSCOMVPN


# ─────────────────────────────────────────────────────────────
# Localization
# ─────────────────────────────────────────────────────────────

STRINGS = {
    "ru": {
        "app_title": "Sub-Deck VPN",
        "status_connected": "Подключено",
        "status_disconnected": "Отключено",
        "status_connecting": "Подключение...",
        "status_disconnecting": "Отключение...",
        "status_offline": "Демон не отвечает",
        "btn_connect": "ПОДКЛЮЧИТЬ",
        "btn_disconnect": "ОТКЛЮЧИТЬ",
        "tab_servers": "Серверы",
        "tab_subscriptions": "Подписки",
        "tab_settings": "Настройки",
        "preset_label": "Пресет маршрутизации:",
        "preset_default": "Default (Весь трафик через VPN)",
        "preset_roscomvpn": "RoscomVPN (Анти-блокировка)",
        "sub_input_placeholder": "Вставьте URL подписки (vless://, https://...)",
        "btn_paste": "📋 Вставить",
        "btn_add": "+ Добавить",
        "btn_refresh_all": "🔄 Обновить все",
        "btn_check_ping": "⚡ Проверить пинг",
        "autostart_label": "Запускать при входе в Desktop Mode",
        "menu_open": "Открыть панель управления",
        "menu_disconnect": "Отключить VPN",
        "menu_connect": "Подключить VPN",
        "menu_quit": "Выход",
        "notify_connected": "VPN успешно подключен: {node}",
        "notify_disconnected": "VPN отключен",
        "no_nodes": "Нет доступных серверов. Добавьте подписку во вкладке «Подписки».",
        "empty_url": "Пожалуйста, введите URL подписки.",
        "sub_added": "Подписка добавлена!",
        "sub_removed": "Подписка удалена",
        "sub_updated": "Подписка обновлена",
    },
    "en": {
        "app_title": "Sub-Deck VPN",
        "status_connected": "Connected",
        "status_disconnected": "Disconnected",
        "status_connecting": "Connecting...",
        "status_disconnecting": "Disconnecting...",
        "status_offline": "Daemon Offline",
        "btn_connect": "CONNECT",
        "btn_disconnect": "DISCONNECT",
        "tab_servers": "Servers",
        "tab_subscriptions": "Subscriptions",
        "tab_settings": "Settings",
        "preset_label": "Routing Preset:",
        "preset_default": "Default (All traffic via VPN)",
        "preset_roscomvpn": "RoscomVPN (Bypass Censorship)",
        "sub_input_placeholder": "Paste subscription URL (vless://, https://...)",
        "btn_paste": "📋 Paste",
        "btn_add": "+ Add",
        "btn_refresh_all": "🔄 Refresh All",
        "btn_check_ping": "⚡ Check Ping",
        "autostart_label": "Start automatically in Desktop Mode",
        "menu_open": "Open Control Panel",
        "menu_disconnect": "Disconnect VPN",
        "menu_connect": "Connect VPN",
        "menu_quit": "Quit",
        "notify_connected": "VPN Connected: {node}",
        "notify_disconnected": "VPN Disconnected",
        "no_nodes": "No servers available. Add a subscription in the Subscriptions tab.",
        "empty_url": "Please enter a valid subscription URL.",
        "sub_added": "Subscription added successfully!",
        "sub_removed": "Subscription removed",
        "sub_updated": "Subscription refreshed",
    }
}


def get_lang() -> str:
    """Detects active system language."""
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

    # 1. Base shield shape
    # Colors
    shield_color = QColor(220, 225, 235)  # Light gray/white for visibility on dark & light panels
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(shield_color))

    # Draw stylized shield / lock
    margin = size * 0.12
    w = size - 2 * margin
    h = size - 2 * margin

    # Draw rounded rect shield top and triangular bottom
    from PyQt6.QtGui import QPainterPath
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
    in_w = size - 2 * in_m
    in_h = size - 2 * in_m
    inner_path.moveTo(size / 2, in_m)
    inner_path.lineTo(size - in_m, in_m + in_h * 0.25)
    inner_path.lineTo(size - in_m, in_m + in_h * 0.55)
    inner_path.quadTo(size / 2, size - in_m, size / 2, size - in_m)
    inner_path.quadTo(in_m, in_m + in_h * 0.55, in_m, in_m + in_h * 0.55)
    inner_path.lineTo(in_m, in_m + in_h * 0.25)
    inner_path.closeSubpath()
    painter.drawPath(inner_path)

    # 2. Status Dot indicator (bottom right)
    dot_radius = size * 0.20
    dot_cx = size - dot_radius - 2
    dot_cy = size - dot_radius - 2

    if status == "connected":
        dot_color = QColor(16, 185, 129)  # Emerald green
    elif status == "connecting":
        dot_color = QColor(245, 158, 11)  # Amber
    elif status == "offline":
        dot_color = QColor(239, 68, 68)   # Red
    else:
        dot_color = QColor(148, 163, 184) # Muted slate gray

    # Dot outer border
    painter.setPen(QPen(QColor(26, 31, 41), 3))
    painter.setBrush(QBrush(dot_color))
    painter.drawEllipse(QPoint(int(dot_cx), int(dot_cy)), int(dot_radius), int(dot_radius))

    painter.end()
    return pixmap


# ─────────────────────────────────────────────────────────────
# UI Stylesheet (Steam Deck Dark Theme)
# ─────────────────────────────────────────────────────────────

STYLESHEET = """
QWidget {
    background-color: #1a1f29;
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Ubuntu, sans-serif;
    font-size: 13px;
}

#headerWidget {
    background-color: #131720;
    border-bottom: 1px solid #2d3748;
    padding: 10px 14px;
}

#headerTitle {
    font-size: 15px;
    font-weight: bold;
    color: #ffffff;
}

#statusCard {
    background-color: #212836;
    border: 1px solid #2e384d;
    border-radius: 12px;
    padding: 16px;
    margin: 8px 12px;
}

#statusBadge {
    font-size: 12px;
    font-weight: bold;
    padding: 3px 8px;
    border-radius: 6px;
}

#statusBadge[status="connected"] {
    background-color: rgba(16, 185, 129, 0.2);
    color: #10b981;
    border: 1px solid #10b981;
}

#statusBadge[status="disconnected"] {
    background-color: rgba(148, 163, 184, 0.2);
    color: #94a3b8;
    border: 1px solid #64748b;
}

#statusBadge[status="connecting"] {
    background-color: rgba(245, 158, 11, 0.2);
    color: #f59e0b;
    border: 1px solid #f59e0b;
}

#statusBadge[status="offline"] {
    background-color: rgba(239, 68, 68, 0.2);
    color: #ef4444;
    border: 1px solid #ef4444;
}

#currentNodeLabel {
    font-size: 14px;
    font-weight: 600;
    color: #f8fafc;
    margin-top: 4px;
}

/* Big Action Button */
QPushButton#actionButton {
    height: 44px;
    font-size: 14px;
    font-weight: bold;
    border-radius: 8px;
    border: none;
    margin-top: 8px;
}

QPushButton#actionButton[btnType="connect"] {
    background-color: #10b981;
    color: #ffffff;
}
QPushButton#actionButton[btnType="connect"]:hover {
    background-color: #059669;
}

QPushButton#actionButton[btnType="disconnect"] {
    background-color: #ef4444;
    color: #ffffff;
}
QPushButton#actionButton[btnType="disconnect"]:hover {
    background-color: #dc2626;
}

/* Tabs */
QTabWidget::pane {
    border: none;
    background-color: #1a1f29;
}

QTabBar::tab {
    background-color: #131720;
    color: #94a3b8;
    padding: 8px 18px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 4px;
    font-weight: 500;
}

QTabBar::tab:selected {
    background-color: #212836;
    color: #38bdf8;
    font-weight: bold;
}

/* Lists */
QListWidget {
    background-color: #161b24;
    border: 1px solid #2e384d;
    border-radius: 8px;
    padding: 4px;
}

QListWidget::item {
    background-color: #212836;
    border-radius: 6px;
    padding: 8px;
    margin: 3px 2px;
    color: #f1f5f9;
}

QListWidget::item:hover {
    background-color: #2a3447;
}

QListWidget::item:selected {
    background-color: #1e3a5f;
    border: 1px solid #38bdf8;
    color: #ffffff;
}

/* Form Elements */
QLineEdit {
    background-color: #141822;
    border: 1px solid #3b475f;
    border-radius: 6px;
    padding: 8px 10px;
    color: #ffffff;
}
QLineEdit:focus {
    border: 1px solid #38bdf8;
}

QComboBox {
    background-color: #141822;
    border: 1px solid #3b475f;
    border-radius: 6px;
    padding: 6px 12px;
    color: #ffffff;
}
QComboBox:focus {
    border: 1px solid #38bdf8;
}
QComboBox QAbstractItemView {
    background-color: #1a1f29;
    border: 1px solid #3b475f;
    selection-background-color: #2a3447;
}

QPushButton {
    background-color: #2e384d;
    border: none;
    border-radius: 6px;
    padding: 7px 14px;
    color: #f1f5f9;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #3b475f;
}
QPushButton:pressed {
    background-color: #1a2230;
}

QPushButton#primaryBtn {
    background-color: #0284c7;
    color: #ffffff;
}
QPushButton#primaryBtn:hover {
    background-color: #0369a1;
}

QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #475569;
    background-color: #141822;
}
QCheckBox::indicator:checked {
    background-color: #38bdf8;
    border-color: #38bdf8;
}

QScrollBar:vertical {
    border: none;
    background: #161b24;
    width: 6px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #475569;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #64748b;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


# ─────────────────────────────────────────────────────────────
# Main Popup Window
# ─────────────────────────────────────────────────────────────

class SubDeckWindow(QWidget):
    """Main pop-up control widget shown when tray icon is clicked."""

    def __init__(self, client: SubDeckApiClient, tray_icon: 'SubDeckTrayApp'):
        super().__init__()
        self.client = client
        self.tray = tray_icon
        self.nodes: List[Dict[str, Any]] = []
        self.current_node: Optional[Dict[str, Any]] = None
        self.is_connected = False
        self.daemon_online = False

        self.setWindowTitle(tr("app_title"))
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.resize(390, 570)
        self.setStyleSheet(STYLESHEET)

        self._init_ui()

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Header ──
        header = QWidget()
        header.setObjectName("headerWidget")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)

        title_label = QLabel(tr("app_title"))
        title_label.setObjectName("headerTitle")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(26, 26)
        close_btn.setStyleSheet("background: transparent; color: #94a3b8; font-size: 14px; padding: 0;")
        close_btn.clicked.connect(self.hide)
        header_layout.addWidget(close_btn)

        root_layout.addWidget(header)

        # ── Status Card ──
        self.status_card = QWidget()
        self.status_card.setObjectName("statusCard")
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(14, 12, 14, 12)
        status_card_layout.setSpacing(6)

        status_top_row = QHBoxLayout()
        self.status_badge = QLabel(tr("status_disconnected"))
        self.status_badge.setObjectName("statusBadge")
        self.status_badge.setProperty("status", "disconnected")
        status_top_row.addWidget(self.status_badge)
        status_top_row.addStretch()

        self.ping_indicator = QLabel("")
        self.ping_indicator.setStyleSheet("color: #94a3b8; font-size: 12px;")
        status_top_row.addWidget(self.ping_indicator)
        status_card_layout.addLayout(status_top_row)

        self.node_name_label = QLabel("—")
        self.node_name_label.setObjectName("currentNodeLabel")
        self.node_name_label.setWordWrap(True)
        status_card_layout.addWidget(self.node_name_label)

        self.action_btn = QPushButton(tr("btn_connect"))
        self.action_btn.setObjectName("actionButton")
        self.action_btn.setProperty("btnType", "connect")
        self.action_btn.clicked.connect(self._toggle_connection)
        status_card_layout.addWidget(self.action_btn)

        root_layout.addWidget(self.status_card)

        # ── Tabs ──
        self.tabs = QTabWidget()
        self.tabs.setContentsMargins(10, 0, 10, 10)

        # Tab 1: Servers
        servers_tab = QWidget()
        servers_layout = QVBoxLayout(servers_tab)
        servers_layout.setContentsMargins(8, 8, 8, 8)

        servers_toolbar = QHBoxLayout()
        ping_btn = QPushButton(tr("btn_check_ping"))
        ping_btn.clicked.connect(self._run_ping_check)
        servers_toolbar.addWidget(ping_btn)
        servers_toolbar.addStretch()
        servers_layout.addLayout(servers_toolbar)

        self.servers_list = QListWidget()
        self.servers_list.itemClicked.connect(self._on_server_selected)
        servers_layout.addWidget(self.servers_list)

        self.tabs.addTab(servers_tab, tr("tab_servers"))

        # Tab 2: Subscriptions
        subs_tab = QWidget()
        subs_layout = QVBoxLayout(subs_tab)
        subs_layout.setContentsMargins(8, 8, 8, 8)

        # Add subscription row
        input_row = QHBoxLayout()
        self.sub_input = QLineEdit()
        self.sub_input.setPlaceholderText(tr("sub_input_placeholder"))
        input_row.addWidget(self.sub_input)

        paste_btn = QPushButton(tr("btn_paste"))
        paste_btn.clicked.connect(self._paste_clipboard)
        input_row.addWidget(paste_btn)

        add_btn = QPushButton(tr("btn_add"))
        add_btn.setObjectName("primaryBtn")
        add_btn.clicked.connect(self._add_subscription)
        input_row.addWidget(add_btn)

        subs_layout.addLayout(input_row)

        # Refresh all row
        subs_toolbar = QHBoxLayout()
        refresh_all_btn = QPushButton(tr("btn_refresh_all"))
        refresh_all_btn.clicked.connect(self._refresh_all_subscriptions)
        subs_toolbar.addWidget(refresh_all_btn)
        subs_toolbar.addStretch()
        subs_layout.addLayout(subs_toolbar)

        self.subs_list = QListWidget()
        subs_layout.addWidget(self.subs_list)

        self.tabs.addTab(subs_tab, tr("tab_subscriptions"))

        # Tab 3: Settings
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)
        settings_layout.setContentsMargins(12, 12, 12, 12)
        settings_layout.setSpacing(14)

        preset_label = QLabel(tr("preset_label"))
        preset_label.setStyleSheet("font-weight: bold; color: #cbd5e1;")
        settings_layout.addWidget(preset_label)

        self.preset_combo = QComboBox()
        self.preset_combo.addItem(tr("preset_default"), PRESET_DEFAULT)
        self.preset_combo.addItem(tr("preset_roscomvpn"), PRESET_ROSCOMVPN)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        settings_layout.addWidget(self.preset_combo)

        settings_layout.addSpacing(6)

        self.autostart_checkbox = QCheckBox(tr("autostart_label"))
        self.autostart_checkbox.stateChanged.connect(self._on_autostart_toggled)
        settings_layout.addWidget(self.autostart_checkbox)

        settings_layout.addStretch()

        # Daemon info label
        self.daemon_label = QLabel("Decky Daemon: 127.0.0.1:45321")
        self.daemon_label.setStyleSheet("color: #64748b; font-size: 11px;")
        settings_layout.addWidget(self.daemon_label)

        self.tabs.addTab(settings_tab, tr("tab_settings"))

        root_layout.addWidget(self.tabs)

    # ─────────────────────────────────────────────────────────
    # UI Actions
    # ─────────────────────────────────────────────────────────

    def _toggle_connection(self):
        """Connects or disconnects VPN based on current state."""
        self.action_btn.setEnabled(False)
        self.status_badge.setText(tr("status_connecting") if not self.is_connected else tr("status_disconnecting"))
        self.status_badge.setProperty("status", "connecting")
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

        def _worker():
            if self.is_connected:
                self.client.disconnect()
            else:
                self.client.connect(self.current_node)
            # Re-fetch status shortly
            time.sleep(0.5)
            self.tray.poll_status_signal.emit()

        threading.Thread(target=_worker, daemon=True).start()

    def _on_server_selected(self, item: QListWidgetItem):
        """User clicked a server in the servers list."""
        node = item.data(Qt.ItemDataRole.UserRole)
        if node:
            self.current_node = node
            self.node_name_label.setText(node.get("name", "Unknown"))
            # If already connected, reconnect to the newly selected node
            if self.is_connected:
                self._toggle_connection()

    def _paste_clipboard(self):
        """Pastes URL from system clipboard."""
        clip = QApplication.clipboard().text().strip()
        if clip:
            self.sub_input.setText(clip)

    def _add_subscription(self):
        """Sends new subscription to backend."""
        url = self.sub_input.text().strip()
        if not url:
            QMessageBox.warning(self, tr("app_title"), tr("empty_url"))
            return

        self.sub_input.clear()

        def _worker():
            success = self.client.add_subscription(url)
            if success:
                self.tray.poll_status_signal.emit()

        threading.Thread(target=_worker, daemon=True).start()

    def _refresh_all_subscriptions(self):
        """Refreshes all configured endpoints."""
        def _worker():
            self.client.update_all_subscriptions()
            self.tray.poll_status_signal.emit()

        threading.Thread(target=_worker, daemon=True).start()

    def _run_ping_check(self):
        """Checks TCP latency for current nodes."""
        self.ping_indicator.setText("Pinging...")

        def _worker():
            alive_nodes = self.client.ping_nodes()
            # Update list on main thread
            QTimer.singleShot(0, lambda: self._update_ping_results(alive_nodes))

        threading.Thread(target=_worker, daemon=True).start()

    def _update_ping_results(self, alive_nodes: List[Dict[str, Any]]):
        """Updates server items with ping latency numbers."""
        ping_map = {f"{n.get('server')}:{n.get('port')}": n.get("ping") for n in alive_nodes}
        for i in range(self.servers_list.count()):
            item = self.servers_list.item(i)
            node = item.data(Qt.ItemDataRole.UserRole)
            if node:
                key = f"{node.get('server')}:{node.get('port')}"
                ping_val = ping_map.get(key)
                name = node.get("name", "Server")
                proto = (node.get("type") or "vless").upper()
                if ping_val is not None:
                    item.setText(f"{name}  [{proto}]  •  {ping_val}ms")
                    if ping_val < 150:
                        item.setForeground(QColor("#10b981"))
                    elif ping_val < 300:
                        item.setForeground(QColor("#f59e0b"))
                    else:
                        item.setForeground(QColor("#ef4444"))
                else:
                    item.setText(f"{name}  [{proto}]  •  timeout")
                    item.setForeground(QColor("#64748b"))

        self.ping_indicator.setText("")

    def _on_preset_changed(self, idx: int):
        preset = self.preset_combo.currentData()
        if preset:
            threading.Thread(target=lambda: self.client.set_preset(preset), daemon=True).start()

    def _on_autostart_toggled(self, state: int):
        enable = (state == 2 or state == Qt.CheckState.Checked.value)
        set_autostart(PLUGIN_DIR, enable)

    # ─────────────────────────────────────────────────────────
    # Data Population
    # ─────────────────────────────────────────────────────────

    def update_state(self, status: Optional[Dict[str, Any]], nodes: List[Dict[str, Any]], settings: Dict[str, Any]):
        """Populates UI with fresh data from backend."""
        self.action_btn.setEnabled(True)

        if not status:
            self.daemon_online = False
            self.is_connected = False
            self.status_badge.setText(tr("status_offline"))
            self.status_badge.setProperty("status", "offline")
            self.status_badge.style().unpolish(self.status_badge)
            self.status_badge.style().polish(self.status_badge)
            self.node_name_label.setText("Decky Loader daemon offline")
            self.action_btn.setEnabled(False)
            return

        self.daemon_online = True
        self.is_connected = bool(status.get("running"))
        self.current_node = status.get("selected_node")

        # Status badge & action button
        if self.is_connected:
            self.status_badge.setText(tr("status_connected"))
            self.status_badge.setProperty("status", "connected")
            self.action_btn.setText(tr("btn_disconnect"))
            self.action_btn.setProperty("btnType", "disconnect")
            if self.current_node:
                self.node_name_label.setText(self.current_node.get("name", "Connected"))
        else:
            self.status_badge.setText(tr("status_disconnected"))
            self.status_badge.setProperty("status", "disconnected")
            self.action_btn.setText(tr("btn_connect"))
            self.action_btn.setProperty("btnType", "connect")
            if self.current_node:
                self.node_name_label.setText(self.current_node.get("name", "—"))
            else:
                self.node_name_label.setText(self.nodes[0].get("name", "—") if self.nodes else "—")

        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
        self.action_btn.style().unpolish(self.action_btn)
        self.action_btn.style().polish(self.action_btn)

        # Preset
        preset = status.get("selected_preset", PRESET_DEFAULT)
        idx = self.preset_combo.findData(preset)
        if idx >= 0 and self.preset_combo.currentIndex() != idx:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(idx)
            self.preset_combo.blockSignals(False)

        # Autostart checkbox
        auto_status = get_desktop_integration_status(PLUGIN_DIR)
        self.autostart_checkbox.blockSignals(True)
        self.autostart_checkbox.setChecked(bool(auto_status.get("autostart")))
        self.autostart_checkbox.blockSignals(False)

        # Update nodes list if changed
        if nodes != self.nodes:
            self.nodes = nodes
            self.servers_list.clear()
            for node in self.nodes:
                name = node.get("name", "Server")
                proto = (node.get("type") or "vless").upper()
                item = QListWidgetItem(f"{name}  [{proto}]")
                item.setData(Qt.ItemDataRole.UserRole, node)
                if self.current_node and node.get("server") == self.current_node.get("server") and node.get("port") == self.current_node.get("port"):
                    item.setSelected(True)
                self.servers_list.addItem(item)

        # Update subscriptions list
        subs = settings.get("subscriptions", [])
        self.subs_list.clear()
        for url in subs:
            # Show domain or truncated link
            domain = url.split("://")[-1].split("/")[0] if "://" in url else url[:30]
            item = QListWidgetItem(f"🔗 {domain} ({url[:45]}...)")
            item.setData(Qt.ItemDataRole.UserRole, url)
            self.subs_list.addItem(item)


# ─────────────────────────────────────────────────────────────
# Tray Application
# ─────────────────────────────────────────────────────────────

class SubDeckTrayApp(QObject):
    """Main System Tray controller managing icon, context menu and background polling."""

    poll_status_signal = pyqtSignal()

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.client = SubDeckApiClient()
        self.last_connected_state: Optional[bool] = None

        # Create window
        self.window = SubDeckWindow(self.client, self)

        # Create tray icon
        self.tray = QSystemTrayIcon(self)
        self._update_tray_icon("disconnected")
        self.tray.setToolTip(f"{tr('app_title')} - {tr('status_disconnected')}")

        # Tray Context Menu (Right Click)
        self.menu = QMenu()
        self.menu.setStyleSheet(STYLESHEET)

        self.status_action = QAction(f"● {tr('status_disconnected')}", self)
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)
        self.menu.addSeparator()

        self.toggle_action = QAction(tr("menu_connect"), self)
        self.toggle_action.triggered.connect(self._toggle_vpn_from_menu)
        self.menu.addAction(self.toggle_action)

        self.menu.addSeparator()

        # Servers Submenu
        self.servers_menu = self.menu.addMenu(tr("tab_servers"))

        # Presets Submenu
        self.preset_menu = self.menu.addMenu(tr("preset_label"))
        self.action_preset_def = QAction(tr("preset_default"), self)
        self.action_preset_def.triggered.connect(lambda: self._set_preset_from_menu(PRESET_DEFAULT))
        self.action_preset_ros = QAction(tr("preset_roscomvpn"), self)
        self.action_preset_ros.triggered.connect(lambda: self._set_preset_from_menu(PRESET_ROSCOMVPN))
        self.preset_menu.addAction(self.action_preset_def)
        self.preset_menu.addAction(self.action_preset_ros)

        self.menu.addSeparator()

        self.open_action = QAction(tr("menu_open"), self)
        self.open_action.triggered.connect(self._toggle_window)
        self.menu.addAction(self.open_action)

        self.menu.addSeparator()

        self.quit_action = QAction(tr("menu_quit"), self)
        self.quit_action.triggered.connect(self._quit_app)
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        # Signal for thread-safe UI updates
        self.poll_status_signal.connect(self._poll_status)

        # Polling timer (every 3 seconds)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_status)
        self.timer.start(3000)

        # Initial poll
        self._poll_status()

    def _update_tray_icon(self, status: str):
        pixmap = create_tray_pixmap(status, size=64)
        self.tray.setIcon(QIcon(pixmap))

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """Handle click on tray icon."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # Left click
            self._toggle_window()

    def _toggle_window(self):
        """Shows or hides the main pop-up window positioned near tray."""
        if self.window.isVisible():
            self.window.hide()
        else:
            # Position near tray icon / mouse cursor
            geom = self.tray.geometry()
            cursor_pos = QCursor.pos()

            win_w = self.window.width()
            win_h = self.window.height()

            # Default positioning near cursor, keeping within screen bounds
            screen = QApplication.primaryScreen().availableGeometry()
            x = cursor_pos.x() - win_w // 2
            y = cursor_pos.y() - win_h - 10

            # Bottom panel boundary check
            if y < screen.top():
                y = cursor_pos.y() + 20
            if x + win_w > screen.right():
                x = screen.right() - win_w - 10
            if x < screen.left():
                x = screen.left() + 10

            self.window.move(x, y)
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()

    def _poll_status(self):
        """Fetches status from API in background thread."""
        def _worker():
            status = self.client.get_status()
            nodes = self.client.get_nodes() if status else []
            settings = self.client.get_settings() if status else {}
            # Update UI on main Qt thread
            QTimer.singleShot(0, lambda: self._apply_state(status, nodes, settings))

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_state(self, status: Optional[Dict[str, Any]], nodes: List[Dict[str, Any]], settings: Dict[str, Any]):
        """Applies fresh backend state to tray icon and menu."""
        self.window.update_state(status, nodes, settings)

        if not status:
            self._update_tray_icon("offline")
            self.tray.setToolTip(f"{tr('app_title')} - {tr('status_offline')}")
            self.status_action.setText(f"● {tr('status_offline')}")
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
            tip = f"{tr('app_title')} - {tr('status_connected')}"
            if node_name:
                tip += f" ({node_name})"
            self.tray.setToolTip(tip)
            self.status_action.setText(f"● {tr('status_connected')}: {node_name[:25]}")
            self.toggle_action.setText(tr("menu_disconnect"))
        else:
            self._update_tray_icon("disconnected")
            self.tray.setToolTip(f"{tr('app_title')} - {tr('status_disconnected')}")
            self.status_action.setText(f"○ {tr('status_disconnected')}")
            self.toggle_action.setText(tr("menu_connect"))

        # Rebuild servers submenu
        self.servers_menu.clear()
        for node in nodes[:20]:  # Up to 20 nodes in tray menu
            name = node.get("name", "Server")
            action = QAction(name, self)
            action.triggered.connect(lambda checked, n=node: self._connect_node_from_menu(n))
            if selected_node and node.get("server") == selected_node.get("server") and node.get("port") == selected_node.get("port"):
                action.setIcon(QIcon(create_tray_pixmap("connected", 16)))
            self.servers_menu.addAction(action)

    def _toggle_vpn_from_menu(self):
        if self.last_connected_state:
            threading.Thread(target=lambda: [self.client.disconnect(), self._poll_status()], daemon=True).start()
        else:
            threading.Thread(target=lambda: [self.client.connect(), self._poll_status()], daemon=True).start()

    def _connect_node_from_menu(self, node: Dict[str, Any]):
        def _worker():
            self.client.connect(node)
            self._poll_status()
        threading.Thread(target=_worker, daemon=True).start()

    def _set_preset_from_menu(self, preset: str):
        threading.Thread(target=lambda: self.client.set_preset(preset), daemon=True).start()

    def _quit_app(self):
        self.app.quit()


# ─────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────

def main():
    # Make sure desktop entry exists
    ensure_desktop_entry(PLUGIN_DIR)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("SubDeckTray")

    tray = SubDeckTrayApp(app)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
