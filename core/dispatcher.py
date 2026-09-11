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
                parts = dur_str.split(":")
                if len(parts) == 3:
                    h, m, s = parts
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
    """Verilen ses dosyasını Telegram'a sesli mesaj olarak yükler."""
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
