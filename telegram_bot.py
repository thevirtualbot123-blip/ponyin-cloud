"""
telegram_bot.py — PONYIN Bot Interface v3.1
============================================
Fix: auto-detect chat_id dari pesan pertama jika belum diset.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Callable, Awaitable

log = logging.getLogger("PONYIN.Bot")


class TelegramBot:

    def __init__(self, token: str, chat_id: str,
                 on_command: Callable[[str, str], Awaitable[None]]):
        self.token      = token.strip() if token else ""
        self.chat_id    = str(chat_id).strip() if chat_id else ""
        self.on_command = on_command
        self.base_url   = f"https://api.telegram.org/bot{self.token}"
        self._offset    = 0
        self._running   = False
        self._authorized = False  # jadi True setelah handshake pertama

    # ── Kirim pesan ──────────────────────────────────────
    async def send(self, text: str, parse_mode: str = "HTML",
                   to_chat_id: str = None) -> bool:
        """Kirim pesan. Jika to_chat_id kosong, pakai self.chat_id."""
        if not self.token:
            return False

        target = to_chat_id or self.chat_id
        if not target:
            log.warning("chat_id belum diset — tidak bisa kirim pesan")
            return False

        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id":    target,
                        "text":       text[:4000],
                        "parse_mode": parse_mode,
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    data = await r.json()
                    if r.status != 200:
                        log.error(f"Send error {r.status}: {data.get('description','')}")
                        return False
                    return True
        except Exception as e:
            log.error(f"Telegram send error: {e}")
            return False

    async def send_signal(self, token_data: dict, decision: dict) -> bool:
        """Format dan kirim signal notifikasi"""
        verdict = token_data.get("verdict", "?")
        if "MASUK" in verdict:     emoji = "✅"
        elif "WATCH" in verdict:   emoji = "⚠️"
        elif "RUGGED" in verdict:  emoji = "⛔"
        else:                       emoji = "❌"

        name   = token_data.get("name", "?")
        symbol = token_data.get("symbol", "?")
        mc     = token_data.get("mc", 0)
        liq    = token_data.get("liq", 0)
        vol1h  = token_data.get("vol1h", 0)
        chg1h  = token_data.get("chg1h", 0)
        top10  = token_data.get("top10_pct", 0)
        risk   = token_data.get("risk_norm", 0)
        lp     = token_data.get("lp_burn", 0)
        age    = token_data.get("age_hours", 0)
        mint   = token_data.get("mint", "")
        flags  = token_data.get("flags", 0)
        pt     = token_data.get("position_type", "?")
        cluster= token_data.get("cluster_risk", "?")
        dev_f  = token_data.get("dev_farm_risk", "?")
        sm     = token_data.get("smart_money", False)
        timing = token_data.get("timing_score", 0)
        hh     = token_data.get("holder_health", 0)
        wash   = token_data.get("wash_trading", False)
        bounce = token_data.get("bounce_potential", False)
        source = token_data.get("source", "?")
        plan   = token_data.get("plan", {})
        sizing = token_data.get("sizing_note", "")

        dec_action = decision.get("action", "?")
        dec_conv   = decision.get("conviction", "?")
        dec_reason = decision.get("reason", "")[:80]

        chg_sign  = "+" if chg1h >= 0 else ""
        top10_str = f"{top10:.1f}%" if top10 > 0 else "N/A"
        lp_str    = f"{lp:.0f}%" if lp > 0 else "N/A"
        sm_str    = "✓ Ada" if sm else "–"
        wash_warn = "\n⚠️ <b>WASH TRADING!</b>" if wash else ""
        bounce_str= "\n🔄 <b>Bounce Potential!</b>" if bounce else ""
        price     = token_data.get("price", 0)
        mint_auth = token_data.get("mint_auth")
        mint_str  = "❌ ACTIVE" if mint_auth else "✓ Revoked"

        msg = f"""{emoji} <b>{verdict}</b> — {name} (${symbol}) [{pt}]{wash_warn}

📊 <b>Market</b>
├ Price: <code>${price:.8f}</code>
├ MC: <b>${mc:,.0f}</b>  Liq: ${liq:,.0f}
├ Vol 1h: ${vol1h:,.0f}  Chg: {chg_sign}{chg1h:.1f}%
└ Age: {age:.1f}h  Source: {source}

🔍 <b>On-Chain</b>
├ Risk: {risk:.1f}/10  LP: {lp_str}
├ Top10: {top10_str}  Health: {hh}/100
└ Mint: {mint_str}

🧠 <b>Sambelikan Analysis</b>
├ Cluster: {cluster}  Dev Farm: {dev_f}
├ Smart Money: {sm_str}  Timing: {timing}/100
├ Flags: {flags}{bounce_str}

🤖 <b>{dec_action} [{dec_conv}]</b>
└ {dec_reason}"""

        if dec_action in ("ENTER", "WATCH") and plan:
            p    = plan.get("entry", 0)
            tp1  = plan.get("tp1", 0)
            tp2  = plan.get("tp2", 0)
            sl   = plan.get("sl", 0)
            tp1p = plan.get("tp1_pct", 30)
            tp2p = plan.get("tp2_pct", 50)
            slp  = plan.get("sl_pct", 20)
            msg += f"""

📈 <b>Trading Plan [{pt}] — EKSEKUSI MANUAL</b>
├ Entry : <code>${p:.8f}</code>
├ TP1 +{tp1p:.0f}%: <code>${tp1:.8f}</code> → jual 50%
├ TP2 +{tp2p:.0f}%: <code>${tp2:.8f}</code> → jual 40%
└ SL -{slp:.0f}%: <code>${sl:.8f}</code>"""
            if sizing:
                msg += f"\n\n💰 {sizing[:80]}"

        msg += f"""

🔗 <a href="https://dexscreener.com/solana/{mint}">DEX</a> | <a href="https://rugcheck.xyz/tokens/{mint}">RugCheck</a> | <a href="https://solscan.io/token/{mint}">Solscan</a>"""

        return await self.send(msg)

    # ── Polling loop ─────────────────────────────────────
    async def run(self):
        if not self.token:
            log.warning("BOT_TOKEN tidak diset — bot disabled")
            return

        log.info("Telegram bot polling started")
        self._running = True

        # Cek apakah bot token valid
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{self.base_url}/getMe",
                                 timeout=aiohttp.ClientTimeout(total=5)) as r:
                    data = await r.json()
                    if data.get("ok"):
                        bot_name = data["result"]["username"]
                        log.info(f"Bot valid: @{bot_name}")
                        print(f"\033[92m✅ Bot @{bot_name} siap\033[0m")
                    else:
                        log.error(f"Bot token tidak valid: {data}")
                        print(f"\033[91m❌ Bot token tidak valid! Cek TELEGRAM_BOT_TOKEN di .env\033[0m")
                        return
        except Exception as e:
            log.error(f"Bot check error: {e}")

        # Kirim startup message jika chat_id ada
        if self.chat_id:
            await self._send_startup()
        else:
            log.warning("TELEGRAM_CHAT_ID belum diset!")
            print("\033[93m⚠  TELEGRAM_CHAT_ID belum diset!\033[0m")
            print("   Chat ke bot kamu lalu kirim /start")
            print("   Chat ID kamu akan otomatis terdeteksi dari pesan pertama")

        while self._running:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as s:
                    async with s.get(
                        f"{self.base_url}/getUpdates",
                        params={"offset": self._offset, "timeout": 25},
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as r:
                        if r.status != 200:
                            await asyncio.sleep(5)
                            continue
                        data = await r.json()

                if not data.get("ok"):
                    await asyncio.sleep(5)
                    continue

                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    await self._handle_update(update)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Bot polling error: {e}")
                await asyncio.sleep(10)

    async def _send_startup(self):
        await self.send(
            "🤖 <b>PONYIN AI AGENT v3.0 aktif!</b>\n\n"
            "<b>Commands:</b>\n"
            "/scan — scan token baru\n"
            "/check &lt;CA&gt; — analisis satu token\n"
            "/status — statistik hari ini\n"
            "/log — 10 signal terakhir\n"
            "/help — semua perintah\n\n"
            "Atau <b>paste CA address langsung</b> (32+ karakter)\n\n"
            "<i>Filter: ELPonyin + Sambelikan\n"
            "Cluster | Dev Farm | Smart Money | Timing\n"
            "Bot hanya SIGNAL — eksekusi tetap manual kamu</i>"
        )

    async def _handle_update(self, update: dict):
        msg = update.get("message", {})
        if not msg:
            return

        from_id   = str(msg.get("from", {}).get("id", ""))
        from_name = msg.get("from", {}).get("first_name", "unknown")
        chat_id   = str(msg.get("chat", {}).get("id", ""))
        text      = msg.get("text", "").strip()

        if not text or not from_id:
            return

        # ── Auto-detect chat_id (jika belum diset) ──────
        if not self.chat_id:
            self.chat_id = from_id
            log.info(f"Auto-detected chat_id: {from_id} ({from_name})")
            print(f"\033[92m✅ Chat ID terdeteksi: {from_id} ({from_name})\033[0m")
            print(f"\033[93m   Tambahkan TELEGRAM_CHAT_ID={from_id} ke .env kamu!\033[0m")
            # Kirim konfirmasi
            await self.send(
                f"✅ <b>Terhubung!</b>\n\n"
                f"Chat ID kamu: <code>{from_id}</code>\n\n"
                f"Simpan ini ke .env:\n"
                f"<code>TELEGRAM_CHAT_ID={from_id}</code>\n\n"
                f"Sekarang bot siap menerima command!",
                to_chat_id=from_id
            )
            # Setelah auto-detect, lanjut proses command
        else:
            # Security: hanya terima dari owner
            if from_id != self.chat_id:
                log.warning(f"Blocked unauthorized: {from_id} ({from_name})")
                return

        # ── Parse command ────────────────────────────────
        if text.startswith("/"):
            parts   = text.split(None, 1)
            command = parts[0].split("@")[0].lower()
            args    = parts[1].strip() if len(parts) > 1 else ""
        else:
            # Cek apakah CA address (32+ chars, no spaces)
            if len(text) >= 32 and " " not in text:
                command = "/check"
                args    = text
            else:
                # Pesan biasa — abaikan
                return

        log.info(f"Bot command: {command} | args: {args[:20]}")
        await self.on_command(command, args)

    def stop(self):
        self._running = False


# ── Format helpers ────────────────────────────────────────────
def format_status(stats: dict, processed_count: int) -> str:
    total = stats.get("total", 0)
    masuk = stats.get("masuk", 0)
    watch = stats.get("watch", 0)
    skip  = stats.get("skip",  0)
    wr    = (masuk / total * 100) if total > 0 else 0
    return (
        f"📊 <b>SIGNAL STATS</b>\n\n"
        f"Total processed : {processed_count}\n"
        f"Signals total   : {total}\n"
        f"✅ MASUK        : {masuk} ({wr:.0f}%)\n"
        f"⚠️ WATCH        : {watch}\n"
        f"❌ SKIP         : {skip}\n\n"
        f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</i>"
    )


def format_log(records: list) -> str:
    if not records:
        return "📋 Belum ada signal."
    lines = ["📋 <b>10 SIGNAL TERAKHIR</b>\n"]
    for rec in records:
        v     = rec.get("verdict", "?")
        emoji = "✅" if "MASUK" in v else ("⚠️" if "WATCH" in v else "❌")
        sym   = rec.get("symbol", "?")
        mc    = rec.get("mc", 0)
        ts    = rec.get("ts", "")[:16]
        pt    = rec.get("position_type", "?")[:3]
        flags = rec.get("flags", 0)
        hh    = rec.get("holder_health", 0)
        mint  = rec.get("mint", "")
        lines.append(
            f"{emoji} <b>{sym}</b> [{pt}] ${mc:,.0f} "
            f"flags:{flags} HH:{hh} "
            f"<a href='https://dexscreener.com/solana/{mint}'>DEX</a>\n"
            f"   <i>{ts}</i>"
        )
    return "\n".join(lines)
