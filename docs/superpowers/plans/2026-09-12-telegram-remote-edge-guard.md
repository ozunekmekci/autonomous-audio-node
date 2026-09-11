# Telegram Remote Controller, Voice Dispatcher & Edge Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement automatic Telegram voice note uploads for recorded speech, a two-way touch-button Telegram remote controller, and an intelligent hardware/power watchdog (Edge Guard) with full silence mode for the Autonomous Audio Node.

**Architecture:** A multi-threaded architecture integrating a background hardware guard (`core/edge_guard.py`), an asynchronous audio uploader (`core/dispatcher.py`), and a long-polling Telegram command loop (`core/bot_controller.py`) coordinated with the HTTP daemon (`web/server.py`) and VAD engine (`core/vad_recorder.py`).

**Tech Stack:** Python 3.10+, Termux:API (`termux-volume`, `termux-battery-status`), Telegram Bot API (`sendVoice`, `sendMessage`, `getUpdates`), POSIX file operations, urllib/urllib3 multipart encoding.

**Spec:** `docs/superpowers/specs/2026-09-12-telegram-remote-edge-guard-design.md`

## Global Constraints
- Target platform: Android 15 (Termux), aarch64.
- Audio format: 48 kHz AAC M4A (`ddaayyyy_saat_dakika_N.m4a`).
- Security whitelist: Telegram commands strictly accepted ONLY from `chat_id: 6444855403`.
- Edge Guard thresholds: Low battery cut-off at <= 10%, thermal warning at >= 43°C, thermal stop at >= 46°C, thermal resume at <= 38°C, disk limit at < 500 MB.
- Silence mode: Mute all streams (`ring`, `notification`, `system`, `music`, `call`) on listening start.
- Power recovery: On reconnecting AC power (> 10%), node wakes up with listening mode explicitly OFF (standby).

---

### Task 1: Silence Protocol & Edge Guard (`core/edge_guard.py`)

**Files:**
- Create: `core/edge_guard.py`
- Test: `tests/test_edge_guard.py`

**Interfaces:**
- Consumes: `core.network.get_battery_info()`, `core.network.send_telegram_notification()`
- Produces: `mute_all_audio()`, `start_edge_guard()`, `stop_edge_guard()`, `get_hardware_health()`

- [ ] **Step 1: Write unit tests for silence protocol and edge guard logic**

```python
# tests/test_edge_guard.py
import unittest
from unittest.mock import patch, MagicMock
from core.edge_guard import EdgeGuard, mute_all_audio

class TestEdgeGuard(unittest.TestCase):
    @patch("subprocess.run")
    def test_mute_all_audio(self, mock_run):
        mute_all_audio()
        self.assertEqual(mock_run.call_count, 5)

    def test_battery_decision_critical(self):
        guard = EdgeGuard(poll_interval=1)
        # Mock battery <= 10%
        battery_data = {"percentage": 9, "status": "DISCHARGING", "plugged": "UNPLUGGED", "temperature": 32.0}
        decision = guard.evaluate_status(battery_data, disk_free_mb=2000, is_listening=True)
        self.assertEqual(decision["action"], "CRITICAL_BATTERY_STOP")

    def test_thermal_decision_overheat_and_resume(self):
        guard = EdgeGuard(poll_interval=1)
        # 46°C -> emergency stop
        battery_data = {"percentage": 80, "status": "CHARGING", "plugged": "PLUGGED_AC", "temperature": 46.5}
        decision = guard.evaluate_status(battery_data, disk_free_mb=2000, is_listening=True)
        self.assertEqual(decision["action"], "THERMAL_STOP")
        self.assertTrue(guard.was_listening_before_overheat)

        # 37°C -> resume
        battery_data_cool = {"percentage": 80, "status": "CHARGING", "plugged": "PLUGGED_AC", "temperature": 37.0}
        decision_cool = guard.evaluate_status(battery_data_cool, disk_free_mb=2000, is_listening=False)
        self.assertEqual(decision_cool["action"], "THERMAL_RESUME")

    def test_disk_low(self):
        guard = EdgeGuard(poll_interval=1)
        battery_data = {"percentage": 80, "status": "CHARGING", "plugged": "PLUGGED_AC", "temperature": 34.0}
        decision = guard.evaluate_status(battery_data, disk_free_mb=400, is_listening=True)
        self.assertEqual(decision["action"], "DISK_LOW_STOP")
```

- [ ] **Step 2: Run tests to verify they fail**
Run: `python3 -m unittest tests/test_edge_guard.py`
Expected: FAIL (ImportError: No module named 'core.edge_guard')

- [ ] **Step 3: Implement `core/edge_guard.py`**

```python
# core/edge_guard.py
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
    """Tüm cihaz seslerini ve bildirimlerini sıfırlar."""
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
        self.last_ac_status = True  # True if plugged
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
            usage = shutil.disk_usage(config.RECORDINGS_DIR)
            return usage.free // (1024 * 1024)
        except Exception:
            return 99999

    def evaluate_status(self, battery_data, disk_free_mb, is_listening):
        pct = battery_data.get("percentage", 100)
        temp = battery_data.get("temperature", 30.0)
        plugged = "PLUGGED" in battery_data.get("plugged", "") or "CHARGING" in battery_data.get("status", "")

        # 1. AC Disconnect / Reconnect Check
        ac_changed = None
        if self.last_ac_status and not plugged:
            ac_changed = "AC_DISCONNECTED"
            self.last_ac_status = False
        elif not self.last_ac_status and plugged:
            ac_changed = "AC_RECONNECTED"
            self.last_ac_status = True

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
```

- [ ] **Step 4: Run unit tests to verify they pass**
Run: `python3 -m unittest tests/test_edge_guard.py`
Expected: PASS (4 tests passed)

- [ ] **Step 5: Commit**
```bash
git add core/edge_guard.py tests/test_edge_guard.py
git commit -m "feat(edge-guard): add hardware power, thermal, storage guard and silence protocol"
```

---

### Task 2: Audio Dispatcher for Telegram (`core/dispatcher.py`)

**Files:**
- Create: `core/dispatcher.py`
- Test: `tests/test_dispatcher.py`

**Interfaces:**
- Consumes: `config.TELEGRAM_BOT_TOKEN`, `config.TELEGRAM_CHAT_ID`
- Produces: `dispatch_voice(file_path)`

- [ ] **Step 1: Write unit tests for audio dispatcher**

```python
# tests/test_dispatcher.py
import unittest
from unittest.mock import patch, MagicMock
from core.dispatcher import build_multipart_voice, get_audio_duration_sec

class TestDispatcher(unittest.TestCase):
    def test_multipart_builder(self):
        body, content_type = build_multipart_voice(
            chat_id="12345",
            caption="Test Caption",
            file_bytes=b"FAKE_AUDIO",
            filename="test.m4a"
        )
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        self.assertIn(b"12345", body)
        self.assertIn(b"Test Caption", body)
        self.assertIn(b"FAKE_AUDIO", body)
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python3 -m unittest tests/test_dispatcher.py`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement `core/dispatcher.py`**

```python
# core/dispatcher.py
import os
import sys
import time
import subprocess
import urllib.request
import uuid
import threading
import queue

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

_dispatch_queue = queue.Queue()
_worker_thread = None
_running = False

def get_audio_duration_sec(filepath):
    """FFmpeg / ffprobe kullanarak ses süresini alır."""
    try:
        res = subprocess.run(
            ["ffmpeg", "-i", filepath],
            stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True
        )
        for line in res.stderr.split("\n"):
            if "Duration:" in line:
                dur_str = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = dur_str.split(":")
                return round(float(h) * 3600 + float(m) * 60 + float(s), 1)
    except Exception:
        pass
    return 0.0

def build_multipart_voice(chat_id, caption, file_bytes, filename):
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    parts = []
    
    # chat_id
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode("utf-8"))
    # caption
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode("utf-8"))
    # parse_mode
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"parse_mode\"\r\n\r\nHTML\r\n".encode("utf-8"))
    # voice file
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"voice\"; filename=\"{filename}\"\r\nContent-Type: audio/mp4\r\n\r\n".encode("utf-8"))
    parts.append(file_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    return b"".join(parts), f"multipart/form-data; boundary={boundary}"

def send_telegram_voice(filepath):
    token = getattr(config, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(config, "TELEGRAM_CHAT_ID", "")
    if not token or not chat_id or not os.path.exists(filepath):
        return False

    filename = os.path.basename(filepath)
    size_kb = round(os.path.getsize(filepath) / 1024, 1)
    dur = get_audio_duration_sec(filepath)
    ts = time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(os.path.getmtime(filepath)))

    caption = (
        f"🎙️ <b>Yeni Konuşma Kaydedildi</b>\n"
        f"📅 <code>{ts}</code>\n"
        f"⏱️ <b>Süre:</b> {dur} sn | 💾 <b>Boyut:</b> {size_kb} KB"
    )

    try:
        with open(filepath, "rb") as f:
            file_bytes = f.read()

        body, content_type = build_multipart_voice(chat_id, caption, file_bytes, filename)
        url = f"https://api.telegram.org/bot{token}/sendVoice"
        req = urllib.request.Request(url, data=body, headers={"Content-Type": content_type})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[!] Telegram ses gönderme hatası: {e}")
        return False

def _queue_worker():
    while _running:
        try:
            filepath = _dispatch_queue.get(timeout=2)
        except queue.Empty:
            continue

        success = send_telegram_voice(filepath)
        if not success:
            # Başarısız olursa 5 sn sonra yeniden denemek için kuyruğa geri koy
            time.sleep(5)
            _dispatch_queue.put(filepath)
        else:
            _dispatch_queue.task_done()

def dispatch_voice(filepath):
    """Yeni ses dosyasını Telegram yükleme kuyruğuna ekler."""
    global _worker_thread, _running
    if not getattr(config, "TELEGRAM_ENABLED", False):
        return
    if not _running:
        _running = True
        _worker_thread = threading.Thread(target=_queue_worker, daemon=True)
        _worker_thread.start()
    _dispatch_queue.put(filepath)
```

- [ ] **Step 4: Run unit tests to verify they pass**
Run: `python3 -m unittest tests/test_dispatcher.py`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add core/dispatcher.py tests/test_dispatcher.py
git commit -m "feat(dispatcher): add asynchronous telegram voice note uploader"
```

---

### Task 3: Two-Way Telegram Bot Controller (`core/bot_controller.py`)

**Files:**
- Create: `core/bot_controller.py`
- Test: `tests/test_bot_controller.py`

**Interfaces:**
- Consumes: `config.TELEGRAM_BOT_TOKEN`, `config.TELEGRAM_CHAT_ID`, `web.server.start_vad_service()`, `web.server.stop_vad_service()`
- Produces: `start_bot_controller()`, `stop_bot_controller()`

- [ ] **Step 1: Write unit tests for command parsing and whitelist security**

```python
# tests/test_bot_controller.py
import unittest
from core.bot_controller import is_authorized, get_reply_keyboard_markup

class TestBotController(unittest.TestCase):
    def test_whitelist_authorization(self):
        self.assertTrue(is_authorized("6444855403", "6444855403"))
        self.assertFalse(is_authorized("9999999999", "6444855403"))

    def test_keyboard_markup_structure(self):
        kb = get_reply_keyboard_markup()
        self.assertIn("keyboard", kb)
        self.assertEqual(len(kb["keyboard"]), 2)
        self.assertEqual(len(kb["keyboard"][0]), 2)
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python3 -m unittest tests/test_bot_controller.py`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement `core/bot_controller.py`**

```python
# core/bot_controller.py
import os
import sys
import time
import json
import urllib.request
import urllib.parse
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from core.edge_guard import mute_all_audio
from core.network import get_local_ip, get_battery_info
from core.dispatcher import send_telegram_voice

def is_authorized(sender_chat_id, allowed_chat_id):
    return str(sender_chat_id).strip() == str(allowed_chat_id).strip()

def get_reply_keyboard_markup():
    return {
        "keyboard": [
            [{"text": "▶ Dinlemeyi Başlat"}, {"text": "⏹ Dinlemeyi Durdur"}],
            [{"text": "📊 Canlı Durum / Pil"}, {"text": "🎙️ Son Kaydı Gönder"}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }

def send_bot_reply(chat_id, text, with_keyboard=True):
    token = getattr(config, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        return
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if with_keyboard:
        payload["reply_markup"] = json.dumps(get_reply_keyboard_markup())

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[!] Bot mesaj gönderme hatası: {e}")

class BotController:
    def __init__(self, start_vad_fn, stop_vad_fn, is_vad_running_fn, is_mic_fn):
        self.start_vad_fn = start_vad_fn
        self.stop_vad_fn = stop_vad_fn
        self.is_vad_running_fn = is_vad_running_fn
        self.is_mic_fn = is_mic_fn
        self.running = False
        self.thread = None
        self.last_update_id = 0

    def handle_command(self, chat_id, text):
        cmd = text.strip()

        if cmd in ["/start", "/yardim", "yardım"]:
            msg = (
                "👋 <b>Autonomous Audio Node Kumandasına Hoş Geldiniz!</b>\n\n"
                "Aşağıdaki butonları kullanarak ortam dinleme düğümünüzü dilediğiniz yerden yönetebilirsiniz:"
            )
            send_bot_reply(chat_id, msg)

        elif cmd in ["▶ Dinlemeyi Başlat", "/dinle", "dinle"]:
            mute_all_audio()
            ok, msg = self.start_vad_fn()
            reply = f"🟢 <b>{msg}</b>\n<i>Tüm cihaz sesleri ve bildirimler sessize alındı.</i>" if ok else f"⚠️ <b>Hata:</b> {msg}"
            send_bot_reply(chat_id, reply)

        elif cmd in ["⏹ Dinlemeyi Durdur", "/dur", "dur"]:
            ok, msg = self.stop_vad_fn()
            reply = f"🔴 <b>{msg}</b>" if ok else f"⚠️ <b>Hata:</b> {msg}"
            send_bot_reply(chat_id, reply)

        elif cmd in ["📊 Canlı Durum / Pil", "/durum", "durum"]:
            running = self.is_vad_running_fn()
            mic = self.is_mic_fn()
            ip = get_local_ip()
            battery = get_battery_info()
            
            # Kayıt sayısı ve depolama
            recs = [f for f in os.listdir(config.RECORDINGS_DIR) if f.endswith(".m4a")] if os.path.exists(config.RECORDINGS_DIR) else []
            free_gb = round(shutil.disk_usage(config.RECORDINGS_DIR).free / (1024**3), 1) if os.path.exists(config.RECORDINGS_DIR) else 0

            status_card = (
                "📊 <b>Autonomous Audio Node Durumu</b>\n"
                "─────────────────────────\n"
                f"🎙️ <b>Mikrofon:</b> {'🟢 Kayıtta' if mic else '🔴 Kapalı'}\n"
                f"⚙️ <b>VAD Motoru:</b> {'🟢 Aktif' if running else '🔴 Durduruldu'}\n"
                f"🔋 <b>Pil:</b> {battery}\n"
                f"💾 <b>Boş Hafıza:</b> {free_gb} GB\n"
                f"📁 <b>Toplam Kayıt:</b> {len(recs)} adet\n"
                "─────────────────────────\n"
                f"🌐 <b>Web:</b> http://{ip}:{config.PORT}/\n"
                f"🌐 <b>mDNS:</b> http://{config.HOSTNAME}:{config.PORT}/"
            )
            send_bot_reply(chat_id, status_card)

        elif cmd in ["🎙️ Son Kaydı Gönder", "/sonkayit", "sonkayıt"]:
            if not os.path.exists(config.RECORDINGS_DIR):
                send_bot_reply(chat_id, "⚠️ Kayıt klasörü bulunamadı.")
                return
            recs = [f for f in os.listdir(config.RECORDINGS_DIR) if f.endswith(".m4a")]
            if not recs:
                send_bot_reply(chat_id, "⚠️ Henüz kaydedilmiş ses dosyası yok.")
                return
            recs.sort(key=lambda x: os.path.getmtime(os.path.join(config.RECORDINGS_DIR, x)), reverse=True)
            latest = os.path.join(config.RECORDINGS_DIR, recs[0])
            send_bot_reply(chat_id, f"⏳ Son ses gönderiliyor: <code>{recs[0]}</code>...")
            send_telegram_voice(latest)

    def poll_updates(self):
        token = getattr(config, "TELEGRAM_BOT_TOKEN", "")
        allowed_chat_id = getattr(config, "TELEGRAM_CHAT_ID", "")
        if not token or not allowed_chat_id:
            return

        while self.running:
            try:
                url = f"https://api.telegram.org/bot{token}/getUpdates?offset={self.last_update_id + 1}&timeout=20"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    for upd in data.get("result", []):
                        self.last_update_id = upd["update_id"]
                        msg = upd.get("message", {})
                        sender_id = msg.get("chat", {}).get("id")
                        text = msg.get("text", "")
                        if is_authorized(sender_id, allowed_chat_id) and text:
                            self.handle_command(sender_id, text)
            except Exception:
                time.sleep(5)

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self.poll_updates, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
```

- [ ] **Step 4: Run unit tests to verify they pass**
Run: `python3 -m unittest tests/test_bot_controller.py`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add core/bot_controller.py tests/test_bot_controller.py
git commit -m "feat(bot-controller): add interactive touch-button telegram remote controller"
```

---

### Task 4: Server & VAD Engine Integration (`web/server.py` & `core/vad_recorder.py`)

**Files:**
- Modify: `core/vad_recorder.py`
- Modify: `web/server.py`

**Interfaces:**
- Wire `dispatch_voice()` in `core/vad_recorder.py:extract_speech_atomic`
- Wire `EdgeGuard` and `BotController` into `web/server.py:main`

- [ ] **Step 1: Update `core/vad_recorder.py` to trigger `dispatch_voice` on new recording**
- [ ] **Step 2: Update `web/server.py` to launch EdgeGuard & BotController on server boot and silence device on start**
- [ ] **Step 3: Run regression tests on whole test suite**
Run: `python3 -m unittest discover -s tests`
Expected: ALL PASS

- [ ] **Step 4: Commit**
```bash
git add core/vad_recorder.py web/server.py
git commit -m "feat(integration): wire edge guard, telegram dispatcher, and bot controller into server and vad"
```

---

### Task 5: Live Deployment & Remote Verification on Android Phone

**Files:**
- Sync: `core/`, `web/`, `config.py` to `192.168.1.38:~/autonomous-audio-node/`
- Documentation: Update `README.md` and `docs/`

- [ ] **Step 1: SCP all updated files to phone**
- [ ] **Step 2: Restart web server and background daemons on phone**
- [ ] **Step 3: Verify Telegram touch buttons display in @Kulak_znbot**
- [ ] **Step 4: Test button clicks: `[▶ Dinlemeyi Başlat]`, `[📊 Canlı Durum / Pil]`, `[⏹ Dinlemeyi Durdur]`**
- [ ] **Step 5: Perform speech test and verify automatic voice note delivery in Telegram**
- [ ] **Step 6: Git commit, push all changes, and update walkthrough artifact**
