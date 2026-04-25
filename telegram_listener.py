"""
telegram_listener.py — PONYIN AI AGENT v5.0
"""
import os, re, logging
from typing import Callable
from config import AgentConfig

log = logging.getLogger("PONYIN.Listener")

CA_RE = re.compile(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b')

SKIP_KEYWORDS = [
    "rugpull", "rugged", "rug pull",
    "honeypot", "honeypot detected",
    "drained", "drain",
    "tp hit", "take profit hit",
    "sl hit", "stop loss hit",
    "avoid this", "don't buy",
    "jangan beli", "jangan masuk",
    "scam confirmed", "scam alert",
    "dev rug", "dev rugged",
]

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
            log.warning("TG credentials tidak ada")
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
            log.warning("TG_SESSION_STRING tidak ada — pakai file session")

        self._client = TelegramClient(session, api_id, self.cfg.TG_API_HASH)

        try:
            if session_string:
                await self._client.connect()
                if not await self._client.is_user_authorized():
                    log.error("StringSession tidak valid! Jalankan generate_session.py")
                    return
            else:
                await self._client.start(phone=self.cfg.TG_PHONE)
        except Exception as e:
            log.error(f"Connection error: {e}")
            return

        log.info("Telegram connected!")

        channels = self.cfg.SIGNAL_CHANNELS
        if not channels:
            log.warning("SIGNAL_CHANNELS kosong")
            return

        entities = []
        for ch in channels:
            try:
                ent = await self._client.get_entity(ch)
                entities.append(ent)
                log.info(f"Monitoring: {getattr(ent,'title',ch)}")
                print(f"  📡 Monitoring: {getattr(ent,'title',ch)}")
            except Exception as e:
                log.error(f"Tidak bisa resolve {ch}: {e}")

        if not entities:
            log.error("Tidak ada channel yang berhasil di-resolve")
            return

        @self._client.on(events.NewMessage(chats=entities))
        async def handler(event):
            await self._handle_message(event)

        log.info(f"Listener aktif — {len(entities)} channel")
        await self._client.run_until_disconnected()

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

        for kw in SKIP_KEYWORDS:
            if kw in text_lower:
                log.debug(f"Skip (keyword '{kw}'): {source}")
                return

        mints = self._extract_cas(text)
        if not mints:
            return

        has_entry_kw = any(kw in text_lower for kw in ENTRY_KEYWORDS)
        log.info(f"Signal dari {source}: {len(mints)} CA | entry_kw: {has_entry_kw}")

        for mint in mints:
            await self.on_signal(f"TG:{source}", mint, text)

    def _extract_cas(self, text: str) -> list:
        candidates = CA_RE.findall(text)

        SKIP_WORDS = {
            "https", "http", "pump", "solana", "raydium", "jupiter",
            "bonding", "curve", "search", "twitter", "telegram",
            "gmgn", "axiom", "padre", "trade", "chart", "none",
            "address", "token", "coin", "market", "cap", "volume",
            "liquidity", "holder", "bundle", "supply", "deploy",
            "deployer", "creator", "mint", "burn", "pair", "block",
        }
        valid = []
        for c in candidates:
            if len(c) < 32: continue
            if c.lower() in SKIP_WORDS: continue
            if any(ch in c for ch in "0OIl"): continue
            valid.append(c)

        seen, result = set(), []
        for v in valid:
            if v not in seen:
                seen.add(v)
                result.append(v)
        return result

    async def disconnect(self):
        if self._client:
            await self._client.disconnect()