"""
Unit tests for node limits in core/constants.py, core/pinger.py and core/parsers.py.
"""

import unittest
from unittest.mock import patch

from core.constants import REGULAR_SUBSCRIPTION_NODE_LIMIT
from core.pinger import select_best_nodes
from core.parsers import parse_subscription_nodes


class TestNodeLimits(unittest.TestCase):
    def test_constants_node_limits(self):
        """Verifies user subscriptions have no limit (None)."""
        self.assertIsNone(REGULAR_SUBSCRIPTION_NODE_LIMIT)

    @patch("core.pinger.check_nodes_ping")
    def test_select_best_nodes_unlimited_target_count_none(self, mock_ping):
        """When target_count is None and ping returns empty, exact original order is preserved."""
        mock_ping.return_value = []
        nodes = [{"name": f"Node {i}", "server": f"1.1.1.{i}", "port": 443} for i in range(25)]
        res = select_best_nodes(nodes, target_count=None)
        self.assertEqual(len(res), 25)
        self.assertEqual([n["name"] for n in res], [f"Node {i}" for i in range(25)])

    def test_select_best_nodes_unlimited_target_count_non_positive(self):
        """When target_count <= 0, all nodes are returned without truncation."""
        nodes = [{"name": f"Node {i}", "server": f"192.0.2.{i}", "port": 443} for i in range(20)]
        for count in (0, -1, -10):
            res = select_best_nodes(nodes, target_count=count)
            self.assertEqual(len(res), 20)
            self.assertEqual(set(n["name"] for n in res), set(f"Node {i}" for i in range(20)))

    def test_select_best_nodes_limited_target_count(self):
        """When target_count > 0, nodes are truncated to target_count."""
        nodes = [{"name": f"Node {i}", "server": f"1.1.1.{i}", "port": 443} for i in range(25)]
        res = select_best_nodes(nodes, target_count=15)
        self.assertEqual(len(res), 15)

    @patch("core.pinger.check_nodes_ping")
    def test_select_best_nodes_unlimited_with_ping(self, mock_ping):
        """When target_count is None, responsive nodes are prioritized, and all nodes are preserved."""
        nodes = [{"name": f"Node {i}", "server": f"1.1.1.{i}", "port": 443} for i in range(10)]
        # Suppose Node 3 and Node 7 responded with low latency
        mock_ping.return_value = [
            {"name": "Node 7", "server": "1.1.1.7", "port": 443, "ping": 20},
            {"name": "Node 3", "server": "1.1.1.3", "port": 443, "ping": 50},
        ]
        res = select_best_nodes(nodes, target_count=None)
        self.assertEqual(len(res), 10)
        self.assertEqual(res[0]["name"], "Node 7")
        self.assertEqual(res[1]["name"], "Node 3")
        # All other 8 nodes must also be present
        returned_names = {n["name"] for n in res}
        self.assertEqual(returned_names, {f"Node {i}" for i in range(10)})

    @patch("core.pinger.check_nodes_ping")
    def test_select_best_nodes_limited_with_ping(self, mock_ping):
        """When target_count is set, responsive nodes are prioritized up to limit."""
        nodes = [{"name": f"Node {i}", "server": f"1.1.1.{i}", "port": 443} for i in range(20)]
        mock_ping.return_value = [
            {"name": "Node 5", "server": "1.1.1.5", "port": 443, "ping": 10},
        ]
        res = select_best_nodes(nodes, target_count=15)
        self.assertEqual(len(res), 15)
        self.assertEqual(res[0]["name"], "Node 5")

    @patch("core.parsers.download_subscription_payload")
    @patch("core.pinger.check_nodes_ping")
    def test_parse_subscription_nodes_limits(self, mock_ping, mock_download):
        """User subscriptions have no limit (all nodes returned) by default unless target_count is specified."""
        mock_ping.return_value = []  # No ping responses, triggers fallback order
        # Create 30 fake VLESS links
        lines = [
            f"vless://uuid{i}@server{i}.com:443?security=reality&sni=sni{i}.com&type=tcp#Node_{i}"
            for i in range(30)
        ]
        payload = "\n".join(lines).encode("utf-8")
        mock_download.return_value = (payload, {})

        # 1. User subscription URL -> unlimited (all 30 nodes)
        user_url = "https://my-custom-vpn-service.org/sub/token123"
        nodes_user, _, _ = parse_subscription_nodes(user_url)
        self.assertEqual(len(nodes_user), 30)

        # 2. User subscription with explicit target_count
        nodes_custom_limit, _, _ = parse_subscription_nodes(user_url, target_count=5)
        self.assertEqual(len(nodes_custom_limit), 5)

        # 3. User subscription with target_count=None or <= 0
        nodes_explicit_none, _, _ = parse_subscription_nodes(user_url, target_count=None)
        self.assertEqual(len(nodes_explicit_none), 30)
        nodes_explicit_zero, _, _ = parse_subscription_nodes(user_url, target_count=0)
        self.assertEqual(len(nodes_explicit_zero), 30)

    def test_get_node_category(self):
        """Verifies categorization into udp, obfs, tls, and all."""
        from core.system import get_node_category

        # Fast UDP
        self.assertEqual(get_node_category({"type": "hysteria2"}), "udp")
        self.assertEqual(get_node_category({"type": "hy2"}), "udp")
        self.assertEqual(get_node_category({"type": "tuic"}), "udp")

        # Obfuscation / Random
        self.assertEqual(get_node_category({"type": "awg"}), "obfs")
        self.assertEqual(get_node_category({"type": "wireguard"}), "obfs")
        self.assertEqual(get_node_category({"type": "warp"}), "obfs")
        self.assertEqual(get_node_category({"type": "shadowsocks"}), "obfs")
        self.assertEqual(get_node_category({"type": "ss"}), "obfs")
        self.assertEqual(get_node_category({"subscription_url": "amnezia_warp"}), "obfs")

        # TLS / Web
        self.assertEqual(get_node_category({"type": "vless", "security": "reality"}), "tls")
        self.assertEqual(get_node_category({"type": "trojan", "security": "tls"}), "tls")
        self.assertEqual(get_node_category({"type": "vmess"}), "tls")

        # Generic / Other
        self.assertEqual(get_node_category({"type": "custom"}), "all")


if __name__ == "__main__":
    unittest.main()
