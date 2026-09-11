import socket
import subprocess
import urllib.request
import urllib.parse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

def get_local_ip():
    """Cihazın yerel ağdaki (Wi-Fi) IP adresini tespit eder."""
    # 1. Yöntem: Dışarıya sahte UDP soketi açarak yerel interface IP'sini bulma (en hızlı & en güvenilir)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        # Gerçek bağlantı kurulmaz, sadece route edilen yerel interface seçilir
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass

    # 2. Yöntem: Termux 'ip route' çıktısını ayrıştırma
    try:
        res = subprocess.run(["ip", "route", "get", "1.1.1.1"], capture_output=True, text=True)
        for part in res.stdout.split():
            if part.count(".") == 3 and not part.startswith("127."):
                return part
    except Exception:
        pass

    return "127.0.0.1"

def send_telegram_notification(message):
    """Yapılandırılmışsa Telegram botu üzerinden yeni IP'yi gönderir."""
    if not getattr(config, "TELEGRAM_ENABLED", False):
        return False
    token = getattr(config, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(config, "TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": message, "parse_mode": "HTML"}).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[!] Telegram bildirim hatası: {e}")
        return False

if __name__ == "__main__":
    ip = get_local_ip()
    print(f"Tespit Edilen Yerel IP: {ip}")
