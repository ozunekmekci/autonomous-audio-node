#!/bin/bash
# ==========================================
# 🛑 Ortam Dinleme Düğümü - Durdurucu
# ==========================================

echo "⏳ Dinleme durduruluyor ve mikrofon kapatılıyor..."

# 1. API üzerinden temiz kapatma dene
RES=$(curl -s -m 2 -X POST http://127.0.0.1:8080/api/stop 2>/dev/null)

# 2. Süreçleri ve mikrofon donanımını kesin olarak temizle
pkill -f "core/vad_recorder.py" 2>/dev/null || true
termux-microphone-record -q 2>/dev/null || true
termux-notification-remove vad-node 2>/dev/null || true

echo "🔴 Dinleme durduruldu. Mikrofon donanımsal olarak kapatıldı."
