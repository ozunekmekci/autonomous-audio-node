import os
import sys
import time
import json
import mimetypes
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# Üst dizini sys.path'e ekle
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import config
from core.network import get_local_ip, send_telegram_notification, start_mdns, stop_mdns

os.makedirs(config.RECORDINGS_DIR, exist_ok=True)
os.makedirs(config.TEMP_DIR, exist_ok=True)

VAD_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "core", "vad_recorder.py")

def is_vad_running():
    try:
        res = subprocess.run(["pgrep", "-f", "core/vad_recorder.py"], capture_output=True, text=True)
        return res.returncode == 0 and len(res.stdout.strip()) > 0
    except Exception:
        return False

def is_mic_recording():
    try:
        res = subprocess.run(["termux-microphone-record", "-i"], capture_output=True, text=True)
        data = json.loads(res.stdout)
        return data.get("isRecording", False)
    except Exception:
        return False

def start_vad_service():
    if is_vad_running():
        return True, "Dinleme zaten aktif."
    
    try:
        subprocess.run(["termux-wake-lock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([
            "termux-notification", "--id", "vad-node",
            "--title", "Ortam Dinleme Düğümü",
            "--content", "Aktif: Sürekli Dinleniyor... 🟢",
            "--ongoing"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        with open(config.LOG_FILE, "a") as log_f:
            subprocess.Popen(
                ["python3", "-u", VAD_SCRIPT_PATH],
                stdout=log_f, stderr=log_f,
                start_new_session=True
            )
        time.sleep(1.0)
        
        # Opsiyonel Telegram bildirimi
        local_ip = get_local_ip()
        send_telegram_notification(
            f"🎙️ <b>Ortam Dinleme Düğümü Başlatıldı!</b>\n"
            f"🟢 <b>Durum:</b> Aktif Dinlemede\n"
            f"🌐 <b>Web Paneli:</b> http://{local_ip}:{config.PORT}/"
        )
        return True, "Dinleme başarıyla başlatıldı. Mikrofon aktif 🟢"
    except Exception as e:
        return False, f"Başlatma hatası: {e}"

def stop_vad_service():
    try:
        subprocess.run(["pkill", "-f", "core/vad_recorder.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["termux-microphone-record", "-q"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["termux-notification-remove", "vad-node"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        time.sleep(0.5)
        running = is_vad_running()
        mic = is_mic_recording()
        
        if not running and not mic:
            send_telegram_notification("🛑 <b>Ortam Dinleme Düğümü Durduruldu.</b>\n🔴 Mikrofon kapatıldı.")
            return True, "Dinleme durduruldu. Mikrofon tamamen KAPATILDI 🔴"
        else:
            return False, "Durdurma uyarısı: Bazı süreçler askıda kalmış olabilir."
    except Exception as e:
        return False, f"Durdurma hatası: {e}"

def get_recordings_list():
    recordings = []
    try:
        for f in os.listdir(config.RECORDINGS_DIR):
            if f.endswith(".m4a") or f.endswith(".opus"):
                fp = os.path.join(config.RECORDINGS_DIR, f)
                st = os.stat(fp)
                recordings.append({
                    "name": f,
                    "size_kb": round(st.st_size / 1024, 1),
                    "modified": time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(st.st_mtime)),
                    "timestamp": st.st_mtime
                })
        recordings.sort(key=lambda x: x["timestamp"], reverse=True)
    except Exception:
        pass
    return recordings

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎙️ Ortam Dinleme Düğümü</title>
    <style>
        :root {
            --bg: #0b0f19;
            --card-bg: #151d30;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --primary: #38bdf8;
            --success: #10b981;
            --danger: #ef4444;
            --border: #263352;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); padding: 20px 16px; max-width: 750px; margin: 0 auto; line-height: 1.5; }
        header { text-align: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
        h1 { font-size: 1.4rem; font-weight: 700; margin-bottom: 8px; color: #fff; }
        .ip-info { font-size: 0.85rem; color: var(--text-muted); margin-bottom: 12px; }
        .badge { display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: 9999px; font-weight: 600; font-size: 0.85rem; }
        .badge.active { background: rgba(16, 185, 129, 0.15); color: var(--success); border: 1px solid var(--success); }
        .badge.inactive { background: rgba(239, 68, 68, 0.15); color: var(--danger); border: 1px solid var(--danger); }
        .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
        .badge.active .dot { background: var(--success); box-shadow: 0 0 10px var(--success); animation: pulse 2s infinite; }
        .badge.inactive .dot { background: var(--danger); }
        @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(1.3); } }
        .controls { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 24px; }
        button { cursor: pointer; padding: 14px; font-size: 0.95rem; font-weight: 700; border: none; border-radius: 10px; transition: all 0.2s; display: flex; align-items: center; justify-content: center; gap: 8px; }
        button:disabled { opacity: 0.4; cursor: not-allowed; }
        .btn-start { background: var(--success); color: white; }
        .btn-start:hover:not(:disabled) { background: #059669; }
        .btn-stop { background: var(--danger); color: white; }
        .btn-stop:hover:not(:disabled) { background: #dc2626; }
        .card { background: var(--card-bg); border-radius: 12px; padding: 18px; border: 1px solid var(--border); }
        .card-header { font-size: 1.05rem; font-weight: 600; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; }
        .file-list { display: flex; flex-direction: column; gap: 10px; }
        .file-item { background: #0b0f19; border: 1px solid var(--border); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
        .file-meta { display: flex; justify-content: space-between; font-size: 0.8rem; color: var(--text-muted); font-weight: 500; }
        .file-name { font-weight: 600; color: var(--primary); word-break: break-all; }
        audio { width: 100%; height: 34px; border-radius: 6px; outline: none; margin-top: 4px; }
        .empty-msg { text-align: center; color: var(--text-muted); padding: 24px; font-size: 0.9rem; }
        #toast { position: fixed; bottom: 20px; right: 20px; left: 20px; max-width: 400px; margin: 0 auto; background: #1e293b; color: white; border: 1px solid var(--border); padding: 12px 18px; border-radius: 8px; display: none; z-index: 1000; box-shadow: 0 6px 16px rgba(0,0,0,0.5); text-align: center; font-size: 0.9rem; }
    </style>
</head>
<body>
    <header>
        <h1>🎙️ Ortam Dinleme Düğümü</h1>
        <div class="ip-info" id="ipDisplay">Yerel IP: Tespit ediliyor...</div>
        <div id="statusBadge" class="badge inactive">
            <span class="dot"></span>
            <span id="statusText">DURUM: KAPALI (DİNLENMİYOR)</span>
        </div>
    </header>

    <div class="controls">
        <button id="btnStart" class="btn-start" onclick="toggleService('start')">
            ▶ DİNLEMEYİ BAŞLAT
        </button>
        <button id="btnStop" class="btn-stop" onclick="toggleService('stop')">
            ⏹ DİNLEMEYİ DURDUR
        </button>
    </div>

    <div class="card">
        <div class="card-header">
            <span>📁 Kaydedilen Konuşma Blokları</span>
            <span id="fileCount" style="font-size: 0.85rem; color: var(--text-muted);">0 dosya</span>
        </div>
        <div id="fileList" class="file-list">
            <div class="empty-msg">Henüz kayıt yok. Konuşma olduğunda otomatik buraya gelecektir.</div>
        </div>
    </div>

    <div id="toast"></div>

    <script>
        function showToast(msg) {
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.style.display = 'block';
            setTimeout(() => { t.style.display = 'none'; }, 3000);
        }

        async function updateStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                document.getElementById('ipDisplay').innerText = 'Düğüm Adresi: ' + data.ip + ' (' + window.location.host + ')';

                const badge = document.getElementById('statusBadge');
                const statusText = document.getElementById('statusText');
                const btnStart = document.getElementById('btnStart');
                const btnStop = document.getElementById('btnStop');
                
                if (data.running) {
                    badge.className = 'badge active';
                    statusText.innerText = 'DURUM: AKTİF (DİNLİYOR 🟢)';
                    btnStart.disabled = true;
                    btnStop.disabled = false;
                } else {
                    badge.className = 'badge inactive';
                    statusText.innerText = 'DURUM: KAPALI (DİNLENMİYOR 🔴)';
                    btnStart.disabled = false;
                    btnStop.disabled = true;
                }

                const list = document.getElementById('fileList');
                document.getElementById('fileCount').innerText = data.recordings.length + ' dosya';
                
                if (data.recordings.length === 0) {
                    list.innerHTML = '<div class="empty-msg">Henüz kayıt yok. Konuşma olduğunda otomatik buraya gelecektir.</div>';
                } else {
                    list.innerHTML = data.recordings.map(f => `
                        <div class="file-item">
                            <div class="file-meta">
                                <span class="file-name">${f.name}</span>
                                <span>${f.size_kb} KB • ${f.modified}</span>
                            </div>
                            <audio controls preload="none">
                                <source src="/recordings/${f.name}" type="audio/mp4">
                                Tarayıcınız ses oynatmayı desteklemiyor.
                            </audio>
                        </div>
                    `).join('');
                }
            } catch (err) {
                console.error('Status error:', err);
            }
        }

        async function toggleService(action) {
            const btn = action === 'start' ? document.getElementById('btnStart') : document.getElementById('btnStop');
            btn.disabled = true;
            try {
                const res = await fetch('/api/' + action, { method: 'POST' });
                const data = await res.json();
                showToast(data.message);
                await updateStatus();
            } catch (err) {
                showToast('Hata: Sunucuya ulaşılamadı');
            }
        }

        setInterval(updateStatus, 3000);
        updateStatus();
    </script>
</body>
</html>
"""

class ControlHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
            return

        elif parsed.path == "/api/status":
            status_data = {
                "running": is_vad_running(),
                "mic": is_mic_recording(),
                "ip": get_local_ip(),
                "recordings": get_recordings_list()
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(status_data).encode("utf-8"))
            return

        elif parsed.path.startswith("/recordings/"):
            filename = os.path.basename(parsed.path)
            filepath = os.path.join(config.RECORDINGS_DIR, filename)
            
            if os.path.exists(filepath) and os.path.isfile(filepath):
                self.send_response(200)
                mime = "audio/mp4" if filename.endswith(".m4a") else "audio/ogg"
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(os.path.getsize(filepath)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                
                with open(filepath, "rb") as f:
                    while chunk := f.read(65536):
                        self.wfile.write(chunk)
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        
        if parsed.path == "/api/start":
            ok, msg = start_vad_service()
            self.send_response(200 if ok else 500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": ok, "message": msg}).encode("utf-8"))
            return

        elif parsed.path == "/api/stop":
            ok, msg = stop_vad_service()
            self.send_response(200 if ok else 500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": ok, "message": msg}).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

def main():
    ip = get_local_ip()
    print(f"[*] Kontrol Paneli ve HTTP Sunucusu Başlatıldı.")
    print(f"    --> Yerel Ağ Bağlantısı: http://{ip}:{config.PORT}/")
    print(f"    --> mDNS Bağlantısı: http://{config.HOSTNAME}:{config.PORT}/")
    
    # mDNS yayını başlat (kulak.local)
    start_mdns(config.HOSTNAME, config.PORT)
    
    server = HTTPServer(("0.0.0.0", config.PORT), ControlHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_mdns()
        server.server_close()

if __name__ == "__main__":
    main()
