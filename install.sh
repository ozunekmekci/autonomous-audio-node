#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# 🎙️ OTONOM ORTAM DİNLEME VE ANALİZ DÜĞÜMÜ (AUTONOMOUS AUDIO NODE)
# Tek Komutla Otomatik Kurulum Betiği
# ==============================================================================
set -e

echo ""
echo "============================================================"
echo "  🎙️  OTONOM ORTAM DİNLEME DÜĞÜMÜ KURULUMU BAŞLIYOR...     "
echo "============================================================"
echo ""

# 1. Gerekli Paketlerin Kurulumu
echo "[1/5] Paket havuzu güncelleniyor ve bağımlılıklar kuruluyor..."
pkg update -y
pkg install -y python ffmpeg termux-api git clang
pip install zeroconf || echo "[!] zeroconf kurulamadı, mDNS devre dışı kalabilir fakat sistem çalışmaya devam edecektir."


# 2. İzinler ve Güç Yönetimi
echo "[2/5] Android arka plan güç kilidi (Wake-Lock) aktif ediliyor..."
termux-wake-lock || true

# 3. Klasör Yapısının Hazırlanması
echo "[3/5] Kayıt ve geçici dosya dizinleri hazırlanıyor..."
mkdir -p ~/recordings ~/vad_temp

# 4. Termux Kısayollarının (~/.bashrc) Tanımlanması
echo "[4/5] Hızlı terminal komutları (~/.bashrc) yapılandırılıyor..."
BASHRC="$HOME/.bashrc"
touch "$BASHRC"

# Eski alias varsa temizle
sed -i '/autonomous-audio-node/d' "$BASHRC" 2>/dev/null || true
sed -i '/alias dinle=/d' "$BASHRC" 2>/dev/null || true
sed -i '/alias dur=/d' "$BASHRC" 2>/dev/null || true
sed -i '/alias durum=/d' "$BASHRC" 2>/dev/null || true

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cat << EOF >> "$BASHRC"
# --- Autonomous Audio Node Kısayolları ---
alias dinle='$PROJECT_DIR/start.sh'
alias dur='$PROJECT_DIR/stop.sh'
alias durum='curl -s http://127.0.0.1:8080/api/status | python3 -c "import sys,json; d=json.load(sys.stdin); print(\"Durum:\", \"🟢 AKTİF\" if d.get(\"running\") else \"🔴 KAPALI\", \"| Mikrofon:\", \"🟢 Kayıtta\" if d.get(\"mic\") else \"🔴 Kapalı\", \"| Kayıt:\", len(d.get(\"recordings\", [])))"'
EOF

# Betiklere çalıştırma izni ver
chmod +x "$PROJECT_DIR/start.sh" "$PROJECT_DIR/stop.sh" 2>/dev/null || true

# 5. Web Kontrol Sunucusunun Başlatılması
echo "[5/5] Kontrol sunucusu arka planda başlatılıyor..."
pkill -f "web/server.py" 2>/dev/null || true
nohup python3 -u "$PROJECT_DIR/web/server.py" </dev/null >/dev/null 2>&1 &
sleep 2

# IP Tespiti
IP=$(python3 -c "import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('8.8.8.8', 80)); print(s.getsockname()[0]); s.close()" 2>/dev/null || echo "127.0.0.1")

echo ""
echo "============================================================"
echo "  ✅ KURULUM BAŞARIYLA TAMAMLANDI!                         "
echo "============================================================"
echo ""
echo "🌐 Web Kontrol Paneli:  http://$IP:8080/"
echo "🌐 mDNS Bağlantısı:     http://kulak.local:8080/"
echo ""
echo "📲 Terminal Komutları:"
echo "   dinle  -> Dinlemeyi başlatır (ekran kapalıyken de dinler)"
echo "   dur    -> Mikrofonu tamamen kapatır ve durdurur"
echo "   durum  -> Canlı durumu görüntüler"
echo ""
echo "İpucu: Tarayıcından http://$IP:8080/ adresini açıp 'BAŞLAT' butonuna basabilirsin."
echo "============================================================"
echo ""
