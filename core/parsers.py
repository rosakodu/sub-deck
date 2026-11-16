"""
Subscription parser for various proxy protocols:
VLESS, VMess, Trojan, Shadowsocks, Hysteria 2.
"""

import base64
import hashlib
import http.client
import json
import os
import re
import socket
import ssl
import struct
import urllib.parse
import urllib.request
import zlib
from typing import Dict, List, Optional, Tuple, Any

from core.constants import (
    DEFAULT_SOCKS_HOST,
    DEFAULT_SOCKS_PORT,
    SUBSCRIPTION_USER_AGENTS,
    SUPPORTED_SCHEMES,
    FREE_SUBSCRIPTIONS,
    FREE_SUBSCRIPTION_NODE_LIMIT,
    REGULAR_SUBSCRIPTION_NODE_LIMIT,
)
from core.pinger import select_best_nodes


def is_free_subscription(url: str) -> bool:
    """Checks whether URL belongs to pre-bundled free subscriptions."""
    if not url:
        return False
    clean_url = url.strip().lower()
    for free_url in FREE_SUBSCRIPTIONS:
        if free_url.lower() in clean_url or clean_url in free_url.lower():
            return True
    return any(marker in clean_url for marker in (
        "igareck/vpn-configs-for-russia",
        "goida-vpn-configs",
        "zieng2/wl"
    ))


def parse_endpoint(endpoint: str) -> Tuple[str, int]:
    """Parses host:port, supporting IPv6 bracket notation [::1]:port and enforcing 1 <= port <= 65535."""
    if endpoint.startswith("["):
        bracket_end = endpoint.find("]")
        if bracket_end == -1:
            return endpoint, 443
        host = endpoint[1:bracket_end]
        rest = endpoint[bracket_end + 1:]
        try:
            port = int(rest.lstrip(":")) if ":" in rest else 443
        except ValueError:
            port = 443
    elif ":" in endpoint:
        host, port_str = endpoint.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            port = 443
    else:
        host = endpoint
        port = 443

    if not (1 <= port <= 65535):
        port = 443

    return host, port


def parse_vless_link(link: str) -> Optional[Dict[str, Any]]:
    """Parses a vless:// URI into node structure."""
    try:
        parsed = urllib.parse.urlparse(link)
        netloc = parsed.netloc
        if "@" not in netloc:
            return None

        uuid, endpoint = netloc.split("@", 1)
        host, port = parse_endpoint(endpoint)
        query = urllib.parse.parse_qs(parsed.query)
        params = {k: v[0] for k, v in query.items()}
        name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else f"VLESS {host}:{port}"

        extra_val = params.get("extra", "")
        extra_obj = None
        if extra_val:
            try:
                extra_obj = json.loads(urllib.parse.unquote(extra_val))
            except Exception:
                try:
                    extra_obj = json.loads(extra_val)
                except Exception:
                    extra_obj = None

        alpn_val = params.get("alpn", "")
        alpn_list = [a.strip() for a in alpn_val.split(",") if a.strip()] if alpn_val else []

        return {
            "type": "vless",
            "name": name,
            "server": host,
            "port": port,
            "uuid": uuid,
            "security": params.get("security", "none"),
            "sni": params.get("sni", ""),
            "pbk": params.get("pbk", ""),
            "sid": params.get("sid", ""),
            "spx": params.get("spx", ""),
            "flow": params.get("flow", ""),
            "fp": params.get("fp", "chrome"),
            "transport": params.get("type", "tcp"),
            "service_name": params.get("serviceName", ""),
            "path": params.get("path", ""),
            "host": params.get("host", ""),
            "mode": params.get("mode", ""),
            "extra": extra_obj,
            "alpn": alpn_list,
        }
    except Exception:
        return None


def parse_vmess_link(link: str) -> Optional[Dict[str, Any]]:
    """Parses a vmess:// URI (Base64 encoded JSON)."""
    try:
        raw_b64 = link[8:].strip()
        fragment_name = ""
        if "#" in raw_b64:
            raw_b64, frag = raw_b64.split("#", 1)
            fragment_name = urllib.parse.unquote(frag.strip())
        if "?" in raw_b64:
            raw_b64 = raw_b64.split("?", 1)[0]

        b64_data = raw_b64.strip()
        padded = b64_data + "=" * (-len(b64_data) % 4)
        raw_json = base64.b64decode(padded).decode("utf-8")
        data = json.loads(raw_json)

        name = data.get("ps") or fragment_name or f"VMess {data.get('add')}:{data.get('port')}"
        tls_val = data.get("tls", "")
        security = "tls" if tls_val == "tls" else "none"

        return {
            "type": "vmess",
            "name": name,
            "server": data.get("add"),
            "port": int(data.get("port", 443)),
            "uuid": data.get("id"),
            "security": security,
            "sni": data.get("sni", ""),
            "transport": data.get("net", "tcp"),
            "path": data.get("path", "/"),
            "host": data.get("host", ""),
        }
    except Exception:
        return None


def parse_trojan_link(link: str) -> Optional[Dict[str, Any]]:
    """Parses a trojan:// URI."""
    try:
        parsed = urllib.parse.urlparse(link)
        netloc = parsed.netloc
        if "@" not in netloc:
            return None
        password, endpoint = netloc.split("@", 1)
        host, port = parse_endpoint(endpoint)
        query = urllib.parse.parse_qs(parsed.query)
        params = {k: v[0] for k, v in query.items()}
        name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else f"Trojan {host}:{port}"

        return {
            "type": "trojan",
            "name": name,
            "server": host,
            "port": port,
            "password": password,
            "security": "tls",
            "sni": params.get("sni", ""),
            "transport": params.get("type", "tcp"),
            "service_name": params.get("serviceName", ""),
            "path": params.get("path", ""),
            "host": params.get("host", ""),
        }
    except Exception:
        return None


def parse_ss_link(link: str) -> Optional[Dict[str, Any]]:
    """Parses a ss:// (Shadowsocks) URI."""
    try:
        parsed = urllib.parse.urlparse(link)
        netloc = parsed.netloc

        if "@" not in netloc:
            try:
                padded = netloc + "=" * (-len(netloc) % 4)
                decoded = base64.b64decode(padded).decode("utf-8")
                if "@" in decoded:
                    netloc = decoded
            except Exception:
                pass

        if "@" not in netloc:
            return None

        credentials, endpoint = netloc.split("@", 1)
        if ":" not in credentials:
            try:
                padded = credentials + "=" * (-len(credentials) % 4)
                credentials = base64.b64decode(padded).decode("utf-8")
            except Exception:
                pass

        if ":" not in credentials:
            return None

        method, password = credentials.split(":", 1)
        host, port = parse_endpoint(endpoint)
        name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else f"Shadowsocks {host}:{port}"

        return {
            "type": "shadowsocks",
            "name": name,
            "server": host,
            "port": port,
            "method": method,
            "password": password,
            "security": "none",
        }
    except Exception:
        return None


def parse_hysteria2_link(link: str) -> Optional[Dict[str, Any]]:
    """Parses a hysteria2:// or hy2:// URI."""
    try:
        parsed = urllib.parse.urlparse(link)
        netloc = parsed.netloc
        if "@" not in netloc:
            return None
        password, endpoint = netloc.split("@", 1)
        host, port = parse_endpoint(endpoint)
        query = urllib.parse.parse_qs(parsed.query)
        params = {k: v[0] for k, v in query.items()}
        name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else f"Hysteria2 {host}:{port}"

        insecure = params.get("insecure", "0") in ("1", "true")

        return {
            "type": "hysteria2",
            "name": name,
            "server": host,
            "port": port,
            "password": password,
            "security": "tls",
            "sni": params.get("sni", ""),
            "insecure": insecure,
            "obfs_type": params.get("obfs", ""),
            "obfs_password": params.get("obfs-password", ""),
        }
    except Exception:
        return None


def parse_tuic_link(link: str) -> Optional[Dict[str, Any]]:
    """Parses a tuic:// URI."""
    try:
        parsed = urllib.parse.urlparse(link)
        netloc = parsed.netloc
        if "@" not in netloc:
            return None
        auth, endpoint = netloc.split("@", 1)
        uuid = auth
        password = ""
        if ":" in auth:
            uuid, password = auth.split(":", 1)
        host, port = parse_endpoint(endpoint)
        query = urllib.parse.parse_qs(parsed.query)
        params = {k: v[0] for k, v in query.items()}
        name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else f"TUIC {host}:{port}"

        insecure = params.get("allow_insecure", "0") in ("1", "true")

        return {
            "type": "tuic",
            "name": name,
            "server": host,
            "port": port,
            "uuid": uuid,
            "password": password,
            "security": "tls",
            "sni": params.get("sni", ""),
            "alpn": params.get("alpn", "h3"),
            "congestion_control": params.get("congestion_control", "bbr"),
            "insecure": insecure,
        }
    except Exception:
        return None


def parse_wireguard_conf(conf_text: str, name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Parses a WireGuard or AmneziaWG .conf INI format ([Interface] ... [Peer]).
    Extracts addresses, keys, endpoint, and AmneziaWG obfuscation parameters
    (Jc, Jmin, Jmax, S1-S4, H1-H4, I1-I5).
    """
    if not conf_text or not isinstance(conf_text, str):
        return None

    current_section = None
    interface_params: Dict[str, str] = {}
    peer_params: Dict[str, str] = {}
    conf_name = name

    for line in conf_text.splitlines():
        line = line.strip()
        if not line:
            continue

        is_comment = line.startswith("#") or line.startswith(";")
        if is_comment:
            clean = line.lstrip("#;").strip()
            if "=" in clean:
                c_key = clean.split("=", 1)[0].strip().lower()
                if c_key in ("i1", "i2", "i3", "i4", "i5", "h1", "h2", "h3", "h4", "jc", "jmin", "jmax", "s1", "s2", "s3", "s4"):
                    line = clean
                    is_comment = False

        if is_comment:
            if not conf_name and (line.lower().startswith("# name") or line.lower().startswith("# description")):
                if "=" in line:
                    conf_name = line.split("=", 1)[1].strip()
                elif ":" in line:
                    conf_name = line.split(":", 1)[1].strip()
            continue

        if not ('<' in line and '>' in line) and not ('"' in line or "'" in line):
            if "#" in line:
                line = line.split("#", 1)[0].strip()
            if ";" in line:
                line = line.split(";", 1)[0].strip()

        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip().lower()
            continue

        if "=" in line and current_section:
            key, val = line.split("=", 1)
            key = key.strip().lower()
            val = val.strip()
            if current_section == "interface":
                interface_params[key] = val
            elif current_section == "peer":
                peer_params[key] = val

    priv_key = interface_params.get("privatekey") or interface_params.get("private_key")
    pub_key = peer_params.get("publickey") or peer_params.get("public_key")
    endpoint = peer_params.get("endpoint")

    if not priv_key or not pub_key or not endpoint:
        return None

    host, port = parse_endpoint(endpoint)
    addr_val = interface_params.get("address") or interface_params.get("ip") or "10.0.0.2/32"
    local_addrs = [a.strip() for a in addr_val.split(",") if a.strip()]

    allowed_val = peer_params.get("allowedips") or peer_params.get("allowed_ips") or "0.0.0.0/0, ::/0"
    allowed_ips = [a.strip() for a in allowed_val.split(",") if a.strip()]

    node: Dict[str, Any] = {
        "type": "awg",
        "name": conf_name or f"AWG {host}:{port}",
        "server": host,
        "port": port,
        "private_key": priv_key,
        "public_key": pub_key,
        "local_address": local_addrs,
        "allowed_ips": allowed_ips,
    }

    psk = peer_params.get("presharedkey") or peer_params.get("preshared_key")
    if psk:
        node["preshared_key"] = psk

    mtu = interface_params.get("mtu") or peer_params.get("mtu")
    if mtu:
        try:
            node["mtu"] = int(mtu)
        except ValueError:
            pass

    dns = interface_params.get("dns")
    if dns:
        node["dns"] = [d.strip() for d in dns.split(",") if d.strip()]

    merged = dict(peer_params)
    merged.update(interface_params)

    for int_param in ("jc", "jmin", "jmax", "s1", "s2", "s3", "s4"):
        if int_param in merged:
            try:
                node[int_param] = int(merged[int_param])
            except ValueError:
                pass

    for str_param in ("h1", "h2", "h3", "h4", "i1", "i2", "i3", "i4", "i5"):
        if str_param in merged:
            node[str_param] = str(merged[str_param])

    return node


def parse_awg_link(link: str) -> Optional[Dict[str, Any]]:
    """
    Parses an awg:// URI. Supports:
    1. Direct URI: awg://private_key@host:port?public_key=...&jc=...#Name
    2. Query-only URI: awg://host:port?private_key=...&public_key=...
    3. Base64-encoded WireGuard/AWG .conf in awg://<base64>#Name
    """
    try:
        raw = link.strip()
        if not raw.lower().startswith("awg://"):
            return None
        body = raw[6:].strip()
        fragment_name = ""
        if "#" in body:
            body, frag = body.split("#", 1)
            fragment_name = urllib.parse.unquote(frag.strip())

        try:
            padded = body + "=" * (-len(body) % 4)
            decoded_bytes = base64.urlsafe_b64decode(padded)
            decoded_text = decoded_bytes.decode("utf-8", errors="ignore").strip()
            if "[Interface]" in decoded_text and "[Peer]" in decoded_text:
                return parse_wireguard_conf(decoded_text, name=fragment_name)
            if decoded_text.startswith("{") and decoded_text.endswith("}"):
                data = json.loads(decoded_text)
                if isinstance(data, dict):
                    if "config" in data and "[Interface]" in data["config"]:
                        return parse_wireguard_conf(data["config"], name=fragment_name or data.get("name"))
        except Exception:
            pass

        parsed = urllib.parse.urlparse(f"awg://{body}")
        netloc = parsed.netloc
        priv_key = ""
        if "@" in netloc:
            priv_key, endpoint = netloc.split("@", 1)
        else:
            endpoint = netloc

        host, port = parse_endpoint(endpoint)
        query = urllib.parse.parse_qs(parsed.query)
        params = {k.lower(): v[0] for k, v in query.items()}

        if not priv_key:
            priv_key = params.get("private_key") or params.get("privatekey") or params.get("pk", "")
        pub_key = params.get("public_key") or params.get("publickey") or params.get("peer_pk") or params.get("pbk", "")

        if not priv_key or not pub_key:
            return None

        name = fragment_name or params.get("name") or f"AWG {host}:{port}"
        addr_val = params.get("address") or params.get("ip") or params.get("local_address") or "10.0.0.2/32"
        local_addrs = [a.strip() for a in addr_val.split(",") if a.strip()]

        allowed_val = params.get("allowed_ips") or params.get("allowedips") or "0.0.0.0/0, ::/0"
        allowed_ips = [a.strip() for a in allowed_val.split(",") if a.strip()]

        node: Dict[str, Any] = {
            "type": "awg",
            "name": name,
            "server": host,
            "port": port,
            "private_key": priv_key,
            "public_key": pub_key,
            "local_address": local_addrs,
            "allowed_ips": allowed_ips,
        }

        psk = params.get("preshared_key") or params.get("presharedkey") or params.get("psk")
        if psk:
            node["preshared_key"] = psk

        mtu = params.get("mtu")
        if mtu:
            try:
                node["mtu"] = int(mtu)
            except ValueError:
                pass

        for int_field in ("jc", "jmin", "jmax", "s1", "s2", "s3", "s4"):
            if int_field in params:
                try:
                    node[int_field] = int(params[int_field])
                except ValueError:
                    pass

        for str_field in ("h1", "h2", "h3", "h4", "i1", "i2", "i3", "i4", "i5"):
            if str_field in params:
                node[str_field] = str(params[str_field])

        return node
    except Exception:
        return None


def decompress_amnezia_vpn_payload(raw_bytes: bytes) -> Optional[str]:
    """
    Decompresses Amnezia VPN base64url payload with zlib.
    Supports skipping 4-byte Qt header, scanning for 0x78 zlib magic byte,
    direct zlib decompression, and raw deflate fallback.
    """
    if not raw_bytes:
        return None

    try:
        candidate_text = raw_bytes.decode("utf-8").strip()
        if (candidate_text.startswith("{") and candidate_text.endswith("}")) or \
           (candidate_text.startswith("[") and candidate_text.endswith("]")):
            return candidate_text
    except Exception:
        pass

    decompressed: Optional[bytes] = None

    if len(raw_bytes) >= 4:
        try:
            decompressed = zlib.decompress(raw_bytes[4:])
        except Exception:
            pass

    if decompressed is None:
        try:
            decompressed = zlib.decompress(raw_bytes)
        except Exception:
            pass

    if decompressed is None:
        idx = 0
        while True:
            idx = raw_bytes.find(b"\x78", idx)
            if idx == -1:
                break
            try:
                decompressed = zlib.decompress(raw_bytes[idx:])
                break
            except Exception:
                idx += 1

    if decompressed is None:
        for offset in (4, 0):
            if len(raw_bytes) > offset:
                try:
                    decompressed = zlib.decompress(raw_bytes[offset:], -zlib.MAX_WBITS)
                    break
                except Exception:
                    pass

    if decompressed is not None:
        try:
            return decompressed.decode("utf-8")
        except Exception:
            return decompressed.decode("latin-1", errors="replace")

    return None


def _parse_awg_dict(d: Dict[str, Any], host_fallback: str, name: str) -> Optional[Dict[str, Any]]:
    low = {str(k).lower(): v for k, v in d.items()}
    priv_key = low.get("private_key") or low.get("privatekey") or low.get("client_priv_key")
    pub_key = low.get("public_key") or low.get("publickey") or low.get("server_pub_key")
    endpoint = low.get("endpoint") or low.get("server") or host_fallback
    port = int(low.get("port", 51820))

    if endpoint and ":" in str(endpoint):
        endpoint, port = parse_endpoint(str(endpoint))

    if not priv_key or not pub_key or not endpoint:
        return None

    local_addrs = low.get("local_address") or low.get("address") or low.get("ip") or ["10.0.0.2/32"]
    if isinstance(local_addrs, str):
        local_addrs = [a.strip() for a in local_addrs.split(",") if a.strip()]

    allowed = low.get("allowed_ips") or low.get("allowedips") or ["0.0.0.0/0", "::/0"]
    if isinstance(allowed, str):
        allowed = [a.strip() for a in allowed.split(",") if a.strip()]

    node = {
        "type": "awg",
        "name": name or f"AWG {endpoint}:{port}",
        "server": endpoint,
        "port": port,
        "private_key": str(priv_key),
        "public_key": str(pub_key),
        "local_address": local_addrs,
        "allowed_ips": allowed,
    }
    psk = low.get("preshared_key") or low.get("presharedkey") or low.get("psk")
    if psk:
        node["preshared_key"] = str(psk)

    mtu = low.get("mtu")
    if mtu:
        try:
            node["mtu"] = int(mtu)
        except (ValueError, TypeError):
            pass

    for int_key in ("jc", "jmin", "jmax", "s1", "s2", "s3", "s4"):
        if int_key in low:
            try:
                node[int_key] = int(low[int_key])
            except (ValueError, TypeError):
                pass

    for str_key in ("h1", "h2", "h3", "h4", "i1", "i2", "i3", "i4", "i5"):
        if str_key in low:
            node[str_key] = str(low[str_key])

    return node


def _parse_amnezia_xray_dict(d: Dict[str, Any], host_fallback: str, name: str) -> Optional[Dict[str, Any]]:
    low = {str(k).lower(): v for k, v in d.items()}
    server = low.get("address") or low.get("server") or host_fallback
    port = int(low.get("port", 443))
    uuid = low.get("user_id") or low.get("id") or low.get("uuid")

    if not server or not uuid:
        return None

    return {
        "type": "vless",
        "name": name or f"Xray {server}:{port}",
        "server": str(server),
        "port": port,
        "uuid": str(uuid),
        "flow": str(low.get("flow", "xtls-rprx-vision")),
        "security": str(low.get("security", "reality")),
        "sni": str(low.get("sni") or low.get("servername") or ""),
        "fp": str(low.get("fingerprint") or low.get("client_fingerprint") or "chrome"),
        "pbk": str(low.get("pbk") or low.get("public_key") or low.get("publickey") or ""),
        "sid": str(low.get("short_id") or low.get("shortid") or low.get("sid") or ""),
        "spx": str(low.get("spider_x") or low.get("spx") or ""),
        "transport": str(low.get("transport") or low.get("network") or "tcp"),
    }


def parse_amnezia_vpn_payload(payload_bytes: bytes, default_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Parses decompressed or raw Amnezia VPN JSON payload.
    Extracts AWG, WireGuard, and Xray containers with parameters
    (Jc, Jmin, Jmax, S1-S4, H1-H4, I1-I5 for AWG; Reality/VLESS for Xray).
    """
    text = decompress_amnezia_vpn_payload(payload_bytes)
    if not text:
        return []

    try:
        data = json.loads(text)
    except Exception:
        return []

    nodes: List[Dict[str, Any]] = []

    servers = []
    if isinstance(data, list):
        servers = data
    elif isinstance(data, dict):
        if "servers" in data and isinstance(data["servers"], list):
            servers = data["servers"]
        else:
            servers = [data]

    for server_data in servers:
        if not isinstance(server_data, dict):
            continue

        server_desc = default_name or server_data.get("description") or server_data.get("name") or ""
        host_name = server_data.get("hostName") or server_data.get("ip") or ""
        default_container = server_data.get("defaultContainer")

        containers = server_data.get("containers", [])
        if isinstance(containers, dict):
            containers = [{"container": k, k: v} for k, v in containers.items()]
        elif not containers and any(k in server_data for k in ("awg", "wireguard", "xray", "last_config")):
            containers = [server_data]

        for c_entry in containers:
            if not isinstance(c_entry, dict):
                continue

            c_type = str(c_entry.get("container", "")).lower()
            if not c_type:
                for possible_key in ("amnezia-awg", "awg", "amnezia-wireguard", "wireguard", "amnezia-xray", "xray"):
                    if possible_key in c_entry:
                        c_type = possible_key
                        break

            # 1. AWG / WireGuard container
            if any(t in c_type for t in ("awg", "wireguard")):
                awg_data = c_entry.get("awg") or c_entry.get("amnezia-awg") or \
                           c_entry.get("wireguard") or c_entry.get("amnezia-wireguard") or c_entry
                last_cfg = awg_data.get("last_config") if isinstance(awg_data, dict) else None
                if not last_cfg and "last_config" in c_entry:
                    last_cfg = c_entry["last_config"]

                node = None
                container_name = f"{server_desc} - AWG" if server_desc else "Amnezia AWG"

                if isinstance(last_cfg, str):
                    last_cfg_str = last_cfg.strip()
                    if last_cfg_str.startswith("{"):
                        try:
                            inner_json = json.loads(last_cfg_str)
                            if isinstance(inner_json, dict):
                                if "config" in inner_json and "[Interface]" in inner_json["config"]:
                                    node = parse_wireguard_conf(inner_json["config"], name=container_name)
                                else:
                                    node = _parse_awg_dict(inner_json, host_name, container_name)
                        except Exception:
                            pass
                    if not node and "[Interface]" in last_cfg_str and "[Peer]" in last_cfg_str:
                        node = parse_wireguard_conf(last_cfg_str, name=container_name)
                elif isinstance(last_cfg, dict):
                    if "config" in last_cfg and "[Interface]" in last_cfg["config"]:
                        node = parse_wireguard_conf(last_cfg["config"], name=container_name)
                    else:
                        node = _parse_awg_dict(last_cfg, host_name, container_name)
                elif isinstance(awg_data, dict) and "[Interface]" in str(awg_data.get("config", "")):
                    node = parse_wireguard_conf(awg_data["config"], name=container_name)

                if node:
                    if host_name and (not node.get("server") or node.get("server") == "127.0.0.1"):
                        node["server"] = host_name
                    nodes.append(node)

            # 2. Xray container
            elif "xray" in c_type:
                xray_data = c_entry.get("xray") or c_entry.get("amnezia-xray") or c_entry
                last_cfg = xray_data.get("last_config") if isinstance(xray_data, dict) else None
                if not last_cfg and "last_config" in c_entry:
                    last_cfg = c_entry["last_config"]

                xray_dict = None
                if isinstance(last_cfg, str):
                    try:
                        xray_dict = json.loads(last_cfg)
                    except Exception:
                        pass
                elif isinstance(last_cfg, dict):
                    xray_dict = last_cfg

                if isinstance(xray_dict, dict):
                    container_name = f"{server_desc} - Xray" if server_desc else "Amnezia Xray"
                    node = _parse_amnezia_xray_dict(xray_dict, host_name, container_name)
                    if node:
                        nodes.append(node)

    if default_container:
        dc_low = default_container.lower()
        def_match = [
            n for n in nodes
            if dc_low in n.get("name", "").lower()
            or dc_low in n.get("type", "").lower()
            or (any(t in dc_low for t in ("awg", "wireguard")) and n.get("type") == "awg")
            or ("xray" in dc_low and n.get("type") == "vless")
        ]
        others = [n for n in nodes if n not in def_match]
        return def_match + others

    return nodes


def parse_vpn_link(link: str) -> Optional[Dict[str, Any]]:
    """
    Parses a vpn:// URI (Amnezia VPN export).
    Returns primary node (awg, wireguard, or xray).
    """
    nodes = parse_amnezia_vpn_link_all(link)
    return nodes[0] if nodes else None


def parse_amnezia_vpn_link_all(link: str) -> List[Dict[str, Any]]:
    """
    Parses a vpn:// URI and returns all extracted container nodes.
    """
    try:
        raw = link.strip()
        if not raw.lower().startswith("vpn://"):
            return []
        body = raw[6:].strip()
        frag_name = ""
        if "#" in body:
            body, frag = body.split("#", 1)
            frag_name = urllib.parse.unquote(frag.strip())

        padded = body + "=" * (-len(body) % 4)
        try:
            raw_bytes = base64.urlsafe_b64decode(padded)
        except Exception:
            raw_bytes = base64.b64decode(padded)

        return parse_amnezia_vpn_payload(raw_bytes, default_name=frag_name)
    except Exception:
        return []


def parse_clash_proxy(proxy: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Converts a Clash/Mihomo YAML proxy dict into sub-deck internal node structure."""
    if not isinstance(proxy, dict):
        return None

    proto = str(proxy.get("type", "")).lower()
    name = str(proxy.get("name", "Proxy"))
    server = str(proxy.get("server", ""))
    port = int(proxy.get("port", 443))

    if not server or not port:
        return None

    if proto == "vless":
        uuid = str(proxy.get("uuid", ""))
        network = str(proxy.get("network", "tcp")).lower()
        tls = bool(proxy.get("tls", False))
        flow = str(proxy.get("flow", ""))
        reality_opts = proxy.get("reality-opts") or {}

        security = "none"
        pbk = ""
        sid = ""
        spx = ""
        if reality_opts:
            security = "reality"
            pbk = str(reality_opts.get("public-key", ""))
            sid = str(reality_opts.get("short-id", ""))
            spx = str(reality_opts.get("spider-x", ""))
        elif tls:
            security = "tls"

        sni = str(proxy.get("servername") or proxy.get("sni") or "")
        fp = str(proxy.get("client-fingerprint", "chrome"))

        grpc_opts = proxy.get("grpc-opts") or {}
        service_name = str(grpc_opts.get("grpc-service-name", ""))

        ws_opts = proxy.get("ws-opts") or {}
        ws_path = str(ws_opts.get("path", "/"))
        ws_headers = ws_opts.get("headers") or {}
        ws_host = str(ws_headers.get("Host", ""))

        return {
            "type": "vless",
            "name": name,
            "server": server,
            "port": port,
            "uuid": uuid,
            "security": security,
            "sni": sni,
            "pbk": pbk,
            "sid": sid,
            "spx": spx,
            "flow": flow,
            "fp": fp,
            "transport": network,
            "service_name": service_name,
            "path": ws_path,
            "host": ws_host,
        }

    elif proto == "vmess":
        uuid = str(proxy.get("uuid", ""))
        network = str(proxy.get("network", "tcp")).lower()
        tls = bool(proxy.get("tls", False))
        sni = str(proxy.get("servername") or proxy.get("sni") or "")
        ws_opts = proxy.get("ws-opts") or {}
        path = str(ws_opts.get("path", "/"))
        ws_headers = ws_opts.get("headers") or {}
        host = str(ws_headers.get("Host", ""))

        return {
            "type": "vmess",
            "name": name,
            "server": server,
            "port": port,
            "uuid": uuid,
            "security": "tls" if tls else "none",
            "sni": sni,
            "transport": network,
            "path": path,
            "host": host,
        }

    elif proto == "trojan":
        password = str(proxy.get("password", ""))
        sni = str(proxy.get("sni") or proxy.get("servername") or "")
        return {
            "type": "trojan",
            "name": name,
            "server": server,
            "port": port,
            "password": password,
            "security": "tls",
            "sni": sni,
        }

    elif proto in ("ss", "shadowsocks"):
        cipher = str(proxy.get("cipher", ""))
        password = str(proxy.get("password", ""))
        return {
            "type": "shadowsocks",
            "name": name,
            "server": server,
            "port": port,
            "method": cipher,
            "password": password,
            "security": "none",
        }

    elif proto in ("hysteria2", "hy2"):
        password = str(proxy.get("password", ""))
        sni = str(proxy.get("sni") or "")
        insecure = bool(proxy.get("skip-cert-verify", False))
        obfs_opts = proxy.get("obfs") or ""
        obfs_pass = proxy.get("obfs-password") or ""
        return {
            "type": "hysteria2",
            "name": name,
            "server": server,
            "port": port,
            "password": password,
            "security": "tls",
            "sni": sni,
            "insecure": insecure,
            "obfs_type": obfs_opts,
            "obfs_password": obfs_pass,
        }

    elif proto == "tuic":
        uuid = str(proxy.get("uuid", ""))
        password = str(proxy.get("password", ""))
        sni = str(proxy.get("sni") or "")
        insecure = bool(proxy.get("skip-cert-verify", False))
        congestion_control = str(proxy.get("congestion-controller", "bbr"))
        return {
            "type": "tuic",
            "name": name,
            "server": server,
            "port": port,
            "uuid": uuid,
            "password": password,
            "security": "tls",
            "sni": sni,
            "insecure": insecure,
            "congestion_control": congestion_control,
        }

    return None


def parse_xray_json_nodes(content: bytes) -> List[Dict[str, Any]]:
    """Extracts nodes and smart balancers from Happ / Xray / Sing-box JSON array subscription payload."""
    try:
        raw_text = content.decode("utf-8", errors="replace").strip()
        data = json.loads(raw_text)
        if not isinstance(data, list):
            return []

        nodes = []
        for item in data:
            if not isinstance(item, dict):
                continue
            remarks = item.get("remarks") or item.get("name") or "Proxy"
            outbounds = item.get("outbounds", [])
            balancers = item.get("routing", {}).get("balancers", [])
            is_balancer = len(balancers) > 0 or len([o for o in outbounds if o.get("tag") in ("proxy", "proxy-2")]) > 1

            server = ""
            port = 443
            proto = "balancer" if is_balancer else "vless"

            proxy_obs = [
                o for o in outbounds
                if o.get("tag") in ("proxy", "proxy-2")
                or "vnext" in o.get("settings", {})
                or "servers" in o.get("settings", {})
            ]
            if proxy_obs:
                p0 = proxy_obs[0]
                if not is_balancer:
                    proto = p0.get("protocol", "vless")
                vnext = p0.get("settings", {}).get("vnext", [])
                if vnext:
                    server = str(vnext[0].get("address", ""))
                    port = int(vnext[0].get("port", 443))
                else:
                    servers = p0.get("settings", {}).get("servers", [])
                    if servers:
                        server = str(servers[0].get("address", ""))
                        port = int(servers[0].get("port", 443))

            # For balancers with multiple outbounds, pick the TCP/Reality endpoint for ping if available
            if is_balancer and len(proxy_obs) > 1:
                for ob in proxy_obs:
                    if ob.get("streamSettings", {}).get("network") == "tcp":
                        vnext = ob.get("settings", {}).get("vnext", [])
                        if vnext:
                            server = str(vnext[0].get("address", server))
                            port = int(vnext[0].get("port", port))
                            break

            uuid = ""
            flow = ""
            security = "none"
            sni = ""
            pbk = ""
            sid = ""
            spx = ""
            fp = "chrome"
            transport = "tcp"

            if proxy_obs:
                p0 = proxy_obs[0]
                st = p0.get("streamSettings", {})
                transport = st.get("network", "tcp")
                security = st.get("security", "none")
                reality_cfg = st.get("realitySettings", {})
                tls_cfg = st.get("tlsSettings", {})
                sni = reality_cfg.get("serverName") or tls_cfg.get("serverName", "")
                fp = reality_cfg.get("fingerprint") or tls_cfg.get("fingerprint", "chrome")
                pbk = reality_cfg.get("publicKey", "")
                sid = reality_cfg.get("shortId", "")
                spx = reality_cfg.get("spiderX", "")

                vnext = p0.get("settings", {}).get("vnext", [])
                if vnext:
                    users = vnext[0].get("users", [])
                    if users:
                        uuid = users[0].get("id", "")
                        flow = users[0].get("flow", "")

            nodes.append({
                "type": proto,
                "name": remarks,
                "server": server,
                "port": port,
                "uuid": uuid,
                "flow": flow,
                "security": security,
                "sni": sni,
                "pbk": pbk,
                "sid": sid,
                "spx": spx,
                "fp": fp,
                "transport": transport,
                "raw_config": item,
            })
        return nodes
    except Exception:
        return []


def parse_clash_yaml_nodes(content: bytes) -> List[Dict[str, Any]]:
    """Extracts proxies from Clash / Mihomo YAML payload."""
    try:
        import yaml
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            proxies = data.get("proxies", [])
            if isinstance(proxies, list):
                nodes = []
                for p in proxies:
                    parsed = parse_clash_proxy(p)
                    if parsed:
                        nodes.append(parsed)
                return nodes
    except Exception:
        pass
    return []


def parse_node_link(link: str) -> Optional[Dict[str, Any]]:
    """Dispatches line to appropriate protocol parser."""
    line = link.strip()
    if line.startswith("vless://"):
        return parse_vless_link(line)
    if line.startswith("vmess://"):
        return parse_vmess_link(line)
    if line.startswith("trojan://"):
        return parse_trojan_link(line)
    if line.startswith("ss://"):
        return parse_ss_link(line)
    if line.startswith("hysteria2://") or line.startswith("hy2://"):
        return parse_hysteria2_link(line)
    if line.startswith("tuic://"):
        return parse_tuic_link(line)
    if line.startswith("awg://"):
        return parse_awg_link(line)
    if line.startswith("vpn://"):
        return parse_vpn_link(line)
    if "[Interface]" in line and "[Peer]" in line:
        return parse_wireguard_conf(line)
    return None


def get_device_hwid() -> str:
    """
    Returns a persistent 32-character hexadecimal Hardware ID (HWID).
    Derives from /etc/machine-id or /var/lib/dbus/machine-id, falling back to a hashed hostname.
    """
    candidates = ["/etc/machine-id", "/var/lib/dbus/machine-id"]
    for path in candidates:
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    val = f.read().strip()
                    if val and len(val) >= 16:
                        return val.lower()
        except Exception:
            continue

    # Fallback: stable SHA-256 slice from hostname + user
    raw = f"{socket.gethostname()}-subdeck-steamdeck".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def is_proxy_reachable(host: str = DEFAULT_SOCKS_HOST, port: int = DEFAULT_SOCKS_PORT, timeout: float = 0.5) -> bool:
    """Checks whether local proxy daemon is actively listening on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def download_subscription_payload(url: str, timeout: float = 15.0) -> Tuple[Optional[bytes], Optional[Any]]:
    """Downloads subscription raw bytes using fallback User-Agents and local proxy fallback."""
    if not url or not url.startswith(("http://", "https://")):
        return None, None

    ctx = ssl._create_unverified_context()
    hwid = get_device_hwid()
    base_headers = {
        "x-hwid": hwid,
        "x-device-os": "Linux",
        "x-device-model": "SteamDeck",
    }

    # 1. Direct download attempt
    for ua in SUBSCRIPTION_USER_AGENTS:
        try:
            headers = dict(base_headers)
            headers["User-Agent"] = ua
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read(), resp.info()
        except Exception:
            continue

    # 2. Local proxy fallback (if 127.0.0.1:10808 is reachable via SOCKS5)
    if is_proxy_reachable(DEFAULT_SOCKS_HOST, DEFAULT_SOCKS_PORT):
        try:
            import socks

            class SOCKSHTTPSConnection(http.client.HTTPSConnection):
                def __init__(self, host, port=None, context=None, check_hostname=None, **kwargs):
                    super().__init__(host, port=port, context=context, **kwargs)
                    self._check_hostname = check_hostname

                def connect(self):
                    sock = socks.create_connection(
                        (self.host, self.port),
                        timeout=self.timeout,
                        proxy_type=socks.SOCKS5,
                        proxy_addr=DEFAULT_SOCKS_HOST,
                        proxy_port=DEFAULT_SOCKS_PORT,
                    )
                    server_hostname = self.host if self._check_hostname is not False else None
                    if self._context:
                        self.sock = self._context.wrap_socket(sock, server_hostname=server_hostname)
                    else:
                        self.sock = sock

            class SOCKSHTTPConnection(http.client.HTTPConnection):
                def connect(self):
                    self.sock = socks.create_connection(
                        (self.host, self.port),
                        timeout=self.timeout,
                        proxy_type=socks.SOCKS5,
                        proxy_addr=DEFAULT_SOCKS_HOST,
                        proxy_port=DEFAULT_SOCKS_PORT,
                    )

            class SOCKSHandler(urllib.request.HTTPSHandler, urllib.request.HTTPHandler):
                def __init__(self, debuglevel=None, context=None, check_hostname=None):
                    super().__init__(debuglevel=debuglevel, context=context, check_hostname=check_hostname)
                    self._check_hostname = check_hostname

                def https_open(self, req):
                    return self.do_open(
                        SOCKSHTTPSConnection,
                        req,
                        context=self._context,
                        check_hostname=self._check_hostname,
                    )

                def http_open(self, req):
                    return self.do_open(SOCKSHTTPConnection, req)

            socks_opener = urllib.request.build_opener(SOCKSHandler(context=ctx))
            for ua in SUBSCRIPTION_USER_AGENTS:
                try:
                    headers = dict(base_headers)
                    headers["User-Agent"] = ua
                    req = urllib.request.Request(url, headers=headers)
                    with socks_opener.open(req, timeout=timeout) as resp:
                        return resp.read(), resp.info()
                except Exception:
                    continue
        except Exception:
            pass

    return None, None


def parse_subscription_userinfo(headers: Any) -> Dict[str, int]:
    """Parses subscription-userinfo header: upload, download, total, expire (in bytes/epoch)."""
    userinfo: Dict[str, int] = {}
    if not headers:
        return userinfo

    raw_header = None
    for k, v in headers.items():
        if k.lower() == "subscription-userinfo":
            raw_header = v
            break

    if not raw_header:
        return userinfo

    # Typical format: upload=1073741824; download=5368709120; total=53687091200; expire=1735689600
    for part in raw_header.split(";"):
        part = part.strip()
        if "=" in part:
            key, val = part.split("=", 1)
            key = key.strip().lower()
            val = val.strip()
            try:
                if key in ("upload", "download", "total", "expire"):
                    userinfo[key] = int(val)
            except ValueError:
                continue

    return userinfo


def parse_content_disposition_filename(headers: Any) -> Optional[str]:
    """Extracts subscription filename/title from Content-Disposition header."""
    if not headers:
        return None

    raw_header = None
    for k, v in headers.items():
        if k.lower() == "content-disposition":
            raw_header = v
            break

    if not raw_header:
        return None

    # Try RFC 5987 filename*=UTF-8''...
    match_rfc = re.search(r"filename\*\s*=\s*(?:UTF-8''|utf-8'')([^;\s]+)", raw_header, re.IGNORECASE)
    if match_rfc:
        try:
            return urllib.parse.unquote(match_rfc.group(1)).strip().strip('"\'')
        except Exception:
            pass

    # Try filename="abc" or filename=abc
    match = re.search(r'filename\s*=\s*("([^"]+)"|([^;\s]+))', raw_header, re.IGNORECASE)
    if match:
        name = match.group(2) if match.group(2) is not None else match.group(3)
        if name:
            name = name.strip().strip('"\'')
            # Decode if percent-encoded
            try:
                name = urllib.parse.unquote(name)
            except Exception:
                pass
            return name

    return None


def extract_update_interval(headers: Any, text: str) -> Optional[int]:
    """Finds profile-update-interval from HTTP headers or payload text."""
    if headers:
        for key, val in headers.items():
            if key.lower() == "profile-update-interval":
                try:
                    return int(val)
                except Exception:
                    pass

    match = re.search(r'(?:#|//)?\s*profile-update-interval\s*:\s*(\d+)', text[:1000], re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            pass
    return None


def decode_subscription_lines(content: bytes) -> List[str]:
    """Decodes plain text or base64 subscription payload into lines."""
    try:
        text = content.decode("utf-8").strip()
    except Exception:
        text = content.decode("latin-1", errors="replace").strip()

    if "[Interface]" in text and "[Peer]" in text:
        return [text]

    if text.startswith("vpn://"):
        return [text]

    is_plain = any(text.startswith(sch) or f"\n{sch}" in text for sch in SUPPORTED_SCHEMES)
    if is_plain:
        return text.splitlines()

    # Attempt base64 decoding
    try:
        clean_b64 = "".join(text.split())
        padded = clean_b64 + "=" * (-len(clean_b64) % 4)
        decoded = base64.b64decode(padded).decode("utf-8", errors="replace")
        if "[Interface]" in decoded and "[Peer]" in decoded:
            return [decoded]
        return decoded.splitlines()
    except Exception:
        return text.splitlines()


def parse_subscription_nodes(url: str, log_func=None) -> Tuple[List[Dict[str, Any]], Optional[int], Dict[str, Any]]:
    """Fetches, parses and dedupes nodes for a subscription URL, returning (nodes, interval, metadata)."""
    clean_url = (url or "").strip()
    if clean_url.startswith("vpn://"):
        if log_func:
            log_func(f"Detected Amnezia vpn:// URI: {clean_url[:30]}...")
        vpn_nodes = parse_amnezia_vpn_link_all(clean_url)
        if vpn_nodes:
            for n in vpn_nodes:
                n["subscription_url"] = url
            primary_name = vpn_nodes[0].get("name") or "Amnezia VPN"
            return vpn_nodes, None, {"name": primary_name}
        return [], None, {}

    if clean_url.startswith(SUPPORTED_SCHEMES):
        if log_func:
            log_func(f"Detected single node direct URI: {clean_url[:30]}...")
        node = parse_node_link(clean_url)
        if node:
            node["subscription_url"] = url
            name = node.get("name") or "Custom Node"
            metadata = {"name": name}
            return [node], None, metadata
        return [], None, {}

    content, headers = download_subscription_payload(url)
    if content is None:
        if log_func:
            log_func(f"Failed to download subscription content for: {url}")
        return [], None, {}

    try:
        raw_text = content.decode("utf-8", errors="ignore")
    except Exception:
        raw_text = ""
    interval = extract_update_interval(headers, raw_text)

    metadata: Dict[str, Any] = {}
    userinfo = parse_subscription_userinfo(headers)
    if userinfo:
        metadata.update(userinfo)

    filename = parse_content_disposition_filename(headers)
    if filename:
        metadata["name"] = filename

    # 1. Check if subscription is an Xray / Happ JSON array payload
    json_nodes = parse_xray_json_nodes(content)
    raw_nodes = []
    if json_nodes:
        if log_func:
            log_func(f"Detected Happ/Xray JSON payload with {len(json_nodes)} configurations.")
        for node in json_nodes:
            node["subscription_url"] = url
            raw_nodes.append(node)
    else:
        # 2. Check if subscription is a Clash / Mihomo YAML payload
        yaml_nodes = parse_clash_yaml_nodes(content)
        if yaml_nodes:
            for node in yaml_nodes:
                node["subscription_url"] = url
                raw_nodes.append(node)
        else:
            # 2.5. Check if payload is an Amnezia VPN payload (raw or decompressed)
            amnezia_nodes = parse_amnezia_vpn_payload(content)
            if amnezia_nodes:
                if log_func:
                    log_func(f"Detected Amnezia VPN container payload with {len(amnezia_nodes)} configurations.")
                for node in amnezia_nodes:
                    node["subscription_url"] = url
                    raw_nodes.append(node)
            else:
                # 3. Plain text or base64 links
                lines = decode_subscription_lines(content)
                for line in lines:
                    try:
                        line_clean = line.strip()
                        if line_clean.startswith("vpn://"):
                            vnodes = parse_amnezia_vpn_link_all(line_clean)
                            for vn in vnodes:
                                vn["subscription_url"] = url
                                raw_nodes.append(vn)
                            continue
                        node = parse_node_link(line)
                        if node:
                            node["subscription_url"] = url
                            raw_nodes.append(node)
                    except Exception:
                        continue

    # Deduplicate nodes by name
    seen_names = set()
    unique_nodes = []
    for node in raw_nodes:
        name = node.get("name")
        if name and name not in seen_names:
            seen_names.add(name)
            unique_nodes.append(node)

    if log_func:
        log_func(f"Parsed {len(unique_nodes)} unique nodes for {url}")

    # Select responsive nodes
    limit = FREE_SUBSCRIPTION_NODE_LIMIT if is_free_subscription(url) else REGULAR_SUBSCRIPTION_NODE_LIMIT
    selected_nodes = select_best_nodes(unique_nodes, target_count=limit, log_func=log_func)

    return selected_nodes, interval, metadata
