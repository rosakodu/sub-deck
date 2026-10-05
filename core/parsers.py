"""
Subscription parser for various proxy protocols:
VLESS, VMess, Trojan, Shadowsocks, Hysteria 2.
"""

import base64
import json
import re
import ssl
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple, Any

from core.constants import (
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
    """Parses host:port, supporting IPv6 bracket notation [::1]:port."""
    if endpoint.startswith("["):
        bracket_end = endpoint.find("]")
        if bracket_end == -1:
            return endpoint, 443
        host = endpoint[1:bracket_end]
        rest = endpoint[bracket_end + 1:]
        port = int(rest.lstrip(":")) if ":" in rest else 443
    elif ":" in endpoint:
        host, port_str = endpoint.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            port = 443
    else:
        host = endpoint
        port = 443
    return host, port


def parse_vless_link(link: str) -> Optional[Dict[str, Any]]:
    """Parses a vless:// URI into node structure."""
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
    return None


def download_subscription_payload(url: str, timeout: float = 15.0) -> Tuple[Optional[bytes], Optional[Any]]:
    """Downloads subscription raw bytes using fallback User-Agents."""
    ctx = ssl._create_unverified_context()
    for ua in SUBSCRIPTION_USER_AGENTS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read(), resp.info()
        except Exception:
            continue
    return None, None


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

    is_plain = any(text.startswith(sch) or f"\n{sch}" in text for sch in SUPPORTED_SCHEMES)
    if is_plain:
        return text.splitlines()

    # Attempt base64 decoding
    try:
        clean_b64 = "".join(text.split())
        padded = clean_b64 + "=" * (-len(clean_b64) % 4)
        decoded = base64.b64decode(padded).decode("utf-8", errors="replace")
        return decoded.splitlines()
    except Exception:
        return text.splitlines()


def parse_subscription_nodes(url: str, log_func=None) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Fetches, parses and dedupes nodes for a subscription URL."""
    content, headers = download_subscription_payload(url)
    if content is None:
        if log_func:
            log_func(f"Failed to download subscription content for: {url}")
        return [], None

    try:
        raw_text = content.decode("utf-8", errors="ignore")
    except Exception:
        raw_text = ""
    interval = extract_update_interval(headers, raw_text)

    lines = decode_subscription_lines(content)
    raw_nodes = []
    for line in lines:
        node = parse_node_link(line)
        if node:
            node["subscription_url"] = url
            raw_nodes.append(node)

    # Deduplicate nodes by (name, server, port)
    seen_names = set()
    seen_endpoints = set()
    unique_nodes = []
    for node in raw_nodes:
        name = node.get("name")
        endpoint = (node.get("server"), node.get("port"))
        if name and endpoint[0] and endpoint[1]:
            if name not in seen_names and endpoint not in seen_endpoints:
                seen_names.add(name)
                seen_endpoints.add(endpoint)
                unique_nodes.append(node)

    if log_func:
        log_func(f"Parsed {len(unique_nodes)} unique nodes for {url}")

    # Select responsive nodes
    limit = FREE_SUBSCRIPTION_NODE_LIMIT if is_free_subscription(url) else REGULAR_SUBSCRIPTION_NODE_LIMIT
    selected_nodes = select_best_nodes(unique_nodes, target_count=limit, log_func=log_func)

    return selected_nodes, interval
