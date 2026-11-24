"""
Speedtest, latency, and exit-country flag measurement for proxy nodes
using ephemeral local xray / sing-box instances.
"""

import json
import os
import re
import socket
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

from core.pinger import extract_node_sni, handshake_ping
from core.singbox_config import build_singbox_outbound
from core.xray_config import build_outbound

SINGBOX_TYPES = ("awg", "wireguard", "hysteria2", "tuic", "anytls")


def country_code_to_flag(code: Optional[str]) -> Optional[str]:
    if not code or not isinstance(code, str):
        return None
    clean = code.strip().upper()
    if len(clean) != 2 or not clean.isalpha():
        return None
    return chr(0x1F1E6 + ord(clean[0]) - ord("A")) + chr(0x1F1E6 + ord(clean[1]) - ord("A"))


def extract_flag_from_name(name: Optional[str]) -> Optional[str]:
    if not name or not isinstance(name, str):
        return None
    match = re.search(r"[\U0001F1E6-\U0001F1FF]{2}", name)
    return match.group(0) if match else None


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _resolve_server_ip(server: str) -> str:
    try:
        return socket.gethostbyname(server)
    except Exception:
        return server


def _wait_for_port(port: int, timeout: float = 2.5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except Exception:
            time.sleep(0.05)
    return False


def _build_temp_xray_config(node: Dict[str, Any], server_ip: str, socks_port: int) -> Dict[str, Any]:
    outbound = build_outbound(node, server_ip)
    outbound["tag"] = "proxy"
    return {
        "log": {"loglevel": "none"},
        "inbounds": [
            {
                "tag": "socks-in",
                "port": socks_port,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": False},
            }
        ],
        "outbounds": [outbound],
    }


def _build_temp_singbox_config(node: Dict[str, Any], server_ip: str, socks_port: int) -> Dict[str, Any]:
    outbound = build_singbox_outbound(node, server_ip)
    outbound["tag"] = "proxy"
    return {
        "log": {"level": "panic"},
        "inbounds": [
            {
                "type": "socks",
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "listen_port": socks_port,
            }
        ],
        "outbounds": [outbound],
        "route": {"final": "proxy"},
    }


def _curl_country_flag(socks_port: int) -> Optional[str]:
    endpoints = (
        ("https://ipwho.is/", "country_code"),
        ("http://ip-api.com/json/?fields=countryCode", "countryCode"),
    )
    for url, key in endpoints:
        try:
            res = subprocess.run(
                [
                    "curl", "-s",
                    "--socks5-hostname", f"127.0.0.1:{socks_port}",
                    "--connect-timeout", "3",
                    "--max-time", "4",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0 and res.stdout:
                data = json.loads(res.stdout)
                flag = country_code_to_flag(data.get(key))
                if flag:
                    return flag
        except Exception:
            continue
    return None


def _curl_download_mbps(socks_port: int, timeout: float = 5.0) -> Optional[float]:
    try:
        res = subprocess.run(
            [
                "curl", "-s", "-o", "/dev/null",
                "--socks5-hostname", f"127.0.0.1:{socks_port}",
                "--connect-timeout", "3",
                "--max-time", str(int(timeout)),
                "-w", "%{speed_download}",
                "https://speed.cloudflare.com/__down?bytes=5000000",
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
        if res.returncode == 0 and res.stdout.strip():
            bps = float(res.stdout.strip())
            if bps > 0:
                return round((bps * 8.0) / 1_000_000.0, 2)
    except Exception:
        pass
    return None


def _curl_upload_mbps(socks_port: int, payload_path: str, timeout: float = 5.0) -> Optional[float]:
    try:
        res = subprocess.run(
            [
                "curl", "-s", "-o", "/dev/null",
                "--socks5-hostname", f"127.0.0.1:{socks_port}",
                "--connect-timeout", "3",
                "--max-time", str(int(timeout)),
                "-X", "POST",
                "--data-binary", f"@{payload_path}",
                "-w", "%{speed_upload}",
                "https://speed.cloudflare.com/__up",
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
        if res.returncode == 0 and res.stdout.strip():
            bps = float(res.stdout.strip())
            if bps > 0:
                return round((bps * 8.0) / 1_000_000.0, 2)
    except Exception:
        pass
    return None


def speedtest_node(
    node: Dict[str, Any],
    xray_path: Optional[str] = None,
    singbox_path: Optional[str] = None,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    result = node.copy()
    ntype = str(node.get("type", "")).lower()
    if ntype == "auto_balancer":
        result["ping"] = 1
        return result

    host = node.get("server")
    port = node.get("port")
    if not host or not port:
        result["ping"] = -1
        result["speed_down"] = None
        result["speed_up"] = None
        result["country_flag"] = extract_flag_from_name(node.get("name"))
        return result

    sni = extract_node_sni(node)
    is_udp = ntype in ("awg", "wireguard")
    lat = handshake_ping(host, int(port), sni=sni, timeout=2.0, is_udp=is_udp)
    if lat is None or lat <= 0:
        result["ping"] = -1
        result["speed_down"] = None
        result["speed_up"] = None
        result["country_flag"] = extract_flag_from_name(node.get("name"))
        return result

    result["ping"] = max(1, int(lat))
    use_singbox = ntype in SINGBOX_TYPES
    bin_path = singbox_path if use_singbox else xray_path
    if not bin_path or not os.path.exists(bin_path):
        result["speed_down"] = None
        result["speed_up"] = None
        result["country_flag"] = extract_flag_from_name(node.get("name"))
        return result

    socks_port = _get_free_port()
    server_ip = _resolve_server_ip(host)
    proc = None

    with tempfile.TemporaryDirectory(prefix="subdeck_speed_") as tmpdir:
        cfg_path = os.path.join(tmpdir, "config.json")
        payload_path = os.path.join(tmpdir, "upload.bin")
        try:
            cfg = (
                _build_temp_singbox_config(node, server_ip, socks_port)
                if use_singbox
                else _build_temp_xray_config(node, server_ip, socks_port)
            )
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            with open(payload_path, "wb") as f:
                f.write(b"\x00" * (1024 * 1024))  # 1 MB upload payload

            cmd = [bin_path, "run", "-c", cfg_path]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            if _wait_for_port(socks_port, timeout=2.5):
                flag = _curl_country_flag(socks_port)
                down = _curl_download_mbps(socks_port, timeout=timeout)
                up = _curl_upload_mbps(socks_port, payload_path, timeout=timeout)
                result["country_flag"] = flag or extract_flag_from_name(node.get("name"))
                result["speed_down"] = down
                result["speed_up"] = up
            else:
                result["country_flag"] = extract_flag_from_name(node.get("name"))
                result["speed_down"] = None
                result["speed_up"] = None
        except Exception:
            result["country_flag"] = extract_flag_from_name(node.get("name"))
            result["speed_down"] = None
            result["speed_up"] = None
        finally:
            if proc is not None:
                try:
                    proc.terminate()
                    proc.wait(timeout=1.5)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=1.0)
                    except Exception:
                        pass

    return result


def speedtest_nodes(
    nodes: List[Dict[str, Any]],
    xray_path: Optional[str] = None,
    singbox_path: Optional[str] = None,
    max_workers: int = 4,
    timeout: float = 5.0,
) -> List[Dict[str, Any]]:
    if not nodes:
        return []

    results: List[Optional[Dict[str, Any]]] = [None] * len(nodes)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(speedtest_node, n, xray_path, singbox_path, timeout): idx
            for idx, n in enumerate(nodes)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                results[idx] = fut.result()
            except Exception:
                fallback = nodes[idx].copy()
                fallback["ping"] = -1
                results[idx] = fallback

    return [r for r in results if r is not None]
