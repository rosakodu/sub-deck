"""
Sing-box configuration generator for Hysteria 2 and TUIC v5.
Constructs inbound/outbound/routing topologies with preset rules.
"""

from typing import Dict, Any, Optional, List
from core.constants import (
    DEFAULT_SOCKS_HOST,
    DEFAULT_SOCKS_PORT,
    PRESET_DEFAULT,
    PRESET_BYPASS_RU,
    PRESET_GAMING,
    PRESET_ROSCOMVPN,
    STEAM_CDN_DOMAINS,
    RU_BYPASS_DOMAINS,
)


def build_singbox_outbound(node: Dict[str, Any], server_ip: str, iface: Optional[str] = None) -> Dict[str, Any]:
    """Builds protocol outbound structure for Hysteria 2 or TUIC."""
    proto = node.get("type", "hysteria2")
    server_host = node.get("server", server_ip)
    port = node.get("port", 443)

    outbound: Dict[str, Any] = {
        "tag": "proxy",
        "server": server_ip or server_host,
        "server_port": port,
    }
    if iface:
        outbound["bind_interface"] = iface

    if proto in ("hysteria2", "hy2"):
        outbound["type"] = "hysteria2"
        outbound["password"] = node.get("password", "")
        tls_obj: Dict[str, Any] = {
            "enabled": True,
            "server_name": node.get("sni") or server_host,
            "insecure": bool(node.get("insecure", False)),
        }
        outbound["tls"] = tls_obj
        if node.get("obfs_type"):
            outbound["obfs"] = {
                "type": node.get("obfs_type"),
                "password": node.get("obfs_password", ""),
            }

    elif proto == "tuic":
        outbound["type"] = "tuic"
        outbound["uuid"] = node.get("uuid", "")
        outbound["password"] = node.get("password", "")
        outbound["congestion_control"] = node.get("congestion_control", "bbr")
        alpn = node.get("alpn", "h3")
        alpn_list = [alpn] if isinstance(alpn, str) else alpn
        outbound["tls"] = {
            "enabled": True,
            "server_name": node.get("sni") or server_host,
            "insecure": bool(node.get("insecure", False)),
            "alpn": alpn_list,
        }

    return outbound


def build_singbox_config(
    node: Dict[str, Any],
    server_ip: str,
    preset: str = PRESET_DEFAULT,
    iface: Optional[str] = None,
) -> Dict[str, Any]:
    """Generates complete sing-box JSON configuration for Hysteria 2 / TUIC / Cloudflare WARP."""
    proto = node.get("type", "hysteria2").lower()
    is_warp = proto in ("warp", "wireguard")

    direct_outbound: Dict[str, Any] = {"type": "direct", "tag": "direct"}
    if iface:
        direct_outbound["bind_interface"] = iface

    endpoints = []
    if is_warp:
        wg_endpoint: Dict[str, Any] = {
            "type": "wireguard",
            "tag": "proxy",
            "address": node.get("local_address", ["172.16.0.2/32"]),
            "private_key": node.get("private_key", ""),
            "peers": [
                {
                    "address": server_ip or node.get("server", "162.159.192.1"),
                    "port": int(node.get("port", 2408)),
                    "public_key": node.get("peer_public_key", "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="),
                    "reserved": node.get("reserved", [0, 0, 0]),
                    "allowed_ips": ["0.0.0.0/0", "::/0"],
                }
            ],
            "mtu": int(node.get("mtu", 1280)),
        }
        if iface:
            wg_endpoint["bind_interface"] = iface
        endpoints.append(wg_endpoint)

        outbounds = [
            direct_outbound,
            {"type": "block", "tag": "block"},
        ]
    else:
        proxy_outbound = build_singbox_outbound(node, server_ip, iface=iface)
        outbounds = [
            proxy_outbound,
            direct_outbound,
            {"type": "block", "tag": "block"},
        ]

    rules: List[Dict[str, Any]] = [
        {"ip_is_private": True, "outbound": "direct"},
    ]

    if preset == PRESET_BYPASS_RU:
        rules.append({"domain_suffix": [".ru", ".su", ".xn--p1ai"] + RU_BYPASS_DOMAINS, "outbound": "direct"})
    elif preset == PRESET_GAMING:
        rules.append({"domain_suffix": STEAM_CDN_DOMAINS, "outbound": "direct"})
    elif preset == PRESET_ROSCOMVPN:
        rules.append({"domain_suffix": [".ru", ".su", ".xn--p1ai"] + RU_BYPASS_DOMAINS, "outbound": "direct"})

    if is_warp:
        rules.append({"action": "route", "outbound": "proxy"})

    cfg: Dict[str, Any] = {
        "log": {"level": "warn"},
        "inbounds": [
            {
                "type": "socks",
                "tag": "socks-in",
                "listen": DEFAULT_SOCKS_HOST,
                "listen_port": DEFAULT_SOCKS_PORT,
            }
        ],
        "outbounds": outbounds,
        "route": {
            "rules": rules,
            "auto_detect_interface": True if not iface else False,
        },
    }
    if endpoints:
        cfg["endpoints"] = endpoints
    return cfg
