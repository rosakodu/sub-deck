"""
Lightweight asynchronous HTTP/JSON API server for sub-deck.
Enables communication between the Decky Loader backend and external tools,
such as the Desktop Mode System Tray widget.
"""

import os
import json
import asyncio
from typing import Any, Dict, Optional, Callable
from urllib.parse import urlparse

from core.constants import IPC_HOST, IPC_PORT, IPC_SOCKET_PATH
from core.pinger import check_nodes_ping
from core.system import get_user_home


class SubDeckApiServer:
    """Async HTTP daemon server for IPC control of VPN manager."""

    def __init__(self, plugin_instance, logger=None):
        self.plugin = plugin_instance
        self.logger = logger
        self.tcp_server: Optional[asyncio.AbstractServer] = None
        self.unix_server: Optional[asyncio.AbstractServer] = None
        self._running = False

    def log(self, msg: str):
        if self.logger:
            self.logger.info(f"[API Server] {msg}")
        else:
            print(f"[API Server] {msg}")

    async def start(self) -> None:
        """Starts TCP and Unix domain socket listeners."""
        if self._running:
            return
        self._running = True

        # 1. Start TCP listener (127.0.0.1:45321)
        try:
            self.tcp_server = await asyncio.start_server(
                self._handle_client,
                host=IPC_HOST,
                port=IPC_PORT,
                reuse_address=True
            )
            self.log(f"Listening on TCP http://{IPC_HOST}:{IPC_PORT}")
        except Exception as e:
            self.log(f"Failed to start TCP listener on {IPC_HOST}:{IPC_PORT}: {e}")

        # 2. Start Unix domain socket listener (/tmp/sub-deck.sock)
        try:
            if os.path.exists(IPC_SOCKET_PATH):
                try:
                    os.remove(IPC_SOCKET_PATH)
                except Exception:
                    pass

            self.unix_server = await asyncio.start_unix_server(
                self._handle_client,
                path=IPC_SOCKET_PATH
            )
            # Allow non-root users (desktop session) to access the socket
            try:
                os.chmod(IPC_SOCKET_PATH, 0o666)
            except Exception:
                pass
            self.log(f"Listening on Unix socket {IPC_SOCKET_PATH}")
        except Exception as e:
            self.log(f"Failed to start Unix socket listener: {e}")

    async def stop(self) -> None:
        """Stops listeners and cleans up socket files."""
        self._running = False
        if self.tcp_server:
            self.tcp_server.close()
            await self.tcp_server.wait_closed()
            self.tcp_server = None

        if self.unix_server:
            self.unix_server.close()
            await self.unix_server.wait_closed()
            self.unix_server = None

        if os.path.exists(IPC_SOCKET_PATH):
            try:
                os.remove(IPC_SOCKET_PATH)
            except Exception:
                pass
        self.log("API Server stopped.")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Processes HTTP requests from clients."""
        try:
            # Read request line and headers
            header_data = bytearray()
            while True:
                line = await reader.readline()
                if not line:
                    break
                header_data.extend(line)
                if line == b"\r\n" or line == b"\n":
                    break
                if len(header_data) > 65536:
                    break

            if not header_data:
                writer.close()
                await writer.wait_closed()
                return

            header_text = header_data.decode("utf-8", errors="replace")
            lines = header_text.splitlines()
            if not lines:
                writer.close()
                await writer.wait_closed()
                return

            request_line = lines[0].strip()
            parts = request_line.split()
            if len(parts) < 2:
                writer.close()
                await writer.wait_closed()
                return

            method = parts[0].upper()
            raw_url = parts[1]
            parsed_url = urlparse(raw_url)
            path = parsed_url.path

            # Parse headers
            headers = {}
            for h in lines[1:]:
                if ":" in h:
                    k, v = h.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            content_length = int(headers.get("content-length", 0))

            # Read body if present
            body_bytes = b""
            if content_length > 0:
                body_bytes = await reader.readexactly(content_length)

            # Handle CORS preflight
            if method == "OPTIONS":
                await self._send_cors_response(writer)
                return

            # Parse JSON body if present
            body_data = {}
            if body_bytes:
                try:
                    body_data = json.loads(body_bytes.decode("utf-8"))
                except Exception:
                    body_data = {}

            # Route request
            status_code, response_data = await self._route_request(method, path, body_data)
            await self._send_json_response(writer, status_code, response_data)

        except Exception as e:
            try:
                await self._send_json_response(writer, 500, {"error": str(e)})
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _route_request(self, method: str, path: str, data: Dict[str, Any]) -> tuple:
        """Dispatches request to appropriate plugin method."""
        vpn = self.plugin.vpn
        if not vpn:
            return 503, {"error": "VPN manager not initialized"}

        # ── GET /api/status ──
        if method == "GET" and path == "/api/status":
            settings = vpn.load_settings()
            return 200, {
                "running": vpn.is_running(),
                "selected_node": settings.get("selected_node"),
                "selected_preset": settings.get("selected_preset", "default"),
                "subscriptions_count": len(settings.get("subscriptions", [])),
                "version": "1.1.3",
            }

        # ── GET /api/nodes ──
        if method == "GET" and path == "/api/nodes":
            return 200, {"nodes": vpn.get_nodes()}

        # ── GET /api/settings ──
        if method == "GET" and path == "/api/settings":
            return 200, {"settings": vpn.load_settings()}

        # ── POST /api/connect ──
        if method == "POST" and path == "/api/connect":
            node = data.get("node")
            if not node:
                # If node wasn't passed directly, check if we have a saved selected_node
                settings = vpn.load_settings()
                node = settings.get("selected_node")

            if not node:
                # Fallback to the first available node
                nodes = vpn.get_nodes()
                if nodes:
                    node = nodes[0]

            if not node:
                return 400, {"error": "No proxy node specified or available"}

            success = await self.plugin.connect_node(node)
            return 200, {"success": success, "node": node}

        # ── POST /api/disconnect ──
        if method == "POST" and path == "/api/disconnect":
            success = await self.plugin.disconnect()
            return 200, {"success": success}

        # ── POST /api/subscription/add ──
        if method == "POST" and path == "/api/subscription/add":
            url = data.get("url", "").strip()
            if not url:
                return 400, {"error": "Empty subscription URL"}
            nodes = await self.plugin.add_subscription(url)
            return 200, {"success": True, "nodes_count": len(nodes)}

        # ── POST /api/subscription/remove ──
        if method == "POST" and path == "/api/subscription/remove":
            url = data.get("url", "").strip()
            if not url:
                return 400, {"error": "Empty subscription URL"}
            nodes = await self.plugin.remove_subscription(url)
            return 200, {"success": True, "nodes_count": len(nodes)}

        # ── POST /api/subscription/update ──
        if method == "POST" and path == "/api/subscription/update":
            url = data.get("url", "").strip()
            if not url:
                return 400, {"error": "Empty subscription URL"}
            nodes = await self.plugin.update_subscription(url)
            return 200, {"success": True, "nodes_count": len(nodes)}

        # ── POST /api/subscription/update_all ──
        if method == "POST" and path == "/api/subscription/update_all":
            nodes = await self.plugin.loop.run_in_executor(None, vpn.parse_all_subscriptions)
            return 200, {"success": True, "nodes_count": len(nodes)}

        # ── POST /api/preset ──
        if method == "POST" and path == "/api/preset":
            preset = data.get("preset", "default")
            await self.plugin.save_preset(preset)
            return 200, {"success": True, "preset": preset}

        # ── POST /api/ping ──
        if method == "POST" and path == "/api/ping":
            nodes = vpn.get_nodes()
            alive_nodes = await self.plugin.loop.run_in_executor(
                None, lambda: check_nodes_ping(nodes, timeout=1.2)
            )
            return 200, {"nodes": alive_nodes}

        # ── GET /api/desktop/status ──
        if method == "GET" and path == "/api/desktop/status":
            from tray.desktop_integration import get_desktop_integration_status
            status = get_desktop_integration_status(self.plugin.vpn.plugin_dir)
            return 200, status

        # ── POST /api/desktop/autostart ──
        if method == "POST" and path == "/api/desktop/autostart":
            enable = bool(data.get("enable", True))
            from tray.desktop_integration import set_autostart
            success = set_autostart(self.plugin.vpn.plugin_dir, enable)
            return 200, {"success": success, "autostart": enable}

        # ── POST /api/desktop/launch ──
        if method == "POST" and path == "/api/desktop/launch":
            from tray.desktop_integration import launch_tray_process
            success = launch_tray_process(self.plugin.vpn.plugin_dir)
            return 200, {"success": success}

        return 404, {"error": f"Endpoint not found: {method} {path}"}

    async def _send_cors_response(self, writer: asyncio.StreamWriter) -> None:
        """Responds to CORS preflight OPTIONS."""
        response = (
            b"HTTP/1.1 204 No Content\r\n"
            b"Access-Control-Allow-Origin: *\r\n"
            b"Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
            b"Access-Control-Allow-Headers: Content-Type\r\n"
            b"Connection: close\r\n\r\n"
        )
        writer.write(response)
        await writer.drain()

    async def _send_json_response(self, writer: asyncio.StreamWriter, status_code: int, data: Any) -> None:
        """Sends an HTTP response with JSON payload."""
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        status_text = "OK" if status_code == 200 else ("Not Found" if status_code == 404 else "Error")
        headers = (
            f"HTTP/1.1 {status_code} {status_text}\r\n"
            f"Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(payload)}\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("utf-8")

        writer.write(headers + payload)
        await writer.drain()
