# Tasarım Belgesi: Telegram Uzaktan Kumanda, Ses Dağıtım Motoru ve Donanım Nöbetçisi (Edge Guard)

**Tarih:** 12 Eylül 2026  
**Durum:** Onaylandı / İncelemede  
**Depo:** `ozunekmekci/autonomous-audio-node`  

---

## 1. Genel Amaç ve Kapsam

Bu tasarım belgesi; Android (Termux) tabanlı otonom ortam dinleme düğümüne (Autonomous Audio Node) üç kritik sistem bileşeninin eklenmesini detaylandırır:

1. **Ses Dağıtım Motoru (Audio Dispatcher):** VAD tarafından algılanıp kaydedilen her yeni ses dosyasını anında Telegram üzerinden dinlenebilir bir sesli mesaj (`sendVoice`) olarak iletme.
2. **Çift Yönlü Telegram Kumandası (Telegram Bot Controller):** Dokunmatik menü butonları ve metin komutları ile cihazı dünyanın her yerinden (aynı yerel ağda olmadan) başlatma, durdurma ve telemetri sorgulama.
3. **Akıllı Donanım ve Güç Nöbetçisi (Edge Guard) & Tam Sessizlik:** Fişten çekilme, kritik pil (%10), termal aşırı ısınma (43°C/46°C) ve disk doluluk risklerine karşı donanımı koruma ve dinleme başladığında cihazı tamamen sessize alma.

---

## 2. Mimari ve Bileşenler

```
                               ┌────────────────────────────────────────┐
                               │       Autonomous Audio Node Core       │
                               └──────────────────┬─────────────────────┘
                                                  │
                ┌─────────────────────────────────┼────────────────────────────────┐
                │                                 │                                │
                ▼                                 ▼                                ▼
     [core/edge_guard.py]              [core/dispatcher.py]             [core/bot_controller.py]
  Akıllı Güç & Donanım Nöbetçisi    Otomatik Telegram Ses Gönderici   Çift Yönlü Telegram Kumandası
```

### 2.1. Tam Sessizlik Protokolü (Silence Protocol)
Ortam dinleme başladığında harici bildirimlerin ve aramaların mikrofona gürültü olarak girmesini ve telefonun titreşerek masaya vurmasını engellemek için tüm ses akışları sıfırlanır:
* `termux-volume ring 0` (Zil sesi)
* `termux-volume notification 0` (Bildirim sesleri)
* `termux-volume system 0` (Sistem tıklama/tuş sesleri)
* `termux-volume music 0` (Medya sesleri)
* `termux-volume call 0` (Arama sesleri)

### 2.2. Akıllı Güç & Donanım Nöbetçisi (`core/edge_guard.py`)
Arka planda bağımsız bir Thread olarak her 30 saniyede bir `termux-battery-status` ve `shutil.disk_usage` değerlerini izler:
1. **Şarj Kesintisi (Fişten Çekilme):**
   * Durum: `status != CHARGING` ve `plugged == UNPLUGGED`.
   * Davranış: Dinleme kesilmez (bataryadan devam eder). Telegram'a `⚠️ Şarj aleti kesildi, bataryadan devam ediliyor (%XX)` bildirimi gönderilir.
2. **Kritik Pil Eşiği (%10):**
   * Durum: `percentage <= 10`.
   * Davranış: Aktif ses kaydı atomik olarak tamamlanır, VAD motoru ve mikrofon donanımsal olarak kapatılır. Telegram'a `🛑 Kritik Pil (%10): Güvenli durdurma yapıldı, bekleme moduna geçildi` mesajı atılır.
3. **Yeniden Şarja Takılma (> %10):**
   * Durum: `percentage > 10` ve şarja takıldı.
   * Davranış: Sistem çevrimiçi olur ve Telegram'a `⚡ Cihaz şarja takıldı (%XX), sistem hazır` bildirimi gönderir. **KRİTİK GÜVENLİK KURALI:** Mikrofon otomatik olarak **AÇILMAZ**; dinleme modu kapalı (standby) kalır, kullanıcı Telegram veya Web üzerinden onay verene kadar hot-mic engellenir.
4. **Termal Koruma (Isınma Koruması & Histerezis):**
   * **Sarı Alarm (43°C):** `temperature >= 43.0` olduğunda Telegram'a ısınma uyarısı gönderilir.
   * **Kırmızı Alarm (46°C - Acil Durdurma):** `temperature >= 46.0` olduğunda mikrofon kapatılır, sistem durumu (`was_listening_before_overheat = True`) hafızaya kaydedilir ve Telegram'a acil soğuma bildirimi gönderilir.
   * **Güvenli Soğuma (38°C):** Sıcaklık 38°C altına düştüğünde Telegram'a `🟢 Sıcaklık normale döndü (XX°C)` bildirimi atılır. Eğer cihaz ısınmadan önce dinlemedeyse, **otomatik olarak dinlemeye kaldığı yerden devam eder** (State Memory).
5. **Disk Alanı Koruması:**
   * Boş alan < 500 MB ise Telegram'a disk uyarısı gönderilir ve dosya bozulmalarını önlemek için kayıt güvenle durdurulur.

### 2.3. Ses Dağıtım Motoru (`core/dispatcher.py`)
`core/vad_recorder.py` bir ses dilimini `ddaayyyy_saat_dakika_N.m4a` formatında tamamladığı anda:
* Telegram Bot API `sendVoice` uç noktası kullanılarak `.m4a` dosyası doğrudan sohbet ekranında çalınabilir bir sesli mesaj (waveform grafiğiyle) olarak yüklenir.
* **Başlık (Caption):**
  ```text
  🎙️ Yeni Ses Algılandı
  📅 12.09.2026 02:15:30
  ⏱️ Süre: 6.2 sn | 💾 Boyut: 92.4 KB
  ```
* **Kayıp Önleme:** İnternet bağlantısı geçici olarak kesilirse dosyalar silinmez, sıraya alınır ve bağlantı sağlandığında kronolojik sırayla Telegram'a aktarılır. Dosyalar yerel `~/recordings` dizininde arşiv olarak korunur.

### 2.4. Çift Yönlü Telegram Kumandası (`core/bot_controller.py`)
Uzun yoklamalı (Long-Polling `getUpdates`) hafif arka plan iş parçacığı:
* **Güvenlik / Whitelist:** Yalnızca `TELEGRAM_CHAT_ID = 6444855403` olan kullanıcıdan gelen mesajları işler. Diğer tüm kullanıcılardan gelen mesajlar sessizce yok sayılır.
* **Dokunmatik Klavye Menüsü (ReplyKeyboardMarkup):**
  ```
  ┌─────────────────────────┬─────────────────────────┐
  │  ▶ Dinlemeyi Başlat     │  ⏹ Dinlemeyi Durdur     │
  ├─────────────────────────┼─────────────────────────┤
  │  📊 Canlı Durum / Pil   │  🎙️ Son Kaydı Gönder    │
  └─────────────────────────┴─────────────────────────┘
  ```
* **Desteklenen Komutlar:**
  * `▶ Dinlemeyi Başlat` veya `/dinle`: `mute_all_audio()` çalıştırır, VAD motorunu başlatır, Telegram'a `🟢 Dinleme başlatıldı. Mikrofon aktif, bildirimler sessize alındı.` döner.
  * `⏹ Dinlemeyi Durdur` veya `/dur`: Mikrofonu kapatır, Telegram'a `🔴 Mikrofon kapatıldı, sistem beklemede.` döner.
  * `📊 Canlı Durum / Pil` veya `/durum`: Mikrofon, pil yüzdesi, şarj durumu, sıcaklık, disk alanı, kayıt sayısı ve web erişim linklerini içeren özet bilgi kartı döner.
  * `🎙️ Son Kaydı Gönder` veya `/sonkayit`: En son üretilen `.m4a` sesini `sendVoice` ile sohbete gönderir.

---

## 3. Yapılandırma ve Dosya Mimarisi

* `config.py`: Varsayılan ayarlar (eşikler, sıcaklık limitleri, buton metinleri).
* `config_local.py`: Kişisel bot token ve Chat ID (`.gitignore` korumalı).
* `core/edge_guard.py`: [YENİ] Güç, termal, disk ve tam sessizlik yöneticisi.
* `core/dispatcher.py`: [YENİ] Otomatik sesli mesaj yükleyicisi.
* `core/bot_controller.py`: [YENİ] Telegram bot kumanda döngüsü.
* `web/server.py`: [GÜNCELLEME] Edge Guard ve Bot Controller iş parçacıklarını başlatma/durdurma.
* `core/vad_recorder.py`: [GÜNCELLEME] Ses dilimi kaydedildiğinde `dispatcher.dispatch()` tetikleme.

---

## 4. Doğrulama ve Test Planı

1. **Tam Sessizlik Testi:** `mute_all_audio()` çağrıldığında sistem ses seviyelerinin 0 olduğu `termux-volume` ile doğrulanacak.
2. **Telegram Buton Testi:** `@Kulak_znbot` üzerinden butonlara dokunulduğunda (`▶ Dinlemeyi Başlat` ve `⏹ Dinlemeyi Durdur`) mikrofonun fiziksel olarak açılıp kapandığı doğrulanacak.
3. **Otomatik Ses Gönderim Testi:** Konuşma yapıldığında `.m4a` dosyasının başarıyla oluşturulup Telegram'a `sendVoice` olarak düştüğü teyit edilecek.
4. **Edge Guard Simülasyonu:** Şarj durumu, termal eşikler ve telemetri raporlama işlevleri test edilecek.
