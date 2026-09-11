import os
import sys
import time
import signal
import subprocess

# Üst dizini sys.path'e ekle (config ve core erişimi)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import config
from core.naming import generate_safe_filename

os.makedirs(config.RECORDINGS_DIR, exist_ok=True)
os.makedirs(config.TEMP_DIR, exist_ok=True)

running = True

def cleanup():
    """Program sonlanırken donanımsal mikrofonu kapatır ve geçici dosyaları siler."""
    print("\n[*] Temizlik yapılıyor...")
    subprocess.run(["termux-microphone-record", "-q"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(config.STREAM_FILE):
        try: os.remove(config.STREAM_FILE)
        except Exception: pass

def signal_handler(sig, frame):
    global running
    print("\n[!] Durdurma sinyali alındı.")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def get_stream_duration(file_path):
    """Opus stream dosyasının güncel süresini döndürür."""
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return float(res.stdout.strip())
    except Exception:
        return 0.0

def get_window_energy(file_path, start_sec, duration_sec):
    """Yüksek geçiren filtre sonrası pencerenin ortalama ses enerjisini (dB) ölçer."""
    try:
        cmd = [
            "ffmpeg", "-y", "-ss", f"{start_sec:.2f}", "-i", file_path,
            "-t", f"{duration_sec:.2f}",
            "-af", f"highpass=f={config.HIGHPASS_FREQ},volumedetect",
            "-vn", "-sn", "-dn", "-f", "null", "/dev/null"
        ]
        res = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
        for line in res.stderr.splitlines():
            if "mean_volume:" in line:
                val = line.split("mean_volume:")[1].split("dB")[0].strip()
                return float(val)
    except Exception:
        pass
    return -99.0

def extract_speech_atomic(src_file, start_sec, end_sec, final_path):
    """
    Konuşma bloğunu geçici bir dosyaya dönüştürür; boyutu doğrulanınca
    atomik olarak hedef yola taşır. Bozuk dosya oluşmasını %100 engeller.
    """
    tmp_out = os.path.join(config.TEMP_DIR, f"extract_{int(time.time() * 1000)}.m4a")
    try:
        cmd = [
            "ffmpeg", "-y", "-ss", f"{start_sec:.2f}", "-to", f"{end_sec:.2f}",
            "-i", src_file, "-c:a", "aac", "-b:a", "64k", tmp_out
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 0:
            os.replace(tmp_out, final_path)
            return True
        else:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            return False
    except Exception as e:
        print(f"[!] Extract hatası: {e}")
        if os.path.exists(tmp_out):
            try: os.remove(tmp_out)
            except Exception: pass
        return False

def start_recorder():
    """Kesintisiz 48kHz Opus kayıt oturumunu başlatır."""
    if os.path.exists(config.STREAM_FILE):
        try: os.remove(config.STREAM_FILE)
        except Exception: pass
    subprocess.run(["termux-microphone-record", "-q"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cmd = ["termux-microphone-record", "-f", config.STREAM_FILE, "-e", "opus", "-l", "0"]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    subprocess.run(["termux-wake-lock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("[*] SIFIR KÖR NOKTALI (KESİNTİSİZ) VAD MOTORU DEVREDE.")
    print(f"    --> Eşik: {config.NOISE_GATE_DB} dB | Filtre: {config.HIGHPASS_FREQ} Hz | Sessizlik Limiti: {config.SILENCE_LIMIT_SEC}s")
    
    start_recorder()
    time.sleep(2.0)

    in_speech = False
    speech_start_sec = 0.0
    silence_accumulated = 0.0

    while running:
        time.sleep(config.CHECK_INTERVAL)
        if not running:
            break

        if not os.path.exists(config.STREAM_FILE) or os.path.getsize(config.STREAM_FILE) < 1000:
            continue

        curr_duration = get_stream_duration(config.STREAM_FILE)
        if curr_duration < 2.0:
            continue

        window_start = max(0.0, curr_duration - 2.0)
        energy = get_window_energy(config.STREAM_FILE, window_start, 2.0)
        t_str = time.strftime("%H:%M:%S")

        if energy > config.NOISE_GATE_DB:
            if not in_speech:
                speech_start_sec = max(0.0, window_start - config.PRE_ROLL_SEC)
                in_speech = True
                silence_accumulated = 0.0
                print(f"\n[+] [{t_str}] KONUŞMA ALGILANDI! ({energy:.1f} dB > {config.NOISE_GATE_DB} dB) - Başlangıç: {speech_start_sec:.1f}s")
            else:
                silence_accumulated = 0.0
                print(f"    [{t_str}] Konuşma sürüyor... ({energy:.1f} dB, süre: {curr_duration - speech_start_sec:.1f}s)")
        else:
            if in_speech:
                silence_accumulated += config.CHECK_INTERVAL
                print(f"    [{t_str}] Sessizlik: {silence_accumulated:.1f}s / {config.SILENCE_LIMIT_SEC:.1f}s ({energy:.1f} dB)")

                if silence_accumulated >= config.SILENCE_LIMIT_SEC:
                    speech_end_sec = curr_duration
                    out_name, out_path = generate_safe_filename(config.RECORDINGS_DIR, extension=".m4a")

                    print(f"[*] [{t_str}] Kesintisiz blok çıkarılıyor [{speech_start_sec:.1f}s -> {speech_end_sec:.1f}s]...")
                    ok = extract_speech_atomic(config.STREAM_FILE, speech_start_sec, speech_end_sec, out_path)
                    if ok:
                        sz = os.path.getsize(out_path)
                        dur = speech_end_sec - speech_start_sec
                        print(f"[✓] [{t_str}] KAYDEDİLDİ: {out_name} ({sz/1024:.1f} KB, {dur:.1f}s)\n")
                    else:
                        print(f"[!] [{t_str}] Blok çıkarılamadı!")

                    in_speech = False
                    silence_accumulated = 0.0
                    start_recorder()
                    time.sleep(1.5)
            else:
                print(f"[~] [{t_str}] Ortam/Sessiz: {energy:.1f} dB (Stream: {curr_duration:.0f}s)", end="\r", flush=True)
                if curr_duration > config.MAX_SILENT_STREAM_AGE:
                    start_recorder()
                    time.sleep(1.5)

    cleanup()

if __name__ == "__main__":
    main()
