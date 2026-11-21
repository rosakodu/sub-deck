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
        stack.enter_context(patch("vpn_manager.run_command", side_effect=self.run_command))
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
