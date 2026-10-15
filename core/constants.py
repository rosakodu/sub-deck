"""
Centralized constants for sub-deck.
Single source of truth for URLs, defaults and configuration.
"""

# Preset identifiers
PRESET_DEFAULT = "default"
PRESET_ROSCOMVPN = "roscomvpn"

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
)

# User-Agents for subscription fetching
SUBSCRIPTION_USER_AGENTS = [
    "clash-verge/v1.6.6",
    "v2rayN/6.42",
    "sing-box/1.9.0",
    "FlClash/0.14.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
]

# Binary download sources
XRAY_RELEASE_URL = "https://github.com/XTLS/Xray-core/releases/download/v26.9.30/Xray-linux-64.zip"
TUN2SOCKS_RELEASE_URL = "https://github.com/xjasonlyu/tun2socks/releases/download/v2.7.0/tun2socks-linux-amd64.zip"

# Geo database sources (for roscomvpn preset)
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

