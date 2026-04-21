#!/usr/bin/env python3
"""
PONYIN AI AGENT v3.1 — FIXED
==============================
Fix:
  - sizing_note error → filter_engine selalu set field ini
  - Auto scan TIDAK jalan kecuali diberi command atau ada signal dari channel
  - Deduplication: token yang sama tidak diproses ulang dalam 30 menit
  - Bot notif hanya kirim MASUK/WATCH (bukan SKIP)
  - Tidak ada loop yang trigger scan sendiri
"""

import asyncio, sys, os, json, logging
from datetime import datetime, timedelta

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
║       PONYIN AI AGENT v3.1 — Signal Only + Telegram Bot         ║
║  Channel Signal / Manual Command → Filter → Notif ke HP         ║
╚══════════════════════════════════════════════════════════════════╝{R}
{D}Filter: ELPonyin + Sambelikan | SIGNAL ONLY — eksekusi manual{R}
""")


class PonyinAgent:

    def __init__(self):
        self.cfg      = AgentConfig()
        self.fetcher  = DataFetcher()
        self.filter   = FilterEngine(self.cfg)
        self.decision = DecisionEngine(self.cfg)
        self.display  = Display()
        self.bot      = TelegramBot(
            token=self.cfg.BOT_TOKEN,
            chat_id=self.cfg.BOT_CHAT_ID,
            on_command=self._handle_bot_command,
        )
        self.tg_listener = TelegramListener(self.cfg, self._on_signal)

        # Deduplication: {mint: datetime_terakhir_diproses}
        self._processed: dict = {}
        self._DEDUP_MINUTES   = 30  # token sama tidak diproses ulang dalam 30 menit

        self._queue = asyncio.Queue()
        self._stats = {"total": 0, "masuk": 0, "watch": 0, "skip": 0}

    def _is_duplicate(self, mint: str) -> bool:
        """Cek apakah token sudah diproses dalam DEDUP_MINUTES terakhir."""
        if mint not in self._processed:
            return False
        last = self._processed[mint]
        age  = (datetime.now() - last).total_seconds() / 60
        return age < self._DEDUP_MINUTES

    def _mark_processed(self, mint: str):
        self._processed[mint] = datetime.now()

    # ── Signal callback dari Telegram listener ────────────
    async def _on_signal(self, source: str, mint: str, raw_text: str):
        """Hanya dipanggil saat ada pesan baru di channel signal."""
        if self._is_duplicate(mint):
            log.debug(f"Dedup skip: {mint[:12]} (baru diproses)")
            return
        self._mark_processed(mint)
        await self._queue.put({
            "source": source, "mint": mint,
            "raw": raw_text, "ts": datetime.now().isoformat(),
            "manual": False,
        })

    # ── Process satu signal ───────────────────────────────
    async def process_signal(self, sig: dict):
        mint   = sig["mint"]
        source = sig.get("source", "MANUAL")
        raw    = sig.get("raw", "")
        manual = sig.get("manual", False)

        print(f"\n{C}{'─'*60}{R}")
        src_label = f"{Y}[MANUAL]{R}" if manual else f"{C}[{source[:25]}]{R}"
        print(f"{src_label} {D}{datetime.now().strftime('%H:%M:%S')}{R}")
        if raw and not manual:
            preview = raw[:80] + "..." if len(raw) > 80 else raw
            print(f"{D}{preview}{R}")
        print(f"{D}Fetching: {mint[:24]}...{R}")

        async with self.fetcher.session() as session:
            token = await self.fetcher.fetch_token(session, mint)
            if not token:
                msg = f"❌ Token tidak ditemukan:\n<code>{mint}</code>"
                print(f"{RD}Token tidak ditemukan.{R}")
                if manual:
                    await self.bot.send(msg)
                return

            # Filter + decision
            token    = self.filter.run(token)
            decision = await self.decision.decide(token, source, raw)

            # Display terminal
            self.display.print_signal(token, decision, source)

            # Stats
            self._stats["total"] += 1
            v = token.verdict
            if "MASUK" in v:   self._stats["masuk"] += 1
            elif "WATCH" in v: self._stats["watch"] += 1
            else:               self._stats["skip"]  += 1

            # Log ke file
            self._log_signal(token, decision, source)

            # Kirim ke bot Telegram:
            # - Manual check: selalu kirim detail lengkap
            # - Channel signal MASUK/WATCH: kirim detail lengkap
            # - Channel signal SKIP: kirim notif SINGKAT saja (1 baris)
            #   agar user bisa lihat dan putuskan sendiri
            from_channel = source.startswith("TG:")

            if (manual or "MASUK" in v or "WATCH" in v) and self.cfg.BOT_TOKEN:
                token_dict = {**token.to_dict()}
                dec_dict   = {
                    "action":     decision.action,
                    "conviction": decision.conviction,
                    "reason":     decision.reason,
                }
                await self.bot.send_signal(token_dict, dec_dict)

            elif "SKIP" in v and from_channel and self.cfg.BOT_TOKEN:
                # SKIP dari channel signal: kirim ringkasan singkat
                # Agar user bisa cross-check sendiri
                top_flag = next(
                    (d.step for d in token.filter_details if d.passed is False),
                    "multiple flags"
                )
                skip_msg = (
                    f"⏭ <b>SKIP</b> — {token.name} (${token.symbol}) "
                    f"[{token.position_type}]
"
                    f"MC: ${token.mc:,.0f} | Flags: {token.flags} "
                    f"| Top flag: {top_flag}
"
                    f"<a href='https://dexscreener.com/solana/{token.mint}'>DEX</a> | "
                    f"<a href='https://rugcheck.xyz/tokens/{token.mint}'>RugCheck</a>"
                )
                await self.bot.send(skip_msg)

    # ── Consumer loop ─────────────────────────────────────
    async def signal_consumer(self):
        """Proses queue signal satu per satu, tidak spam."""
        while True:
            sig = await self._queue.get()
            try:
                await self.process_signal(sig)
            except Exception as e:
                log.error(f"Error process signal: {e}", exc_info=True)
                if self.cfg.BOT_TOKEN and sig.get("manual"):
                    await self.bot.send(f"⚠️ Error: {str(e)[:120]}")
            finally:
                self._queue.task_done()
            await asyncio.sleep(1.5)  # jeda antar pemrosesan

    # ── TIDAK ADA auto scan loop! ─────────────────────────
    # Scan hanya terjadi jika:
    # 1. Ada pesan di channel signal (via TelegramListener)
    # 2. User kirim /scan atau /check ke bot
    # Ini mencegah spam notif setiap menit

    # ── Handle command dari bot ───────────────────────────
    async def _handle_bot_command(self, command: str, args: str):
        log.info(f"Bot cmd: {command} args={args[:30]}")

        if command in ("/start", "/help"):
            await self.bot.send(
                "🤖 <b>PONYIN AI AGENT v3.1</b>\n\n"
                "<b>Commands:</b>\n"
                "/scan — scan token baru sekali\n"
                "/check &lt;CA&gt; — analisis satu token\n"
                "/status — statistik hari ini\n"
                "/log — 10 signal terakhir\n"
                "/help — perintah ini\n\n"
                "Atau <b>paste CA (32+ karakter)</b> langsung\n\n"
                "<i>Bot hanya kirim notif MASUK/WATCH.\n"
                "SKIP tidak dikirim agar tidak spam.\n"
                "Eksekusi tetap manual kamu.</i>"
            )

        elif command == "/status":
            await self.bot.send(format_status(self._stats, len(self._processed)))

        elif command == "/log":
            records = self._load_log(10)
            await self.bot.send(format_log(records))

        elif command == "/scan":
            await self.bot.send("🔍 <b>Scanning token baru sekali...</b>")
            try:
                async with self.fetcher.session() as session:
                    mints = await self.fetcher.get_new_token_mints(session)
                    new   = [m for m in mints if not self._is_duplicate(m)]
                    if not new:
                        await self.bot.send("✅ Tidak ada token baru saat ini.")
                        return
                    await self.bot.send(
                        f"📡 {len(new)} kandidat ditemukan.\n"
                        f"Hanya MASUK/WATCH yang dikirim."
                    )
                    for mint in new[:15]:
                        self._mark_processed(mint)
                        await self._queue.put({
                            "source": "CMD_SCAN",
                            "mint": mint,
                            "raw": "",
                            "ts": datetime.now().isoformat(),
                            "manual": False,
                        })
            except Exception as e:
                await self.bot.send(f"❌ Error scan: {str(e)[:100]}")

        elif command in ("/check", "/c"):
            mint = args.strip()
            if len(mint) < 32:
                await self.bot.send(
                    "⚠️ Format: /check &lt;CA address&gt;\n"
                    "Atau paste CA langsung (32+ karakter)"
                )
                return
            await self.bot.send(f"🔍 Menganalisis...\n<code>{mint}</code>")
            # Force recheck (hapus dari dedup)
            self._processed.pop(mint, None)
            await self._queue.put({
                "source": "BOT_CHECK",
                "mint": mint,
                "raw": "Manual check",
                "ts": datetime.now().isoformat(),
                "manual": True,  # selalu kirim hasilnya
            })

        else:
            # Mungkin langsung CA
            ca = command.lstrip("/").strip()
            if len(ca) >= 32 and " " not in ca:
                await self.bot.send(f"🔍 Menganalisis...\n<code>{ca}</code>")
                self._processed.pop(ca, None)
                await self._queue.put({
                    "source": "BOT_DIRECT",
                    "mint": ca,
                    "raw": "Direct CA",
                    "ts": datetime.now().isoformat(),
                    "manual": True,
                })
            else:
                await self.bot.send(f"❓ Command tidak dikenal: {command}\nKetik /help")

    # ── Health server (untuk Railway/Render) ──────────────
    async def health_server(self):
        port = int(os.getenv("PORT", "8080"))
        try:
            from aiohttp import web
            app = web.Application()
            app.router.add_get("/", lambda r: web.Response(text="PONYIN OK"))
            app.router.add_get("/health", lambda r: web.Response(
                text=json.dumps({
                    "status": "ok",
                    "signals": self._stats["total"],
                    "processed": len(self._processed),
                }),
                content_type="application/json"
            ))
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, "0.0.0.0", port).start()
            log.info(f"Health server: port {port}")
        except Exception as e:
            log.warning(f"Health server skip: {e}")

    # ── Hourly summary (opsional, tidak spam) ─────────────
    async def hourly_summary(self):
        """Kirim summary ke bot setiap 1 jam — hanya jika ada signal."""
        while True:
            await asyncio.sleep(3600)
            if self._stats["total"] > 0:
                await self.bot.send(
                    f"⏰ <b>Update 1 Jam</b>\n\n"
                    + format_status(self._stats, len(self._processed))
                )

    # ── Log helpers ───────────────────────────────────────
    def _log_signal(self, token, decision, source):
        rec = {
            "ts": datetime.now().isoformat(),
            "source": source,
            "mint": token.mint,
            "name": token.name,
            "symbol": token.symbol,
            "verdict": token.verdict,
            "flags": token.flags,
            "mc": token.mc,
            "liq": token.liq,
            "vol1h": token.vol1h,
            "price": token.price,
            "top10_pct": token.top10_pct,
            "risk_norm": token.risk_norm,
            "lp_burn": token.lp_burn,
            "position_type": token.position_type,
            "wash_trading": token.wash_trading_flag,
            "cluster_risk": token.cluster_risk,
            "dev_farm_risk": token.dev_farm_risk,
            "smart_money": token.smart_money_present,
            "timing_score": token.timing_score,
            "holder_health": token.holder_health,
            "bounce_potential": token.bounce_potential,
            "sizing_note": token.sizing_note,
            "plan": token.plan,
            "decision": decision.action,
            "conviction": decision.conviction,
            "reason": decision.reason,
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

    # ── Terminal input (lokal saja) ───────────────────────
    async def input_loop(self):
        is_cloud = bool(os.getenv("RENDER") or os.getenv("RAILWAY_ENVIRONMENT")
                        or os.getenv("RAILWAY_SERVICE_ID"))
        if is_cloud:
            while True:
                await asyncio.sleep(3600)
            return

        print(f"\n{G}Ketik CA, 'scan', 'status', 'log', atau 'quit'{R}")
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

            if cmd in ("quit", "q"):
                print(f"{Y}Agent dihentikan.{R}")
                sys.exit(0)
            elif cmd == "scan":
                await self._handle_bot_command("/scan", "")
            elif cmd == "status":
                print(format_status(self._stats, len(self._processed)))
            elif cmd == "log":
                for r in self._load_log(10):
                    v = r.get("verdict","?")
                    vc = G if "MASUK" in v else (Y if "WATCH" in v else D)
                    print(f"  {vc}{r.get('symbol','?'):<10}{R} "
                          f"${r.get('mc',0):>8,.0f} {v[:6]} "
                          f"{r.get('ts','')[:16]}")
            elif len(raw) >= 32 and " " not in raw:
                await self._handle_bot_command("/check", raw)
            else:
                print(f"{Y}Tidak dikenal. Ketik CA/scan/status/log/quit{R}")

    # ── Main run ──────────────────────────────────────────
    async def run(self):
        banner()

        is_cloud = bool(os.getenv("RENDER") or os.getenv("RAILWAY_ENVIRONMENT"))
        print(f"{G}PONYIN AGENT v3.1 starting...{R}")
        print(f"  Mode       : {'☁ Cloud' if is_cloud else '💻 Local'}")
        print(f"  Bot token  : {'✓ Set' if self.cfg.BOT_TOKEN else '✗ Tidak ada'}")
        print(f"  Signal ch  : {', '.join(self.cfg.SIGNAL_CHANNELS) or 'none'}")
        print(f"  AI         : {'ON' if self.cfg.AI_ENABLED else 'OFF (rule-based)'}")
        print(f"  Auto scan  : OFF (hanya jalan via /scan command atau channel signal)")
        print()

        tasks = [
            asyncio.create_task(self.signal_consumer(), name="consumer"),
            asyncio.create_task(self.health_server(),   name="health"),
            asyncio.create_task(self.hourly_summary(),  name="hourly"),
            asyncio.create_task(self.input_loop(),      name="input"),
        ]

        if self.cfg.BOT_TOKEN:
            tasks.append(asyncio.create_task(self.bot.run(), name="tg_bot"))
            print(f"{G}✅ Telegram Bot aktif{R}")
        else:
            print(f"{Y}⚠  BOT_TOKEN tidak ada{R}")

        if self.cfg.TG_API_ID and self.cfg.TG_API_HASH:
            tasks.append(asyncio.create_task(
                self.tg_listener.run(), name="tg_listener"
            ))
            print(f"{G}✅ Channel listener aktif{R}")
        else:
            print(f"{Y}⚠  TG credentials tidak ada — channel listener off{R}")

        print(f"\n{G}{B}🚀 AGENT AKTIF{R}\n")

        try:
            await asyncio.gather(*tasks)
        except SystemExit:
            pass
        except Exception as e:
            log.error(f"Fatal: {e}", exc_info=True)
            await self.bot.send(f"🚨 Agent crash: {str(e)[:100]}")
            raise


if __name__ == "__main__":
    agent = PonyinAgent()
    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        print(f"\n{Y}Agent dihentikan.{R}")
