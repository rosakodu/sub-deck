"""
HTTP Client for communication with Sub-Deck local IPC API daemon.
Handles REST requests with fail-safe error handling and timeouts.
"""

import json
import urllib.request
import urllib.error
from typing import Dict, List, Any, Optional

from core.constants import IPC_HOST, IPC_PORT


class SubDeckApiClient:
    """Client for local sub-deck daemon."""

    def __init__(self, host: str = IPC_HOST, port: int = IPC_PORT, timeout: float = 3.0):
        self.base_url = f"http://{host}:{port}/api"
        self.timeout = timeout

    def _request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Performs HTTP request to the local daemon."""
        url = f"{self.base_url}{endpoint}"
        body_bytes = None
        headers = {"User-Agent": "SubDeck-Tray/1.0"}

        if data is not None:
            body_bytes = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
        req_timeout = timeout if timeout is not None else self.timeout
        try:
            with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                resp_data = resp.read().decode("utf-8", errors="replace")
                if resp_data:
                    return json.loads(resp_data)
                return {}
        except Exception:
            return None

    def is_available(self) -> bool:
        """Checks whether the daemon is actively responding."""
        res = self._request("GET", "/status")
        return res is not None

    def get_status(self) -> Optional[Dict[str, Any]]:
        """Fetches current connection state, selected node and preset."""
        return self._request("GET", "/status")

    def get_nodes(self) -> List[Dict[str, Any]]:
        """Fetches cached proxy nodes."""
        res = self._request("GET", "/nodes")
        if res and "nodes" in res:
            return res["nodes"]
        return []

    def get_settings(self) -> Dict[str, Any]:
        """Fetches plugin settings (subscriptions, presets, etc.)."""
        res = self._request("GET", "/settings")
        if res and "settings" in res:
            return res["settings"]
        return {}

    def connect(self, node: Optional[Dict[str, Any]] = None) -> bool:
        """Starts VPN connection to specified or active node."""
        payload = {"node": node} if node else {}
        res = self._request("POST", "/connect", payload)
        return bool(res and res.get("success"))

    def disconnect(self) -> bool:
        """Tears down VPN routing and stops core processes."""
        res = self._request("POST", "/disconnect")
        return bool(res and res.get("success"))

    def add_subscription(self, url: str) -> bool:
        """Adds and parses a new subscription endpoint."""
        res = self._request("POST", "/subscription/add", {"url": url}, timeout=30.0)
        return bool(res and res.get("success"))

    def remove_subscription(self, url: str) -> bool:
        """Removes an existing subscription URL."""
        res = self._request("POST", "/subscription/remove", {"url": url}, timeout=10.0)
        return bool(res and res.get("success"))

    def update_subscription(self, url: str) -> bool:
        """Refreshes a specific subscription."""
        res = self._request("POST", "/subscription/update", {"url": url}, timeout=30.0)
        return bool(res and res.get("success"))

    def update_all_subscriptions(self) -> bool:
        """Refreshes all configured subscriptions."""
        res = self._request("POST", "/subscription/update_all", timeout=60.0)
        return bool(res and res.get("success"))

    def set_preset(self, preset: str) -> bool:
        """Sets the active routing preset (default or roscomvpn)."""
        res = self._request("POST", "/preset", {"preset": preset})
        return bool(res and res.get("success"))

    def ping_nodes(self) -> List[Dict[str, Any]]:
        """Runs TCP latency check on candidate nodes."""
        res = self._request("POST", "/ping")
        if res and "nodes" in res:
            return res["nodes"]
        return []

    def get_desktop_status(self) -> Dict[str, Any]:
        """Checks autostart and desktop installation status."""
        res = self._request("GET", "/desktop/status")
        return res or {"installed": False, "autostart": False}

    def set_autostart(self, enable: bool) -> bool:
        """Toggles desktop autostart."""
        res = self._request("POST", "/desktop/autostart", {"enable": enable})
        return bool(res and res.get("success"))
