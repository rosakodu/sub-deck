import asyncio
import tempfile
import unittest
from unittest.mock import Mock, patch

from core.constants import DNS_SERVERS, PRESET_ROSCOMVPN
from core.tunnel_routing import TunnelRouting
from core.server import SubDeckApiServer
from core.xray_config import build_xray_config, build_auto_balancer_config
from core.singbox_config import build_singbox_config
from vpn_manager import VPNManager


class TestCoreFixes(unittest.TestCase):
    def test_tunnel_routing_dns_merge(self):
        tr = TunnelRouting(log=Mock())
        captured_commands = []

        def mock_run(cmd):
            captured_commands.append(cmd)
            return Mock(returncode=0, stderr="")

        with patch("core.tunnel_routing.run_command", side_effect=mock_run):
            tr.configure("192.168.1.1", "eth0", ["1.2.3.4"], node_dns="10.254.254.254")

        dns_cmd = next(c for c in captured_commands if c[:2] == ["resolvectl", "dns"])
        expected_dns = ["10.254.254.254"] + [s for s in DNS_SERVERS if s != "10.254.254.254"]
        self.assertEqual(dns_cmd[3:], expected_dns)

    def test_xray_balancer_filters_unencrypted_vless(self):
        nodes = [
            {"type": "vless", "server": "1.1.1.1", "port": 443, "uuid": "u1", "security": "none"},
            {"type": "vless", "server": "1.1.1.2", "port": 443, "uuid": "u2", "security": ""},
            {"type": "vless", "server": "1.1.1.3", "port": 443, "uuid": "u3", "security": "false"},
            {"type": "vless", "server": "1.1.1.4", "port": 443, "uuid": "u4"},
            {"type": "vless", "server": "1.1.1.5", "port": 443, "uuid": "u5", "security": "reality", "sni": "example.com", "pbk": "abc"},
            {"type": "vless", "server": "1.1.1.6", "port": 443, "uuid": "u6", "security": "tls", "sni": "example.com"},
        ]
        cfg, ips = build_auto_balancer_config(nodes)
        self.assertEqual(ips, ["1.1.1.5", "1.1.1.6"])
        tags = [o["tag"] for o in cfg["outbounds"] if o.get("tag", "").startswith("proxy-")]
        self.assertEqual(tags, ["proxy-5", "proxy-6"])

    def test_xray_roscomvpn_no_category_ru_blocked(self):
        node = {"type": "vless", "server": "1.1.1.5", "port": 443, "uuid": "u5", "security": "tls"}
        cfg_single = build_xray_config(node, "1.1.1.5", preset=PRESET_ROSCOMVPN)
        self.assertFalse(any("category-ru-blocked" in str(r) for r in cfg_single["routing"]["rules"]))

        cfg_balancer, _ = build_auto_balancer_config([node], preset=PRESET_ROSCOMVPN)
        self.assertFalse(any("category-ru-blocked" in str(r) for r in cfg_balancer["routing"]["rules"]))

    def test_singbox_warp_dns_and_fallback(self):
        warp_node = {
            "type": "warp",
            "name": "Cloudflare WARP",
            "server": "162.159.192.1",
            "port": 2408,
            "private_key": "AAAA",
            "peer_public_key": "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="
        }
        cfg = build_singbox_config(warp_node, "162.159.192.1")
        dns_servers = cfg["dns"]["servers"]

        server_ips = [s["server"] for s in dns_servers]
        self.assertNotIn("10.254.254.254", server_ips)
        self.assertEqual(server_ips[0], "1.1.1.1")
        self.assertIn("fallback-dns", [s["tag"] for s in dns_servers])

        # Verify route rules don't contain 10.254.254.254
        for rule in cfg["route"]["rules"]:
            for cidr in rule.get("ip_cidr", []):
                self.assertNotIn("10.254.254.254", cidr)


class TestServerFixes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        class MockPlugin:
            def __init__(self):
                self.vpn = self
                self.loop = asyncio.get_event_loop()
            def is_running(self):
                return True
            def load_settings(self):
                return {"selected_node": {"name": "Default"}}
            def get_nodes(self):
                return [{"name": "Node0"}, {"name": "Node1"}]
            async def connect_node(self, node):
                return True

        self.plugin = MockPlugin()
        self.server = SubDeckApiServer(self.plugin)

    async def test_ping_real_empty_and_none(self):
        with patch("core.pinger.http_url_test", return_value=None):
            code, res = await self.server._route_request("POST", "/api/ping/real", {})
            self.assertEqual(code, 200)
            self.assertFalse(res["success"])
            self.assertIsNone(res["delay_ms"])

            code, res = await self.server._route_request("POST", "/api/ping/real", None)
            self.assertEqual(code, 200)
            self.assertFalse(res["success"])

    async def test_real_delay_get_alias(self):
        with patch("core.pinger.http_url_test", return_value=45.5):
            code, res = await self.server._route_request("GET", "/api/real_delay", {})
            self.assertEqual(code, 200)
            self.assertTrue(res["success"])
            self.assertEqual(res["delay_ms"], 45.5)

    async def test_connect_by_index(self):
        code, res = await self.server._route_request("POST", "/api/connect", {"index": 1})
        self.assertEqual(code, 200)
        self.assertEqual(res["node"]["name"], "Node1")

        code, res = await self.server._route_request("POST", "/api/connect", {"index": 99})
        self.assertEqual(code, 400)

        code, res = await self.server._route_request("POST", "/api/connect", {"index": "invalid"})
        self.assertEqual(code, 400)

    def test_selected_node_persists_across_stop_and_stale_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            mgr = VPNManager(tmp_dir, tmp_dir)
            test_node = {"name": "Test Node 1", "server": "1.2.3.4", "port": 443, "type": "vless"}
            
            # Simulate node connection
            with mgr._storage.lock:
                settings = mgr.load_settings()
                settings["selected_node"] = test_node
                mgr.save_settings(settings)
            mgr._active_node = test_node

            # Disconnect / stop
            mgr.stop()
            self.assertIsNone(mgr._active_node)
            self.assertEqual(mgr.load_settings().get("selected_node"), test_node)

            # Cleanup stale on boot
            mgr.cleanup_stale()
            self.assertEqual(mgr.load_settings().get("selected_node"), test_node)


if __name__ == "__main__":
    unittest.main()
