#!/bin/bash
# ==========================================
# 🎙️ Ortam Dinleme Düğümü - Başlatıcı
# ==========================================

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "⏳ Sistem arka planda başlatılıyor..."
termux-wake-lock 2>/dev/null || true

# Web sunucusunu başlat (eğer çalışmıyorsa)
if ! pgrep -f "web/server.py" > /dev/null; then
    nohup python3 -u web/server.py </dev/null >/dev/null 2>&1 &
    sleep 1
fi

# Dinlemeyi API üzerinden tetikle
curl -s -X POST http://127.0.0.1:8080/api/start | python3 -c "import sys, json; print(json.load(sys.stdin).get('message', 'Başlatıldı.'))" 2>/dev/null || true

IP=$(python3 -c "from core.network import get_local_ip; print(get_local_ip())" 2>/dev/null || echo "127.0.0.1")
echo "🟢 Web Kontrol Paneli: http://$IP:8080/"
