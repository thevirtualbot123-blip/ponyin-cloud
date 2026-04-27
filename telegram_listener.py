"""
telegram_listener.py — PONYIN AI AGENT v3.4
Fixes:
  - try/except di handler event supaya exception tidak hilang diam-diam
  - CA regex diperketat ke 43-44 char (Solana address yang valid)
  - SKIP_KEYWORDS tidak lagi memblok kata umum di signal legit
  - Logging lebih informatif saat connection gagal
"""
import os, re, logging
from typing import Callable
from config import AgentConfig

log = logging.getLogger("PONYIN.Listener")

# Solana address = 32 byte = 43-44 karakter Base58
# Base58 charset: 1-9, A-H, J-N, P-Z, a-k, m-z  (tanpa 0, O, I, l)
CA_RE = re.compile(r'(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{43,44}(?![1-9A-HJ-NP-Za-km-z])')

SKIP_KEYWORDS = [
    "rugpull", "rug pull",
    "honeypot detected",
    "tp hit", "take profit hit",
    "sl hit", "stop loss hit",
    "avoid this", "don't buy",
    "jangan beli", "jangan masuk",
    "scam confirmed", "scam alert",
    "dev rug", "dev rugged",
    "rugged 🔴",
]

# FIX: hapus "drain" dari SKIP_KEYWORDS karena bisa muncul di "raydium" atau pesan valid
# FIX: hapus "rugged" karena bisa muncul di "not rugged" atau "unrugged"

ENTRY_KEYWORDS = [
    "mc:", "volume:", "liquidity:", "top 10:",
    "early holders", "sniper", "bundle",
    "pump", "pumpfun", "pump.fun",
    "new pair", "just launched", "fresh",
    "🚀", "🔥", "💊", "🟢", "✅",
    "buy", "entry", "masuk", "call",
    "gem", "alpha", "lowcap", "low cap",
    "ca:", "contract:", "address:",
]

# Kata yang bisa kebaca sebagai CA tapi bukan CA (panjang tapi bukan Base58 address)
SKIP_EXACT = {
    "https", "http", "solana", "raydium", "jupiter", "bonding",
    "search", "twitter", "telegram", "gmgn", "axiom", "padre",
    "trade", "chart", "none", "address", "token", "coin",
    "market", "liquidity", "holder", "supply", "deployer",
    "creator", "burn", "pair", "block", "dexscreener",
}


class TelegramListener:

    def __init__(self, cfg: AgentConfig, on_signal: Callable):
        self.cfg       = cfg
        self.on_signal = on_signal
        self._client   = None

    async def run(self):
        try:
            from telethon import TelegramClient, events
            from telethon.sessions import StringSession
        except ImportError:
            log.error("Telethon tidak terinstall: pip install telethon")
            return

        if not self.cfg.TG_API_ID or not self.cfg.TG_API_HASH:
            log.warning("TG_API_ID / TG_API_HASH tidak ada — listener dinonaktifkan")
            return

        try:
            api_id = int(self.cfg.TG_API_ID)
        except (ValueError, TypeError):
            log.error("TELEGRAM_API_ID harus angka!")
            return

        session_string = os.getenv("TG_SESSION_STRING", "").strip()
        if session_string:
            session = StringSession(session_string)
            log.info("Menggunakan StringSession")
        else:
            session = self.cfg.TG_SESSION
            log.warning("TG_SESSION_STRING tidak ada — pakai file session (tidak cocok untuk cloud)")

        self._client = TelegramClient(session, api_id, self.cfg.TG_API_HASH)

        try:
            if session_string:
                await self._client.connect()
                if not await self._client.is_user_authorized():
                    log.error(
                        "StringSession tidak valid atau expired!\n"
                        "Jalankan generate_session.py lagi dan update TG_SESSION_STRING."
                    )
                    return
                log.info("StringSession authorized ✓")
            else:
                await self._client.start(phone=self.cfg.TG_PHONE)
        except Exception as e:
            log.error(f"Telethon connection error: {e}")
            return

        log.info("Telegram connected!")

        channels = self.cfg.SIGNAL_CHANNELS
        if not channels:
            log.warning("SIGNAL_CHANNELS kosong — listener tidak akan memonitor channel apapun")
            return

        entities = []
        for ch in channels:
            try:
                ent = await self._client.get_entity(ch)
                entities.append(ent)
                log.info(f"Monitoring channel: {getattr(ent,'title',ch)}")
                print(f"  📡 Monitoring: {getattr(ent,'title',ch)}")
            except Exception as e:
                log.error(f"Gagal resolve channel '{ch}': {e}")

        if not entities:
            log.error("Tidak ada channel yang berhasil di-resolve — listener berhenti")
            return

        # ── FIX: bungkus handler dengan try/except supaya exception tidak hilang ──
        @self._client.on(events.NewMessage(chats=entities))
        async def handler(event):
            try:
                await self._handle_message(event)
            except Exception as e:
                log.error(f"Handler error: {e}", exc_info=True)

        log.info(f"Listener aktif — {len(entities)} channel dimonitor")
        print(f"\n  ✅ Listener aktif — {len(entities)} channel")

        try:
            await self._client.run_until_disconnected()
        except Exception as e:
            log.error(f"Listener disconnected: {e}")

    async def _handle_message(self, event):
        msg  = event.message
        text = msg.message or ""
        if not text or len(text) < 10:
            return

        try:
            chat   = await event.get_chat()
            source = getattr(chat, 'title', None) or getattr(chat, 'username', 'tg')
        except Exception:
            source = "telegram"

        text_lower = text.lower()

        # Cek skip keywords — hanya skip jika yakin bukan signal valid
        for kw in SKIP_KEYWORDS:
            if kw in text_lower:
                log.debug(f"Skip message (keyword '{kw}'): {source}")
                return

        mints = self._extract_cas(text)
        if not mints:
            log.debug(f"No CA found in message from {source}: {text[:60].replace(chr(10),' ')}")
            return

        has_entry_kw = any(kw in text_lower for kw in ENTRY_KEYWORDS)
        log.info(
            f"Signal dari {source}: {len(mints)} CA "
            f"| entry_kw={has_entry_kw} "
            f"| preview: {text[:80].replace(chr(10),' ')}"
        )

        for mint in mints:
            try:
                await self.on_signal(f"TG:{source}", mint, text)
            except Exception as e:
                log.error(f"on_signal error for {mint[:12]}: {e}", exc_info=True)

    def _extract_cas(self, text: str) -> list:
        # FIX: regex sekarang 43-44 char (Solana address = 32 byte = 43-44 base58)
        # dengan negative lookbehind/ahead supaya tidak potong dari string lebih panjang
        candidates = CA_RE.findall(text)

        valid = []
        seen  = set()
        for c in candidates:
            cl = c.lower()
            # Skip jika persis sama dengan kata di SKIP_EXACT (tidak mungkin 43 char, tapi tetap cek)
            if cl in SKIP_EXACT:
                continue
            # Skip duplikat
            if c in seen:
                continue
            # Double-check: tidak boleh ada karakter 0, O, I, l (sudah dijaga regex tapi tetap cek)
            if any(ch in c for ch in "0OIl"):
                continue
            seen.add(c)
            valid.append(c)

        return valid

    async def disconnect(self):
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
