# PONYIN AI AGENT v3.0
### Solana Meme Coin AI Agent — 24/7 Cloud + Telegram Bot

---

## Setup (ikuti urutan ini)

### STEP 1 — Buat Telegram Bot (5 menit)
1. Buka Telegram → chat **@BotFather**
2. Ketik `/newbot`
3. Ikuti instruksi (nama bot bebas)
4. Copy **token** yang diberikan → `TELEGRAM_BOT_TOKEN`
5. Chat ke bot kamu → kirim `/start`
6. Chat **@userinfobot** → copy angka ID → `TELEGRAM_CHAT_ID`

### STEP 2 — Dapatkan Telegram API (untuk baca channel)
1. Buka **https://my.telegram.org/apps**
2. Login dengan nomor HP
3. Klik **"API Development Tools"** → buat app baru
4. Copy `api_id` dan `api_hash`

### STEP 3 — Deploy ke Render (gratis, 24/7)

#### A. Push ke GitHub dulu
```bash
git init
git add .
git commit -m "ponyin agent v3"
git remote add origin https://github.com/username/ponyin-agent
git push -u origin main
```

#### B. Deploy di Render
1. Buka **https://render.com** → Sign up gratis
2. **New** → **Background Worker**
3. Connect GitHub repo
4. Settings:
   - Name: `ponyin-agent`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python agent.py`
   - Plan: **Free**
5. **Environment Variables** → tambahkan semua dari `.env.example`
6. Klik **Create Background Worker**

#### C. Telegram Session (PENTING!)
Telethon butuh login sekali via OTP. Karena Render tidak bisa input terminal:

**Cara 1 — Generate session lokal dulu:**
```bash
pip install telethon python-dotenv
python generate_session.py  # akan minta OTP sekali
# File ponyin_agent.session akan terbuat
```
Upload `ponyin_agent.session` ke Render menggunakan Secret Files atau environment variable string.

**Cara 2 — Tanpa Telethon (Bot only):**
Kosongkan `TELEGRAM_API_ID` → hanya bot mode (tidak baca channel, hanya terima command dan auto scan).

---

## Cara Pakai via Telegram Bot

Setelah deploy, chat ke bot kamu:

| Command | Fungsi |
|---------|--------|
| `/scan` | Scan token baru sekali |
| `/check <CA>` | Analisis satu token |
| `/status` | Statistik signal hari ini |
| `/log` | 10 signal terakhir |
| Kirim CA langsung | Auto-detect dan analisis |

Kamu juga otomatis dapat notif saat signal dari channel MASUK/WATCH filter.

---

## Render vs Replit

| | Render Free | Replit Free |
|---|---|---|
| Sleep? | ❌ Tidak (Background Worker) | ✅ Ya (tidur setelah inaktif) |
| 24/7? | ✅ Ya | ❌ Butuh "Always On" (berbayar) |
| RAM | 512MB | 512MB |
| CPU | Shared | Shared |
| Rekomen? | ✅ **Pilih ini** | ❌ Tidak untuk use case ini |

---

## Masalah Telegram Session di Cloud

Telethon menyimpan session file `.session`. Di Render, filesystem tidak persistent antar deploy.

**Solusi:**
1. Generate session lokal: `python generate_session.py`
2. Encode ke string: `base64 ponyin_agent.session`
3. Simpan sebagai env var `TG_SESSION_STRING`
4. Di `telegram_listener.py`, load dari env var jika ada

Atau: gunakan **StringSession** dari Telethon (tidak butuh file).
