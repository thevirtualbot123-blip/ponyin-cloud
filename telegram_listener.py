#!/usr/bin/env python3
"""
telegram_listener.py — PONYIN AI AGENT v4.0
(No changes needed from original — already stable)
"""
import asyncio, logging, os, re
from datetime import datetime
from typing import Optional, Callable

log = logging.getLogger("PONYIN.Listener")


try:
    from telethon import TelegramClient, events
    from telethon.tl.types import Channel, PeerChannel
    TELETHON_OK = True
except ImportError:
    TELETHON_OK = False
    log.warning("Telethon tidak terinstall — channel listener OFF")


CA_RE = re.compile(r'[1-9A-HJ-NP-Za-km-z]{32,44}')


class TelegramListener:

    def __init__(self, cfg, on_signal: Callable):
        self.cfg       = cfg
        self.on_signal = on_signal
        self._client   = None
        self._task     = None
        self._running  = False

    async def _ensure_client(self):
        if not TELETHON_OK:
            return False
        if self._client and self._client.is_connected():
            return True
        # Load session dari .env string
        session_str = getattr(self.cfg, 'TELETHON_SESSION', '')
        if not session_str:
            log.error("TELETHON_SESSION tidak di-set — listener OFF")
            return False
        try:
            from telethon.sessions import StringSession
            from telethon.tl.types import Channel, PeerChannel
            self._client = TelegramClient(
                StringSession(session_str),
                self.cfg.TG_API_ID,
                self.cfg.TG_API_HASH,
            )
            await self._client.connect()
            if not await self._client.is_user_authorized():
                log.error("Telethon session tidak authorized — perlu /generate_session.py")
                return False
            return True
        except Exception as e:
            log.error(f"Telethon connect error: {e}")
            return False

    async def run(self):
        if not self.cfg.SIGNAL_CHANNELS:
            log.info("SIGNAL_CHANNELS kosong — listener OFF")
            return
        if not await self._ensure_client():
            return
        self._running = True
        log.info(f"Telegram listener aktif: {len(self.cfg.SIGNAL_CHANNELS)} channel(s)")
        @self._client.on(events.NewMessage(chats=self.cfg.SIGNAL_CHANNELS))
        async def handler(event):
            try:
                msg = event.message
                if not msg:
                    return
                text = msg.text or msg.raw_text or ""
                if not text:
                    return
                matches = CA_RE.findall(text)
                if matches:
                    mint = matches[0]
                    ch = await event.get_chat()
                    ch_name = getattr(ch, 'title', 'unknown')
                    log.info(f"CA dari channel: [{ch_name}] {mint[:24]}...")
                    await self.on_signal(f"TG:{ch_name}", mint, text[:200])
            except Exception as e:
                log.debug(f"Handler error: {e}")
        await self._client.run_until_disconnected()

    async def stop(self):
        self._running = False
        if self._client:
            await self._client.disconnect()
