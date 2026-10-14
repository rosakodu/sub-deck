#!/usr/bin/env python3
"""
Sub-Deck Desktop Tray Companion.
Native StatusNotifierItem and DBusMenu tray implementation with ZERO external dependencies.
Uses standard SteamOS / Linux libraries: GLib, cairo, dbus.
Provides full desktop VPN management directly from KDE Plasma taskbar in Desktop Mode.
"""

import sys
import os
import time
import math
import threading
import subprocess
import re
from typing import Optional, Dict, List, Any, Callable

# Ensure plugin root directory is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(SCRIPT_DIR)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from gi.repository import GLib
import cairo
import dbus
import dbus.service
import dbus.mainloop.glib

from tray.api_client import SubDeckApiClient
from tray.desktop_integration import set_autostart, get_desktop_integration_status
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
        "action_connect": "🟢 Включить VPN",
        "action_disconnect": "🔴 Отключить VPN",
        "menu_select_server": "Выбрать сервер",
        "menu_subscriptions": "Подписки",
        "menu_preset": "Пресет маршрутизации",
        "btn_paste_sub": "📋 Вставить из буфера обмена",
        "btn_add_manual": "✏️ Ввести URL вручную...",
        "btn_check_ping": "⚡ Проверить пинг",
        "btn_refresh_all": "🔄 Обновить все подписки",
        "toggle_autostart": "Автозапуск в Desktop Mode",
        "action_quit": "Выход из трея",
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
        "action_connect": "🟢 Connect VPN",
        "action_disconnect": "🔴 Disconnect VPN",
        "menu_select_server": "Select Server",
        "menu_subscriptions": "Subscriptions",
        "menu_preset": "Routing Preset",
        "btn_paste_sub": "📋 Paste from Clipboard",
        "btn_add_manual": "✏️ Enter URL manually...",
        "btn_check_ping": "⚡ Check Ping",
        "btn_refresh_all": "🔄 Refresh All Subscriptions",
        "toggle_autostart": "Autostart in Desktop Mode",
        "action_quit": "Exit Tray",
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


def format_bytes(b: Optional[int]) -> str:
    if not b or b <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    val = float(b)
    idx = 0
    while val >= 1024.0 and idx < len(units) - 1:
        val /= 1024.0
        idx += 1
    return f"{val:.1f} {units[idx]}"


def format_expiry(expire_ts: Optional[int], lang: str) -> str:
    if not expire_ts or expire_ts <= 0:
        return ""
    diff = expire_ts - int(time.time())
    if diff <= 0:
        return "Срок истёк" if lang == "ru" else "Expired"
    days = diff // 86400
    if days > 0:
        return f"{days} дн." if lang == "ru" else f"{days}d left"
    hours = diff // 3600
    return f"{hours} ч." if lang == "ru" else f"{hours}h left"


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
# Dynamic Vector Cairo Tray Icon & Pixmap Formatter
# ─────────────────────────────────────────────────────────────

def render_tray_icon(status: str = "disconnected", size: int = 32) -> dbus.Struct:
    """
    Renders vector tray icon using Cairo and converts to SNI IconPixmap struct (w, h, data).
    Status values: 'connected', 'connecting', 'offline', 'disconnected'.
    Returns dbus.Struct((dbus.Int32(w), dbus.Int32(h), dbus.ByteArray(data))).
    """
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)

    # 1. Outer Shield Base
    margin = size * 0.10
    w = size - 2 * margin
    h = size - 2 * margin

    ctx.move_to(size / 2, margin)
    ctx.line_to(size - margin, margin + h * 0.25)
    ctx.line_to(size - margin, margin + h * 0.60)
    ctx.curve_to(size / 2, size - margin, size / 2, size - margin, size / 2, size - margin)
    ctx.curve_to(margin, margin + h * 0.60, margin, margin + h * 0.60, margin, margin + h * 0.60)
    ctx.line_to(margin, margin + h * 0.25)
    ctx.close_path()

    ctx.set_source_rgba(0.90, 0.92, 0.96, 1.0)
    ctx.fill()

    # 2. Inner Shield Accent Cutout
    in_m = size * 0.20
    in_h = size - 2 * in_m

    ctx.move_to(size / 2, in_m)
    ctx.line_to(size - in_m, in_m + in_h * 0.25)
    ctx.line_to(size - in_m, in_m + in_h * 0.55)
    ctx.curve_to(size / 2, size - in_m, size / 2, size - in_m, size / 2, size - in_m)
    ctx.curve_to(in_m, in_m + in_h * 0.55, in_m, in_m + in_h * 0.55, in_m, in_m + in_h * 0.55)
    ctx.line_to(in_m, in_m + in_h * 0.25)
    ctx.close_path()

    ctx.set_source_rgba(0.12, 0.15, 0.20, 1.0)
    ctx.fill()

    # 3. Status Indicator Dot (bottom right)
    dot_r = size * 0.21
    dot_cx = size - dot_r - 1.0
    dot_cy = size - dot_r - 1.0

    if status == "connected":
        r, g, b = (0.06, 0.72, 0.50)  # Emerald green
    elif status == "connecting":
        r, g, b = (0.96, 0.62, 0.04)  # Amber
    elif status == "offline":
        r, g, b = (0.94, 0.27, 0.27)  # Red
    else:
        r, g, b = (0.58, 0.64, 0.72)  # Slate gray

    ctx.arc(dot_cx, dot_cy, dot_r, 0, 2 * math.pi)
    ctx.set_source_rgba(r, g, b, 1.0)
    ctx.fill()

    ctx.arc(dot_cx, dot_cy, dot_r, 0, 2 * math.pi)
    ctx.set_line_width(size * 0.06)
    ctx.set_source_rgba(0.10, 0.12, 0.16, 1.0)
    ctx.stroke()

    surface.flush()
    raw = bytes(surface.get_data())

    # Cairo FORMAT_ARGB32 is stored natively in little-endian as (B, G, R, A).
    # KDE StatusNotifierItem specification requires network ARGB32 bytes (A, R, G, B).
    out = bytearray(len(raw))
    for i in range(0, len(raw), 4):
        b_val = raw[i]
        g_val = raw[i + 1]
        r_val = raw[i + 2]
        a_val = raw[i + 3]
        out[i] = a_val
        out[i + 1] = r_val
        out[i + 2] = g_val
        out[i + 3] = b_val

    return dbus.Struct((dbus.Int32(size), dbus.Int32(size), dbus.ByteArray(out)))


# ─────────────────────────────────────────────────────────────
# StatusNotifierItem & DBusMenu Adaptors
# ─────────────────────────────────────────────────────────────

class SubDeckSNI(dbus.service.Object):
    """
    Standard org.kde.StatusNotifierItem implementation for KDE Plasma & Wayland.
    Exports ItemIsMenu=True and Menu=/MenuBar so both Left-Click and Right-Click
    open the native desktop menu directly in KDE Plasma taskbar.
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
            icon_struct = self.tray_app.current_icon_struct
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
                    dbus.Array([icon_struct], signature='(iiay)'),
                    dbus.String(self.tray_app.current_title),
                    dbus.String(self.tray_app.current_tooltip)
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
    Transfers structured menu layouts and receives action click events from KDE Plasma.
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
# Tray Application Controller
# ─────────────────────────────────────────────────────────────

class SubDeckTrayApp:
    """Main System Tray controller managing SNI, DBusMenu, state synchronization and polling."""

    def __init__(self, main_loop: GLib.MainLoop):
        self.main_loop = main_loop
        self.client = SubDeckApiClient()

        self.last_connected_state: Optional[bool] = None
        self.nodes: List[Dict[str, Any]] = []
        self.settings: Dict[str, Any] = {}
        self.status: Optional[Dict[str, Any]] = None
        self.ping_map: Dict[str, int] = {}

        # Display properties
        self.current_title = tr("app_title")
        self.current_tooltip = tr("status_disconnected")
        self.current_icon_struct = render_tray_icon("disconnected", 32)

        # Action registry: action_id -> callback
        self.action_callbacks: Dict[int, Callable[[], None]] = {}
        self.next_action_id = 100

        # Submenu roots: parent_id -> list of child Structs
        self.menu_children_map: Dict[int, List[dbus.Struct]] = {}
        self.root_items: List[dbus.Struct] = []

        # Setup DBus connection with GLib mainloop
        self.session_bus = dbus.SessionBus()
        self.sni = SubDeckSNI(self.session_bus, '/StatusNotifierItem', self)
        self.dbusmenu = SubDeckDBusMenu(self.session_bus, '/MenuBar', self)

        # Register StatusNotifierItem with KDE Plasma StatusNotifierWatcher
        try:
            watcher = self.session_bus.get_object('org.kde.StatusNotifierWatcher', '/StatusNotifierWatcher')
            watcher_iface = dbus.Interface(watcher, 'org.kde.StatusNotifierWatcher')
            watcher_iface.RegisterStatusNotifierItem(self.session_bus.get_unique_name())
        except Exception as e:
            print(f"[SubDeckTray] StatusNotifierWatcher warning (will retry): {e}")

        # Start periodic status polling (every 2.5 seconds)
        GLib.timeout_add(2500, self._on_poll_timer)

        # Trigger initial poll immediately
        self._trigger_background_poll()

    def _send_desktop_notification(self, title: str, message: str, timeout_ms: int = 4000):
        """Sends native desktop notification via org.freedesktop.Notifications."""
        try:
            notify_obj = self.session_bus.get_object('org.freedesktop.Notifications', '/org/freedesktop/Notifications')
            notify_iface = dbus.Interface(notify_obj, 'org.freedesktop.Notifications')
            notify_iface.Notify('Sub-Deck VPN', 0, '', title, message, [], {}, timeout_ms)
        except Exception:
            pass

    def _on_poll_timer(self) -> bool:
        self._trigger_background_poll()
        return True  # Keep GLib timer repeating

    def _trigger_background_poll(self):
        """Runs API queries in background worker thread and safely schedules UI update via GLib.idle_add."""
        def _worker():
            status = self.client.get_status()
            nodes = self.client.get_nodes() if status else []
            settings = self.client.get_settings() if status else {}
            GLib.idle_add(self._apply_state, status, nodes, settings)

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

    def _apply_state(self, status: Optional[Dict[str, Any]], nodes: List[Dict[str, Any]], settings: Dict[str, Any]) -> bool:
        """Main thread handler: builds complete DBusMenu hierarchy and updates StatusNotifierItem."""
        self.status = status
        self.nodes = nodes
        self.settings = settings

        self.action_callbacks.clear()
        self.menu_children_map.clear()
        self.next_action_id = 100

        # Handle daemon offline scenario
        if not status:
            self.current_icon_struct = render_tray_icon("offline", 32)
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
            return False

        is_running = bool(status.get("running"))
        selected_node = status.get("selected_node")
        node_name = selected_node.get("name", "") if selected_node else ""

        # Notification on connection state transition
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

        # Icon and Tooltip
        sub_meta_dict = settings.get("subscription_metadata", {})
        active_sub_url = selected_node.get("subscription_url") if selected_node else None
        active_meta = sub_meta_dict.get(active_sub_url, {}) if active_sub_url else {}

        traffic_str = ""
        if active_meta.get("total"):
            used = (active_meta.get("upload") or 0) + (active_meta.get("download") or 0)
            traffic_str = f" [{format_bytes(used)} / {format_bytes(active_meta['total'])}]"

        if is_running:
            self.current_icon_struct = render_tray_icon("connected", 32)
            self.current_tooltip = f"{tr('app_title')}: {node_name or 'Active'}{traffic_str}"
            status_label = f"🟢 {tr('status_connected', name=node_name[:26])}{traffic_str}"
        else:
            self.current_icon_struct = render_tray_icon("disconnected", 32)
            self.current_tooltip = f"{tr('app_title')} - {tr('status_disconnected')}"
            status_label = f"⚪ {tr('status_disconnected')}"

        self.sni.NewIcon()
        self.sni.NewToolTip()

        new_root_items: List[dbus.Struct] = []

        # 1. Top status item (header)
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

        # 2. Quick Connect / Disconnect Action
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
        else:
            conn_id = self._register_action(self._connect_default_node)
            new_root_items.append(dbus.Struct((
                dbus.Int32(conn_id),
                dbus.Dictionary({
                    dbus.String('label'): dbus.String(tr("action_connect")),
                    dbus.String('enabled'): dbus.Boolean(bool(nodes or selected_node)),
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

        # Paste from clipboard
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

        # Manual URL input via kdialog / prompt
        manual_act_id = self._register_action(self._prompt_manual_subscription)
        subs_children.append(dbus.Struct((
            dbus.Int32(manual_act_id),
            dbus.Dictionary({
                dbus.String('label'): dbus.String(tr("btn_add_manual")),
                dbus.String('enabled'): dbus.Boolean(True),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array([], signature=dbus.Signature('v'))
        )))

        # Refresh all subscriptions
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
            sub_meta_dict = settings.get("subscription_metadata", {})
            for url in subs:
                meta = sub_meta_dict.get(url, {})
                title = meta.get("name")
                if not title:
                    domain = url.split("://")[-1].split("/")[0] if "://" in url else url[:28]
                    title = domain

                traffic_info = ""
                if meta.get("total"):
                    u = (meta.get("upload") or 0) + (meta.get("download") or 0)
                    traffic_info = f" • {format_bytes(u)}/{format_bytes(meta['total'])}"

                expiry_info = ""
                if meta.get("expire"):
                    exp_str = format_expiry(meta["expire"], get_lang())
                    if exp_str:
                        expiry_info = f" ({exp_str})"

                sub_label = f"🔗 {title}{traffic_info}{expiry_info}"
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

        # Separator
        new_root_items.append(dbus.Struct((
            dbus.Int32(40),
            dbus.Dictionary({
                dbus.String('type'): dbus.String('separator'),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array([], signature=dbus.Signature('v'))
        )))

        # 6. Autostart Toggle
        autostart_active = get_desktop_integration_status(PLUGIN_DIR).get("autostart", False)
        autostart_prefix = "✔ " if autostart_active else ""
        autostart_act_id = self._register_action(self._toggle_autostart)
        new_root_items.append(dbus.Struct((
            dbus.Int32(autostart_act_id),
            dbus.Dictionary({
                dbus.String('label'): dbus.String(f"{autostart_prefix}{tr('toggle_autostart')}"),
                dbus.String('enabled'): dbus.Boolean(True),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array([], signature=dbus.Signature('v'))
        )))

        # 7. Quit Tray Action
        quit_act_id = self._register_action(self._quit_tray)
        new_root_items.append(dbus.Struct((
            dbus.Int32(quit_act_id),
            dbus.Dictionary({
                dbus.String('label'): dbus.String(tr("action_quit")),
                dbus.String('enabled'): dbus.Boolean(True),
                dbus.String('visible'): dbus.Boolean(True),
            }, signature=dbus.Signature('sv')),
            dbus.Array([], signature=dbus.Signature('v'))
        )))

        self.root_items = new_root_items
        self.dbusmenu.bump_layout()
        return False  # GLib.idle_add callback returns False so it runs once

    # ─────────────────────────────────────────────────────────────
    # Actions implementation
    # ─────────────────────────────────────────────────────────────

    def _connect_default_node(self):
        def _worker():
            self.client.connect()
            time.sleep(0.4)
            self._trigger_background_poll()
        threading.Thread(target=_worker, daemon=True).start()

    def _disconnect_vpn(self):
        def _worker():
            self.client.disconnect()
            time.sleep(0.4)
            self._trigger_background_poll()
        threading.Thread(target=_worker, daemon=True).start()

    def _connect_node(self, node: Dict[str, Any]):
        def _worker():
            self.client.connect(node)
            time.sleep(0.4)
            self._trigger_background_poll()
        threading.Thread(target=_worker, daemon=True).start()

    def _set_preset(self, preset: str):
        def _worker():
            self.client.set_preset(preset)
            time.sleep(0.3)
            self._trigger_background_poll()
        threading.Thread(target=_worker, daemon=True).start()

    def _toggle_autostart(self):
        curr = get_desktop_integration_status(PLUGIN_DIR).get("autostart", False)
        set_autostart(PLUGIN_DIR, not curr)
        self._trigger_background_poll()

    def _quit_tray(self):
        print("[SubDeckTray] Exiting tray...")
        self.main_loop.quit()

    def _read_clipboard_url(self) -> str:
        """Reads subscription URL from KDE Klipper via DBus or system clipboard tools."""
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

        # 1. KDE Klipper via DBus
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

        # 2. System helper fallback (wl-paste, xclip, etc.)
        try:
            sys_clip = read_system_clipboard()
            m = _clean_match(sys_clip)
            if m:
                return m
        except Exception:
            pass

        return ""

    def _prompt_kdialog(self, title: str, text: str, default: str = "") -> Optional[str]:
        """Shows native KDE input dialog via kdialog."""
        try:
            res = subprocess.run(
                ["kdialog", "--title", title, "--inputbox", text, default],
                capture_output=True,
                text=True,
                timeout=30
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception as e:
            print(f"[SubDeckTray] kdialog error: {e}")
        return None

    def _paste_and_add_subscription(self):
        clip_text = self._read_clipboard_url()

        if not clip_text:
            # Fallback to kdialog if clipboard doesn't contain a link
            val = self._prompt_kdialog(
                tr("dialog_add_sub_title"),
                tr("dialog_add_sub_msg")
            )
            if val and val.strip():
                clip_text = val.strip()

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
                GLib.idle_add(
                    self._send_desktop_notification,
                    tr("app_title"),
                    tr("notify_sub_added", count=len(nodes)),
                    3500
                )
            else:
                GLib.idle_add(
                    self._send_desktop_notification,
                    tr("app_title"),
                    tr("notify_sub_failed"),
                    3500
                )
            time.sleep(0.5)
            self._trigger_background_poll()

        threading.Thread(target=_worker, daemon=True).start()

    def _prompt_manual_subscription(self):
        val = self._prompt_kdialog(
            tr("dialog_add_sub_title"),
            tr("dialog_add_sub_msg")
        )
        if not val or not val.strip():
            return

        url = val.strip()
        is_valid = any(url.lower().startswith(scheme) for scheme in ("http://", "https://") + SUPPORTED_SCHEMES)
        if not is_valid:
            self._send_desktop_notification(
                tr("app_title"),
                tr("notify_sub_failed"),
                4000
            )
            return

        def _worker():
            success = self.client.add_subscription(url)
            if success:
                nodes = self.client.get_nodes()
                GLib.idle_add(
                    self._send_desktop_notification,
                    tr("app_title"),
                    tr("notify_sub_added", count=len(nodes)),
                    3500
                )
            else:
                GLib.idle_add(
                    self._send_desktop_notification,
                    tr("app_title"),
                    tr("notify_sub_failed"),
                    3500
                )
            time.sleep(0.5)
            self._trigger_background_poll()

        threading.Thread(target=_worker, daemon=True).start()

    def _refresh_all_subscriptions(self):
        def _worker():
            self.client.update_all_subscriptions()
            time.sleep(0.5)
            self._trigger_background_poll()
        threading.Thread(target=_worker, daemon=True).start()

    def _run_ping_check(self):
        self._send_desktop_notification(
            tr("app_title"),
            tr("notify_ping_measuring"),
            2000
        )

        def _worker():
            alive_nodes = self.client.ping_nodes()
            GLib.idle_add(self._apply_ping_results, alive_nodes)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_ping_results(self, alive_nodes: List[Dict[str, Any]]) -> bool:
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
        return False


# ─────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────

def main():
    # Setup GLib DBus mainloop
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    loop = GLib.MainLoop()
    tray = SubDeckTrayApp(loop)

    if "--test" in sys.argv:
        print("[SubDeckTray] Test mode: initialization successful, exiting.")
        sys.exit(0)

    try:
        loop.run()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
