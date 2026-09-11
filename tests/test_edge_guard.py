import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.edge_guard import EdgeGuard, mute_all_audio

class TestEdgeGuard(unittest.TestCase):
    @patch("subprocess.run")
    def test_mute_all_audio(self, mock_run):
        mute_all_audio()
        self.assertEqual(mock_run.call_count, 5)

    def test_battery_decision_critical(self):
        guard = EdgeGuard(poll_interval=1)
        battery_data = {"percentage": 9, "status": "DISCHARGING", "plugged": "UNPLUGGED", "temperature": 32.0}
        decision = guard.evaluate_status(battery_data, disk_free_mb=2000, is_listening=True)
        self.assertEqual(decision["action"], "CRITICAL_BATTERY_STOP")

    def test_thermal_decision_overheat_and_resume(self):
        guard = EdgeGuard(poll_interval=1)
        # 46.5°C -> Emergency stop
        battery_data = {"percentage": 80, "status": "CHARGING", "plugged": "PLUGGED_AC", "temperature": 46.5}
        decision = guard.evaluate_status(battery_data, disk_free_mb=2000, is_listening=True)
        self.assertEqual(decision["action"], "THERMAL_STOP")
        self.assertTrue(guard.was_listening_before_overheat)

        # 37.0°C -> Safe resume
        battery_data_cool = {"percentage": 80, "status": "CHARGING", "plugged": "PLUGGED_AC", "temperature": 37.0}
        decision_cool = guard.evaluate_status(battery_data_cool, disk_free_mb=2000, is_listening=False)
        self.assertEqual(decision_cool["action"], "THERMAL_RESUME")

    def test_disk_low(self):
        guard = EdgeGuard(poll_interval=1)
        battery_data = {"percentage": 80, "status": "CHARGING", "plugged": "PLUGGED_AC", "temperature": 34.0}
        decision = guard.evaluate_status(battery_data, disk_free_mb=400, is_listening=True)
        self.assertEqual(decision["action"], "DISK_LOW_STOP")

if __name__ == "__main__":
    unittest.main()
