import os

# ==========================================
# 🎙️ OTONOM ORTAM DİNLEME DÜĞÜMÜ AYARLARI
# ==========================================

# --- Akustik & VAD Parametreleri ---
NOISE_GATE_DB = -52.0       # İnsan sesi tetikleme eşiği (dB). Ortam dip gürültüsü -65 dB iken -52 dB idealdir.
HIGHPASS_FREQ = 200         # Yüksek geçiren filtre (Hz). Klima, fan ve motor uğultularını keser.
SILENCE_LIMIT_SEC = 3.5     # Konuşma bittikten sonra beklenecek sessizlik süresi (saniye).
CHECK_INTERVAL = 1.5        # VAD kayan pencere analiz sıklığı (saniye).
PRE_ROLL_SEC = 1.0          # Konuşmanın ilk hecesini kaçırmamak için başa eklenen ön-tampon (saniye).
MAX_SILENT_STREAM_AGE = 60  # Sessizlik anında stream dosyasını sıfırlama aralığı (saniye, disk dolmasını önler).

# --- Web & Ağ Ayarları ---
PORT = 8080                 # Web Kontrol Paneli ve API portu.
HOSTNAME = "kulak.local"    # mDNS yerel alan adı (Destekleyen ağlarda http://kulak.local:8080).

# --- Dizin Yapısı ---
BASE_DIR = os.path.expanduser("~")
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
TEMP_DIR = os.path.join(BASE_DIR, "vad_temp")
STREAM_FILE = os.path.join(TEMP_DIR, "live_stream.opus")
LOG_FILE = os.path.join(BASE_DIR, "vad.log")

# --- Opsiyonel Telegram Bildirim Ayarları ---
# Telefon her yeni Wi-Fi ağına bağlandığında yeni IP adresini Telegram'dan almak isterseniz:
TELEGRAM_ENABLED = False
TELEGRAM_BOT_TOKEN = ""     # @BotFather'dan alınan bot token
TELEGRAM_CHAT_ID = ""       # Bildirimin gönderileceği Chat ID

# Yerel özel ayarları (token vb.) config_local.py veya .env dosyasından yükle
try:
    import config_local
    TELEGRAM_ENABLED = getattr(config_local, "TELEGRAM_ENABLED", TELEGRAM_ENABLED)
    TELEGRAM_BOT_TOKEN = getattr(config_local, "TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    TELEGRAM_CHAT_ID = getattr(config_local, "TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)
except ImportError:
    pass

