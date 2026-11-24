"""Build the desktop tray's DBusMenu items."""

from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Tuple

import dbus

from core.constants import PRESET_BYPASS_RU, PRESET_DEFAULT, PRESET_GAMING, PRESET_ROSCOMVPN
from core.system import clean_node_name, get_node_category
from tray.localization import format_bytes, format_expiry, get_lang, tr


@dataclass(frozen=True)
class MenuActions:
    connect_default: Callable[[], None]
    disconnect: Callable[[], None]
    ping: Callable[[], None]
    connect_node: Callable[[Dict[str, Any]], None]
    paste_subscription: Callable[[], None]
    add_subscription: Callable[[], None]
    refresh_subscriptions: Callable[[], None]
    generate_warp: Callable[[], None]
    set_preset: Callable[[str], None]
    update_rules: Callable[[], None]
    set_protocol_filter: Callable[[str], None]
    toggle_autostart: Callable[[], None]
    quit_tray: Callable[[], None]


def _item(item_id: int, properties: Dict[str, Any], children: List[dbus.Struct]) -> dbus.Struct:
    return dbus.Struct((
        dbus.Int32(item_id),
        dbus.Dictionary({dbus.String(key): value for key, value in properties.items()},
                        signature=dbus.Signature('sv')),
        dbus.Array(children, signature=dbus.Signature('v')),
    ))


def menu_label(item_id: int, label: str, enabled: bool = True) -> dbus.Struct:
    return _item(item_id, {
        'label': dbus.String(label),
        'enabled': dbus.Boolean(enabled),
        'visible': dbus.Boolean(True),
    }, [])


def _separator(item_id: int) -> dbus.Struct:
    return _item(item_id, {
        'type': dbus.String('separator'),
        'visible': dbus.Boolean(True),
    }, [])


def _submenu(item_id: int, label: str, children: List[dbus.Struct]) -> dbus.Struct:
    return _item(item_id, {
        'label': dbus.String(label),
        'children-display': dbus.String('submenu'),
        'visible': dbus.Boolean(True),
    }, children)


def build_menu(
    *,
    status_label: str,
    is_running: bool,
    selected_node: Optional[Dict[str, Any]],
    selected_preset: str,
    nodes: List[Dict[str, Any]],
    settings: Dict[str, Any],
    protocol_filter: str,
    ping_map: Dict[str, int],
    autostart_enabled: Callable[[], bool],
    register: Callable[[Callable[[], None]], int],
    actions: MenuActions,
) -> Tuple[List[dbus.Struct], Dict[int, List[dbus.Struct]]]:
    root = [menu_label(1, status_label, enabled=False), _separator(2)]
    if is_running:
        root.append(menu_label(register(actions.disconnect), tr("action_disconnect")))
    else:
        root.append(menu_label(register(actions.connect_default), tr("action_connect"),
                               enabled=bool(nodes or selected_node)))
    root.append(_separator(3))

    servers = [menu_label(register(actions.ping), tr("btn_check_ping")), _separator(11)]
    display_nodes = nodes
    if protocol_filter != "all":
        display_nodes = [node for node in nodes if get_node_category(node) == protocol_filter]
    if not display_nodes:
        key = "no_servers_filter" if nodes else "no_servers"
        servers.append(menu_label(12, tr(key), enabled=False))
    for node in display_nodes:
        label = clean_node_name(node.get("name", "Server"))
        node_type = node.get("type") or ""
        if node_type.lower() not in ("auto_balancer", "balancer"):
            label += f" [{(node_type or 'vless').upper()}]"
        ping = ping_map.get(f"{node.get('server')}:{node.get('port')}")
        if ping is not None:
            if ping > 0:
                label += f" • {ping}ms"
            elif ping == -1:
                label += " • Unavailable"
        if (is_running and selected_node and node.get("server") == selected_node.get("server")
                and node.get("port") == selected_node.get("port")):
            label = f"✔ {label}"
        servers.append(menu_label(register(partial(actions.connect_node, node)), label))
    root.append(_submenu(10, tr("menu_select_server"), servers))

    subscriptions = [
        menu_label(register(actions.paste_subscription), tr("btn_paste_sub")),
        menu_label(register(actions.add_subscription), tr("btn_add_manual")),
        menu_label(register(actions.refresh_subscriptions), tr("btn_refresh_all")),
        menu_label(register(actions.generate_warp), tr("btn_generate_warp")),
        _separator(21),
    ]
    urls = settings.get("subscriptions", [])
    if not urls:
        subscriptions.append(menu_label(22, tr("no_subscriptions"), enabled=False))
    else:
        metadata = settings.get("subscription_metadata", {})
        for url in urls:
            meta = metadata.get(url, {})
            title = meta.get("name")
            if not title:
                title = url.split("://")[-1].split("/")[0] if "://" in url else url[:28]
            label = f"🔗 {title}"
            if meta.get("total"):
                used = (meta.get("upload") or 0) + (meta.get("download") or 0)
                label += f" • {format_bytes(used)}/{format_bytes(meta['total'])}"
            if meta.get("expire"):
                expiry = format_expiry(meta["expire"], get_lang())
                if expiry:
                    label += f" ({expiry})"
            subscriptions.append(menu_label(register(lambda: None), label, enabled=False))
    root.append(_submenu(20, tr("menu_subscriptions"), subscriptions))

    presets = []
    for preset, key in (
        (PRESET_DEFAULT, "preset_default"),
        (PRESET_BYPASS_RU, "preset_bypass_ru"),
        (PRESET_GAMING, "preset_gaming"),
        (PRESET_ROSCOMVPN, "preset_roscomvpn"),
    ):
        prefix = "✔ " if selected_preset == preset else ""
        presets.append(menu_label(register(partial(actions.set_preset, preset)), f"{prefix}{tr(key)}"))
    presets.extend([_separator(31), menu_label(register(actions.update_rules), tr("btn_update_rules"))])
    root.append(_submenu(30, tr("menu_preset"), presets))

    filters = []
    for protocol, key in (
        ("all", "filter_all"),
        ("tls", "filter_tls"),
        ("obfs", "filter_obfs"),
        ("udp", "filter_udp"),
    ):
        prefix = "✔ " if protocol_filter == protocol else ""
        filters.append(menu_label(register(partial(actions.set_protocol_filter, protocol)), f"{prefix}{tr(key)}"))
    root.append(_submenu(35, tr("menu_protocol_filter"), filters))

    prefix = "✔ " if autostart_enabled() else ""
    root.extend([
        _separator(40),
        menu_label(register(actions.toggle_autostart), f"{prefix}{tr('toggle_autostart')}"),
        menu_label(register(actions.quit_tray), tr("action_quit")),
    ])
    return root, {10: servers, 20: subscriptions, 30: presets, 35: filters}
