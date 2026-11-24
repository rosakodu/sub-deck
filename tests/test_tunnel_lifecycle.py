import asyncio
from contextlib import ExitStack
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from core.constants import TUN_INTERFACE, TUN_ROUTE_PROTOCOL
from main import Plugin
from vpn_manager import VPNManager


class TunnelLifecycleTests(unittest.TestCase):
    node = {"name": "Test node", "type": "vless", "server": "192.0.2.8"}
    gateway = "192.0.2.1"
    interface = "wlan0"

    def setUp(self):
        stack = self.enterContext(ExitStack())
        root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.manager = VPNManager(str(root), str(root), logger=Mock())
        self.commands = []
        self.failure = None
        stack.enter_context(patch("core.tunnel_routing.run_command", side_effect=self.run_command))
        stack.enter_context(patch("vpn_manager.subprocess.run"))
        self.spawn = stack.enter_context(patch("vpn_manager.subprocess.Popen"))
        self.core = Mock(pid=1)
        self.tun = Mock(pid=2)
        self.spawn.side_effect = [self.core, self.tun]
        stack.enter_context(patch("vpn_manager.is_interface_present", return_value=False))
        stack.enter_context(patch("vpn_manager.get_default_gateway", return_value=(self.gateway, self.interface)))
        stack.enter_context(patch("vpn_manager.validate_xray_config", return_value=(True, "")))
        stack.enter_context(patch("vpn_manager.wait_for_port", return_value=True))
        stack.enter_context(patch("vpn_manager.wait_for_interface", return_value=True))
        stack.enter_context(patch.object(self.manager, "ensure_binaries", return_value=True))
        stack.enter_context(patch.object(self.manager, "generate_config", return_value=self.node["server"]))

    def run_command(self, command):
        self.commands.append(command)
        return subprocess.CompletedProcess(command, int(command[:3] == self.failure), "", "test")

    def test_dns_failure_rolls_back_routing_and_children(self):
        self.failure = ["resolvectl", "domain", TUN_INTERFACE]

        self.assertFalse(self.manager.start(self.node))

        self.assertIn(["ip", "route", "del", self.node["server"], "via", self.gateway, "dev",
                       self.interface, "proto", TUN_ROUTE_PROTOCOL], self.commands)
        self.assertIn(["ip", "link", "delete", TUN_INTERFACE], self.commands)
        self.assertNotIn(["ip", "link", "delete", "tun0"], self.commands)
        self.assertIsNone(self.manager.load_settings().get("selected_node"))
        self.core.terminate.assert_called_once()
        self.tun.terminate.assert_called_once()

    def test_failed_host_route_is_not_removed(self):
        self.failure = ["ip", "route", "add"]

        self.assertFalse(self.manager.start(self.node))

        self.assertFalse(any(command[:4] == ["ip", "route", "del", self.node["server"]]
                             for command in self.commands))

    def test_resume_skips_connection_after_manual_stop(self):
        self.assertTrue(self.manager.start(self.node))
        generation = self.manager.resume_generation()
        self.assertIsNotNone(generation)

        self.manager.stop()
        self.manager.recover_after_resume(generation, network_ready=True)

        self.assertEqual(self.spawn.call_count, 2)
        self.assertIsNone(self.manager.resume_generation())

    def test_stale_cleanup_accepts_saved_single_server_ip(self):
        settings = self.manager.load_settings()
        settings["_routing_state"] = {
            "tun_interface": TUN_INTERFACE,
            "server_ip": self.node["server"],
            "gw_ip": self.gateway,
            "iface": self.interface,
        }
        self.manager.save_settings(settings)

        self.manager.cleanup_stale()

        self.assertIn(["ip", "route", "del", self.node["server"], "via", self.gateway, "dev",
                       self.interface, "proto", TUN_ROUTE_PROTOCOL], self.commands)
        self.assertNotIn("_routing_state", self.manager.load_settings())

    def test_resume_timeout_clears_connection_without_retry(self):
        self.assertTrue(self.manager.start(self.node))
        generation = self.manager.resume_generation()

        self.manager.recover_after_resume(generation, network_ready=False)

        self.assertIsNone(self.manager.resume_generation())
        self.assertFalse(self.manager.is_running())
        self.assertEqual(self.manager.load_settings().get("selected_node"), self.node)
        self.assertEqual(self.spawn.call_count, 2)

    def test_failed_route_cleanup_survives_restart_and_is_retried(self):
        self.assertTrue(self.manager.start(self.node))
        route = [self.node["server"], "via", self.gateway, "dev", self.interface,
                 "proto", TUN_ROUTE_PROTOCOL]
        delete = ["ip", "route", "del", *route]
        probe = ["ip", "route", "show", "exact", *route]

        def fail_host_route(command):
            if command == delete:
                return subprocess.CompletedProcess(command, 1, "", "permission denied")
            if command == probe:
                return subprocess.CompletedProcess(command, 0, "owned route still present", "")
            return self.run_command(command)

        with patch("core.tunnel_routing.run_command", side_effect=fail_host_route):
            self.assertFalse(self.manager.stop())

        settings = self.manager.load_settings()
        self.assertEqual(settings["selected_node"], self.node)
        self.assertEqual(settings["_routing_state"]["server_ip"], [self.node["server"]])
        self.assertFalse(settings["_routing_state"]["cleanup_tun"])
        self.manager._logger.info.assert_any_call("VPN cleanup failed: " + " ".join(delete) + ": permission denied")

        restarted = VPNManager(self.manager.plugin_dir, self.manager.settings_dir, logger=Mock())
        self.commands.clear()
        self.assertTrue(restarted.stop())
        self.assertEqual(self.commands, [delete])
        self.assertNotIn("_routing_state", restarted.load_settings())

    def test_already_missing_routes_and_interface_count_as_clean(self):
        self.assertTrue(self.manager.start(self.node))

        def missing(command):
            if command[:4] == ["ip", "route", "show", "exact"]:
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.CompletedProcess(command, 1, "", "not found")

        with (
            patch("core.tunnel_routing.run_command", side_effect=missing),
            patch("core.tunnel_routing.is_interface_present", return_value=False),
        ):
            self.assertTrue(self.manager.stop())

        self.assertNotIn("_routing_state", self.manager.load_settings())

    def test_interface_that_could_not_be_removed_blocks_reconnect(self):
        self.assertTrue(self.manager.start(self.node))

        with (
            patch("core.tunnel_routing.is_interface_present", return_value=True),
            patch("core.tunnel_routing.run_command", side_effect=lambda command:
                  subprocess.CompletedProcess(command, int(command[:3] == ["ip", "link", "delete"]),
                                              "", "interface busy")),
        ):
            self.assertFalse(self.manager.start(self.node))

        self.assertEqual(self.spawn.call_count, 2)
        self.assertIn("_routing_state", self.manager.load_settings())


class SuspendMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovers_selected_connection_when_process_has_died(self):
        plugin = Plugin()
        plugin.loop = asyncio.get_running_loop()
        plugin.vpn = Mock()
        plugin.vpn.is_running.return_value = False
        plugin.vpn.resume_generation.return_value = 0
        with (
            patch("main.asyncio.sleep", new=AsyncMock(side_effect=[None, asyncio.CancelledError])),
            patch("main.time", Mock(**{
                "clock_gettime.side_effect": [100, 143],
                "monotonic.side_effect": [100, 103],
            })),
            patch("main.get_default_gateway", return_value=("192.0.2.1", "wlan0")),
        ):
            await plugin._sleep_monitor_loop()

        plugin.vpn.recover_after_resume.assert_called_once_with(0, True)
