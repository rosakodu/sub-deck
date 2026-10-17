"""
Xray configuration generator and validator.
Constructs inbound/outbound/routing topologies for supported protocols.
"""

import json
import subprocess
from typing import Dict, Any, Tuple, Optional, List
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


def build_outbound(node: Dict[str, Any], server_ip: str) -> Dict[str, Any]:
    """Generates protocol-specific Xray outbound configuration block."""
    protocol = node.get("type")
    server_host = node["server"]
    port = node["port"]

    if protocol == "vless":
        stream_settings: Dict[str, Any] = {}
        transport = node.get("transport", "tcp")

        if transport == "xhttp":
            stream_settings["network"] = "xhttp"
            xhttp_settings: Dict[str, Any] = {
                "path": node.get("path") or "/",
                "host": node.get("host") or node.get("sni") or server_host,
                "mode": node.get("mode") or "packet-up",
            }
            if node.get("extra"):
                xhttp_settings["extra"] = node["extra"]
            stream_settings["xhttpSettings"] = xhttp_settings

            stream_settings["security"] = "tls"
            stream_settings["tlsSettings"] = {
                "serverName": node.get("sni") or node.get("host") or server_host,
                "fingerprint": node.get("fp") or "edge",
                "alpn": node.get("alpn") or ["h2"],
            }
        elif transport == "grpc":
            stream_settings["network"] = "grpc"
            stream_settings["grpcSettings"] = {
                "serviceName": node.get("service_name", "grpc"),
                "multiMode": node.get("mode") == "multi",
            }
        elif transport in ("ws", "websocket"):
            stream_settings["network"] = "ws"
            ws_settings: Dict[str, Any] = {"path": node.get("path") or "/"}
            if node.get("host") or node.get("sni"):
                ws_settings["headers"] = {"Host": node.get("host") or node.get("sni")}
            stream_settings["wsSettings"] = ws_settings
        else:
            stream_settings["network"] = "tcp"

        security = node.get("security", "none")
        if security == "reality":
            stream_settings["security"] = "reality"
            stream_settings["realitySettings"] = {
                "serverName": node.get("sni") or server_host,
                "fingerprint": node.get("fp") or "chrome",
                "publicKey": node.get("pbk", ""),
                "shortId": node.get("sid", ""),
                "spiderX": node.get("spx", ""),
            }
        elif security == "tls" and transport != "xhttp":
            stream_settings["security"] = "tls"
            stream_settings["tlsSettings"] = {
                "serverName": node.get("sni") or server_host,
                "fingerprint": node.get("fp") or "chrome",
                "alpn": node.get("alpn") or [],
            }
        elif security == "none" and transport != "xhttp":
            stream_settings["security"] = "none"

        user_obj: Dict[str, Any] = {
            "id": node["uuid"],
            "encryption": "none",
        }
        if node.get("flow"):
            user_obj["flow"] = node["flow"]

        return {
            "protocol": "vless",
            "tag": "proxy",
            "settings": {
                "vnext": [
                    {
                        "address": server_ip,
                        "port": port,
                        "users": [user_obj],
                    }
                ]
            },
            "streamSettings": stream_settings,
        }

    elif protocol == "vmess":
        stream_settings = {"network": node.get("transport", "tcp")}
        if node.get("security") == "tls":
            stream_settings["security"] = "tls"
            stream_settings["tlsSettings"] = {
                "serverName": node.get("sni") or server_host,
                "fingerprint": node.get("fp") or "chrome",
            }
        return {
            "protocol": "vmess",
            "tag": "proxy",
            "settings": {
                "vnext": [
                    {
                        "address": server_ip,
                        "port": port,
                        "users": [
                            {
                                "id": node["uuid"],
                                "alterId": 0,
                                "security": "auto",
                            }
                        ],
                    }
                ]
            },
            "streamSettings": stream_settings,
        }

    elif protocol == "trojan":
        stream_settings = {
            "network": node.get("transport", "tcp"),
            "security": "tls",
            "tlsSettings": {
                "serverName": node.get("sni") or server_host,
                "fingerprint": node.get("fp") or "chrome",
            },
        }
        return {
            "protocol": "trojan",
            "tag": "proxy",
            "settings": {
                "servers": [
                    {
                        "address": server_ip,
                        "port": port,
                        "password": node["password"],
                    }
                ]
            },
            "streamSettings": stream_settings,
        }

    elif protocol == "shadowsocks":
        return {
            "protocol": "shadowsocks",
            "tag": "proxy",
            "settings": {
                "servers": [
                    {
                        "address": server_ip,
                        "port": port,
                        "method": node["method"],
                        "password": node["password"],
                    }
                ]
            },
        }

    # Default fallback outbound
    return {
        "protocol": "freedom",
        "tag": "proxy",
        "settings": {},
    }


def build_xray_config(node: Dict[str, Any], server_ip: str, preset: str = "default", iface: Optional[str] = None) -> Dict[str, Any]:
    """Generates complete Xray JSON configuration structure."""
    outbound = build_outbound(node, server_ip)

    direct_outbound: Dict[str, Any] = {"protocol": "freedom", "tag": "direct", "settings": {"domainStrategy": "UseIP"}}
    if iface:
        direct_outbound["streamSettings"] = {"sockopt": {"interface": iface}}
        if "streamSettings" in outbound:
            outbound["streamSettings"].setdefault("sockopt", {})["interface"] = iface

    outbounds = [
        outbound,
        direct_outbound,
        {"protocol": "blackhole", "tag": "block"},
    ]

    routing_rules = [
        {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
    ]

    if preset == PRESET_BYPASS_RU:
        routing_rules.append({
            "type": "field",
            "domain": RU_BYPASS_DOMAINS + ["geosite:category-ru"],
            "outboundTag": "direct"
        })
        routing_rules.append({
            "type": "field",
            "ip": ["geoip:ru"],
            "outboundTag": "direct"
        })
        routing_rules.append({
            "type": "field",
            "outboundTag": "proxy",
            "network": "tcp,udp"
        })
    elif preset == PRESET_GAMING:
        # Steam game CDN and platform downloads go direct for max throughput and lowest latency
        routing_rules.append({
            "type": "field",
            "domain": STEAM_CDN_DOMAINS,
            "outboundTag": "direct"
        })
        routing_rules.append({
            "type": "field",
            "outboundTag": "proxy",
            "network": "tcp,udp"
        })
    elif preset == PRESET_ROSCOMVPN:
        routing_rules.append({
            "type": "field",
            "domain": ["geosite:category-ru-blocked"],
            "outboundTag": "proxy"
        })
        routing_rules.append({
            "type": "field",
            "outboundTag": "direct",
            "network": "tcp,udp"
        })
    else:  # PRESET_DEFAULT (Full Tunnel)
        routing_rules.append({
            "type": "field",
            "outboundTag": "proxy",
            "network": "tcp,udp"
        })

    return {
        "log": {
            "loglevel": "warning",
        },
        "inbounds": [
            {
                "tag": "socks-in",
                "port": DEFAULT_SOCKS_PORT,
                "listen": DEFAULT_SOCKS_HOST,
                "protocol": "socks",
                "settings": {
                    "auth": "noauth",
                    "udp": True,
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls", "quic"],
                },
            }
        ],
        "outbounds": outbounds,
        "routing": {
            "domainStrategy": "AsIs",
            "rules": routing_rules,
        },
    }


def build_auto_balancer_config(
    nodes: List[Dict[str, Any]],
    preset: str = PRESET_DEFAULT,
    iface: Optional[str] = None
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Constructs an Xray multi-outbound topology with an observatory and leastPing balancer.
    Automatically steers traffic through the lowest-latency responsive node.
    """
    from core.system import resolve_host

    outbounds = []
    server_ips = []
    candidate_tags = []

    # Collect valid proxy candidate nodes
    for idx, node in enumerate(nodes):
        if node.get("type") not in ("vless", "vmess", "trojan", "shadowsocks", "balancer"):
            continue
        host = node.get("server")
        if not host:
            continue
        ip = resolve_host(host) or host
        if ip and ip not in server_ips:
            server_ips.append(ip)

        tag = f"proxy-{idx + 1}"
        if node.get("raw_config") and "outbounds" in node["raw_config"]:
            import copy
            proxy_ob = None
            for o in node["raw_config"]["outbounds"]:
                if o.get("protocol") in ("vless", "vmess", "trojan", "shadowsocks"):
                    proxy_ob = copy.deepcopy(o)
                    break
            if not proxy_ob and node["raw_config"]["outbounds"]:
                proxy_ob = copy.deepcopy(node["raw_config"]["outbounds"][0])
            ob = proxy_ob or build_outbound(node, ip)
        else:
            try:
                ob = build_outbound(node, ip)
            except Exception:
                continue

        ob["tag"] = tag
        if iface and "streamSettings" in ob:
            ob["streamSettings"].setdefault("sockopt", {})["interface"] = iface

        outbounds.append(ob)
        candidate_tags.append(tag)

    if not outbounds:
        outbounds.append({"protocol": "freedom", "tag": "proxy-1"})
        candidate_tags.append("proxy-1")

    direct_outbound: Dict[str, Any] = {"protocol": "freedom", "tag": "direct", "settings": {"domainStrategy": "UseIP"}}
    if iface:
        direct_outbound["streamSettings"] = {"sockopt": {"interface": iface}}

    outbounds.append(direct_outbound)
    outbounds.append({"protocol": "blackhole", "tag": "block"})

    # Base routing rules
    routing_rules = [
        {"type": "field", "port": "53", "outboundTag": candidate_tags[0]},
        {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
    ]

    if preset == PRESET_BYPASS_RU:
        routing_rules.append({"type": "field", "domain": RU_BYPASS_DOMAINS + ["geosite:category-ru"], "outboundTag": "direct"})
        routing_rules.append({"type": "field", "ip": ["geoip:ru"], "outboundTag": "direct"})
    elif preset == PRESET_GAMING:
        routing_rules.append({"type": "field", "domain": STEAM_CDN_DOMAINS, "outboundTag": "direct"})
    elif preset == PRESET_ROSCOMVPN:
        routing_rules.append({"type": "field", "domain": ["geosite:category-ru-blocked"], "balancerTag": "auto_least_ping"})
        routing_rules.append({"type": "field", "outboundTag": "direct", "network": "tcp,udp"})

    # Catch-all rule for leastPing balancer
    routing_rules.append({
        "type": "field",
        "network": "tcp,udp",
        "balancerTag": "auto_least_ping"
    })

    config_data = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "socks-in",
                "port": DEFAULT_SOCKS_PORT,
                "listen": DEFAULT_SOCKS_HOST,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
                "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]}
            }
        ],
        "outbounds": outbounds,
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "balancers": [
                {
                    "tag": "auto_least_ping",
                    "selector": ["proxy-"],
                    "strategy": {"type": "leastPing"},
                    "fallbackTag": candidate_tags[0]
                }
            ],
            "rules": routing_rules
        },
        "observatory": {
            "probeUrl": "http://www.gstatic.com/generate_204",
            "probeInterval": "30s",
            "subjectSelector": ["proxy-"]
        }
    }

    return config_data, server_ips


def validate_xray_config(xray_path: str, config_path: str, env: Dict[str, str]) -> Tuple[bool, str]:
    """Runs `xray -test -config <path>` to verify config syntax before starting process."""
    try:
        res = subprocess.run(
            [xray_path, "-test", "-config", config_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            timeout=3.0,
        )
        if res.returncode == 0:
            return True, ""
        return False, res.stderr or res.stdout
    except Exception as e:
        return False, str(e)
