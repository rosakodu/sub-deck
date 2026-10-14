#!/usr/bin/env python3
"""
Sub-Deck Desktop Tray Companion.
Provides a streamlined, native StatusNotifierItem system tray popup for managing
VPN connections, servers, subscriptions, and presets without opening Steam Big Picture.
Fully compatible with KDE Plasma Wayland (Steam Deck Desktop Mode), supporting
identical native context menus on BOTH Left-Click and Right-Click.
"""

import sys
import os
import time
import threading
import re
from typing import Optional, Dict, List, Any, Callable

# Ensure plugin root directory is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(SCRIPT_DIR)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

try:
    from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal, QObject
    from PyQt6.QtGui import (
        QIcon, QPixmap, QPainter, QColor, QFont, QAction, QCursor, QBrush, QPen,
        QPainterPath, QImage
    )
    from PyQt6.QtWidgets import (
        QApplication, QInputDialog
    )
except ImportError:
    try:
        from PySide6.QtCore import Qt, QTimer, QPoint, Signal as pyqtSignal, QObject
        from PySide6.QtGui import (
            QIcon, QPixmap, QPainter, QColor, QFont, QAction, QCursor, QBrush, QPen,
            QPainterPath, QImage
        )
        from PySide6.QtWidgets import (
            QApplication, QInputDialog
        )
    except ImportError:
        print("Error: Neither PyQt6 nor PySide6 is installed.")
        print("Please install python-pyqt6 (e.g.: sudo pacman -S python-pyqt6)")
        sys.exit(1)

import dbus
import dbus.service
import dbus.mainloop.pyqt6

from tray.api_client import SubDeckApiClient
from core.constants import PRESET_DEFAULT, PRESET_ROSCOMVPN, SUPPORTED_SCHEMES
from core.system import read_system_clipboard


# ─────────────────────────────────────────────────────────────
# Localization
# ─────────────────────────────────────────────────────────────

STRINGS = {
    "ru": {
        "app_title": "Sub-Deck VPN",
        "status_connected": "Подключено: {name}",
        "status_disconnected": "Отключено",
        "status_offline": "Демон не отвечает",
        "action_disconnect": "🔴 Отключить VPN",
        "menu_select_server": "Выбрать сервер",
        "menu_subscriptions": "Подписки",
        "menu_preset": "Пресет маршрутизации",
        "btn_paste_sub": "📋 Вставить из буфера обмена",
        "btn_check_ping": "⚡ Проверить пинг",
        "btn_refresh_all": "🔄 Обновить все подписки",
        "preset_default": "Default (Весь трафик через VPN)",
        "preset_roscomvpn": "RoscomVPN (Анти-блокировка)",
        "notify_connected": "VPN подключен: {node}",
        "notify_disconnected": "VPN отключен",
        "notify_sub_added": "Подписка добавлена: получено {count} серверов",
        "notify_sub_failed": "Буфер обмена пуст или не содержит ссылку на подписку",
        "notify_ping_measuring": "Измерение задержки серверов...",
        "notify_ping_results": "Результаты пинга:",
        "no_servers": "Нет доступных серверов",
        "no_subscriptions": "Нет добавленных подписок",
        "dialog_add_sub_title": "Добавить подписку",
        "dialog_add_sub_msg": "Введите или вставьте URL подписки:",
    },
    "en": {
        "app_title": "Sub-Deck VPN",
        "status_connected": "Connected: {name}",
        "status_disconnected": "Disconnected",
        "status_offline": "Daemon Offline",
        "action_disconnect": "🔴 Disconnect VPN",
        "menu_select_server": "Select Server",
        "menu_subscriptions": "Subscriptions",
        "menu_preset": "Routing Preset",
        "btn_paste_sub": "📋 Paste from Clipboard",
        "btn_check_ping": "⚡ Check Ping",
        "btn_refresh_all": "🔄 Refresh All Subscriptions",
        "preset_default": "Default (All traffic via VPN)",
        "preset_roscomvpn": "RoscomVPN (Bypass Censorship)",
        "notify_connected": "VPN Connected: {node}",
        "notify_disconnected": "VPN Disconnected",
        "notify_sub_added": "Subscription added: {count} servers found",
        "notify_sub_failed": "Clipboard is empty or does not contain a valid URL",
        "notify_ping_measuring": "Measuring server latency...",
        "notify_ping_results": "Ping Results:",
        "no_servers": "No available servers",
        "no_subscriptions": "No subscriptions added",
        "dialog_add_sub_title": "Add Subscription",
        "dialog_add_sub_msg": "Enter or paste subscription URL:",
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
# Dynamic Tray Icon Generator & Pixmap Formatter
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


def pixmap_to_sni_pixmap(pixmap: QPixmap) -> dbus.Struct:
    """Converts a QPixmap to org.kde.StatusNotifierItem IconPixmap ARGB32 network struct."""
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    w, h = image.width(), image.height()
    raw = bytearray()
    for y in range(h):
        for x in range(w):
            p = image.pixel(x, y)
            raw.extend([(p >> 24) & 0xFF, (p >> 16) & 0xFF, (p >> 8) & 0xFF, p & 0xFF])
    return dbus.Struct((dbus.Int32(w), dbus.Int32(h), dbus.ByteArray(raw)))


# ─────────────────────────────────────────────────────────────
# StatusNotifierItem & DBusMenu Adaptors
# ─────────────────────────────────────────────────────────────

class SubDeckSNI(dbus.service.Object):
    """
    Standard org.kde.StatusNotifierItem implementation.
    Crucially exports 'ItemIsMenu: True' which forces KDE Plasma to treat both
    Left-Click (ЛКМ) and Right-Click (ПКМ) as context menu requests.
    """

    def __init__(self, conn, path, tray_app):
        super().__init__(conn, path)
        self.tray_app = tray_app

    @dbus.service.method('org.freedesktop.DBus.Properties', in_signature='ss', out_signature='v')
    def Get(self, iface, prop):
        return self.GetAll(iface).get(prop, '')

    @dbus.service.method('org.freedesktop.DBus.Properties', in_signature='s', out_signature='a{sv}')
    def GetAll(self, iface):
        if iface == 'org.kde.StatusNotifierItem':
            icon_struct = pixmap_to_sni_pixmap(self.tray_app.current_icon_pixmap)
            return {
                'Category': dbus.String('ApplicationStatus'),
                'Id': dbus.String('sub-deck'),
                'Title': dbus.String(self.tray_app.current_title),
                'Status': dbus.String('Active'),
                'ItemIsMenu': dbus.Boolean(True),
                'IconName': dbus.String(''),
                'IconPixmap': dbus.Array([icon_struct], signature='(iiay)'),
                'OverlayIconPixmap': dbus.Array([], signature='(iiay)'),
                'AttentionIconPixmap': dbus.Array([], signature='(iiay)'),
                'AttentionIconName': dbus.String(''),
                'AttentionMovieName': dbus.String(''),
                'OverlayIconName': dbus.String(''),
                'IconThemePath': dbus.String(''),
                'WindowId': dbus.Int32(0),
                'Menu': dbus.ObjectPath('/MenuBar'),
                'ToolTip': dbus.Struct((
                    dbus.String(''),
                    dbus.Array([], signature='(iiay)'),
                    dbus.String(self.tray_app.current_tooltip),
                    dbus.String('')
                )),
            }
        return {}

    @dbus.service.method('org.kde.StatusNotifierItem', in_signature='ii')
    def Activate(self, x, y):
        pass

    @dbus.service.method('org.kde.StatusNotifierItem', in_signature='ii')
    def ContextMenu(self, x, y):
        pass

    @dbus.service.method('org.kde.StatusNotifierItem', in_signature='ii')
    def SecondaryActivate(self, x, y):
        pass

    @dbus.service.method('org.kde.StatusNotifierItem', in_signature='is')
    def Scroll(self, delta, dir):
        pass

    @dbus.service.method('org.kde.StatusNotifierItem', in_signature='s')
    def ProvideXdgActivationToken(self, token):
        pass

    @dbus.service.signal('org.kde.StatusNotifierItem')
    def NewTitle(self):
        pass

    @dbus.service.signal('org.kde.StatusNotifierItem')
    def NewIcon(self):
        pass

    @dbus.service.signal('org.kde.StatusNotifierItem')
    def NewToolTip(self):
        pass

    @dbus.service.signal('org.kde.StatusNotifierItem')
    def NewStatus(self, status):
        pass

    @dbus.service.signal('org.kde.StatusNotifierItem')
    def NewMenu(self):
        pass


class SubDeckDBusMenu(dbus.service.Object):
    """
    Standard com.canonical.dbusmenu implementation.
    Delivers dynamic menu hierarchies and click events directly to KDE Plasma.
    """

    def __init__(self, conn, path, tray_app):
        super().__init__(conn, path)
        self.tray_app = tray_app
        self.revision = dbus.UInt32(1)

    @dbus.service.method('com.canonical.dbusmenu', in_signature='i', out_signature='b')
    def AboutToShow(self, id):
        return True

    @dbus.service.method('com.canonical.dbusmenu', in_signature='iias', out_signature='u(ia{sv}av)')
    def GetLayout(self, parent_id, recursion_depth, property_names):
        return self.tray_app.get_menu_layout(parent_id, recursion_depth)

    @dbus.service.method('com.canonical.dbusmenu', in_signature='isvu', out_signature='')
    def Event(self, id, eventId, data, timestamp):
        if eventId == 'clicked':
            self.tray_app.trigger_menu_action(id)

    @dbus.service.method('com.canonical.dbusmenu', in_signature='aias', out_signature='a(ia{sv})')
    def GetGroupProperties(self, ids, propertyNames):
        return dbus.Array([], signature=dbus.Signature('(ia{sv})'))

    @dbus.service.method('com.canonical.dbusmenu', in_signature='is', out_signature='v')
    def GetProperty(self, id, property):
        return dbus.String('')

    @dbus.service.signal('com.canonical.dbusmenu', signature='ui')
    def LayoutUpdated(self, revision, parentId):
        pass

    def bump_layout(self):
        self.revision = dbus.UInt32(int(self.revision) + 1)
        self.LayoutUpdated(self.revision, dbus.Int32(0))


# ─────────────────────────────────────────────────────────────
# Background State Signaler
# ─────────────────────────────────────────────────────────────

class StateBridge(QObject):
    state_updated = pyqtSignal(object, object, object)
    ping_completed = pyqtSignal(list)
    show_notification = pyqtSignal(str, str)


# ─────────────────────────────────────────────────────────────
# Tray Application
# ─────────────────────────────────────────────────────────────

class SubDeckTrayApp(QObject):
    """Main System Tray controller managing SNI, DBusMenu, state and polling."""

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

        # Display properties
        self.current_title = tr("app_title")
        self.current_tooltip = f"{tr('app_title')} - {tr('status_disconnected')}"
        self.current_icon_pixmap = create_tray_pixmap("disconnected", 48)

        # Action registry: ID -> callback
        self.action_callbacks: Dict[int, Callable[[], None]] = {}
        self.next_action_id = 100

        # Submenu roots: parent_id -> list of child Structs
        self.menu_children_map: Dict[int, List[dbus.Struct]] = {}
        self.root_items: List[dbus.Struct] = []

        # Connect signals
        self.bridge.state_updated.connect(self._apply_state)
        self.bridge.ping_completed.connect(self._apply_ping_results)
        self.bridge.show_notification.connect(self._send_desktop_notification)

        # Setup DBus
        self.session_bus = dbus.SessionBus()
        self.sni = SubDeckSNI(self.session_bus, '/StatusNotifierItem', self)
        self.dbusmenu = SubDeckDBusMenu(self.session_bus, '/MenuBar', self)

        # Register with KDE Plasma StatusNotifierWatcher
        try:
            watcher = self.session_bus.get_object('org.kde.StatusNotifierWatcher', '/StatusNotifierWatcher')
            watcher_iface = dbus.Interface(watcher, 'org.kde.StatusNotifierWatcher')
            watcher_iface.RegisterStatusNotifierItem(self.session_bus.get_unique_name())
        except Exception as e:
            print(f"[SubDeckTray] StatusNotifierWatcher registration warning: {e}")

        # Background polling timer (every 2.5s)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_status_background)
        self.timer.start(2500)

        # Initial poll
        self._poll_status_background()

    def _send_desktop_notification(self, title: str, message: str, timeout_ms: int = 4000):
        """Sends native desktop notification via org.freedesktop.Notifications."""
        try:
            notify_obj = self.session_bus.get_object('org.freedesktop.Notifications', '/org/freedesktop/Notifications')
            notify_iface = dbus.Interface(notify_obj, 'org.freedesktop.Notifications')
            notify_iface.Notify('Sub-Deck VPN', 0, '', title, message, [], {}, timeout_ms)
        except Exception:
            pass

    def _poll_status_background(self):
        """Runs in separate thread and emits result via Qt Signal."""
        def _worker():
            status = self.client.get_status()
            nodes = self.client.get_nodes() if status else []
            settings = self.client.get_settings() if status else {}
            self.bridge.state_updated.emit(status, nodes, settings)

        threading.Thread(target=_worker, daemon=True).start()

    def _register_action(self, callback: Callable[[], None]) -> int:
        aid = self.next_action_id
        self.next_action_id += 1
        self.action_callbacks[aid] = callback
        return aid

    def trigger_menu_action(self, action_id: int):
        cb = self.action_callbacks.get(action_id)
        if cb:
            cb()

    def get_menu_layout(self, parent_id: int, recursion_depth: int) -> tuple:
        """Returns the DBusMenu hierarchy according to com.canonical.dbusmenu spec."""
        parent_id_int = int(parent_id)
        if parent_id_int == 0:
            root_props = dbus.Dictionary({
                dbus.String('children-display'): dbus.String('submenu')
            }, signature=dbus.Signature('sv'))
            children = dbus.Array(self.root_items, signature=dbus.Signature('v'))
            root = dbus.Struct((dbus.Int32(0), root_props, children))
            return (self.dbusmenu.revision, root)

        sub_children = self.menu_children_map.get(parent_id_int, [])
        sub_props = dbus.Dictionary({
            dbus.String('children-display'): dbus.String('submenu')
        }, signature=dbus.Signature('sv'))
        sub_root = dbus.Struct((dbus.Int32(parent_id_int), sub_props, dbus.Array(sub_children, signature=dbus.Signature('v'))))
        return (self.dbusmenu.revision, sub_root)

    def _apply_state(self, status: Optional[Dict[str, Any]], nodes: List[Dict[str, Any]], settings: Dict[str, Any]):
        """Slot executed strictly on GUI thread. Builds menu hierarchy and updates icon."""
        self.status = status
        self.nodes = nodes
        self.settings = settings

        self.action_callbacks.clear()
        self.menu_children_map.clear()
        self.next_action_id = 100

        if not status:
            self.current_icon_pixmap = create_tray_pixmap("offline", 48)
            self.current_tooltip = f"{tr('app_title')} - {tr('status_offline')}"
            self.sni.NewIcon()
            self.sni.NewToolTip()

            status_item = dbus.Struct((
                dbus.Int32(1),
                dbus.Dictionary({
                    dbus.String('label'): dbus.String(f"🔴 {tr('status_offline')}"),
                    dbus.String('enabled'): dbus.Boolean(False),
                    dbus.String('visible'): dbus.Boolean(True),
                }, signature=dbus.Signature('sv')),
                dbus.Array([], signature=dbus.Signature('v'))
            ))
            self.root_items = [status_item]
            self.dbusmenu.bump_layout()
            return

        is_running = bool(status.get("running"))
        selected_node = status.get("selected_node")
        node_name = selected_node.get("name", "") if selected_node else ""

        # Notification on state transition
        if self.last_connected_state is not None and self.last_connected_state != is_running:
            if is_running:
                self._send_desktop_notification(
                    tr("app_title"),
                    tr("notify_connected", node=node_name or "VPN"),
                    2500
                )
            else:
                self._send_desktop_notification(
                    tr("app_title"),
                    tr("notify_disconnected"),
                    2000
                )
        self.last_connected_state = is_running

        # Icon & Tooltip
        if is_running:
            self.current_icon_pixmap = create_tray_pixmap("connected", 48)
            self.current_tooltip = f"{tr('app_title')} - {tr('status_connected', name=node_name or 'Active')}"
            status_label = f"🟢 {tr('status_connected', name=node_name[:26])}"
        else:
            self.current_icon_pixmap = create_tray_pixmap("disconnected", 48)
            self.current_tooltip = f"{tr('app_title')} - {tr('status_disconnected')}"
            status_label = f"⚪ {tr('status_disconnected')}"

        self.sni.NewIcon()
        self.sni.NewToolTip()

        new_root_items: List[dbus.Struct] = []

        # 1. Top status item (disabled)
        new_root_items.append(dbus.Struct((
            dbus.Int32(1),
            dbus.Dictionary({
                dbus.String('label'): dbus.String(status_label),
                dbus.String('enabled'): dbus.Boolean(False),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array([], signature=dbus.Signature('v'))
        )))

        # Separator
        new_root_items.append(dbus.Struct((
            dbus.Int32(2),
            dbus.Dictionary({
                dbus.String('type'): dbus.String('separator'),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array([], signature=dbus.Signature('v'))
        )))

        # 2. Disconnect Action (visible only when connected)
        if is_running:
            disconn_id = self._register_action(self._disconnect_vpn)
            new_root_items.append(dbus.Struct((
                dbus.Int32(disconn_id),
                dbus.Dictionary({
                    dbus.String('label'): dbus.String(tr("action_disconnect")),
                    dbus.String('enabled'): dbus.Boolean(True),
                    dbus.String('visible'): dbus.Boolean(True),
                }, signature=dbus.Signature('sv')),
                dbus.Array([], signature=dbus.Signature('v'))
            )))
            new_root_items.append(dbus.Struct((
                dbus.Int32(3),
                dbus.Dictionary({
                    dbus.String('type'): dbus.String('separator'),
                    dbus.String('visible'): dbus.Boolean(True),
                }, signature=dbus.Signature('sv')),
                dbus.Array([], signature=dbus.Signature('v'))
            )))

        # 3. "Select Server" Submenu
        servers_menu_id = 10
        server_children: List[dbus.Struct] = []

        # Ping action
        ping_act_id = self._register_action(self._run_ping_check)
        server_children.append(dbus.Struct((
            dbus.Int32(ping_act_id),
            dbus.Dictionary({
                dbus.String('label'): dbus.String(tr("btn_check_ping")),
                dbus.String('enabled'): dbus.Boolean(True),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array([], signature=dbus.Signature('v'))
        )))
        server_children.append(dbus.Struct((
            dbus.Int32(11),
            dbus.Dictionary({
                dbus.String('type'): dbus.String('separator'),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array([], signature=dbus.Signature('v'))
        )))

        if not nodes:
            server_children.append(dbus.Struct((
                dbus.Int32(12),
                dbus.Dictionary({
                    dbus.String('label'): dbus.String(tr("no_servers")),
                    dbus.String('enabled'): dbus.Boolean(False),
                    dbus.String('visible'): dbus.Boolean(True),
                }, signature=dbus.Signature('sv')),
                dbus.Array([], signature=dbus.Signature('v'))
            )))
        else:
            for node in nodes:
                name = node.get("name", "Server")
                proto = (node.get("type") or "vless").upper()
                key = f"{node.get('server')}:{node.get('port')}"
                ping_val = self.ping_map.get(key)

                label = f"{name} [{proto}]"
                if ping_val is not None:
                    label += f" • {ping_val}ms"

                is_current = bool(
                    is_running and
                    selected_node and
                    node.get("server") == selected_node.get("server") and
                    node.get("port") == selected_node.get("port")
                )
                if is_current:
                    label = f"✔ {label}"

                node_act_id = self._register_action(lambda n=node: self._connect_node(n))
                server_children.append(dbus.Struct((
                    dbus.Int32(node_act_id),
                    dbus.Dictionary({
                        dbus.String('label'): dbus.String(label),
                        dbus.String('enabled'): dbus.Boolean(True),
                        dbus.String('visible'): dbus.Boolean(True),
                    }, signature=dbus.Signature('sv')),
                    dbus.Array([], signature=dbus.Signature('v'))
                )))

        self.menu_children_map[servers_menu_id] = server_children
        new_root_items.append(dbus.Struct((
            dbus.Int32(servers_menu_id),
            dbus.Dictionary({
                dbus.String('label'): dbus.String(tr("menu_select_server")),
                dbus.String('children-display'): dbus.String('submenu'),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array(server_children, signature=dbus.Signature('v'))
        )))

        # 4. Subscriptions Submenu
        subs_menu_id = 20
        subs_children: List[dbus.Struct] = []

        paste_act_id = self._register_action(self._paste_and_add_subscription)
        subs_children.append(dbus.Struct((
            dbus.Int32(paste_act_id),
            dbus.Dictionary({
                dbus.String('label'): dbus.String(tr("btn_paste_sub")),
                dbus.String('enabled'): dbus.Boolean(True),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array([], signature=dbus.Signature('v'))
        )))

        refresh_act_id = self._register_action(self._refresh_all_subscriptions)
        subs_children.append(dbus.Struct((
            dbus.Int32(refresh_act_id),
            dbus.Dictionary({
                dbus.String('label'): dbus.String(tr("btn_refresh_all")),
                dbus.String('enabled'): dbus.Boolean(True),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array([], signature=dbus.Signature('v'))
        )))

        subs_children.append(dbus.Struct((
            dbus.Int32(21),
            dbus.Dictionary({
                dbus.String('type'): dbus.String('separator'),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array([], signature=dbus.Signature('v'))
        )))

        subs = settings.get("subscriptions", [])
        if not subs:
            subs_children.append(dbus.Struct((
                dbus.Int32(22),
                dbus.Dictionary({
                    dbus.String('label'): dbus.String(tr("no_subscriptions")),
                    dbus.String('enabled'): dbus.Boolean(False),
                    dbus.String('visible'): dbus.Boolean(True),
                }, signature=dbus.Signature('sv')),
                dbus.Array([], signature=dbus.Signature('v'))
            )))
        else:
            for url in subs:
                domain = url.split("://")[-1].split("/")[0] if "://" in url else url[:28]
                sub_label = f"🔗 {domain} ({url[:35]}...)"
                sub_id = self._register_action(lambda: None)
                subs_children.append(dbus.Struct((
                    dbus.Int32(sub_id),
                    dbus.Dictionary({
                        dbus.String('label'): dbus.String(sub_label),
                        dbus.String('enabled'): dbus.Boolean(False),
                        dbus.String('visible'): dbus.Boolean(True),
                    }, signature=dbus.Signature('sv')),
                    dbus.Array([], signature=dbus.Signature('v'))
                )))

        self.menu_children_map[subs_menu_id] = subs_children
        new_root_items.append(dbus.Struct((
            dbus.Int32(subs_menu_id),
            dbus.Dictionary({
                dbus.String('label'): dbus.String(tr("menu_subscriptions")),
                dbus.String('children-display'): dbus.String('submenu'),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array(subs_children, signature=dbus.Signature('v'))
        )))

        # 5. Routing Preset Submenu
        preset_menu_id = 30
        preset_children: List[dbus.Struct] = []
        current_preset = status.get("selected_preset", PRESET_DEFAULT)

        def_prefix = "✔ " if current_preset == PRESET_DEFAULT else ""
        ros_prefix = "✔ " if current_preset == PRESET_ROSCOMVPN else ""

        def_act_id = self._register_action(lambda: self._set_preset(PRESET_DEFAULT))
        preset_children.append(dbus.Struct((
            dbus.Int32(def_act_id),
            dbus.Dictionary({
                dbus.String('label'): dbus.String(f"{def_prefix}{tr('preset_default')}"),
                dbus.String('enabled'): dbus.Boolean(True),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array([], signature=dbus.Signature('v'))
        )))

        ros_act_id = self._register_action(lambda: self._set_preset(PRESET_ROSCOMVPN))
        preset_children.append(dbus.Struct((
            dbus.Int32(ros_act_id),
            dbus.Dictionary({
                dbus.String('label'): dbus.String(f"{ros_prefix}{tr('preset_roscomvpn')}"),
                dbus.String('enabled'): dbus.Boolean(True),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array([], signature=dbus.Signature('v'))
        )))

        self.menu_children_map[preset_menu_id] = preset_children
        new_root_items.append(dbus.Struct((
            dbus.Int32(preset_menu_id),
            dbus.Dictionary({
                dbus.String('label'): dbus.String(tr("menu_preset")),
                dbus.String('children-display'): dbus.String('submenu'),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array(preset_children, signature=dbus.Signature('v'))
        )))

        self.root_items = new_root_items
        self.dbusmenu.bump_layout()

    def _disconnect_vpn(self):
        """Disconnects active VPN."""
        def _worker():
            self.client.disconnect()
            time.sleep(0.4)
            self._poll_status_background()
        threading.Thread(target=_worker, daemon=True).start()

    def _connect_node(self, node: Dict[str, Any]):
        """Directly activates VPN with the chosen server."""
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

    def _read_clipboard_url(self) -> str:
        """Reads subscription URL from Qt clipboard, Klipper DBus, or system helpers."""
        valid_schemes = ("http://", "https://") + SUPPORTED_SCHEMES

        def _clean_match(raw: str) -> Optional[str]:
            if not raw:
                return None
            raw = str(raw).strip()
            if any(raw.lower().startswith(s) for s in valid_schemes):
                return raw
            m = re.search(r'(https?://[^\s<>"\'\)]+|vless://[^\s<>"\'\)]+|vmess://[^\s<>"\'\)]+|ss://[^\s<>"\'\)]+|trojan://[^\s<>"\'\)]+)', raw, re.IGNORECASE)
            if m:
                return m.group(1).strip()
            return None

        # 1. Standard Qt clipboard
        try:
            txt = QApplication.clipboard().text()
            m = _clean_match(txt)
            if m:
                return m
        except Exception:
            pass

        # 2. KDE Klipper via DBus
        try:
            klipper_obj = self.session_bus.get_object('org.kde.klipper', '/klipper')
            klipper_iface = dbus.Interface(klipper_obj, 'org.kde.klipper.klipper')
            txt = klipper_iface.getClipboardContents()
            m = _clean_match(txt)
            if m:
                return m
            history = klipper_iface.getClipboardHistoryMenu()
            for item in history:
                m = _clean_match(item)
                if m:
                    return m
        except Exception:
            pass

        # 3. System helper fallback
        try:
            sys_clip = read_system_clipboard()
            m = _clean_match(sys_clip)
            if m:
                return m
        except Exception:
            pass

        return ""

    def _paste_and_add_subscription(self):
        """Reads system clipboard and adds subscription URL, prompting user if not detected."""
        clip_text = self._read_clipboard_url()

        if not clip_text:
            text, ok = QInputDialog.getText(
                None,
                tr("dialog_add_sub_title"),
                tr("dialog_add_sub_msg"),
            )
            if ok and text.strip():
                clip_text = text.strip()

        is_valid = bool(clip_text) and any(clip_text.lower().startswith(scheme) for scheme in ("http://", "https://") + SUPPORTED_SCHEMES)
        if not is_valid:
            self._send_desktop_notification(
                tr("app_title"),
                tr("notify_sub_failed"),
                4000
            )
            return

        def _worker():
            success = self.client.add_subscription(clip_text)
            if success:
                nodes = self.client.get_nodes()
                self.bridge.show_notification.emit(
                    tr("app_title"),
                    tr("notify_sub_added", count=len(nodes))
                )
            else:
                self.bridge.show_notification.emit(
                    tr("app_title"),
                    tr("notify_sub_failed")
                )
            time.sleep(0.5)
            self._poll_status_background()

        threading.Thread(target=_worker, daemon=True).start()

    def _refresh_all_subscriptions(self):
        def _worker():
            self.client.update_all_subscriptions()
            time.sleep(0.5)
            self._poll_status_background()
        threading.Thread(target=_worker, daemon=True).start()

    def _run_ping_check(self):
        """Measures latency of all candidate servers in background and sends popup notification."""
        self._send_desktop_notification(
            tr("app_title"),
            tr("notify_ping_measuring"),
            2000
        )

        def _worker():
            alive_nodes = self.client.ping_nodes()
            self.bridge.ping_completed.emit(alive_nodes)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_ping_results(self, alive_nodes: List[Dict[str, Any]]):
        self.ping_map = {f"{n.get('server')}:{n.get('port')}": n.get("ping") for n in alive_nodes}

        report_lines = []
        for node in self.nodes:
            name = node.get("name", "Server")
            key = f"{node.get('server')}:{node.get('port')}"
            ping_val = self.ping_map.get(key)
            if ping_val is not None:
                report_lines.append(f"• {name} — {ping_val} ms")
            else:
                report_lines.append(f"• {name} — n/a")

        if report_lines:
            report_text = "\n".join(report_lines[:8])
            if len(report_lines) > 8:
                report_text += f"\n... и ещё {len(report_lines) - 8}"
            self._send_desktop_notification(
                tr("notify_ping_results"),
                report_text,
                7000
            )

        self._apply_state(self.status, self.nodes, self.settings)


# ─────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────

def main():
    try:
        dbus.mainloop.pyqt6.DBusQtMainLoop(set_as_default=True)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("SubDeckTray")

    tray = SubDeckTrayApp(app)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
