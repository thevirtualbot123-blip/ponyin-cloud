#!/usr/bin/env python3
"""
telegram_bot.py — PONYIN AI AGENT v3.1
Fixes:
  - send_signal now reads TP1/TP2/SL percentages from plan (not hardcoded 30/50/20)
  - Uses plan values for dynamic sizing notes.
"""
import logging, asyncio, re
from datetime import datetime
from dataclasses import dataclass, field

log = logging.getLogger("PONYIN.Bot")

try:
    from telegram import Bot as TelegramLibBot
    TG_AVAILABLE = True
except ImportError:
    TG_AVAILABLE = False
    log.warning("python-telegram-bot tidak terinstall — /check dan /scan tdk work.")


def format_status(stats: dict, processed: int) -> str:
    return (
        f"📊 <b>Status PONYIN AI Agent</b>\n\n"
        f"Total signal: <b>{stats['total']}</b>\n"
        f"  • MASUK:  {stats['masuk']}\n"
        f"  • WATCH:  {stats['watch']}\n"
        f"  • SKIP:   {stats['skip']}\n\n"
        f"Processed unique: <b>{processed}</b>\n"
        f"Last check: <i>{datetime.now().strftime('%H:%M:%S')}</i>"
    )


def format_log(records: list) -> str:
    if not records:
        return "📭 Belum ada signal."
    lines = []
    for r in records[-10:]:
        a = "MASUK" if "MASUK" in r.get("verdict","") else ("WATCH" if "WATCH" in r.get("verdict","") else "SKIP")
        lines.append(
            f"{a} <code>{r.get('symbol','?')}</code> "
            f"MC:${r.get('mc',0):,.0f} "
            f"{r.get('ts','')[:16]}"
        )
    return "📜 <b>10 Signal Terakhir</b>\n\n" + "\n".join(lines)


@dataclass
class TelegramBot:
    token: str
    chat_id: str
    on_command: callable = field(default=lambda cmd, args: None)

    def __post_init__(self):
        self._bot   = TelegramLibBot(token=self.token) if TG_AVAILABLE and self.token else None
        self._queue = asyncio.Queue()

    async def send(self, text: str, parse_mode: str = "HTML"):
        if not self._bot or not self.chat_id:
            log.debug(f"[DRY] {text[:80]}")
            return
        try:
            await self._bot.send_message(
                chat_id=self.chat_id,
                text=text[:4095],
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )
            log.info("Tg msg sent")
        except Exception as e:
            log.warning(f"Send failed: {e}")

    async def _consume(self):
        while True:
            text, mode = await self._queue.get()
            await self.send(text, mode)
            self._queue.task_done()
            await asyncio.sleep(0.8)

    async def enqueue(self, text: str, parse_mode: str = "HTML"):
        await self._queue.put((text, parse_mode))

    async def run(self):
        if not self._bot:
            return
        asyncio.create_task(self._consume())
        try:
            log.info("Tg bot polling start")
            from telegram.ext import (
                ApplicationBuilder, CommandHandler, MessageHandler, filters
            )
            app = (
                ApplicationBuilder()
                .token(self.token)
                .concurrent_updates(True)
                .build()
            )
            app.add_handler(CommandHandler(["start","help"], self._cmd))
            app.add_handler(CommandHandler("status",   self._cmd))
            app.add_handler(CommandHandler("log",      self._cmd))
            app.add_handler(CommandHandler("scan",     self._cmd))
            app.add_handler(CommandHandler("check",    self._cmd))
            app.add_handler(CommandHandler("c",        self._cmd))
            app.add_handler(MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self._text_handler))
            await app.run_polling(
                drop_pending_updates=True,
                allowed_updates=["message"],
            )
        except Exception as e:
            log.error(f"Bot error: {e}", exc_info=True)

    async def _cmd(self, update, context):
        text = update.message.text or ""
        parts = text.split(None, 1)
        cmd   = parts[0].strip().lower()
        args  = parts[1].strip() if len(parts) > 1 else ""
        log.info(f"Tg cmd: {cmd} args={args[:30]}")
        await self.on_command(cmd, args)

    async def _text_handler(self, update, context):
        text = (update.message.text or "").strip()
        ca   = self._extract_ca(text)
        if ca:
            log.info(f"CA detected: {ca[:24]}")
            await self.on_command(ca, "")

    def _extract_ca(self, text: str) -> str:
        for word in text.split():
            m = re.match(r'[1-9A-HJ-NP-Za-km-z]{32,44}', word)
            if m:
                return m.group()
        return ""

    async def send_signal(self, t: dict, decision: dict):
        try:
            mint   = t.get("mint", "")
            symbol = t.get("symbol", "?")
            name   = t.get("name", "Unknown")
            mc     = t.get("mc", 0)
            liq    = t.get("liq", 0)
            price  = t.get("price", 0)
            chg1h  = t.get("chg1h", 0)
            chg5m  = t.get("chg5m", 0)
            risk   = t.get("risk_norm", 0)
            top10  = t.get("top10_pct", 0)
            lp     = t.get("lp_burn", 0)
            hld    = t.get("holder_count_gmgn", 0) or t.get("holder_count_rc", 0)
            flags  = t.get("flags", 0)
            verdict= t.get("verdict", "UNKNOWN")
            source = t.get("source", "MANUAL")
            pos    = t.get("position_type", "LOWCAP")
            wash   = t.get("wash_trading_flag", False)
            plan   = t.get("plan") or {}

            ch1h_s = f"{chg1h:+.1f}%" if chg1h != 0 else "n/a"
            ch5m_s = f"{chg5m:+.1f}%" if chg5m != 0 else "n/a"
            liq_s  = f"${liq:,.0f}"   if liq > 0  else "~$0"
            price_s= f"${price:.8f}"  if price and price > 0 else "N/A"

            tp1_p = plan.get("tp1_pct", 30) if plan else 30
            tp2_p = plan.get("tp2_pct", 50) if plan else 50
            sl_p  = plan.get("sl_pct",  20) if plan else 20

            # Verdict emoji
            if   "MASUK" in verdict: emoji = "🟢"
            elif "WATCH" in verdict: emoji = "🟡"
            else:                     emoji = "🔴"

            verdict_line = f"{emoji} <b>{verdict}</b> — {pos}"
            if wash:
                verdict_line += " [WASH]"

            text = (
                f"{verdict_line}\n"
                f"<code>{mint}</code>\n"
                f"━━━━━━━━━━━━━━\n"
                f"💵 {name} (<b>${symbol}</b>)\n"
                f"Price: {price_s}\n"
                f"MC: ${mc:,.0f} | Liq: {liq_s}\n"
                f"Chg: {ch1h_s} (1h) | {ch5m_s} (5m)\n"
                f"Risk: {risk}/10 | Top10: {top10:.1f}% | Flags: {flags}\n"
                f"LP: {lp:.0f}% | Holders: {hld:,}\n"
                f"━━━━━━━━━━━━━━\n"
                f"🧠 <b>{decision['action']}</b> | Conviction: {decision['conviction']}\n"
                f"Reason: {decision['reason']}\n\n"
            )

            if plan:
                ent = plan.get("entry", 0)
                tp1 = plan.get("tp1", 0)
                tp2 = plan.get("tp2", 0)
                sl  = plan.get("sl", 0)
                def fp(v):
                    if v < 0.001: return f"${v:.8f}"
                    return f"${v:.6f}"
                text += (
                    f"📋 Plan:\n"
                    f"  Entry: {fp(ent)}\n"
                    f"  TP1 +{tp1_p:.0f}%: {fp(tp1)} → 50%\n"
                    f"  TP2 +{tp2_p:.0f}%: {fp(tp2)} → 40%\n"
                    f"  SL -{sl_p:.0f}%: {fp(sl)}\n\n"
                )

            text += (
                f"<a href='https://dexscreener.com/solana/{mint}'>DEX</a> | "
                f"<a href='https://rugcheck.xyz/tokens/{mint}'>RugCheck</a> | "
                f"<a href='https://gmgn.ai/sol/token/{mint}'>GMGN</a>\n"
                f"<i>PONYIN AI Agent v7.1</i>"
            )

            await self.send(text)

        except Exception as e:
            log.error(f"send_signal error: {e}", exc_info=True)
