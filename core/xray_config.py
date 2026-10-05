"""
Xray configuration generator and validator.
Constructs inbound/outbound/routing topologies for supported protocols.
"""

import json
import subprocess
from typing import Dict, Any, Tuple
from core.constants import DEFAULT_SOCKS_HOST, DEFAULT_SOCKS_PORT, PRESET_ROSCOMVPN


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


def build_xray_config(node: Dict[str, Any], server_ip: str, preset: str = "default") -> Dict[str, Any]:
    """Generates complete Xray JSON configuration structure."""
    outbound = build_outbound(node, server_ip)

    outbounds = [
        outbound,
        {"protocol": "freedom", "tag": "direct", "settings": {"domainStrategy": "UseIP"}},
        {"protocol": "blackhole", "tag": "block"},
    ]

    if preset == PRESET_ROSCOMVPN:
        routing_rules = [
            {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
            {"type": "field", "outboundTag": "proxy", "network": "tcp,udp"},
        ]
    else:
        routing_rules = [
            {"type": "field", "outboundTag": "proxy", "network": "tcp,udp"},
        ]

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
