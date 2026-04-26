"""
telegram_bot.py — PONYIN AI AGENT v4.2
Fix:
  - holder count display: priority GMGN/Helius > RugCheck
  - All variables properly declared
  - GMGN link (trading platform utama)
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

    async def send(self, text: str, parse_mode: str = "HTML",
                   to_chat_id: str = None) -> bool:
        if not self.token:
            return False
        target = to_chat_id or self.chat_id
        if not target:
            log.warning("chat_id belum diset")
            return False
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id":                  target,
                        "text":                     text[:4000],
                        "parse_mode":               parse_mode,
                        "disable_web_page_preview": True,
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
        """Format dan kirim signal — semua variable di-declare di sini"""

        # ── Ambil semua data token ──────────────────────
        verdict    = token_data.get("verdict", "?")
        name       = token_data.get("name", "Unknown")
        symbol     = token_data.get("symbol", "???")
        mc         = token_data.get("mc", 0)
        liq        = token_data.get("liq", 0)
        vol1h      = token_data.get("vol1h", 0)
        chg1h      = token_data.get("chg1h", 0)
        top10      = token_data.get("top10_pct", 0)
        risk       = token_data.get("risk_norm", 0)
        lp         = token_data.get("lp_burn", 0)
        age        = token_data.get("age_hours", 0)
        mint       = token_data.get("mint", "")
        flags      = token_data.get("flags", 0)
        pt         = token_data.get("position_type", "?")
        cluster    = token_data.get("cluster_risk", "?")
        cs         = token_data.get("cluster_score", 0)
        dev_f      = token_data.get("dev_farm_risk", "?")
        sm         = token_data.get("smart_money_present", False)
        timing     = token_data.get("timing_score", 0)
        hh         = token_data.get("holder_health", 0)
        wash       = token_data.get("wash_trading_flag", False)
        bounce     = token_data.get("bounce_potential", False)
        source     = token_data.get("source", "?")
        price      = token_data.get("price", 0)
        mint_auth  = token_data.get("mint_auth")
        buys       = token_data.get("buys1h", 0)
        sells      = token_data.get("sells1h", 0)
        momentum   = token_data.get("momentum_score", 50)
        
        # ── FIX: Prioritas holder count GMGN/Helius > RugCheck ──
        hc_gmgn = token_data.get("holder_count_gmgn", 0)
        hc_rc   = token_data.get("holder_count_rc", 0)
        hcount  = hc_gmgn if hc_gmgn > 0 else (hc_rc if hc_rc > 50 else 0)
        hcount_str = f"{hcount}" if hcount > 0 else "N/A"
        
        plan       = token_data.get("plan", {})
        sizing     = token_data.get("sizing_note", "")

        # ── Decision ─────────────────────────────────────
        dec_action = decision.get("action", "?")
        dec_conv   = decision.get("conviction", "?")
        dec_reason = decision.get("reason", "")[:80]

        # ── Format strings ────────────────────────────────
        if "MASUK" in verdict:     emoji = "✅"
        elif "WATCH" in verdict:   emoji = "⚠️"
        elif "RUGGED" in verdict:  emoji = "⛔"
        else:                       emoji = "❌"

        chg_sign   = "+" if chg1h >= 0 else ""
        top10_str  = f"{top10:.1f}%" if top10 > 0 else "N/A"
        lp_str     = f"{lp:.0f}%" if lp > 0 else "⚠️ 0%"
        sm_str     = "✓ Ada" if sm else "–"
        mint_str   = "❌ ACTIVE" if mint_auth else "✓ Revoked"
        wash_warn  = "\n⚠️ <b>WASH TRADING DETECTED</b>" if wash else ""
        bounce_str = "\n🔄 <b>Bounce Potential</b>" if bounce else ""
        bsr_str    = f"{buys}B/{sells}S" if (buys + sells) > 0 else "N/A"

        # Momentum emoji
        if   momentum >= 80: mom_e = "🚀"
        elif momentum >= 60: mom_e = "📈"
        elif momentum >= 40: mom_e = "➡️"
        else:                 mom_e = "📉"

        # Age format
        if age < 1:
            age_str = f"{age*60:.0f}m"
        else:
            age_str = f"{age:.1f}h"

        # ── Build message ─────────────────────────────────
        msg = (
            f"{emoji} <b>{verdict}</b> — {name} (<b>${symbol}</b>) [{pt}]{wash_warn}\n"
            f"\n"
            f"📊 <b>Market</b>\n"
            f"├ Price: <code>${price:.8f}</code>\n"
            f"├ MC: <b>${mc:,.0f}</b>  Liq: ${liq:,.0f}\n"
            f"├ Vol 1h: ${vol1h:,.0f}  Chg: {chg_sign}{chg1h:.1f}%\n"
            f"└ Age: {age_str}  Txn: {bsr_str}\n"
            f"\n"
            f"🔍 <b>On-Chain</b>\n"
            f"├ Risk: {risk:.1f}/10  LP: {lp_str}\n"
            f"├ Top10: {top10_str}  Health: {hh}/100\n"
            f"└ Mint: {mint_str}  Holders: {hcount_str}\n"
            f"\n"
            f"🧠 <b>Sambelikan Analysis</b>\n"
            f"├ Cluster: {cluster} ({cs}/100)  Dev Farm: {dev_f}\n"
            f"├ Smart Money: {sm_str}  Timing: {timing}/100\n"
            f"├ Momentum: {mom_e} {momentum}/100\n"
            f"├ Flags: {flags}  Source: {source}{bounce_str}\n"
            f"\n"
            f"🤖 <b>{dec_action} [{dec_conv}]</b>\n"
            f"└ {dec_reason}\n"
        )

        # Trading plan
        if dec_action in ("ENTER", "WATCH") and plan:
            p    = plan.get("entry", 0)
            tp1  = plan.get("tp1", 0)
            tp2  = plan.get("tp2", 0)
            sl   = plan.get("sl", 0)
            tp1p = plan.get("tp1_pct", 30)
            tp2p = plan.get("tp2_pct", 50)
            slp  = plan.get("sl_pct", 20)
            msg += (
                f"\n"
                f"📈 <b>Trading Plan [{pt}] — MANUAL</b>\n"
                f"├ Entry : <code>${p:.8f}</code>\n"
                f"├ TP1 +{tp1p:.0f}%: <code>${tp1:.8f}</code> → jual 50%\n"
                f"├ TP2 +{tp2p:.0f}%: <code>${tp2:.8f}</code> → jual 40%\n"
                f"└ SL -{slp:.0f}%: <code>${sl:.8f}</code>\n"
            )
            if sizing:
                msg += f"\n💰 {sizing[:100]}\n"

        # Links
        gmgn_url = f"https://gmgn.ai/sol/token/Hanzx0OI_{mint}"
        dex_url  = f"https://dexscreener.com/solana/{mint}"
        rc_url   = f"https://rugcheck.xyz/tokens/{mint}"
        sol_url  = f"https://solscan.io/token/{mint}"

        msg += (
            f"\n"
            f"🔗 <a href='{gmgn_url}'>GMGN</a> | "
            f"<a href='{dex_url}'>DEX</a> | "
            f"<a href='{rc_url}'>RugCheck</a> | "
            f"<a href='{sol_url}'>Solscan</a>"
        )

        return await self.send(msg)

    async def run(self):
        if not self.token:
            log.warning("BOT_TOKEN tidak diset")
            return

        log.info("Telegram bot polling started")
        self._running = True

        # Validasi token
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{self.base_url}/getMe",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as r:
                    data = await r.json()
                    if data.get("ok"):
                        bot_name = data["result"]["username"]
                        log.info(f"Bot valid: @{bot_name}")
                        print(f"\033[92m✅ Bot @{bot_name} siap\033[0m")
                    else:
                        log.error(f"Bot token tidak valid: {data}")
                        return
        except Exception as e:
            log.error(f"Bot check error: {e}")

        if self.chat_id:
            await self._send_startup()
        else:
            print("\033[93m⚠ TELEGRAM_CHAT_ID belum diset — kirim /start ke bot\033[0m")

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
            "🤖 <b>PONYIN AI AGENT v4.2 aktif!</b>\n\n"
            "<b>Commands:</b>\n"
            "/scan — scan token baru sekali\n"
            "/check &lt;CA&gt; — analisis satu token\n"
            "/status — statistik hari ini\n"
            "/log — 10 signal terakhir\n"
            "/help — semua perintah\n\n"
            "Atau <b>paste CA langsung</b> (32+ karakter)\n\n"
            "<i>Fix v4.2: holder count GMGN/Helius priority, auth debug</i>"
        )

    async def _handle_update(self, update: dict):
        msg      = update.get("message", {})
        if not msg:
            return
        from_id   = str(msg.get("from", {}).get("id", ""))
        from_name = msg.get("from", {}).get("first_name", "unknown")
        text      = msg.get("text", "").strip()
        if not text or not from_id:
            return

        # Auto-detect chat_id
        if not self.chat_id:
            self.chat_id = from_id
            log.info(f"Auto-detected chat_id: {from_id} ({from_name})")
            await self.send(
                f"✅ <b>Terhubung!</b>\n\n"
                f"Chat ID: <code>{from_id}</code>\n"
                f"Simpan ke .env:\n<code>TELEGRAM_CHAT_ID={from_id}</code>",
                to_chat_id=from_id
            )
        elif from_id != self.chat_id:
            log.warning(f"Blocked: {from_id} ({from_name})")
            return

        # Parse command
        if text.startswith("/"):
            parts   = text.split(None, 1)
            command = parts[0].split("@")[0].lower()
            args    = parts[1].strip() if len(parts) > 1 else ""
        elif len(text) >= 32 and " " not in text:
            command = "/check"
            args    = text
        else:
            return

        log.info(f"Bot cmd: {command} | args: {args[:24]}")
        await self.on_command(command, args)

    def stop(self):
        self._running = False


def format_status(stats: dict, processed_count: int) -> str:
    total = stats.get("total", 0)
    masuk = stats.get("masuk", 0)
    watch = stats.get("watch", 0)
    skip  = stats.get("skip", 0)
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
        gmgn  = f"https://gmgn.ai/sol/token/Hanzx0OI_{mint}"
        lines.append(
            f"{emoji} <b>${sym}</b> [{pt}] ${mc:,.0f} "
            f"flags:{flags} HH:{hh} "
            f"<a href='{gmgn}'>GMGN</a>\n"
            f"   <i>{ts}</i>"
        )
    return "\n".join(lines)