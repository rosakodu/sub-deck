"""
Unit tests for Throne-style ping mechanics and per-subscription pinging.
"""

import unittest
from unittest.mock import patch, MagicMock
from core.pinger import handshake_ping, ping_all_nodes, extract_node_sni


class TestThronePingMechanics(unittest.TestCase):

    def test_extract_node_sni(self):
        # Explicit SNI
        self.assertEqual(extract_node_sni({"sni": "example.com"}), "example.com")
        # Explicit host
        self.assertEqual(extract_node_sni({"host": "host.com"}), "host.com")
        # Inferred from domain server for VLESS/Trojan
        self.assertEqual(
            extract_node_sni({"server": "vpn.domain.org", "type": "vless", "security": "reality"}),
            "vpn.domain.org"
        )
        # IP server should not be inferred as SNI
        self.assertIsNone(
            extract_node_sni({"server": "192.168.1.1", "type": "vless", "security": "reality"})
        )

    @patch("core.pinger.socket.create_connection")
    def test_handshake_ping_tcp_success(self, mock_conn):
        mock_sock = MagicMock()
        mock_conn.return_value = mock_sock

        lat = handshake_ping("1.1.1.1", 443, sni=None, timeout=1.0)
        self.assertIsNotNone(lat)
        self.assertGreater(lat, 0)
        mock_sock.close.assert_called_once()

    @patch("core.pinger.socket.create_connection", side_effect=OSError("Connection refused"))
    @patch("core.pinger.subprocess.run")
    def test_handshake_ping_tcp_failure_no_icmp_fallback(self, mock_subproc, mock_conn):
        """TCP proxies must not fall back to ICMP on connection error, returning None (Unavailable)."""
        lat = handshake_ping("1.1.1.1", 443, sni=None, timeout=1.0, is_udp=False)
        self.assertIsNone(lat)
        mock_subproc.assert_not_called()

    @patch("core.pinger.subprocess.run")
    def test_handshake_ping_udp_uses_icmp(self, mock_subproc):
        """UDP proxies (WireGuard/AWG) use ICMP ping."""
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_subproc.return_value = mock_res

        lat = handshake_ping("1.1.1.1", 51820, sni=None, timeout=1.0, is_udp=True)
        self.assertIsNotNone(lat)
        mock_subproc.assert_called_once()

    @patch("core.pinger.handshake_ping")
    def test_ping_all_nodes_updates_lat_and_unavailable(self, mock_ping):
        def side_effect(host, port, sni=None, timeout=2.0, is_udp=False):
            if host == "online.com":
                return 45.0
            return None

        mock_ping.side_effect = side_effect

        nodes = [
            {"name": "Node 1", "server": "online.com", "port": 443, "type": "vless"},
            {"name": "Node 2", "server": "offline.com", "port": 443, "type": "vless"},
        ]

        res = ping_all_nodes(nodes)
        self.assertEqual(res[0]["ping"], 45)
        self.assertEqual(res[1]["ping"], -1)  # Unavailable (Throne format)

    @patch("core.pinger.handshake_ping")
    def test_ping_all_nodes_sub_millisecond_clamped_to_one(self, mock_ping):
        mock_ping.return_value = 0.4
        nodes = [
            {"name": "Local Fast", "server": "fast.local", "port": 443, "type": "vless"},
        ]
        res = ping_all_nodes(nodes)
        self.assertEqual(res[0]["ping"], 1)


if __name__ == "__main__":
    unittest.main()
