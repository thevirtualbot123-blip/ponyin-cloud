"""
data_fetcher.py — PONYIN AI AGENT v6.0 (with GMGN + legacy scan endpoints)
"""
import asyncio, aiohttp, logging, re
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, List
from filter_engine import Token

log = logging.getLogger("PONYIN.Fetcher")
HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}
CA_PATTERN = re.compile(r'[1-9A-HJ-NP-Za-km-z]{32,44}')


class DataFetcher:

    def __init__(self, cfg=None):
        from config import AgentConfig
        self.cfg = cfg or AgentConfig()

    @asynccontextmanager
    async def session(self):
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as sess:
            yield sess

    async def _get(self, session, url, headers=HDR, timeout=10):
        try:
            async with session.get(url, headers=headers, timeout=timeout) as r:
                if r.status == 200:
                    return await r.json(content_type=None)
                log.debug(f"HTTP {r.status}: {url[:60]}")
                return None
        except asyncio.TimeoutError:
            log.debug(f"Timeout: {url[:60]}")
            return None
        except Exception as e:
            log.debug(f"Fetch error {url[:60]}: {e}")
            return None

    # ── DexScreener ─────────────────────────────────────
    async def dex_token(self, session, mint: str) -> Optional[dict]:
        return await self._get(
            session, f"https://api.dexscreener.com/tokens/v1/solana/{mint}"
        )

    # ── GMGN API (public demo key – free) ───────────────
    async def gmgn_token_info(self, session, mint: str) -> Optional[dict]:
        url = f"https://gmgn.ai/defi/quotation/v1/token/sol/{mint}"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "x-api-key": "gmgn_solbscbaseethmonadtron",
        }
        try:
            async with session.get(url, headers=headers, timeout=12) as r:
                if r.status == 200:
                    data = await r.json()
                    if data.get("code") == 0 and data.get("data"):
                        return data["data"]
                    log.debug(f"GMGN API code={data.get('code')} msg={data.get('msg')}")
                else:
                    log.debug(f"GMGN HTTP {r.status}")
        except Exception as e:
            log.debug(f"GMGN token info error: {e}")
        return None

    def _apply_gmgn_data(self, t: Token, data: dict) -> Token:
        t.gmgn_data = data

        top10 = data.get("top_10_holder_pct")
        if top10 is not None and 0 < top10 <= 100:
            t.top10_pct = round(float(top10), 1)
            t.top10_source = "GMGN"

        hc = data.get("holder_count")
        if hc:
            t.holder_count_gmgn = int(hc)

        dev = data.get("dev_hold_pct")
        if dev is not None:
            t.dev_hold_pct = float(dev)

        bundle = data.get("bundle_pct") or data.get("bundler_trader_amount_rate")
        if bundle is not None:
            t.bundle_pct = float(bundle)

        sniper = data.get("sniper_count")
        if sniper is not None:
            t.sniper_count = int(sniper)

        smart = data.get("smart_degen_count")
        if smart is not None:
            t.smart_money_count = int(smart)
            t.smart_money_present = int(smart) > 0

        kol = data.get("renowned_wallets")
        if kol is not None:
            t.kol_holders = int(kol)

        t.is_honeypot = bool(data.get("is_honeypot"))
        t.rug_ratio = float(data.get("rug_ratio") or 0)
        t.wash_trade_gmgn = bool(data.get("wash_trade_flag"))
        t.fresh_wallet_rate = float(data.get("fresh_wallet_rate") or 0)
        t.rat_trader_rate = float(data.get("rat_trader_amount_rate") or 0)
        return t

    # ── RugCheck ─────────────────────────────────────────
    async def rugcheck_full(self, session, mint: str) -> Optional[dict]:
        return await self._get(
            session, f"https://api.rugcheck.xyz/v1/tokens/{mint}/report"
        )

    # ── Discovery (new mints) ───────────────────────────
    async def get_new_token_mints(self, session) -> List[str]:
        profiles, boosted, rc_new = await asyncio.gather(
            self.dex_latest_profiles(session),
            self.dex_boosted(session),
            self.rc_new_tokens(session),
            return_exceptions=True,
        )
        mints = []
        for src in (profiles, boosted, rc_new):
            if isinstance(src, list):
                for item in src:
                    m = item.get("tokenAddress") or item.get("mint") or ""
                    if m:
                        mints.append(m)
        return list(dict.fromkeys(mints))[:25]

    async def dex_latest_profiles(self, session) -> list:
        d = await self._get(session, "https://api.dexscreener.com/token-profiles/latest/v1")
        return [x for x in (d or []) if x.get("chainId") == "solana"]

    async def dex_boosted(self, session) -> list:
        d = await self._get(session, "https://api.dexscreener.com/token-boosts/latest/v1")
        return [x for x in (d or []) if x.get("chainId") == "solana"]

    async def rc_new_tokens(self, session) -> list:
        d = await self._get(session, "https://api.rugcheck.xyz/v1/stats/new_tokens")
        return d if isinstance(d, list) else []

    # ── Fetch utama ─────────────────────────────────────
    async def fetch_token(self, session, mint: str) -> Optional[Token]:
        dex_data = await self.dex_token(session, mint)
        token = self._parse_dex(dex_data)
        if not token:
            return None

        gmgn_data = await self.gmgn_token_info(session, mint)
        rc_data = await self.rugcheck_full(session, mint)

        if gmgn_data:
            token = self._apply_gmgn_data(token, gmgn_data)
        if rc_data:
            token = self._apply_rugcheck(token, rc_data)

        return token

    # ── Parse helpers ────────────────────────────────────
    def _parse_socials(self, pair):
        tw = tg = web = False
        info = pair.get("info") or {}
        for s in info.get("socials") or []:
            t_url = (s.get("type") or "").lower()
            url = (s.get("url") or "").lower()
            if t_url in ("twitter", "x") or "twitter.com" in url or "x.com" in url:
                tw = True
            if t_url == "telegram" or "t.me" in url:
                tg = True
        for w in info.get("websites") or []:
            url = (w.get("url") or "").lower()
            if url:
                web = True
            if "twitter.com" in url or "x.com" in url:
                tw = True
            if "t.me" in url:
                tg = True
        for k in ("twitter", "twitterUrl"):
            if pair.get(k):
                tw = True
        for k in ("telegram", "telegramUrl"):
            if pair.get(k):
                tg = True
        for k in ("website", "websiteUrl"):
            if pair.get(k):
                web = True
        return tw, tg, web

    def _parse_pair(self, pair):
        try:
            base = pair.get("baseToken") or {}
            mint = base.get("address", "")
            if not mint or len(mint) < 30:
                return None

            price = float(pair.get("priceUsd") or 0)
            mc = float(pair.get("marketCap") or pair.get("fdv") or 0)
            liq = float((pair.get("liquidity") or {}).get("usd") or 0)
            vol = pair.get("volume") or {}
            pc = pair.get("priceChange") or {}
            txns = pair.get("txns") or {}
            h1 = txns.get("h1") or {}

            cr = pair.get("pairCreatedAt") or 0
            if cr:
                cd = datetime.fromtimestamp(cr / 1000)
                created = cd.strftime("%Y-%m-%d %H:%M")
                age_h = (datetime.now() - cd).total_seconds() / 3600
            else:
                created, age_h = "unknown", 0.0

            tw, tg, web = self._parse_socials(pair)

            return Token(
                mint=mint,
                name=base.get("name", "Unknown"),
                symbol=base.get("symbol", "???"),
                price=price,
                mc=mc,
                liq=liq,
                vol1h=float(vol.get("h1") or 0),
                vol6h=float(vol.get("h6") or 0),
                vol24h=float(vol.get("h24") or 0),
                chg1h=float(pc.get("h1") or 0),
                chg6h=float(pc.get("h6") or 0),
                chg24h=float(pc.get("h24") or 0),
                buys1h=int(h1.get("buys") or 0),
                sells1h=int(h1.get("sells") or 0),
                has_twitter=tw,
                has_telegram=tg,
                has_website=web,
                dex=pair.get("dexId", ""),
                pair_addr=pair.get("pairAddress", ""),
                created=created,
                age_hours=age_h,
            )
        except Exception as e:
            log.debug(f"Parse pair error: {e}")
            return None

    def _parse_dex(self, data):
        if not data:
            return None
        pairs = data if isinstance(data, list) else data.get("pairs") or []
        if not pairs:
            return None
        sol = [p for p in pairs if isinstance(p, dict) and p.get("chainId") == "solana"]
        pool = sol or [p for p in pairs if isinstance(p, dict)]
        if not pool:
            return None
        best = max(pool, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))
        return self._parse_pair(best)

    def _apply_rugcheck(self, t: Token, rc: dict) -> Token:
        if not rc:
            return t
        t.is_rugged = bool(rc.get("rugged"))
        t.mint_auth = rc.get("mintAuthority")
        t.freeze_auth = rc.get("freezeAuthority")

        raw = int(rc.get("score") or 0)
        t.risk_raw = raw
        if raw < 500:
            t.risk_norm, t.risk_label = round(raw / 500 * 3, 1), "good"
        elif raw < 2000:
            t.risk_norm, t.risk_label = round(3 + (raw - 500) / 1500 * 4, 1), "warn"
        else:
            t.risk_norm, t.risk_label = min(10.0, round(7 + (raw - 2000) / 3000 * 3, 1)), "danger"

        for mkt in rc.get("markets") or []:
            lp = mkt.get("lp") or {}
            pct = float(lp.get("lpLockedPct") or 0)
            if pct > t.lp_burn:
                t.lp_burn = pct
            if lp.get("lpBurned") or lp.get("burned"):
                t.lp_burn = 100.0

        t.rc_risks = []
        for r in rc.get("risks") or []:
            name = r.get("name", "")
            level = (r.get("level") or "").lower()
            desc = r.get("description", "")
            val = str(r.get("value") or "")
            if name:
                t.rc_risks.append((level, name, desc, val))

        # Top10 hanya jika sumber sebelumnya belum ada
        if t.top10_pct == 0:
            top_h = rc.get("topHolders") or []
            t.top_holders = top_h
            if top_h:
                total = 0.0
                for h in top_h[:10]:
                    pct = float(h.get("pct") or 0)
                    if 0 < pct <= 1.0:
                        pct *= 100
                    total += pct
                if total > 0:
                    t.top10_pct = round(total, 1)
                    t.top10_source = f"RugCheck ({len(top_h)})"
                    t.holder_count_rc = len(top_h)
        else:
            t.top_holders = rc.get("topHolders") or []
            if not t.holder_count_rc:
                t.holder_count_rc = len(t.top_holders)

        return t