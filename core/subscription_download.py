"""Fetches subscription payloads directly or through the local SOCKS proxy."""

import hashlib
import http.client
import os
import socket
import ssl
import urllib.request
from typing import Any, Optional, Tuple

from core.constants import DEFAULT_SOCKS_HOST, DEFAULT_SOCKS_PORT, SUBSCRIPTION_USER_AGENTS


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
