"""
Unit tests for auto-select best server and emoji stripping functionality.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.system import clean_node_name
from core.pinger import find_best_node
from core.xray_config import build_auto_balancer_config
from vpn_manager import VPNManager
import tempfile


class TestAutoSelectBestServer(unittest.TestCase):
    def test_clean_node_name_emoji_stripping(self):
        """Verifies clean_node_name strips all Unicode emojis and flags."""
        cases = [
            ("🇩🇪 Germany 01", "Germany 01"),
            ("🇱🇹 Lithuania | Vless", "Lithuania | Vless"),
            ("⚡ Auto-Select Best", "Auto-Select Best"),
            ("🛡️ Red Shield VPN", "Red Shield VPN"),
            ("🔴 Disconnect VPN", "Disconnect VPN"),
            ("🟢 Connect VPN", "Connect VPN"),
            ("🌐 Global Server", "Global Server"),
            ("🏴‍☠️ Pirate Proxy", "Pirate Proxy"),
            ("⚡ Авто-выбор лучшего", "Авто-выбор лучшего"),
            ("⚡ Авто-выбор сервера", "Авто-выбор сервера"),
            ("[автобалансер] 🇩🇪 Fast Server", "Fast Server"),
            ("Normal Server Name", "Normal Server Name"),
        ]
        for raw, expected in cases:
            cleaned = clean_node_name(raw)
            self.assertEqual(cleaned, expected, f"Failed for raw='{raw}': got '{cleaned}'")

    def test_find_best_node_empty(self):
        """Returns None if no candidate nodes exist."""
        self.assertIsNone(find_best_node([]))
        self.assertIsNone(find_best_node([{"type": "auto_balancer", "name": "auto"}]))

    def test_find_best_node_responsive_selection(self):
        """Selects the node with lowest latency when ping succeeds."""
        nodes = [
            {"name": "Slow Node", "server": "1.1.1.1", "port": 443, "type": "vless"},
            {"name": "Fast Node", "server": "2.2.2.2", "port": 443, "type": "vless"},
            {"name": "Medium Node", "server": "3.3.3.3", "port": 443, "type": "vless"},
        ]

        def mock_handshake(host, port, sni=None, timeout=1.5):
            if host == "1.1.1.1":
                return 250.0
            elif host == "2.2.2.2":
                return 35.0
            elif host == "3.3.3.3":
                return 120.0
            return None

        with patch("core.pinger.handshake_ping", side_effect=mock_handshake):
            best = find_best_node(nodes)
            self.assertIsNotNone(best)
            self.assertEqual(best["name"], "Fast Node")
            self.assertEqual(best["ping"], 35)

    def test_find_best_node_fallback_to_cached_ping(self):
        """Falls back to cached ping if parallel handshake ping fails for all nodes."""
        nodes = [
            {"name": "Node A", "server": "1.1.1.1", "port": 443, "type": "vless", "ping": 180},
            {"name": "Node B", "server": "2.2.2.2", "port": 443, "type": "vless", "ping": 42},
            {"name": "Node C", "server": "3.3.3.3", "port": 443, "type": "vless", "ping": None},
        ]

        with patch("core.pinger.handshake_ping", return_value=None):
            best = find_best_node(nodes)
            self.assertIsNotNone(best)
            self.assertEqual(best["name"], "Node B")
            self.assertEqual(best["ping"], 42)

    def test_find_best_node_fallback_to_first_node(self):
        """Falls back to first candidate node when no ping is available anywhere."""
        nodes = [
            {"name": "First Node", "server": "1.1.1.1", "port": 443, "type": "vless"},
            {"name": "Second Node", "server": "2.2.2.2", "port": 443, "type": "vless"},
        ]

        with patch("core.pinger.handshake_ping", return_value=None):
            best = find_best_node(nodes)
            self.assertIsNotNone(best)
            self.assertEqual(best["name"], "First Node")

    def test_xray_observatory_interval(self):
        """Verifies build_auto_balancer_config configures 15s probeInterval."""
        nodes = [
            {"type": "vless", "server": "1.1.1.1", "port": 443, "uuid": "u1", "security": "reality", "sni": "s.com", "pbk": "p"},
            {"type": "vless", "server": "2.2.2.2", "port": 443, "uuid": "u2", "security": "tls", "sni": "s.com"},
        ]
        cfg, _ = build_auto_balancer_config(nodes)
        self.assertEqual(cfg["observatory"]["probeInterval"], "15s")
        self.assertEqual(cfg["routing"]["balancers"][0]["strategy"]["type"], "leastPing")

    def test_save_nodes_and_load_settings_clean_emojis(self):
        """Verifies save_nodes and load_settings clean emojis from node names and metadata."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            mgr = VPNManager(tmp_dir, tmp_dir)
            mgr.save_nodes([
                {"name": "🇩🇪 Germany [VLESS]", "server": "1.1.1.1", "port": 443, "type": "vless"},
                {"name": "🛡️ Warp Generation (QUIC)", "server": "2.2.2.2", "port": 443, "type": "awg"},
            ])
            nodes = mgr.load_nodes()
            names = [n["name"] for n in nodes if n.get("type") != "auto_balancer"]
            self.assertEqual(names, ["Warp Generation (QUIC)", "Germany [VLESS]"])

            mgr.save_settings({
                "selected_node": {"name": "⚡ Fast [VLESS]"},
                "subscription_metadata": {"sub1": {"name": "🛡️ Red Shield"}},
            })
            settings = mgr.load_settings()
            self.assertEqual(settings["selected_node"]["name"], "Fast [VLESS]")
            self.assertEqual(settings["subscription_metadata"]["sub1"]["name"], "Red Shield")

    def test_auto_balancer_best_node_priority(self):
        """Verifies that passing best_node in auto_balancer node config places it first in balancer outbounds."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            mgr = VPNManager(tmp_dir, tmp_dir)
            candidates = [
                {"name": "Node A", "server": "1.1.1.1", "port": 443, "type": "vless", "uuid": "u1", "security": "reality", "sni": "a.com", "pbk": "p", "ping": 100},
                {"name": "Node B", "server": "2.2.2.2", "port": 443, "type": "vless", "uuid": "u2", "security": "reality", "sni": "b.com", "pbk": "p", "ping": 20},
            ]
            mgr.save_nodes(candidates)
            auto_node = {
                "type": "auto_balancer",
                "name": "Авто-выбор сервера",
                "best_node": candidates[1],  # Node B is best
            }
            with patch("vpn_manager.resolve_host", side_effect=lambda h: h):
                server_ips = mgr.generate_config(auto_node)
                self.assertIn("2.2.2.2", server_ips)
                with open(mgr.config_path, "r", encoding="utf-8") as f:
                    import json
                    cfg = json.load(f)
                # First proxy outbound must be the best node
                ob1 = cfg["outbounds"][0]
                self.assertEqual(ob1["settings"]["vnext"][0]["address"], "2.2.2.2")
                self.assertEqual(cfg["routing"]["balancers"][0]["fallbackTag"], "proxy-1")


if __name__ == "__main__":
    unittest.main()
