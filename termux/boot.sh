#!/data/data/com.termux/files/usr/bin/bash
# ==========================================
# Termux:Boot Başlatıcı Betiği
# Cihaz şarja takılıp açıldığında otomatik başlar
# ==========================================

# Sistemin ağ bağlantısını bekle
sleep 10

DIR="$HOME/autonomous-audio-node"
if [ -d "$DIR" ]; then
    cd "$DIR"
    termux-wake-lock
    nohup python3 -u web/server.py </dev/null >/dev/null 2>&1 &
    # İsteğe bağlı: Telefon açılır açılmaz dinlemeyi de başlatmak için:
    # ./start.sh
fi
