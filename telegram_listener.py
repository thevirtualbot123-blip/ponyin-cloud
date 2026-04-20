"""
telegram_listener.py — Monitor signal channel Telegram.

Session management:
- Pakai StringSession dari env var TG_SESSION_STRING (recommended)
- Fallback ke file session jika tidak ada string session
- Session string dibuat SEKALI via generate_session.py
"""
import os
import re
import logging
from typing import Callable, Awaitable, Optional
from config import AgentConfig

log = logging.getLogger("PONYIN.Listener")

CA_RE = re.compile(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}(?:pump)?\b')

SIGNAL_KEYWORDS = [
    "buy", "entry", "enter", "masuk", "beli", "snipe", "gem",
    "new pair", "fresh", "launch", "just launched", "🟢", "✅", "🔥",
    "alpha", "call", "low cap", "lowcap", "100x", "potential", "CA:", "ca:"
]

SKIP_KEYWORDS = [
    "sold", "exit", "jual", "keluar", "take profit", "tp hit",
    "stop loss", "sl hit", "rugged", "rug", "dead", "scam",
    "avoid", "skip", "don't buy", "jangan beli", "drained"
]


class TelegramListener:

    def __init__(self, cfg: AgentConfig, on_signal: Callable):
        self.cfg       = cfg
        self.on_signal = on_signal
        self._client   = None

    async def run(self):
        """Start listener — pakai StringSession agar tidak minta OTP ulang"""
        try:
            from telethon import TelegramClient, events
            from telethon.sessions import StringSession
        except ImportError:
            log.error("Telethon tidak terinstall: pip install telethon")
            return

        if not self.cfg.TG_API_ID or not self.cfg.TG_API_HASH:
            log.warning("TG credentials tidak ada — listener disabled")
            return

        try:
            api_id = int(self.cfg.TG_API_ID)
        except (ValueError, TypeError):
            log.error("TELEGRAM_API_ID harus angka!")
            return

        # ── Session management ────────────────────────────
        # Prioritas: StringSession dari env > file session
        session_string = os.getenv("TG_SESSION_STRING", "").strip()

        if session_string:
            # Pakai StringSession — tidak butuh file, tidak minta OTP
            session = StringSession(session_string)
            log.info("Menggunakan StringSession dari env var (tidak perlu OTP)")
        else:
            # Fallback ke file session
            session_file = self.cfg.TG_SESSION  # "ponyin_agent"
            session = session_file
            log.info(f"Menggunakan file session: {session_file}.session")
            log.warning(
                "TG_SESSION_STRING tidak diset di .env!\n"
                "   Jalankan generate_session.py sekali untuk buat session string.\n"
                "   Ini mencegah minta OTP setiap restart."
            )

        # ── Buat client ───────────────────────────────────
        self._client = TelegramClient(session, api_id, self.cfg.TG_API_HASH)

        try:
            if session_string:
                # StringSession: langsung connect, tidak perlu phone/OTP
                await self._client.connect()
                if not await self._client.is_user_authorized():
                    log.error(
                        "StringSession tidak valid atau expired!\n"
                        "   Jalankan ulang generate_session.py untuk buat session baru."
                    )
                    return
            else:
                # File session: butuh phone untuk login pertama kali
                await self._client.start(phone=self.cfg.TG_PHONE)

        except Exception as e:
            err = str(e)
            if "ApiIdInvalid" in err or "api_id" in err.lower():
                print("\n\033[91m[ERROR] API credentials tidak valid!\033[0m")
                print("  → Dapatkan di: https://my.telegram.org/apps")
            elif "AUTH_KEY" in err or "session" in err.lower():
                print("\n\033[91m[ERROR] Session expired atau tidak valid!\033[0m")
                print("  → Hapus TG_SESSION_STRING dari .env")
                print("  → Jalankan: python generate_session.py")
            else:
                log.error(f"Connection error: {e}")
            return

        log.info("Telegram connected!")
        print("\033[92m✅ Telethon connected — monitoring channels\033[0m")

        # ── Resolve channels ──────────────────────────────
        channels = self.cfg.SIGNAL_CHANNELS
        if not channels:
            log.warning("SIGNAL_CHANNELS kosong — tidak ada yang dimonitor")
            return

        channel_entities = []
        for ch in channels:
            try:
                entity = await self._client.get_entity(ch)
                channel_entities.append(entity)
                title = getattr(entity, 'title', ch)
                log.info(f"Monitoring: {ch} ({title})")
                print(f"  📡 Monitoring: {title}")
            except Exception as e:
                log.error(f"Tidak bisa resolve channel {ch}: {e}")

        if not channel_entities:
            log.error("Tidak ada channel yang berhasil di-resolve")
            return

        # ── Event handler ─────────────────────────────────
        @self._client.on(events.NewMessage(chats=channel_entities))
        async def handler(event):
            await self._handle_message(event)

        log.info(f"Listener aktif — {len(channel_entities)} channels")
        await self._client.run_until_disconnected()

    async def _handle_message(self, event):
        msg  = event.message
        text = msg.message or ""
        if not text:
            return

        try:
            chat   = await event.get_chat()
            source = getattr(chat, 'title', None) or getattr(chat, 'username', 'tg')
        except Exception:
            source = "telegram"

        text_lower = text.lower()

        # Skip exit/rug signals
        if any(kw in text_lower for kw in SKIP_KEYWORDS):
            log.debug(f"Skip (exit keyword): {source}")
            return

        # Extract CAs
        mints = self._extract_cas(text)
        if not mints:
            return

        for mint in mints:
            log.info(f"Signal dari {source}: {mint[:16]}...")
            await self.on_signal(f"TG:{source}", mint, text)

    def _extract_cas(self, text: str) -> list:
        candidates = CA_RE.findall(text)
        SKIP = {"https", "http", "pump", "solana", "raydium", "jupiter"}
        valid = [c for c in candidates if 32 <= len(c) <= 44 and c.lower() not in SKIP]
        seen, result = set(), []
        for v in valid:
            if v not in seen:
                seen.add(v)
                result.append(v)
        return result

    async def disconnect(self):
        if self._client:
            await self._client.disconnect()
