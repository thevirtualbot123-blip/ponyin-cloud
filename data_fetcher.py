"""
data_fetcher.py — PONYIN AI AGENT v5.0
========================================
- Fetch DexScreener (wajib)
- Fetch Helius holders & supply (gratis, lebih akurat)
- Fetch RugCheck (pelengkap)
- Timeout ketat, graceful degradation
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

CA_PATTERN = re.compile(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b')


class DataFetcher:

    def __init__(self, cfg=None):
        from config import AgentConfig
        self.cfg = cfg or AgentConfig()

    @asynccontextmanager
    async def session(self):
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False),
            timeout=aiohttp.ClientTimeout(total=15)
        ) as sess:
            yield sess

    async def _get(self, session, url: str, headers: dict = HDR, timeout: int = 10) -> Optional[dict]:
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
        return await self._get(session, f"https://api.dexscreener.com/tokens/v1/solana/{mint}")

    # ── Helius RPC ───────────────────────────────────────
    async def helius_get_largest_holders(self, session, mint: str, limit: int = 50) -> Optional[dict]:
        if not self.cfg.HELIUS_API_KEY:
            return None
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenLargestAccounts",
            "params": [mint, {"commitment": "confirmed"}],
        }
        try:
            async with session.post(self.cfg.HELIUS_RPC_URL, json=payload, timeout=12) as r:
                if r.status == 200:
                    data = await r.json()
                    if data.get("result"):
                        return data["result"]
        except Exception as e:
            log.debug(f"Helius holders error: {e}")
        return None

    async def helius_get_token_supply(self, session, mint: str) -> Optional[int]:
        if not self.cfg.HELIUS_API_KEY:
            return None
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenSupply",
            "params": [mint, {"commitment": "confirmed"}],
        }
        try:
            async with session.post(self.cfg.HELIUS_RPC_URL, json=payload, timeout=8) as r:
                if r.status == 200:
                    data = await r.json()
                    if data.get("result"):
                        return int(data["result"]["value"]["amount"])
        except Exception as e:
            log.debug(f"Helius supply error: {e}")
        return None
    def _apply_helius_holders(self, t: Token, holders_data: dict, supply: Optional[int]) -> Token:
        """Hitung top10 & total holders dari data Helius, dengan validasi ketat."""
        if not holders_data or "value" not in holders_data:
            return t

        holder_list = holders_data["value"]
        t.helius_holders_available = True
        t.holder_list_helius = holder_list

        # JANGAN hitung Top10 jika token masih bonding curve (liq = 0)
        # karena supply dan desimal tidak konsisten.
        if t.liq <= 0 or t.mc <= 0:
            t.top10_source = "Helius (bonding curve — skip)"
            t.holder_count_helius = len(holder_list)
            return t

        # Cari desimal token dengan memanggil Helius getTokenInfo kecil
        # Untuk sekarang, gunakan fallback 9 desimal (umum untuk Solana)
        decimals = 9  # Mayoritas token SPL menggunakan 9 desimal
        if supply:
            supply_decimal = supply / (10 ** decimals)
        else:
            supply_decimal = None

        total_pct = 0.0
        for h in holder_list[:10]:
            amount = int(h.get("amount", 0))
            if supply_decimal and supply_decimal > 0:
                pct = (amount / supply_decimal * 100)
            else:
                pct = 0.0
            total_pct += pct

        # Validasi: persentase harus masuk akal (0% - 100%)
        if 0 < total_pct <= 100:
            t.top10_pct = round(total_pct, 1)
            t.top10_source = f"Helius ({len(holder_list)} holders)"
        else:
            t.top10_pct = 0.0
            t.top10_source = f"Helius (invalid pct {total_pct:.1f}%)"

        t.holder_count_helius = len(holder_list)
        return t

    # ── RugCheck ─────────────────────────────────────────
    async def rugcheck_full(self, session, mint: str) -> Optional[dict]:
        return await self._get(session, f"https://api.rugcheck.xyz/v1/tokens/{mint}/report")

    # ── Fetch utama ─────────────────────────────────────
    async def fetch_token(self, session, mint: str) -> Optional[Token]:
        # 1. Dex wajib
        dex_data = await self.dex_token(session, mint)
        token = self._parse_dex(dex_data)
        if not token:
            return None

        # 2. Paralel Helius + RugCheck
        results = await asyncio.gather(
            self.helius_get_largest_holders(session, mint),
            self.helius_get_token_supply(session, mint),
            self.rugcheck_full(session, mint),
            return_exceptions=True
        )
        helius_holders = results[0] if not isinstance(results[0], Exception) else None
        helius_supply  = results[1] if not isinstance(results[1], Exception) else None
        rc_data        = results[2] if not isinstance(results[2], Exception) else None

        if helius_holders:
            token = self._apply_helius_holders(token, helius_holders, helius_supply)
        if rc_data:
            token = self._apply_rugcheck(token, rc_data)

        return token

    # ── Parse DexScreener ────────────────────────────────
    def _parse_socials(self, pair: dict):
        tw = tg = web = False
        info = pair.get("info") or {}
        for s in (info.get("socials") or []):
            t = (s.get("type") or "").lower()
            url = (s.get("url") or "").lower()
            if t in ("twitter","x") or "twitter.com" in url or "x.com" in url: tw = True
            if t == "telegram" or "t.me" in url: tg = True
        for w in (info.get("websites") or []):
            url = (w.get("url") or "").lower()
            if url: web = True
            if "twitter.com" in url or "x.com" in url: tw = True
            if "t.me" in url: tg = True
        for k in ("twitter","twitterUrl"): 
            if pair.get(k): tw = True
        for k in ("telegram","telegramUrl"): 
            if pair.get(k): tg = True
        for k in ("website","websiteUrl"):  
            if pair.get(k): web = True
        return tw, tg, web

    def _parse_pair(self, pair: dict) -> Optional[Token]:
        try:
            base = pair.get("baseToken") or {}
            mint = base.get("address", "")
            if not mint or len(mint) < 30: return None

            price = float(pair.get("priceUsd") or 0)
            mc    = float(pair.get("marketCap") or pair.get("fdv") or 0)
            liq   = float((pair.get("liquidity") or {}).get("usd") or 0)
            vol   = pair.get("volume") or {}
            pc    = pair.get("priceChange") or {}
            txns  = pair.get("txns") or {}
            h1    = txns.get("h1") or {}

            cr = pair.get("pairCreatedAt") or 0
            if cr:
                cd = datetime.fromtimestamp(cr / 1000)
                created = cd.strftime("%Y-%m-%d %H:%M")
                age_h = (datetime.now() - cd).total_seconds() / 3600
            else:
                created, age_h = "unknown", 0.0

            tw, tg, web = self._parse_socials(pair)

            return Token(
                mint=mint, name=base.get("name","Unknown"),
                symbol=base.get("symbol","???"),
                price=price, mc=mc, liq=liq,
                vol1h=float(vol.get("h1") or 0),
                vol6h=float(vol.get("h6") or 0),
                vol24h=float(vol.get("h24") or 0),
                chg1h=float(pc.get("h1") or 0),
                chg6h=float(pc.get("h6") or 0),
                chg24h=float(pc.get("h24") or 0),
                buys1h=int(h1.get("buys") or 0),
                sells1h=int(h1.get("sells") or 0),
                has_twitter=tw, has_telegram=tg, has_website=web,
                dex=pair.get("dexId",""),
                pair_addr=pair.get("pairAddress",""),
                created=created, age_hours=age_h,
            )
        except Exception as e:
            log.debug(f"Parse pair error: {e}")
            return None

    def _parse_dex(self, data) -> Optional[Token]:
        if not data: return None
        pairs = data if isinstance(data, list) else data.get("pairs") or []
        if not pairs: return None
        sol = [p for p in pairs if isinstance(p, dict) and p.get("chainId") == "solana"]
        pool = sol or [p for p in pairs if isinstance(p, dict)]
        if not pool: return None
        best = max(pool, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))
        return self._parse_pair(best)

    def _apply_rugcheck(self, t: Token, rc: dict) -> Token:
        if not rc: return t
        t.is_rugged    = bool(rc.get("rugged"))
        t.mint_auth    = rc.get("mintAuthority")
        t.freeze_auth  = rc.get("freezeAuthority")

        raw = int(rc.get("score") or 0)
        t.risk_raw = raw
        if raw < 500:
            t.risk_norm, t.risk_label = round(raw / 500 * 3, 1), "good"
        elif raw < 2000:
            t.risk_norm, t.risk_label = round(3 + (raw-500)/1500*4, 1), "warn"
        else:
            t.risk_norm, t.risk_label = min(10.0, round(7+(raw-2000)/3000*3, 1)), "danger"

        for mkt in (rc.get("markets") or []):
            lp  = mkt.get("lp") or {}
            pct = float(lp.get("lpLockedPct") or 0)
            if pct > t.lp_burn: t.lp_burn = pct
            if lp.get("lpBurned") or lp.get("burned"): t.lp_burn = 100.0

        t.rc_risks = []
        for r in (rc.get("risks") or []):
            name  = r.get("name", "")
            level = (r.get("level") or "").lower()
            desc  = r.get("description", "")
            val   = str(r.get("value") or "")
            if name: t.rc_risks.append((level, name, desc, val))

        # Top holders hanya jika belum dari Helius
        if not (hasattr(t, 'helius_holders_available') and t.helius_holders_available):
            top_h = rc.get("topHolders") or []
            t.top_holders = top_h
            if top_h:
                total = 0.0
                for h in top_h[:10]:
                    pct = float(h.get("pct") or 0)
                    if 0 < pct <= 1.0: pct *= 100
                    total += pct
                if total > 0:
                    t.top10_pct    = round(total, 1)
                    t.top10_source = f"RugCheck ({len(top_h)})"
                    t.holder_count_rc = len(top_h)
        else:
            t.top_holders = rc.get("topHolders") or []
            if not t.holder_count_rc:
                t.holder_count_rc = len(t.top_holders)

        return t

    # ── Discovery ────────────────────────────────────────
    async def get_new_token_mints(self, session) -> List[str]:
        profiles, boosted, rc_new = await asyncio.gather(
            self.dex_latest_profiles(session),
            self.dex_boosted(session),
            self.rc_new_tokens(session),
        )
        mints = []
        for item in profiles + boosted:
            m = item.get("tokenAddress", "")
            if m: mints.append(m)
        for item in rc_new:
            m = item.get("mint", "")
            if m: mints.append(m)
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

    def extract_ca_from_text(self, text: str) -> Optional[str]:
        if not text: return None
        candidates = CA_PATTERN.findall(text)
        valid = [c for c in candidates if 32 <= len(c) <= 44]
        if not valid: return None
        for keyword in ["CA:", "ca:", "Contract:", "contract:", "Address:"]:
            idx = text.find(keyword)
            if idx != -1:
                after = text[idx + len(keyword):].strip().split()[0]
                if 32 <= len(after) <= 44:
                    return after
        return max(valid, key=len)