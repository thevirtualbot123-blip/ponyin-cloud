#!/usr/bin/env python3
"""
PONYIN AI AGENT v3.0 — 24/7 Cloud + Telegram Bot
=================================================
Deploy: Render.com Background Worker (gratis, tidak sleep)

Fitur:
- Monitor signal channel Telegram (Telethon user client)
- Auto scan DexScreener + RugCheck
- Filter ELPonyin + Sambelikan strategies
- Bot Telegram: /scan /check /status /log
- Notif otomatis ke HP kamu saat signal MASUK/WATCH

Setup .env:
  TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE → Telethon
  TELEGRAM_BOT_TOKEN → @BotFather
  TELEGRAM_CHAT_ID   → ID kamu (@userinfobot)
  SIGNAL_CHANNELS    → channel yang dimonitor
"""

import asyncio, sys, os, json, logging
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

G="\033[92m"; RD="\033[91m"; Y="\033[93m"; C="\033[96m"
B="\033[1m";  D="\033[2m";   R="\033[0m"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ]
)
log = logging.getLogger("PONYIN")

from config import AgentConfig
from data_fetcher import DataFetcher
from filter_engine import FilterEngine
from decision_engine import DecisionEngine
from telegram_listener import TelegramListener
from telegram_bot import TelegramBot, format_status, format_log
from display import Display

def banner():
    print(f"""
{C}{B}
╔══════════════════════════════════════════════════════════════════╗
║       PONYIN AI AGENT v3.0 — 24/7 Cloud + Telegram Bot          ║
║  Signal Channel → Filter → Bot Notif → Kamu Eksekusi Manual     ║
╚══════════════════════════════════════════════════════════════════╝{R}
{D}Filter: ELPonyin + Sambelikan (Cluster, Dev Farm, Smart Money, Timing){R}
""")


class PonyinAgent:

    def __init__(self):
        self.cfg      = AgentConfig()
        self.fetcher  = DataFetcher()
        self.filter   = FilterEngine(self.cfg)
        self.decision = DecisionEngine(self.cfg)
        self.display  = Display()

        # Telegram Bot (notif ke kamu)
        self.bot = TelegramBot(
            token=self.cfg.BOT_TOKEN,
            chat_id=self.cfg.BOT_CHAT_ID,
            on_command=self._handle_bot_command,
        )

        # Telegram Listener (baca channel signal)
        self.tg_listener = TelegramListener(self.cfg, self._on_signal)

        self._processed: set = set()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._stats = {"total": 0, "masuk": 0, "watch": 0, "skip": 0}

    # ── Signal masuk ke queue ─────────────────────────────
    async def _on_signal(self, source: str, mint: str, raw_text: str):
        if mint in self._processed:
            return
        self._processed.add(mint)
        await self._queue.put({
            "source": source, "mint": mint,
            "raw": raw_text, "ts": datetime.now().isoformat()
        })

    # ── Process satu signal ───────────────────────────────
    async def process_signal(self, sig: dict, manual: bool = False):
        mint   = sig["mint"]
        source = sig.get("source", "MANUAL")
        raw    = sig.get("raw", "")

        # Terminal output
        print(f"\n{C}{'─'*60}{R}")
        src_label = f"{Y}[MANUAL]{R}" if manual else f"{C}[{source[:20]}]{R}"
        print(f"{src_label} {D}{datetime.now().strftime('%H:%M:%S')}{R}")
        if raw and not manual:
            print(f"{D}{raw[:80]}...{R}" if len(raw)>80 else f"{D}{raw}{R}")
        print(f"{D}Fetching: {mint[:20]}...{R}")

        async with self.fetcher.session() as session:
            token = await self.fetcher.fetch_token(session, mint)
            if not token:
                msg = f"❌ Token tidak ditemukan: <code>{mint}</code>"
                print(f"{RD}Token tidak ditemukan{R}")
                if manual:
                    await self.bot.send(msg)
                return

            token    = self.filter.run(token)
            decision = await self.decision.decide(token, source, raw)

            # Terminal display
            self.display.print_signal(token, decision, source)

            # Update stats
            self._stats["total"] += 1
            v = token.verdict
            if "MASUK" in v:   self._stats["masuk"] += 1
            elif "WATCH" in v: self._stats["watch"] += 1
            else:               self._stats["skip"]  += 1

            # Log
            self._log_signal(token, decision, source)

            # Kirim ke Bot Telegram
            # Kirim notif untuk MASUK, WATCH, dan manual check apapun
            should_notify = (
                manual or
                "MASUK" in token.verdict or
                "WATCH" in token.verdict
            )

            if should_notify and self.cfg.BOT_TOKEN:
                token_dict = token.to_dict()
                token_dict.update({
                    "price":        token.price,
                    "plan":         token.plan,
                    "sizing_note":  token.sizing_note,
                    "source":       source,
                    "dex":          token.dex,
                    "age_hours":    token.age_hours,
                    "mint_auth":    token.mint_auth,
                    "wash_trading": token.wash_trading_flag,
                    "chg1h":        token.chg1h,
                    "chg24h":       token.chg24h,
                    "buys1h":       token.buys1h,
                    "sells1h":      token.sells1h,
                    "lp_burn":      token.lp_burn,
                    "has_twitter":  token.has_twitter,
                    "has_telegram": token.has_telegram,
                })
                dec_dict = {
                    "action":     decision.action,
                    "conviction": decision.conviction,
                    "reason":     decision.reason,
                }
                await self.bot.send_signal(token_dict, dec_dict)

    # ── Handle command dari Bot Telegram ─────────────────
    async def _handle_bot_command(self, command: str, args: str):
        """Proses command dari Telegram bot"""
        log.info(f"Bot command: {command} {args[:30]}")

        if command in ("/start", "/help"):
            await self.bot.send(
                "🤖 <b>PONYIN AI AGENT v3.0</b>\n\n"
                "<b>Commands:</b>\n"
                "/scan — scan token baru sekali\n"
                "/check &lt;CA&gt; — check satu token\n"
                "/status — statistik signal hari ini\n"
                "/log — 10 signal terakhir\n\n"
                "<b>Atau:</b>\n"
                "Kirim CA address langsung (32+ karakter)\n\n"
                "<i>Filter: ELPonyin + Sambelikan\n"
                "Strategi: Cluster, Dev Farm, Smart Money,\n"
                "Timing Score, Position Sizing</i>"
            )

        elif command == "/status":
            await self.bot.send(format_status(self._stats, len(self._processed)))

        elif command == "/log":
            records = self._load_log(10)
            await self.bot.send(format_log(records))

        elif command == "/scan":
            await self.bot.send("🔍 Scanning token baru...")
            try:
                async with self.fetcher.session() as session:
                    mints = await self.fetcher.get_new_token_mints(session)
                    new   = [m for m in mints if m not in self._processed]
                    if not new:
                        await self.bot.send("Tidak ada token baru ditemukan.")
                        return
                    await self.bot.send(f"📡 {len(new)} kandidat baru — menganalisis...")
                    count = 0
                    for mint in new[:10]:
                        await self._queue.put({
                            "source": "MANUAL_SCAN", "mint": mint,
                            "raw": "", "ts": datetime.now().isoformat()
                        })
                        count += 1
                    await self.bot.send(
                        f"✅ {count} token masuk queue untuk dianalisis.\n"
                        f"Hasil akan dikirim otomatis."
                    )
            except Exception as e:
                await self.bot.send(f"❌ Error scan: {str(e)[:100]}")

        elif command in ("/check", "/c"):
            mint = args.strip()
            if len(mint) < 32:
                await self.bot.send(
                    "⚠️ Format salah.\n"
                    "Gunakan: /check &lt;CA address&gt;\n"
                    "Atau kirim CA langsung (32+ karakter)"
                )
                return
            await self.bot.send(f"🔍 Menganalisis: <code>{mint}</code>")
            if mint in self._processed:
                self._processed.discard(mint)  # Force recheck
            await self._queue.put({
                "source": "BOT_MANUAL", "mint": mint,
                "raw": "Manual check via bot", "ts": datetime.now().isoformat()
            })

        else:
            # Mungkin CA address langsung
            if len(command.replace("/","")) >= 32:
                mint = command.replace("/","")
                await self._queue.put({
                    "source": "BOT_MANUAL", "mint": mint,
                    "raw": "Direct CA", "ts": datetime.now().isoformat()
                })
            else:
                await self.bot.send(f"❓ Command tidak dikenal: {command}")

    # ── Consumer loop ─────────────────────────────────────
    async def signal_consumer(self):
        while True:
            sig = await self._queue.get()
            try:
                manual = sig.get("source", "") in ("MANUAL", "BOT_MANUAL", "MANUAL_SCAN")
                await self.process_signal(sig, manual=manual)
            except Exception as e:
                log.error(f"Error processing {sig.get('mint','?')}: {e}")
                if self.cfg.BOT_TOKEN:
                    await self.bot.send(f"⚠️ Error: {str(e)[:100]}")
            finally:
                self._queue.task_done()
            await asyncio.sleep(1.5)

    # ── Auto scan loop ─────────────────────────────────────
    async def scan_loop(self):
        if not self.cfg.AUTO_SCAN_ENABLED:
            while True:
                await asyncio.sleep(3600)
            return
        await asyncio.sleep(20)  # warmup
        log.info(f"Auto scan aktif — interval {self.cfg.SCAN_INTERVAL}s")
        while True:
            try:
                async with self.fetcher.session() as session:
                    mints = await self.fetcher.get_new_token_mints(session)
                    new   = [m for m in mints if m not in self._processed]
                    if new:
                        print(f"{D}[SCAN] {len(new)} kandidat baru{R}")
                        for mint in new[:10]:
                            await self._queue.put({
                                "source": "AUTO_SCAN", "mint": mint,
                                "raw": "", "ts": datetime.now().isoformat()
                            })
            except Exception as e:
                log.error(f"Scan error: {e}")
            await asyncio.sleep(self.cfg.SCAN_INTERVAL)

    # ── Health check HTTP server (untuk Render) ───────────
    async def health_server(self):
        """
        Simple HTTP server untuk Render health check.
        Render Web Service butuh HTTP response.
        Untuk Background Worker tidak perlu, tapi tidak ada salahnya.
        """
        port = int(os.getenv("PORT", "10000"))
        try:
            from aiohttp import web
            app = web.Application()
            app.router.add_get("/", lambda r: web.Response(text="PONYIN AGENT OK"))
            app.router.add_get("/health", lambda r: web.Response(
                text=json.dumps({
                    "status":    "ok",
                    "signals":   self._stats["total"],
                    "processed": len(self._processed),
                    "ts":        datetime.now().isoformat()
                }),
                content_type="application/json"
            ))
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", port)
            await site.start()
            log.info(f"Health server on port {port}")
        except Exception as e:
            log.warning(f"Health server skip: {e}")

    # ── Status periodic ────────────────────────────────────
    async def status_loop(self):
        while True:
            await asyncio.sleep(3600)  # setiap 1 jam
            total = self._stats["total"]
            if total > 0:
                msg = format_status(self._stats, len(self._processed))
                await self.bot.send(f"⏰ <b>Update 1 Jam</b>\n\n{msg}")

    # ── Log helpers ────────────────────────────────────────
    def _log_signal(self, token, decision, source):
        rec = {
            "ts": datetime.now().isoformat(),
            "source": source,
            "mint": token.mint, "name": token.name, "symbol": token.symbol,
            "verdict": token.verdict, "flags": token.flags,
            "mc": token.mc, "liq": token.liq, "vol1h": token.vol1h,
            "price": token.price,
            "top10_pct": token.top10_pct, "risk_norm": token.risk_norm,
            "lp_burn": token.lp_burn,
            "position_type":   getattr(token, "position_type",   "?"),
            "wash_trading":    getattr(token, "wash_trading_flag", False),
            "cluster_risk":    getattr(token, "cluster_risk",     "?"),
            "dev_farm_risk":   getattr(token, "dev_farm_risk",    "?"),
            "smart_money":     getattr(token, "smart_money_present", False),
            "timing_score":    getattr(token, "timing_score",     0),
            "holder_health":   getattr(token, "holder_health",    0),
            "bounce_potential":getattr(token, "bounce_potential", False),
            "plan": token.plan,
            "sizing_note": getattr(token, "sizing_note", ""),
            "decision": decision.action, "conviction": decision.conviction,
            "reason": decision.reason,
            "dex_link": f"https://dexscreener.com/solana/{token.mint}",
        }
        with open("agent_signals.json", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def _load_log(self, n: int = 10) -> list:
        try:
            with open("agent_signals.json") as f:
                lines = [json.loads(l) for l in f if l.strip()]
            return lines[-n:]
        except Exception:
            return []

    # ── Terminal input (jika dijalankan lokal) ─────────────
    async def input_loop(self):
        """Input loop untuk penggunaan lokal (tidak aktif di Render)"""
        is_render = os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID")
        if is_render:
            # Di Render tidak ada stdin interaktif
            while True:
                await asyncio.sleep(3600)
            return

        print(f"\n{G}Ketik CA untuk manual check, 'scan', 'status', atau 'quit'{R}")
        loop = asyncio.get_event_loop()
        while True:
            try:
                raw = await loop.run_in_executor(
                    None, lambda: input(f"\n{B}{C}Ponyin>{R} ").strip()
                )
            except (EOFError, KeyboardInterrupt):
                break
            if not raw: continue
            cmd = raw.lower()
            if cmd in ("quit","q"):
                sys.exit(0)
            elif cmd == "scan":
                await self._handle_bot_command("/scan", "")
            elif cmd == "status":
                print(format_status(self._stats, len(self._processed)))
            elif cmd == "log":
                recs = self._load_log(10)
                for r in recs:
                    v  = r.get("verdict","?")
                    sym= r.get("symbol","?")
                    mc = r.get("mc",0)
                    ts = r.get("ts","")[:16]
                    print(f"  {sym:<10} ${mc:>8,.0f} {v[:6]} {ts}")
            elif len(raw) >= 32:
                await self._handle_bot_command("/check", raw)
            else:
                print(f"{Y}Tidak dikenal. Ketik CA/scan/status/quit{R}")

    # ── Main run ───────────────────────────────────────────
    async def run(self):
        banner()

        is_render = bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"))
        print(f"{G}PONYIN AGENT v3.0 starting...{R}")
        print(f"  Mode       : {'☁ Render Cloud' if is_render else '💻 Local'}")
        print(f"  Auto scan  : {'ON ('+str(self.cfg.SCAN_INTERVAL)+'s)' if self.cfg.AUTO_SCAN_ENABLED else 'OFF'}")
        print(f"  Bot token  : {'✓ Set' if self.cfg.BOT_TOKEN else '✗ Tidak ada'}")
        print(f"  Signal ch  : {', '.join(self.cfg.SIGNAL_CHANNELS) or 'none'}")
        print(f"  AI         : {'ON' if self.cfg.AI_ENABLED else 'OFF (rule-based)'}")
        print()

        tasks = [
            asyncio.create_task(self.signal_consumer(), name="consumer"),
            asyncio.create_task(self.scan_loop(),       name="scanner"),
            asyncio.create_task(self.status_loop(),     name="status_loop"),
            asyncio.create_task(self.health_server(),   name="health"),
            asyncio.create_task(self.input_loop(),      name="input"),
        ]

        # Bot Telegram (notif ke kamu)
        if self.cfg.BOT_TOKEN:
            tasks.append(asyncio.create_task(self.bot.run(), name="tg_bot"))
            print(f"{G}✅ Telegram Bot aktif{R}")
        else:
            print(f"{Y}⚠  BOT_TOKEN tidak ada — notif bot disabled{R}")
            print(f"   Set TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID di .env")

        # Telethon listener (baca channel signal)
        if self.cfg.TG_API_ID and self.cfg.TG_API_HASH:
            tasks.append(asyncio.create_task(self.tg_listener.run(), name="tg_listener"))
            print(f"{G}✅ Telegram channel listener aktif{R}")
        else:
            print(f"{Y}⚠  TG credentials tidak ada — channel listener disabled{R}")

        print(f"\n{G}{B}🚀 AGENT AKTIF 24/7{R}\n")

        try:
            await asyncio.gather(*tasks)
        except SystemExit:
            pass
        except Exception as e:
            log.error(f"Fatal: {e}")
            if self.cfg.BOT_TOKEN:
                await self.bot.send(f"🚨 Agent error: {str(e)[:100]}\nRestarting...")
            raise


if __name__ == "__main__":
    agent = PonyinAgent()
    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        print(f"\n{Y}Agent dihentikan.{R}")
