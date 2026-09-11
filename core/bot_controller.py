import os
import sys
import time
import json
import shutil
import urllib.request
import urllib.parse
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from core.edge_guard import mute_all_audio
from core.network import get_local_ip, get_battery_info
from core.dispatcher import send_telegram_voice

def is_authorized(sender_chat_id, allowed_chat_id):
    if sender_chat_id is None or allowed_chat_id is None:
        return False
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
                url = f"https://api.telegram.org/bot{token}/getUpdates?offset={self.last_update_id + 1}&timeout=15"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    for upd in data.get("result", []):
                        self.last_update_id = upd["update_id"]
                        msg = upd.get("message", {})
                        sender_id = msg.get("chat", {}).get("id")
                        text = msg.get("text", "")
                        if is_authorized(sender_id, allowed_chat_id) and text:
                            self.handle_command(sender_id, text)
            except Exception:
                time.sleep(3)

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self.poll_updates, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
