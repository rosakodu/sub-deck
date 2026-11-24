"""Desktop tray translations and subscription label formatting."""

import os
import time
from typing import Optional


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
        "menu_protocol_filter": "Фильтр протоколов",
        "filter_all": "Все протоколы",
        "filter_tls": "TLS / Веб (Reality / Trojan)",
        "filter_obfs": "Обфускация / Random (AWG / Warp)",
        "filter_udp": "Скоростной UDP (Hysteria 2 / TUIC)",
        "no_servers_filter": "Нет серверов для выбранного протокола",
        "btn_paste_sub": "📋 Вставить из буфера обмена",
        "btn_add_manual": "✏️ Ввести URL вручную...",
        "btn_check_ping": "⚡ Проверить пинг",
        "btn_refresh_all": "🔄 Обновить все подписки",
        "btn_generate_warp": "Warp Generation",
        "notify_warp_generated": "Warp Generation успешно сгенерирован",
        "notify_warp_failed": "Ошибка генерации Warp Generation",
        "toggle_autostart": "Автозапуск в Desktop Mode",
        "action_quit": "Выход из трея",
        "preset_default": "Весь трафик",
        "preset_bypass_ru": "Только заблокированные сайты (РФ напрямую)",
        "preset_gaming": "Игровой",
        "preset_roscomvpn": "Roscom",
        "btn_update_rules": "🔄 Обновить правила маршрутизации",
        "notify_rules_updated": "Правила маршрутизации успешно обновлены",
        "notify_rules_failed": "Ошибка обновления правил",
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
        "menu_protocol_filter": "Protocol Filter",
        "filter_all": "All Protocols",
        "filter_tls": "TLS / Web (Reality / Trojan)",
        "filter_obfs": "Obfuscation / Random (AWG / Warp)",
        "filter_udp": "Fast UDP (Hysteria 2 / TUIC)",
        "no_servers_filter": "No servers found for this protocol filter",
        "btn_paste_sub": "📋 Paste from Clipboard",
        "btn_add_manual": "✏️ Enter URL manually...",
        "btn_check_ping": "⚡ Check Ping",
        "btn_refresh_all": "🔄 Refresh All Subscriptions",
        "btn_generate_warp": "Warp Generation",
        "notify_warp_generated": "Warp Generation successfully generated",
        "notify_warp_failed": "Failed to generate Warp Generation",
        "btn_update_rules": "🔄 Update Routing Rules",
        "notify_rules_updated": "Routing rules successfully updated",
        "notify_rules_failed": "Failed to update routing rules",
        "toggle_autostart": "Autostart in Desktop Mode",
        "action_quit": "Exit Tray",
        "preset_default": "All Traffic",
        "preset_bypass_ru": "Blocked sites only (Direct RU & LAN)",
        "preset_gaming": "Gaming",
        "preset_roscomvpn": "Roscom",
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
