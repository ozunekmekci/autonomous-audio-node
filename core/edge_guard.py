import subprocess
import shutil
import json
import time
import threading
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from core.network import send_telegram_notification

def mute_all_audio():
    """Tüm cihaz seslerini ve bildirimlerini sıfırlar (Tam Sessizlik Protokolü)."""
    streams = ["ring", "notification", "system", "music", "call"]
    for s in streams:
        try:
            subprocess.run(["termux-volume", s, "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

class EdgeGuard:
    def __init__(self, poll_interval=30):
        self.poll_interval = poll_interval
        self.running = False
        self.thread = None
        self.was_listening_before_overheat = False
        self.last_ac_status = None  # None at init, then boolean
        self.overheat_active = False
        self.low_battery_stopped = False

    def get_battery_raw(self):
        try:
            res = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=3)
            return json.loads(res.stdout)
        except Exception:
            return {"percentage": 100, "status": "CHARGING", "plugged": "PLUGGED_AC", "temperature": 30.0}

    def get_disk_free_mb(self):
        try:
            target_dir = config.RECORDINGS_DIR if os.path.exists(config.RECORDINGS_DIR) else os.path.expanduser("~")
            usage = shutil.disk_usage(target_dir)
            return usage.free // (1024 * 1024)
        except Exception:
            return 99999

    def evaluate_status(self, battery_data, disk_free_mb, is_listening):
        pct = battery_data.get("percentage", 100)
        temp = battery_data.get("temperature", 30.0)
        plugged_val = battery_data.get("plugged", "")
        status_val = battery_data.get("status", "")
        plugged = (plugged_val in ["PLUGGED_AC", "PLUGGED_USB", "PLUGGED_WIRELESS"]) or (status_val == "CHARGING")

        # 1. AC Disconnect / Reconnect Check
        ac_changed = None
        if self.last_ac_status is not None:
            if self.last_ac_status and not plugged:
                ac_changed = "AC_DISCONNECTED"
                self.last_ac_status = False
            elif not self.last_ac_status and plugged:
                ac_changed = "AC_RECONNECTED"
                self.last_ac_status = True
        else:
            self.last_ac_status = plugged

        # 2. Disk Storage Check
        if disk_free_mb < 500:
            return {"action": "DISK_LOW_STOP", "ac_changed": ac_changed, "temp": temp, "pct": pct}

        # 3. Thermal Check
        if temp >= 46.0:
            if not self.overheat_active:
                self.overheat_active = True
                if is_listening:
                    self.was_listening_before_overheat = True
                return {"action": "THERMAL_STOP", "ac_changed": ac_changed, "temp": temp, "pct": pct}
        elif temp <= 38.0 and self.overheat_active:
            self.overheat_active = False
            if self.was_listening_before_overheat:
                self.was_listening_before_overheat = False
                return {"action": "THERMAL_RESUME", "ac_changed": ac_changed, "temp": temp, "pct": pct}
            return {"action": "THERMAL_NORMAL", "ac_changed": ac_changed, "temp": temp, "pct": pct}
        elif temp >= 43.0 and not self.overheat_active:
            return {"action": "THERMAL_WARN", "ac_changed": ac_changed, "temp": temp, "pct": pct}

        # 4. Critical Battery Check
        if pct <= 10 and not plugged:
            if not self.low_battery_stopped:
                self.low_battery_stopped = True
                return {"action": "CRITICAL_BATTERY_STOP", "ac_changed": ac_changed, "temp": temp, "pct": pct}
        elif pct > 10 and plugged:
            if self.low_battery_stopped:
                self.low_battery_stopped = False
                return {"action": "BATTERY_RECOVERED_STANDBY", "ac_changed": ac_changed, "temp": temp, "pct": pct}

        return {"action": "NONE", "ac_changed": ac_changed, "temp": temp, "pct": pct}

    def run_loop(self, is_listening_fn, stop_fn, start_fn):
        while self.running:
            b_data = self.get_battery_raw()
            disk_mb = self.get_disk_free_mb()
            listening = is_listening_fn()
            decision = self.evaluate_status(b_data, disk_mb, listening)

            # AC bildirimleri
            if decision["ac_changed"] == "AC_DISCONNECTED":
                send_telegram_notification(f"⚠️ <b>Şarj Aleti Kesildi!</b>\n🔋 Cihaz bataryadan çalışmaya devam ediyor (%{decision['pct']}).")
            elif decision["ac_changed"] == "AC_RECONNECTED":
                send_telegram_notification(f"⚡ <b>Şarj Aleti Takıldı!</b>\n🔋 Pil: %{decision['pct']} (Şarj ediliyor).")

            # Eylem bildirimleri ve tetikleyiciler
            act = decision["action"]
            if act == "CRITICAL_BATTERY_STOP":
                send_telegram_notification(f"🛑 <b>Kritik Pil (%{decision['pct']})!</b>\nDonanımı ve sistemi korumak için dinleme güvenle durduruldu, bekleme moduna geçildi.")
                stop_fn()
            elif act == "BATTERY_RECOVERED_STANDBY":
                send_telegram_notification(f"🟢 <b>Cihaz Yeterli Şarja Ulaştı (%{decision['pct']})!</b>\nSistem çevrimiçi. <i>Dinleme kapalıdır (onay bekleniyor).</i>")
            elif act == "THERMAL_WARN":
                send_telegram_notification(f"🌡️ <b>Sarı Alarm: Sıcaklık {decision['temp']:.1f}°C!</b>\nCihaz ısınıyor, izleniyor.")
            elif act == "THERMAL_STOP":
                send_telegram_notification(f"🔥 <b>Kırmızı Alarm: Sıcaklık {decision['temp']:.1f}°C!</b>\nAşırı ısınma nedeniyle dinleme acil durduruldu. 38°C'ye soğuyana kadar bekleniyor.")
                stop_fn()
            elif act == "THERMAL_RESUME":
                send_telegram_notification(f"🟢 <b>Sıcaklık Normale Döndü ({decision['temp']:.1f}°C)!</b>\nTermal hafıza devrede: Dinleme otomatik olarak kaldığı yerden başlatılıyor...")
                start_fn()
            elif act == "DISK_LOW_STOP":
                send_telegram_notification(f"💾 <b>Depolama Uyarısı:</b> Boş alan 500 MB'ın altına düştü! Veri kaybını önlemek için dinleme durduruldu.")
                stop_fn()

            time.sleep(self.poll_interval)

    def start(self, is_listening_fn, stop_fn, start_fn):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self.run_loop, args=(is_listening_fn, stop_fn, start_fn), daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
