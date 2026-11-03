"""
Empirical stress test harness for Sub-Deck Milestone 2 (KDE Notification & Tray Lifecycle):
1. Concurrent launches of 10 tray instances on lock file -> exactly 1 acquires, 9 exit code 0.
2. Rapid notification spam -> replaces_id sequence tracking and resilience.
3. Lock recovery after termination (SIGKILL / SIGTERM / rapid recovery cycles).
"""

import os
import sys
import time
import signal
import tempfile
import subprocess
import threading
import unittest
from unittest.mock import MagicMock, patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import dbus
from tray.tray_app import (
    acquire_single_instance_lock,
    get_tray_lock_path,
    SubDeckTrayApp,
)


class TestTrayConcurrentLaunches(unittest.TestCase):
    """Stress tests concurrent launches on the lock file."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = os.environ.copy()
        self.env["XDG_RUNTIME_DIR"] = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_concurrent_10_instances_lock_contention(self):
        """Simulate rapid concurrent launches of 10 tray instances.
        Verify exactly 1 acquires the lock and stays running; 9 exit cleanly with code 0."""
        cmd = [sys.executable, os.path.join(BASE_DIR, "tray", "tray_app.py")]
        procs = [
            subprocess.Popen(
                cmd,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(10)
        ]

        # Wait for contention resolution (up to 3 seconds)
        time.sleep(1.5)

        alive = [p for p in procs if p.poll() is None]
        dead = [p for p in procs if p.poll() is not None]

        try:
            self.assertEqual(len(alive), 1, f"Expected exactly 1 running instance, got {len(alive)}")
            self.assertEqual(len(dead), 9, f"Expected exactly 9 exited instances, got {len(dead)}")

            for p in dead:
                self.assertEqual(p.returncode, 0, f"Exited instance returned non-zero: {p.returncode}")
                stdout, _ = p.communicate()
                self.assertIn("Another instance is already running (file lock held). Exiting.", stdout)
        finally:
            for p in procs:
                if p.poll() is None:
                    p.terminate()
                    try:
                        p.wait(timeout=3)
                    except Exception:
                        pass
                if p.stdout:
                    p.stdout.close()
                if p.stderr:
                    p.stderr.close()

    def test_high_concurrency_race_direct_lock(self):
        """20 concurrent threads attempting direct acquire_single_instance_lock.
        Kernel flock must guarantee exactly 1 succeeds and 19 receive None."""
        lock_file = os.path.join(self.temp_dir.name, "high_concurrency.lock")
        results = []
        handles = []
        barrier = threading.Barrier(20)

        def _worker():
            barrier.wait()
            h = acquire_single_instance_lock(lock_file)
            if h is not None:
                handles.append(h)
                results.append("acquired")
            else:
                results.append("blocked")

        threads = [threading.Thread(target=_worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        try:
            self.assertEqual(results.count("acquired"), 1, "Exactly 1 thread must acquire lock")
            self.assertEqual(results.count("blocked"), 19, "Exactly 19 threads must be blocked")
        finally:
            for h in handles:
                h.close()


class TestNotificationSpamAndDeduplication(unittest.TestCase):
    """Stress tests notification spam and replaces_id tracking."""

    @patch("dbus.service.BusName")
    @patch("dbus.SessionBus")
    @patch("tray.tray_app.SubDeckSNI")
    @patch("tray.tray_app.SubDeckDBusMenu")
    @patch("tray.tray_app.GLib.timeout_add")
    def test_rapid_notification_spam_tracks_replaces_id(self, *mocks):
        """50 rapid notification calls must track replaces_id sequentially and never revert to 0."""
        mock_session_bus = MagicMock()
        mock_notify_obj = MagicMock()
        mock_notify_iface = MagicMock()
        mock_session_bus.get_object.return_value = mock_notify_obj

        call_log = []

        def fake_notify(app_name, replaces_id, app_icon, summary, body, actions, hints, timeout):
            prev_id = int(replaces_id)
            new_id = prev_id + 1 if prev_id > 0 else 100
            call_log.append({"replaces_id": prev_id, "returned_id": new_id, "summary": summary})
            return new_id

        mock_notify_iface.Notify.side_effect = fake_notify

        with patch("dbus.Interface", return_value=mock_notify_iface), \
             patch("tray.tray_app.SubDeckTrayApp._trigger_background_poll"):
            app = SubDeckTrayApp(MagicMock())
            app.session_bus = mock_session_bus

            # Spam 50 notifications in rapid sequence
            for i in range(50):
                res = app._send_desktop_notification(f"Title {i}", f"Message {i}", timeout_ms=1000)
                self.assertGreater(res, 0)

            self.assertEqual(len(call_log), 50)
            # Call 0 must start with replaces_id == 0
            self.assertEqual(call_log[0]["replaces_id"], 0)
            self.assertEqual(call_log[0]["returned_id"], 100)

            # Calls 1..49 must pass the previously returned ID
            for i in range(1, 50):
                expected_replaces = call_log[i - 1]["returned_id"]
                self.assertEqual(
                    call_log[i]["replaces_id"],
                    expected_replaces,
                    f"Call {i} passed replaces_id={call_log[i]['replaces_id']}, expected {expected_replaces}",
                )
                self.assertNotEqual(call_log[i]["replaces_id"], 0, f"Call {i} reverted replaces_id to 0!")

    @patch("dbus.service.BusName")
    @patch("dbus.SessionBus")
    @patch("tray.tray_app.SubDeckSNI")
    @patch("tray.tray_app.SubDeckDBusMenu")
    @patch("tray.tray_app.GLib.timeout_add")
    def test_notification_error_preserves_last_id_for_next_call(self, *mocks):
        """Temporary D-Bus error must NOT reset _last_notification_id to 0 for subsequent calls."""
        mock_session_bus = MagicMock()
        mock_notify_obj = MagicMock()
        mock_notify_iface = MagicMock()
        mock_session_bus.get_object.return_value = mock_notify_obj

        with patch("dbus.Interface", return_value=mock_notify_iface), \
             patch("tray.tray_app.SubDeckTrayApp._trigger_background_poll"):
            app = SubDeckTrayApp(MagicMock())
            app.session_bus = mock_session_bus

            # 1. Success call -> sets ID to 777
            mock_notify_iface.Notify.return_value = 777
            res1 = app._send_desktop_notification("Normal 1", "Body 1")
            self.assertEqual(res1, 777)
            self.assertEqual(app._last_notification_id, 777)

            # 2. Failing call -> D-Bus error
            mock_notify_iface.Notify.side_effect = RuntimeError("Temporary D-Bus failure")
            res2 = app._send_desktop_notification("Failing", "Body 2")
            self.assertEqual(res2, 0)
            self.assertEqual(app._last_notification_id, 777, "ID must remain 777 despite failure")

            # 3. Recovered call -> must STILL use replaces_id=777
            mock_notify_iface.Notify.side_effect = None
            mock_notify_iface.Notify.return_value = 778
            res3 = app._send_desktop_notification("Recovered", "Body 3")
            self.assertEqual(res3, 778)
            self.assertEqual(app._last_notification_id, 778)

            call_args = mock_notify_iface.Notify.call_args[0]
            self.assertEqual(int(call_args[1]), 777, "Recovered call must replace previous valid ID (777)")

    @patch("dbus.service.BusName")
    @patch("dbus.SessionBus")
    @patch("tray.tray_app.SubDeckSNI")
    @patch("tray.tray_app.SubDeckDBusMenu")
    @patch("tray.tray_app.GLib.timeout_add")
    def test_notification_constant_id_in_place_replacement(self, *mocks):
        """When notification daemon retains constant ID (KDE Plasma in-place update), ID tracks correctly."""
        mock_session_bus = MagicMock()
        mock_notify_obj = MagicMock()
        mock_notify_iface = MagicMock()
        mock_session_bus.get_object.return_value = mock_notify_obj
        mock_notify_iface.Notify.return_value = 42

        with patch("dbus.Interface", return_value=mock_notify_iface), \
             patch("tray.tray_app.SubDeckTrayApp._trigger_background_poll"):
            app = SubDeckTrayApp(MagicMock())
            app.session_bus = mock_session_bus

            for _ in range(20):
                res = app._send_desktop_notification("Status", "Message")
                self.assertEqual(res, 42)
                self.assertEqual(app._last_notification_id, 42)

            # Check that replaces_id sent was 42
            call_args = mock_notify_iface.Notify.call_args[0]
            self.assertEqual(int(call_args[1]), 42)


class TestLockRecoveryAfterTermination(unittest.TestCase):
    """Stress tests lock recovery when holder process terminates (cleanly or abruptly)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = os.environ.copy()
        self.env["XDG_RUNTIME_DIR"] = self.temp_dir.name
        self.cmd = [sys.executable, os.path.join(BASE_DIR, "tray", "tray_app.py")]

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_lock_recovery_after_sigkill(self):
        """When lock holder is killed with SIGKILL (signal 9), next instance must immediately acquire lock."""
        # 1. Start instance A
        p1 = subprocess.Popen(self.cmd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.5)
        self.assertIsNone(p1.poll(), "Instance A must be running and holding lock")

        # 2. Verify instance B cannot acquire lock
        p2 = subprocess.run(self.cmd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        self.assertEqual(p2.returncode, 0)
        self.assertIn("Another instance is already running", p2.stdout)

        # 3. Kill instance A with SIGKILL (ungraceful abort)
        p1.send_signal(signal.SIGKILL)
        p1.wait(timeout=3)
        self.assertIsNotNone(p1.poll())
        if p1.stdout: p1.stdout.close()
        if p1.stderr: p1.stderr.close()

        # 4. Immediately launch instance C -> must acquire lock
        p3 = subprocess.Popen(self.cmd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.5)
        self.assertIsNone(p3.poll(), "Instance C must acquire lock immediately after A was SIGKILLed")

        # 5. Verify instance D cannot acquire lock while C is running
        p4 = subprocess.run(self.cmd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        self.assertEqual(p4.returncode, 0)
        self.assertIn("Another instance is already running", p4.stdout)

        # Clean shutdown
        p3.terminate()
        p3.wait(timeout=3)
        if p3.stdout: p3.stdout.close()
        if p3.stderr: p3.stderr.close()

    def test_lock_recovery_after_sigterm(self):
        """When lock holder is terminated with SIGTERM, next instance must immediately acquire lock."""
        p1 = subprocess.Popen(self.cmd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.5)
        self.assertIsNone(p1.poll())

        p1.terminate()
        p1.wait(timeout=3)
        if p1.stdout: p1.stdout.close()
        if p1.stderr: p1.stderr.close()

        p2 = subprocess.Popen(self.cmd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.5)
        self.assertIsNone(p2.poll(), "Instance B must acquire lock after Instance A SIGTERM")

        p2.terminate()
        p2.wait(timeout=3)
        if p2.stdout: p2.stdout.close()
        if p2.stderr: p2.stderr.close()

    def test_rapid_kill_and_acquire_cycles(self):
        """Rapid 5-cycle stress: spawn -> acquire -> SIGKILL -> spawn successor -> verify acquire."""
        for cycle in range(5):
            proc = subprocess.Popen(self.cmd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            time.sleep(0.3)
            self.assertIsNone(proc.poll(), f"Cycle {cycle}: instance failed to acquire lock on start")

            proc.send_signal(signal.SIGKILL)
            proc.wait(timeout=3)
            self.assertIsNotNone(proc.poll(), f"Cycle {cycle}: instance failed to die on SIGKILL")
            if proc.stdout: proc.stdout.close()
            if proc.stderr: proc.stderr.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
