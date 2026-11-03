"""
Unit tests for Sub-Deck Desktop Tray Lifecycle (Milestone 2).
Covers:
- Single-instance file lock (acquisition, contention, release)
- D-Bus well-known name collision handling
- Desktop notification replaces_id deduplication and ID tracking
- Background polling guard (_is_polling)
- Dynamic script path detection in launch_tray_process and kill_tray_process
- Plugin._unload lifecycle cleanup
"""

import os
import sys
import time
import tempfile
import asyncio
import threading
import unittest
from unittest.mock import patch, MagicMock, call

# Ensure root directory is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import dbus
from tray.tray_app import (
    acquire_single_instance_lock,
    get_tray_lock_path,
    SubDeckTrayApp,
    main,
)
from tray.desktop_integration import (
    kill_tray_process,
    launch_tray_process,
)
from main import Plugin


class TestTrayLock(unittest.TestCase):
    """Verifies single-instance protection via fcntl.flock on lock file."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.lock_file = os.path.join(self.temp_dir.name, "test-sub-deck-tray.lock")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_acquire_single_instance_lock_success(self):
        """First instance should successfully acquire the exclusive lock."""
        handle = acquire_single_instance_lock(self.lock_file)
        self.assertIsNotNone(handle)
        handle.close()

    def test_acquire_single_instance_lock_contention(self):
        """Second instance must fail to acquire lock when first instance holds it."""
        handle1 = acquire_single_instance_lock(self.lock_file)
        self.assertIsNotNone(handle1)

        handle2 = acquire_single_instance_lock(self.lock_file)
        self.assertIsNone(handle2, "Second lock acquisition must return None while first is held")

        handle1.close()

    def test_release_and_reacquire_lock(self):
        """Closing the first handle releases the lock allowing a new acquisition."""
        handle1 = acquire_single_instance_lock(self.lock_file)
        self.assertIsNotNone(handle1)
        handle1.close()

        handle2 = acquire_single_instance_lock(self.lock_file)
        self.assertIsNotNone(handle2, "Should re-acquire lock after previous handle was closed")
        handle2.close()

    def test_main_exits_when_lock_held(self):
        """main() must cleanly exit with code 0 when another instance holds the lock."""
        with patch("tray.tray_app.acquire_single_instance_lock", return_value=None):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 0)

    def test_get_tray_lock_path_format(self):
        """get_tray_lock_path must return a valid path ending in sub-deck-tray.lock or sub-deck-tray-{uid}.lock."""
        path = get_tray_lock_path()
        self.assertTrue(path.endswith(".lock"))
        self.assertTrue("sub-deck-tray" in path)
        self.assertTrue(path.startswith("/") or path.startswith("/run") or path.startswith("/tmp"))

    def test_lock_fallback_on_inaccessible_path(self):
        """Fallback to /tmp/sub-deck-tray-{uid}.lock when primary path is inaccessible."""
        handle = acquire_single_instance_lock("/nonexistent_dir/tray.lock")
        self.assertIsNotNone(handle)
        self.assertNotEqual(handle, False)
        uid = os.getuid()
        self.assertTrue(handle.name.startswith(f"/tmp/sub-deck-tray-{uid}"))
        handle.close()
        try:
            os.remove(handle.name)
        except Exception:
            pass

    def test_lock_user_isolation(self):
        """Distinct UIDs get distinct lock file paths in /tmp."""
        with patch.dict(os.environ, {}, clear=True), patch("os.path.isdir", return_value=False):
            with patch("os.getuid", return_value=1000):
                p1 = get_tray_lock_path()
            with patch("os.getuid", return_value=0):
                p2 = get_tray_lock_path()
            self.assertEqual((p1, p2), ("/tmp/sub-deck-tray-1000.lock", "/tmp/sub-deck-tray-0.lock"))

    def test_main_warns_when_lock_cannot_be_created(self):
        """main() must warn to stderr and proceed when acquire_single_instance_lock returns False."""
        with patch("tray.tray_app.acquire_single_instance_lock", return_value=False), \
             patch("tray.tray_app.dbus.mainloop.glib.DBusGMainLoop"), \
             patch("tray.tray_app.GLib.MainLoop"), \
             patch("tray.tray_app.SubDeckTrayApp"), \
             patch("sys.argv", ["tray_app.py", "--test"]):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 0)


class TestTrayNotificationsAndDbus(unittest.TestCase):
    """Verifies D-Bus single-instance name and notification deduplication via replaces_id."""

    @patch("dbus.service.BusName")
    @patch("dbus.SessionBus")
    @patch("tray.tray_app.SubDeckSNI")
    @patch("tray.tray_app.SubDeckDBusMenu")
    @patch("tray.tray_app.GLib.timeout_add")
    def test_dbus_name_exists_exit(self, mock_timeout, mock_menu, mock_sni, mock_bus, mock_bus_name):
        """When D-Bus name is already owned, SubDeckTrayApp must exit cleanly with code 0."""
        mock_bus_name.side_effect = dbus.exceptions.NameExistsException("org.freedesktop.StatusNotifierItem.sub_deck")

        with patch("tray.tray_app.SubDeckTrayApp._trigger_background_poll"):
            with self.assertRaises(SystemExit) as cm:
                mock_loop = MagicMock()
                SubDeckTrayApp(mock_loop)
            self.assertEqual(cm.exception.code, 0)

    @patch("dbus.service.BusName")
    @patch("dbus.SessionBus")
    @patch("tray.tray_app.SubDeckSNI")
    @patch("tray.tray_app.SubDeckDBusMenu")
    @patch("tray.tray_app.GLib.timeout_add")
    def test_notification_replaces_id_tracking(self, mock_timeout, mock_menu, mock_sni, mock_bus_cls, mock_bus_name):
        """_send_desktop_notification must pass _last_notification_id as replaces_id and update it."""
        mock_session_bus = MagicMock()
        mock_bus_cls.return_value = mock_session_bus

        mock_notify_obj = MagicMock()
        mock_notify_iface = MagicMock()
        mock_session_bus.get_object.return_value = mock_notify_obj

        with patch("dbus.Interface", return_value=mock_notify_iface), \
             patch("tray.tray_app.SubDeckTrayApp._trigger_background_poll"):
            app = SubDeckTrayApp(MagicMock())
            self.assertEqual(app._last_notification_id, 0)

            # First notification: replaces_id should be 0, mock returns ID 101
            mock_notify_iface.Notify.return_value = 101
            res1 = app._send_desktop_notification("Test 1", "Message 1", timeout_ms=3000)

            self.assertEqual(res1, 101)
            self.assertEqual(app._last_notification_id, 101)
            first_call_args = mock_notify_iface.Notify.call_args[0]
            self.assertEqual(first_call_args[0], "Sub-Deck VPN")
            self.assertEqual(int(first_call_args[1]), 0, "First call replaces_id must be 0")
            self.assertEqual(first_call_args[3], "Test 1")
            self.assertEqual(first_call_args[4], "Message 1")

            # Second notification: replaces_id should now be 101, mock returns ID 102
            mock_notify_iface.Notify.return_value = 102
            res2 = app._send_desktop_notification("Test 2", "Message 2", timeout_ms=3000)

            self.assertEqual(res2, 102)
            self.assertEqual(app._last_notification_id, 102)
            second_call_args = mock_notify_iface.Notify.call_args[0]
            self.assertEqual(int(second_call_args[1]), 101, "Second call replaces_id must be 101")
            self.assertEqual(second_call_args[3], "Test 2")
            self.assertEqual(second_call_args[4], "Message 2")

    @patch("dbus.service.BusName")
    @patch("dbus.SessionBus")
    @patch("tray.tray_app.SubDeckSNI")
    @patch("tray.tray_app.SubDeckDBusMenu")
    @patch("tray.tray_app.GLib.timeout_add")
    def test_notification_error_gracefully_handled(self, mock_timeout, mock_menu, mock_sni, mock_bus_cls, mock_bus_name):
        """If D-Bus notification fails, _send_desktop_notification must return 0 without crashing."""
        mock_session_bus = MagicMock()
        mock_bus_cls.return_value = mock_session_bus
        mock_session_bus.get_object.side_effect = Exception("DBus daemon offline")

        with patch("tray.tray_app.SubDeckTrayApp._trigger_background_poll"):
            app = SubDeckTrayApp(MagicMock())
            app._last_notification_id = 50
            res = app._send_desktop_notification("Title", "Body")
            self.assertEqual(res, 0)
            self.assertEqual(app._last_notification_id, 50, "ID must remain unchanged on failure")


class TestPollingGuard(unittest.TestCase):
    """Verifies self._is_polling guard prevents overlapping status polls."""

    @patch("dbus.service.BusName")
    @patch("dbus.SessionBus")
    @patch("tray.tray_app.SubDeckSNI")
    @patch("tray.tray_app.SubDeckDBusMenu")
    @patch("tray.tray_app.GLib.timeout_add")
    def test_polling_guard_blocks_concurrent_polls(self, mock_timeout, mock_menu, mock_sni, mock_bus, mock_bus_name):
        """When _is_polling is True, _trigger_background_poll must abort and return False."""
        with patch("tray.tray_app.SubDeckTrayApp._trigger_background_poll"):
            app = SubDeckTrayApp(MagicMock())

        app._is_polling = True
        with patch("threading.Thread") as mock_thread:
            result = app._trigger_background_poll()
            self.assertFalse(result, "_trigger_background_poll must return False when already polling")
            mock_thread.assert_not_called()

    @patch("dbus.service.BusName")
    @patch("dbus.SessionBus")
    @patch("tray.tray_app.SubDeckSNI")
    @patch("tray.tray_app.SubDeckDBusMenu")
    @patch("tray.tray_app.GLib.timeout_add")
    def test_polling_guard_resets_on_completion_or_error(self, mock_timeout, mock_menu, mock_sni, mock_bus, mock_bus_name):
        """Worker thread must reset _is_polling to False even if client raises exception."""
        with patch("tray.tray_app.SubDeckTrayApp._trigger_background_poll"):
            app = SubDeckTrayApp(MagicMock())

        app._is_polling = False
        app.client.get_status = MagicMock(side_effect=RuntimeError("Network timeout"))

        # Trigger poll and wait for worker thread to complete
        with patch("tray.tray_app.GLib.idle_add") as mock_idle:
            result = app._trigger_background_poll()
            self.assertTrue(result)
            # Give daemon thread a brief moment to run and exit
            import time
            for _ in range(50):
                if not app._is_polling:
                    break
                time.sleep(0.02)
            self.assertFalse(app._is_polling, "_is_polling must be reset to False in finally block")

    @patch("dbus.service.BusName")
    @patch("dbus.SessionBus")
    @patch("tray.tray_app.SubDeckSNI")
    @patch("tray.tray_app.SubDeckDBusMenu")
    @patch("tray.tray_app.GLib.timeout_add")
    def test_trigger_background_poll_thread_safety_barrier(self, mock_timeout, mock_menu, mock_sni, mock_bus, mock_bus_name):
        """20 concurrent threads racing through a Barrier on _trigger_background_poll() start exactly 1 worker and 19 return False."""
        with patch("tray.tray_app.SubDeckTrayApp._trigger_background_poll"):
            app = SubDeckTrayApp(MagicMock())

        app._is_polling = False
        barrier = threading.Barrier(20)
        res = []
        app.client.get_status = MagicMock(side_effect=lambda: (time.sleep(0.08), {})[1])

        def _worker():
            barrier.wait()
            res.append(app._trigger_background_poll())

        with patch("tray.tray_app.GLib.idle_add"):
            threads = [threading.Thread(target=_worker) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

            self.assertEqual((res.count(True), res.count(False)), (1, 19))
            for _ in range(50):
                if not app._is_polling:
                    break
                time.sleep(0.02)

    @patch("dbus.service.BusName")
    @patch("dbus.SessionBus")
    @patch("tray.tray_app.SubDeckSNI")
    @patch("tray.tray_app.SubDeckDBusMenu")
    @patch("tray.tray_app.GLib.timeout_add")
    def test_out_of_order_poll_discard(self, mock_timeout, mock_menu, mock_sni, mock_bus, mock_bus_name):
        """Out-of-order poll sequence ID is discarded."""
        with patch("tray.tray_app.SubDeckTrayApp._trigger_background_poll"):
            app = SubDeckTrayApp(MagicMock())

        app._last_applied_seq = 10
        app.status = {"version": "initial"}
        app.last_status = {"version": "initial"}

        res = app._apply_state(status={"version": "stale"}, nodes=[], settings={}, seq=9)
        self.assertFalse(res)
        self.assertNotEqual(getattr(app, "last_status", None), {"version": "stale"})
        self.assertNotEqual(app.status, {"version": "stale"})
        self.assertEqual(app.status, {"version": "initial"})


class TestDesktopIntegrationLifecycle(unittest.TestCase):
    """Verifies dynamic path detection and clean termination in desktop_integration."""

    @patch("subprocess.run")
    def test_kill_tray_process_dynamic_path(self, mock_subproc):
        """kill_tray_process must target dynamic script_path and fallback pattern."""
        test_plugin_dir = "/home/deck/custom-plugins/sub-deck"
        expected_script = os.path.abspath(os.path.join(test_plugin_dir, "tray", "tray_app.py"))

        result = kill_tray_process(test_plugin_dir)
        self.assertTrue(result)

        calls = mock_subproc.call_args_list
        pkill_calls = [c[0][0] for c in calls if c[0][0][0] == "pkill"]
        self.assertGreaterEqual(len(pkill_calls), 2)
        self.assertIn(["pkill", "-f", expected_script], pkill_calls)
        self.assertIn(["pkill", "-f", "tray/tray_app.py"], pkill_calls)

    @patch("subprocess.run")
    def test_kill_tray_process_without_plugin_dir(self, mock_subproc):
        """kill_tray_process without argument must still kill by fallback pattern."""
        result = kill_tray_process()
        self.assertTrue(result)

        calls = mock_subproc.call_args_list
        pkill_calls = [c[0][0] for c in calls if c[0][0][0] == "pkill"]
        self.assertIn(["pkill", "-f", "tray/tray_app.py"], pkill_calls)

    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run")
    def test_launch_tray_process_detects_already_running(self, mock_subproc, mock_exists):
        """launch_tray_process must return True immediately if pgrep finds running instance."""
        mock_pgrep = MagicMock()
        mock_pgrep.returncode = 0
        mock_pgrep.stdout = b"9999\n"
        mock_subproc.return_value = mock_pgrep

        test_plugin_dir = "/home/deck/custom-plugins/sub-deck"
        res = launch_tray_process(test_plugin_dir)
        self.assertTrue(res)

        # Ensure it checked pgrep with dynamic path
        expected_script = os.path.abspath(os.path.join(test_plugin_dir, "tray", "tray_app.py"))
        mock_subproc.assert_called_with(["pgrep", "-f", expected_script], stdout=-1)


class TestPluginUnloadIntegration(unittest.IsolatedAsyncioTestCase):
    """Verifies that Plugin._unload cleans up running tray companion process."""

    @patch("main.kill_tray_process")
    async def test_unload_calls_kill_tray_process(self, mock_kill):
        """_unload must invoke kill_tray_process with plugin_dir."""
        plugin = Plugin()
        plugin.loop = asyncio.get_running_loop()
        plugin.vpn = MagicMock()
        plugin.vpn.plugin_dir = "/test/plugin/dir"
        plugin.api_server = None
        plugin.update_task = None
        plugin.sleep_task = None

        await plugin._unload()
        mock_kill.assert_called_with("/test/plugin/dir")


if __name__ == "__main__":
    unittest.main()
