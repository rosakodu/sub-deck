"""
Test script for Sub-Deck IPC API Server and API Client.
Verifies server lifecycle, endpoint responses, and client methods.
"""

import os
import sys
import asyncio
import unittest

# Ensure root dir is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.server import SubDeckApiServer
from tray.api_client import SubDeckApiClient
from tray.desktop_integration import get_desktop_paths, generate_autostart_content


class MockVPN:
    def __init__(self):
        self.plugin_dir = BASE_DIR
        self._running = False

    def load_settings(self):
        return {
            "subscriptions": ["https://example.com/sub.txt"],
            "selected_node": {"name": "Test Node", "server": "1.2.3.4", "port": 443, "type": "vless"},
            "selected_preset": "default"
        }

    def is_running(self):
        return self._running

    def get_nodes(self):
        return [
            {"name": "Server 1", "server": "1.1.1.1", "port": 443, "type": "vless"},
            {"name": "Server 2", "server": "2.2.2.2", "port": 8443, "type": "vless"},
        ]


class MockPlugin:
    def __init__(self):
        self.vpn = MockVPN()
        self.loop = asyncio.get_event_loop()

    async def connect_node(self, node):
        self.vpn._running = True
        return True

    async def disconnect(self):
        self.vpn._running = False
        return True

    async def add_subscription(self, url):
        return self.vpn.get_nodes()

    async def remove_subscription(self, url):
        return []

    async def update_subscription(self, url):
        return self.vpn.get_nodes()

    async def save_preset(self, preset):
        return True


class TestSubDeckApi(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.plugin = MockPlugin()
        self.test_port = 45999
        self.server = SubDeckApiServer(self.plugin, host="127.0.0.1", port=self.test_port, socket_path=None)
        await self.server.start()
        self.client = SubDeckApiClient(host="127.0.0.1", port=self.test_port)

    async def asyncTearDown(self):
        await self.server.stop()

    async def test_daemon_status(self):
        status = await asyncio.to_thread(self.client.get_status)
        self.assertIsNotNone(status)
        self.assertFalse(status.get("running"))
        self.assertEqual(status.get("selected_preset"), "default")
        self.assertEqual(status.get("selected_node", {}).get("name"), "Test Node")

    async def test_daemon_nodes(self):
        nodes = await asyncio.to_thread(self.client.get_nodes)
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[0]["name"], "Server 1")

    async def test_daemon_connect_disconnect(self):
        res = await asyncio.to_thread(self.client.connect)
        self.assertTrue(res)
        status = await asyncio.to_thread(self.client.get_status)
        self.assertTrue(status.get("running"))

        res = await asyncio.to_thread(self.client.disconnect)
        self.assertTrue(res)
        status = await asyncio.to_thread(self.client.get_status)
        self.assertFalse(status.get("running"))

    def test_autostart_generation(self):
        content = generate_autostart_content(BASE_DIR)
        self.assertIn("Name=Sub-Deck VPN Tray", content)
        self.assertIn("NoDisplay=true", content)
        self.assertIn("Exec=python3", content)
        self.assertIn("tray/tray_app.py", content)



if __name__ == "__main__":
    unittest.main()
