"""
telegram_bot.py — PONYIN AI AGENT v4.2
Fixes:
  - run() sekarang benar-benar polling getUpdates (sebelumnya stub `pass`)
  - send_signal() sekarang benar-benar format & kirim signal (sebelumnya stub `return True`)
  - stop() set flag berhenti
"""
import asyncio, json, logging
from datetime import datetime
from typing import Callable, Awaitable

log = logging.getLogger("PONYIN.Bot")


def _fp(p: float) -> str:
    """Format harga."""
    if p <= 0: return "$0"
    if p < 0.00001: return f"${p:.10f}"
    if p < 0.001:   return f"${p:.8f}"
    if p < 1:       return f"${p:.6f}"
    return f"${p:.4f}"


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
                        "text":                     text[:4096],
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
        """Format dan kirim signal lengkap ke Telegram."""
        t = token_data
        d = decision

        verdict  = t.get("verdict", "?")
        if "MASUK" in verdict:   emoji, label = "✅", "MASUK"
        elif "WATCH" in verdict: emoji, label = "⚠️", "WATCH"
        else:                    emoji, label = "❌", "SKIP"

        action     = d.get("action",     "?")
        conviction = d.get("conviction", "?")
        reason     = d.get("reason",     "")

        mint   = t.get("mint",    "")
        name   = t.get("name",    "Unknown")
        symbol = t.get("symbol",  "???")
        mc     = t.get("mc",      0)
        liq    = t.get("liq",     0)
        vol1h  = t.get("vol1h",   0)
        price  = t.get("price",   0)
        chg1h  = t.get("chg1h",   0)
        chg5m  = t.get("chg5m",   0)
        age_h  = t.get("age_hours", 0)
        risk   = t.get("risk_norm", 0)
        lp     = t.get("lp_burn",   0)
        top10  = t.get("top10_pct", 0)
        top10s = t.get("top10_source", "N/A")
        flags  = t.get("flags",     0)
        bch    = t.get("dex",       "")
        buys   = t.get("buys1h",    0)
        sells  = t.get("sells1h",   0)

        chg1h_s = f"{'🟢' if chg1h >= 0 else '🔴'}{chg1h:+.1f}%"
        chg5m_s = f"{'▲' if chg5m >= 0 else '▼'}{abs(chg5m):.1f}%"
        age_s   = f"{age_h*60:.0f}m" if age_h < 1 else f"{age_h:.1f}h"

        lp_s   = ("100% 🔥burned" if t.get("gmgn_lp_burned")
                  else (f"{lp:.0f}%" if lp > 0 else "0% ⚠️"))
        top10_s = f"{top10:.1f}% ({top10s})" if top10 > 0 else "N/A ⚠️"
        mint_s  = "🔴 ACTIVE" if t.get("mint_auth") else "✅ Revoked"

        soc = []
        if t.get("has_twitter"):  soc.append("🐦TW")
        if t.get("has_telegram"): soc.append("✈️TG")
        if t.get("has_website"):  soc.append("🌐Web")
        soc_s = " ".join(soc) if soc else "None"

        txn_s = f"{buys}B/{sells}S" if (buys or sells) else "N/A"

        action_emoji = "🚀" if action == "ENTER" else ("👀" if action == "WATCH" else "⏭")

        msg = (
            f"{emoji} <b>{label}</b>  —  <b>{name} (${symbol})</b>\n"
            f"<code>{mint}</code>\n"
        )
        if t.get("wash_trading_flag"):
            msg += f"🚨 <b>WASH TRADING:</b> {t.get('wash_trading_reason','')[:60]}\n"

        msg += (
            f"\n📊 <b>MARKET</b>\n"
            f"Price : <b>{_fp(price)}</b>\n"
            f"MC    : <b>${mc:,.0f}</b>  |  Liq: ${liq:,.0f}\n"
            f"Vol1h : ${vol1h:,.0f}  |  Txn: {txn_s}\n"
            f"Chg1h : {chg1h_s}  |  5m: {chg5m_s}  |  Age: {age_s}\n"
            f"DEX   : {bch}\n"
            f"\n🔐 <b>ON-CHAIN</b>\n"
            f"Risk  : <b>{risk}/10</b>  |  LP: {lp_s}\n"
            f"Top10 : {top10_s}\n"
            f"Mint  : {mint_s}\n"
            f"Social: {soc_s}\n"
        )

        # Tambah info holder/smart money jika ada
        hc = t.get("holder_count_gmgn") or t.get("holder_count_rc") or 0
        if hc:
            msg += f"Holders: {hc}\n"
        if t.get("smart_money_present"):
            msg += f"💎 Smart Money: {t.get('smart_money_pct',0):.1f}%\n"
        if t.get("bundle_pct", 0) > 0:
            msg += f"📦 Bundle: {t.get('bundle_pct',0):.1f}%\n"

        msg += (
            f"\n{action_emoji} <b>[{conviction}] {action}</b>  "
            f"Flags: {flags}\n"
            f"<i>{reason[:150]}</i>\n"
        )

        plan = t.get("plan") or {}
        if plan and action in ("ENTER", "WATCH") and price > 0:
            tp1_pct = plan.get("tp1_pct", 30)
            tp2_pct = plan.get("tp2_pct", 50)
            sl_pct  = plan.get("sl_pct", 20)
            msg += (
                f"\n📋 <b>TRADING PLAN</b> (eksekusi MANUAL)\n"
                f"Entry : {_fp(plan.get('entry', price))}\n"
                f"🟢 TP1 +{tp1_pct:.0f}%: {_fp(plan.get('tp1', 0))} → jual 50%\n"
                f"🟢 TP2 +{tp2_pct:.0f}%: {_fp(plan.get('tp2', 0))} → jual 40%\n"
                f"🌙 Moonbag: 10%\n"
                f"🔴 SL  -{sl_pct:.0f}%: {_fp(plan.get('sl', 0))} → cut loss\n"
            )
        if t.get("sizing_note"):
            msg += f"💼 Sizing: {t.get('sizing_note','')}\n"

        msg += (
            f"\n"
            f"<a href='https://dexscreener.com/solana/{mint}'>📈 DexScreener</a>  "
            f"<a href='https://rugcheck.xyz/tokens/{mint}'>🛡 RugCheck</a>  "
            f"<a href='https://gmgn.ai/sol/token/{mint}'>💹 GMGN</a>\n"
            f"<i>{datetime.now().strftime('%H:%M:%S')} UTC</i>"
        )

        return await self.send(msg)

    async def run(self):
        """
        Long-polling loop untuk terima command dari user.
        FIX: sebelumnya ini stub `pass` — bot tidak pernah menerima command apapun!
        """
        if not self.token:
            log.warning("Bot token tidak ada — polling dinonaktifkan")
            return

        self._running = True
        log.info("Bot polling started")

        import aiohttp

        while self._running:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(
                        f"{self.base_url}/getUpdates",
                        params={
                            "offset":           self._offset,
                            "timeout":          30,
                            "allowed_updates":  json.dumps(["message"]),
                        },
                        timeout=aiohttp.ClientTimeout(total=35),
                    ) as r:
                        if r.status == 401:
                            log.error("Bot token tidak valid!")
                            return
                        if r.status != 200:
                            log.warning(f"getUpdates HTTP {r.status}")
                            await asyncio.sleep(5)
                            continue

                        data = await r.json()
                        updates = data.get("result") or []

                        for upd in updates:
                            self._offset = upd["update_id"] + 1
                            msg   = upd.get("message") or {}
                            text  = (msg.get("text") or "").strip()
                            chat  = str((msg.get("chat") or {}).get("id", ""))
                            from_ = str((msg.get("from") or {}).get("id", ""))

                            # Keamanan: hanya respon ke chat yang diotorisasi
                            if self.chat_id and chat != self.chat_id and from_ != self.chat_id:
                                log.debug(f"Ignored msg from unauthorized chat {chat}")
                                continue

                            if not text:
                                continue

                            # Parse command dan argumen
                            parts = text.split(None, 1)
                            cmd   = parts[0].lower()
                            args  = parts[1].strip() if len(parts) > 1 else ""

                            # CA langsung (bukan command slash)
                            if (not text.startswith("/") and
                                    len(text) >= 32 and " " not in text):
                                cmd, args = text, ""

                            try:
                                await self.on_command(cmd, args)
                            except Exception as e:
                                log.error(f"on_command error: {e}", exc_info=True)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Bot polling error: {e}")
                await asyncio.sleep(5)

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
        gmgn  = f"https://gmgn.ai/sol/token/{mint}"
        lines.append(
            f"{emoji} <b>${sym}</b> [{pt}] ${mc:,.0f} "
            f"flags:{flags} HH:{hh} "
            f"<a href='{gmgn}'>GMGN</a>\n"
            f"   <i>{ts}</i>"
        )
    return "\n".join(lines)
