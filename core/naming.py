import os
import time

def generate_safe_filename(directory, extension=".m4a"):
    """
    Format Kuralı: ddaayyyy_saat_dakika_N.m4a
    Örnek: 12092026_01_35_1.m4a, 12092026_01_35_2.m4a

    Hata Toleransı ve Çakışma Koruması:
    1. Bellekteki sayaçlara değil, doğrudan dosya sistemindeki fiziksel dosyalara bakar.
       Böylece servis çöküp yeniden başlasa bile eski dosyaların üstüne ASLA yazmaz.
    2. Zaman dilimi veya işletim sistemi saat glitch'lerinde bile ASLA çökmez;
       hata durumunda milisaniye tabanlı güvenli bir fallback adı döner.
    """
    try:
        now = time.localtime()
        # %d: 2 haneli gün, %m: 2 haneli ay, %Y: 4 haneli yıl, %H: 2 haneli saat, %M: 2 haneli dakika
        base_prefix = time.strftime("%d%m%Y_%H_%M", now)
        seq = 1
        while seq <= 9999:
            candidate_name = f"{base_prefix}_{seq}{extension}"
            candidate_path = os.path.join(directory, candidate_name)
            if not os.path.exists(candidate_path):
                return candidate_name, candidate_path
            seq += 1
    except Exception as e:
        print(f"[!] İsimlendirme hatası yakalandı: {e}")

    # Acil durum güvenli yedeği (asla boş dönmez, asla çökmez)
    fallback_name = f"fallback_{int(time.time() * 1000)}{extension}"
    return fallback_name, os.path.join(directory, fallback_name)
