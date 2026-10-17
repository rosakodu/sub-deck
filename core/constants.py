"""
Centralized constants for sub-deck.
Single source of truth for URLs, defaults and configuration.
"""

# Plugin version
PLUGIN_VERSION = "1.1.8"

# Preset identifiers
PRESET_DEFAULT = "default"        # Full Tunnel
PRESET_BYPASS_RU = "bypass_ru"    # Bypass Russian resources & LAN
PRESET_GAMING = "gaming"          # Split-tunneling: Steam downloads & games direct, VPN for blocked/voice
PRESET_ROSCOMVPN = "roscomvpn"    # Only blocked (Roskomnadzor registry)

# Real delay probe URLs
URL_TEST_URL = "http://www.gstatic.com/generate_204"
URL_TEST_FALLBACK = "https://cp.cloudflare.com/generate_204"

# Steam download CDN domains (for gaming preset split-tunneling)
STEAM_CDN_DOMAINS = [
    "steamcontent.com",
    "steamserver.net",
    "steamstatic.com",
    "steamgames.com",
    "valvesoftware.com",
    "steampipe.akamaized.net",
    "steam.fcdn.steamcontent.com",
    "epicgames.com",
    "ea.com",
    "battle.net",
    "blizzard.com",
    "gog.com",
]

# Popular Russian domains for bypass_ru preset
RU_BYPASS_DOMAINS = [
    "2gis.com", "2gis.ru", "47news.ru", "alfabank.ru", "auth-nsdi.ru",
    "auto.ru", "avito.ru", "avito.st", "cdn-vk.ru", "cikrf.ru",
    "dobro.ru", "dzen.ru", "evotor.ru", "gazeta.ru", "gosuslugi.ru",
    "gov.ru", "government.ru", "gu-st.ru", "hrlink.ru", "imgsmail.ru",
    "izbirkom.ru", "kinopoisk.ru", "kp.ru", "kremlin.ru", "lemanapro.ru",
    "lenta.ru", "lizaalert.org", "lmru.tech", "mail.ru", "max.ru",
    "mradx.net", "ofd.ru", "ok.ru", "okcdn.ru", "oneme.ru",
    "onf.ru", "ozon.ru", "ozone.ru", "pochta.ru", "rambler.ru",
    "rbc.ru", "res-nsdi.ru", "rutube.ru", "rutubelist.ru", "rzd.ru",
    "sberbank.ru", "sber.ru", "sirius.online", "sochisirius.ru", "sportmail.ru",
    "t2.ru", "tinkoff.ru", "tbank.ru", "taximaxim.ru", "tutu.ru", "userapi.com",
    "vk-portal.net", "vk.com", "vk.ru", "vtb.ru", "wb.ru", "wildberries.ru",
    "xn--80ajghhoc2aj1c8b.xn--p1ai", "ya.ru", "yandex.com", "yandex.net",
    "yandex.ru", "yastatic.net", "mts.ru", "megafon.ru", "beeline.ru",
]

# Default free subscriptions provided out of the box
FREE_SUBSCRIPTIONS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://gitlab.com/avencores/goida-vpn-configs/-/raw/main/githubmirror/1.txt",
    "https://raw.githubusercontent.com/zieng2/wl/main/vless_universal.txt",
]

# Network configuration
DEFAULT_SOCKS_HOST = "127.0.0.1"
DEFAULT_SOCKS_PORT = 10808
TUN_INTERFACE = "tun0"
TUN_IP_CIDR = "198.18.0.1/15"
TUN_MTU = "1420"
DNS_SERVERS = ["8.8.8.8", "1.1.1.1"]

# Supported proxy URL schemes
SUPPORTED_SCHEMES = (
    "vless://",
    "vmess://",
    "trojan://",
    "ss://",
    "hysteria2://",
    "hy2://",
    "tuic://",
)

# User-Agents for subscription fetching
SUBSCRIPTION_USER_AGENTS = [
    "Happ/3.0.0",
    "clash-verge/v1.6.6",
    "v2rayN/6.42",
    "sing-box/1.9.0",
    "FlClash/0.14.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
]

# Binary download sources
XRAY_RELEASE_URL = "https://github.com/XTLS/Xray-core/releases/download/v26.9.30/Xray-linux-64.zip"
TUN2SOCKS_RELEASE_URL = "https://github.com/xjasonlyu/tun2socks/releases/download/v2.7.0/tun2socks-linux-amd64.zip"
SINGBOX_RELEASE_URL = "https://github.com/SagerNet/sing-box/releases/download/v1.14.3/sing-box-1.14.3-linux-amd64.tar.gz"

# Throne routing profiles sources
THRONE_ROUTING_PROFILES = {
    "Bypass_Russia": "https://raw.githubusercontent.com/throneproj/routeprofiles/profile/Bypass_Russia.json",
    "Proxy_Antizapret": "https://raw.githubusercontent.com/throneproj/routeprofiles/profile/Proxy_Antizapret.json",
    "Proxy_Russia_Blocked": "https://raw.githubusercontent.com/throneproj/routeprofiles/profile/Proxy_Russia_Blocked.json",
    "Proxy_Refilter": "https://raw.githubusercontent.com/throneproj/routeprofiles/profile/Proxy_Refilter.json",
}

# Geo database sources (for Xray, sing-box and roscomvpn preset)
GEOIP_DAT_URL = "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat"
GEOSITE_DAT_URL = "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat"
GEOIP_RELEASE_URL = "https://github.com/SagerNet/sing-geoip/releases/latest/download/geoip.db"
GEOSITE_RELEASE_URL = "https://github.com/SagerNet/sing-geosite/releases/latest/download/geosite.db"
MIN_GEO_FILE_SIZE = 1_000_000  # 1 MB
GEO_UPDATE_INTERVAL_SECONDS = 6 * 3600  # 6 hours

# Node limits
FREE_SUBSCRIPTION_NODE_LIMIT = 5
REGULAR_SUBSCRIPTION_NODE_LIMIT = 15
PING_SAMPLE_MAX = 50
PING_DEFAULT_TIMEOUT = 1.0

# Desktop Tray & Local IPC configuration
IPC_HOST = "127.0.0.1"
IPC_PORT = 45321
IPC_SOCKET_PATH = "/tmp/sub-deck.sock"
DESKTOP_APP_ID = "sub-deck-tray"
DESKTOP_APP_NAME = "Sub-Deck VPN"

