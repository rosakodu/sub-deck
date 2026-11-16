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
    """Generates complete sing-box JSON configuration for Hysteria 2 / TUIC / Cloudflare WARP / Amnezia AWG."""
    proto = node.get("type", "hysteria2").lower()
    is_warp = proto in ("warp", "wireguard")
    is_awg = proto == "awg"

    direct_outbound: Dict[str, Any] = {"type": "direct", "tag": "direct"}
    if iface:
        direct_outbound["bind_interface"] = iface

    endpoints = []
    if is_awg:
        local_addr = node.get("local_address", ["10.0.0.2/32"])
        if isinstance(local_addr, str):
            local_addr = [a.strip() for a in local_addr.split(",") if a.strip()]

        awg_endpoint: Dict[str, Any] = {
            "type": "awg",
            "tag": "proxy",
            "address": local_addr,
            "private_key": node.get("private_key", ""),
        }
        if iface:
            awg_endpoint["bind_interface"] = iface
        if node.get("mtu"):
            try:
                awg_endpoint["mtu"] = int(node["mtu"])
            except (ValueError, TypeError):
                pass

        for int_field in ("jc", "jmin", "jmax", "s1", "s2", "s3", "s4"):
            val = node.get(int_field)
            if val is not None and val != "":
                try:
                    awg_endpoint[int_field] = int(val)
                except (ValueError, TypeError):
                    pass

        for str_field in ("h1", "h2", "h3", "h4", "i1", "i2", "i3", "i4", "i5"):
            val = node.get(str_field)
            if val is not None and val != "":
                awg_endpoint[str_field] = str(val)

        peer_allowed = node.get("allowed_ips", ["0.0.0.0/0", "::/0"])
        if isinstance(peer_allowed, str):
            peer_allowed = [a.strip() for a in peer_allowed.split(",") if a.strip()]

        peer_pub = node.get("public_key") or node.get("peer_public_key", "")
        peer_obj: Dict[str, Any] = {
            "address": server_ip or node.get("server", ""),
            "port": int(node.get("port", 51820)),
            "public_key": peer_pub,
            "allowed_ips": peer_allowed,
        }
        if node.get("preshared_key"):
            peer_obj["preshared_key"] = node["preshared_key"]

        awg_endpoint["peers"] = [peer_obj]
        endpoints.append(awg_endpoint)

        outbounds = [
            direct_outbound,
            {"type": "block", "tag": "block"},
        ]
    elif is_warp:
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

    rules: List[Dict[str, Any]] = []

    # If AWG or WARP with internal/custom DNS, route DNS server IPs and port 53 to proxy FIRST
    if is_warp or is_awg:
        node_dns = node.get("dns") or ["10.254.254.254", "1.1.1.1"]
        if isinstance(node_dns, str):
            dns_ips = [d.strip() for d in node_dns.split(",") if d.strip()]
        else:
            dns_ips = [str(d).strip() for d in node_dns if str(d).strip()]
        if dns_ips:
            rules.append({
                "ip_cidr": [f"{ip}/32" if "/" not in ip else ip for ip in dns_ips],
                "outbound": "proxy",
            })
        rules.append({"port": [53], "outbound": "proxy"})

    rules.append({"ip_is_private": True, "outbound": "direct"})

    if preset == PRESET_BYPASS_RU:
        rules.append({"domain_suffix": [".ru", ".su", ".xn--p1ai"] + RU_BYPASS_DOMAINS, "outbound": "direct"})
    elif preset == PRESET_GAMING:
        rules.append({"domain_suffix": STEAM_CDN_DOMAINS, "outbound": "direct"})
    elif preset == PRESET_ROSCOMVPN:
        rules.append({"domain_suffix": [".ru", ".su", ".xn--p1ai"] + RU_BYPASS_DOMAINS, "outbound": "direct"})

    if is_warp or is_awg:
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
        node_dns = node.get("dns") or ["10.254.254.254", "1.1.1.1"]
        if isinstance(node_dns, str):
            node_dns = [d.strip() for d in node_dns.split(",") if d.strip()]
        primary_dns = node_dns[0] if node_dns else "10.254.254.254"

        cfg["dns"] = {
            "servers": [
                {
                    "tag": "remote-dns",
                    "type": "udp",
                    "server": primary_dns,
                    "server_port": 53,
                    "detour": "proxy",
                }
            ],
            "strategy": "prefer_ipv4",
        }
        cfg["route"]["default_domain_resolver"] = "remote-dns"
    return cfg
