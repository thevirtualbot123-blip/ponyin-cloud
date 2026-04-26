"""
data_fetcher.py — PONYIN AI AGENT v7.2
Fixes:
  - GMGN: use tls_client (bypass Cloudflare) → full data tanpa API key
  - Endpoint: /defi/quotation/v1/tokens/sol/{mint} (plural, public)
  - gmgn_new_tokens: also use tls_client for discovery
  - Helius DAS fallback for real holder count
  - Solscan fallback (holder count) removed — no longer needed
"""
import asyncio, aiohttp, logging, re, random
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, List, Tuple
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
            timeout=aiohttp.ClientTimeout(total=20),
        ) as sess:
            yield sess

    async def _get(self, session, url, headers=HDR, timeout=12):
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status == 200:
                    return await r.json(content_type=None)
                log.debug(f"HTTP {r.status}: {url[:70]}")
                return None
        except asyncio.TimeoutError:
            log.debug(f"Timeout: {url[:70]}")
            return None
        except Exception as e:
            log.debug(f"Fetch error {url[:70]}: {e}")
            return None

    # ── DexScreener ─────────────────────────────────────
    async def dex_token(self, session, mint: str) -> Optional[dict]:
        return await self._get(session, f"https://api.dexscreener.com/tokens/v1/solana/{mint}")

    async def dex_tokens_batch(self, session, mints: List[str]) -> list:
        if not mints:
            return []
        batch_str = ",".join(mints[:30])
        data = await self._get(session,
            f"https://api.dexscreener.com/tokens/v1/solana/{batch_str}")
        if not data:
            return []
        return data if isinstance(data, list) else (data.get("pairs") or [])

    # ── GMGN API (tls_client bypass Cloudflare) ─────────
    async def gmgn_token_info(self, session, mint: str) -> Optional[dict]:
        """
        Fetch token info from GMGN public endpoint via tls_client.
        NO API KEY REQUIRED. Returns FULL data.
        """
        import tls_client
        from fake_useragent import UserAgent

        ua = UserAgent()
        url = f"https://gmgn.ai/defi/quotation/v1/tokens/sol/{mint}"

        headers = {
            "Host": "gmgn.ai",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://gmgn.ai/?chain=sol",
            "DNT": "1",
            "User-Agent": ua.random,
        }

        try:
            client = tls_client.Session(
                client_identifier=random.choice(["chrome_120", "chrome_122", "firefox_120"])
            )
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: client.get(url, headers=headers, timeout=15)
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and data.get("code") == 0 and data.get("data"):
                    log.debug(f"GMGN tls OK: {mint[:12]}")
                    return data["data"]
                log.debug(f"GMGN tls code={data.get('code')} msg={data.get('msg','?')} for {mint[:12]}")
            else:
                log.debug(f"GMGN tls HTTP {response.status_code} for {mint[:12]}")
        except Exception as e:
            log.debug(f"GMGN tls error {mint[:12]}: {e}")

        return None

    async def gmgn_new_tokens(self, session) -> List[str]:
        """Fetch trending/new tokens from GMGN (public) via tls_client."""
        import tls_client
        from fake_useragent import UserAgent

        ua = UserAgent()
        headers = {
            "Host": "gmgn.ai",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://gmgn.ai/?chain=sol",
            "DNT": "1",
            "User-Agent": ua.random,
        }

        endpoints = [
            "https://gmgn.ai/defi/quotation/v1/rank/sol/new_creation/1h"
            "?limit=50&orderby=created_timestamp&direction=desc",
            "https://gmgn.ai/defi/quotation/v1/rank/sol/pump_rank/1h"
            "?limit=50&orderby=volume&direction=desc&filters[]=not_wash_trading",
        ]

        mints: List[str] = []
        client = tls_client.Session(
            client_identifier=random.choice(["chrome_120", "chrome_122"])
        )
        for url in endpoints:
            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: client.get(url, headers=headers, timeout=10)
                )
                if response.status_code == 200:
                    data = response.json()
                    items = None
                    if isinstance(data.get("data"), list):
                        items = data["data"]
                    else:
                        for key in ("rank", "tokens", "items", "list"):
                            if isinstance(data.get(key), list):
                                items = data[key]
                                break
                    if items:
                        for item in items:
                            addr = (item.get("address") or item.get("token_address")
                                    or item.get("mint") or "")
                            if addr and len(addr) >= 32:
                                mints.append(addr)
            except Exception as e:
                log.debug(f"gmgn_new_tokens error: {e}")

        unique = list(dict.fromkeys(mints))
        if unique:
            log.info(f"GMGN discovery: {len(unique)} tokens")
        return unique[:60]

    @staticmethod
    def _unwrap_gmgn(data: dict) -> dict:
        if not data:
            return {}
        token_nested = data.get("token")
        if isinstance(token_nested, dict) and token_nested:
            return token_nested
        return data

    @staticmethod
    def _gmgn_float(data: dict, *keys, default: float = 0.0) -> float:
        for k in keys:
            v = data.get(k)
            if v is not None:
                try:
                    return float(v)
                except (ValueError, TypeError):
                    continue
        return default

    @staticmethod
    def _gmgn_int(data: dict, *keys, default: int = 0) -> int:
        for k in keys:
            v = data.get(k)
            if v is not None:
                try:
                    return int(v)
                except (ValueError, TypeError):
                    continue
        return default

    def _apply_gmgn_data(self, t: Token, data: dict) -> Token:
        t.gmgn_data = data
        td = self._unwrap_gmgn(data)

        # ── Top 10 holders ────────────────────────────────
        for key in ("top_10_holder_pct", "top_10_holder_rate",
                    "top10HolderPercent", "top10_holder_rate",
                    "topHolderRate", "top_10_holder_percent"):
            raw = td.get(key)
            if raw is not None:
                try:
                    v = float(raw)
                    if 0 < v <= 1.0:
                        v *= 100
                    if 0 < v <= 100:
                        t.top10_pct = round(v, 1)
                        t.top10_source = "GMGN"
                except (ValueError, TypeError):
                    pass
                break

        # ── Holder count ──────────────────────────────────
        hc = self._gmgn_int(td,
            "holder_count", "holder", "holderCount",
            "holders", "holder_num")
        if hc:
            t.holder_count_gmgn = hc

        # ── Dev supply ────────────────────────────────────
        dev = self._gmgn_float(td,
            "dev_hold_pct", "dev_holding_pct", "devHoldingPercent",
            "creator_hold_pct", "creator_holding")
        t.dev_hold_pct = dev

        # ── LP Burn ───────────────────────────────────────
        burn_status = str(td.get("burn_status") or "").lower()
        burn_ratio_raw = (td.get("burn_ratio") or td.get("lp_burn_ratio") or
                          td.get("lpBurnRatio") or "0")
        try:
            br = float(burn_ratio_raw)
            if br >= 0.95:
                t.lp_burn = 100.0
            elif br > 0:
                t.lp_burn = max(t.lp_burn, round(br * 100, 1))
        except (ValueError, TypeError):
            pass
        if burn_status in ("burn", "burned", "true", "yes"):
            t.lp_burn = 100.0

        # ── Bundle % ──────────────────────────────────────
        bundle = self._gmgn_float(td,
            "bundle_pct", "bundler_pct", "bundlerPercent",
            "bundler_trader_amount_rate", "bundleRate")
        if bundle:
            t.bundle_pct = bundle

        # ── Sniper ────────────────────────────────────────
        t.sniper_count = self._gmgn_int(td,
            "sniper_count", "sniperCount", "sniper_num")

        # ── Smart money / KOL ─────────────────────────────
        smart = self._gmgn_int(td,
            "smart_degen_count", "smartDegenCount", "smart_money_count",
            "smart_holder_count")
        t.smart_money_count = smart
        if smart > 0:
            t.smart_money_present = True

        kol = self._gmgn_int(td,
            "renowned_wallets", "renowned_wallet_count",
            "renownedWalletCount", "kol_count")
        t.kol_holders = kol

        # ── Security ──────────────────────────────────────
        t.is_honeypot = bool(
            td.get("is_honeypot") or td.get("isHoneypot") or
            td.get("honeypot") or False
        )
        t.rug_ratio = self._gmgn_float(td,
            "rug_ratio", "dev_rug_ratio", "rugRatio", "rugged_ratio")

        t.wash_trade_gmgn = bool(
            td.get("wash_trade_flag") or td.get("is_wash_trading") or
            td.get("washTrading") or td.get("wash_trading") or False
        )
        t.fresh_wallet_rate = self._gmgn_float(td,
            "fresh_wallet_rate", "freshWalletRate", "fresh_rate")
        t.rat_trader_rate = self._gmgn_float(td,
            "rat_trader_amount_rate", "ratTraderRate", "rat_trader_rate")

        return t

    # ── Helius fallback ─────────────────────────────────
    async def helius_get_largest_holders(self, session, mint: str) -> Optional[dict]:
        if not self.cfg.HELIUS_API_KEY:
            return None
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenLargestAccounts",
            "params": [mint, {"commitment": "confirmed"}],
        }
        try:
            async with session.post(
                self.cfg.HELIUS_RPC_URL, json=payload,
                timeout=aiohttp.ClientTimeout(total=12)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("result")
        except Exception as e:
            log.debug(f"Helius largest holders error: {e}")
        return None

    async def helius_get_token_supply(self, session, mint: str) -> Optional[dict]:
        if not self.cfg.HELIUS_API_KEY:
            return None
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenSupply",
            "params": [mint, {"commitment": "confirmed"}],
        }
        try:
            async with session.post(
                self.cfg.HELIUS_RPC_URL, json=payload,
                timeout=aiohttp.ClientTimeout(total=8)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("result")
        except Exception as e:
            log.debug(f"Helius supply error: {e}")
        return None

    async def helius_get_token_holder_count(self, session, mint: str) -> int:
        if not self.cfg.HELIUS_API_KEY:
            return 0
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccounts",
            "params": {
                "mint": mint,
                "limit": 1,
                "displayOptions": {},
            },
        }
        try:
            async with session.post(
                self.cfg.HELIUS_RPC_URL, json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    result = data.get("result")
                    if isinstance(result, dict):
                        total = result.get("total", 0)
                        if total:
                            return int(total)
        except Exception as e:
            log.debug(f"Helius holder count error {mint[:12]}: {e}")
        return 0

    def _apply_helius_holders(self, t: Token, holders_data: dict, supply_data: dict) -> Token:
        if not holders_data or "value" not in holders_data:
            return t
        holder_list = holders_data["value"]
        supply_info = supply_data.get("value") if supply_data else {}
        ui_supply = float(supply_info.get("uiAmount", 0))
        if ui_supply <= 0:
            return t
        total_ui = sum(float(h.get("uiAmount", 0)) for h in holder_list[:10])
        if total_ui > 0:
            t.top10_pct = round((total_ui / ui_supply) * 100, 1)
            t.top10_source = "Helius"
        return t

    # ── RugCheck ─────────────────────────────────────────
    async def rugcheck_full(self, session, mint: str) -> Optional[dict]:
        return await self._get(session, f"https://api.rugcheck.xyz/v1/tokens/{mint}/report")

    # ── Discovery: new mints ─────────────────────────────
    async def get_new_token_mints(self, session) -> List[str]:
        profiles, boosted, rc_new, gmgn_new = await asyncio.gather(
            self.dex_latest_profiles(session),
            self.dex_boosted(session),
            self.rc_new_tokens(session),
            self.gmgn_new_tokens(session),
            return_exceptions=True,
        )
        mints = []
        for src in (profiles, boosted, rc_new):
            if isinstance(src, list):
                for item in src:
                    m = item.get("tokenAddress") or item.get("mint") or ""
                    if m:
                        mints.append(m)
        if isinstance(gmgn_new, list):
            for m in gmgn_new:
                if isinstance(m, str) and m:
                    mints.append(m)
        return list(dict.fromkeys(mints))[:100]

    async def dex_latest_profiles(self, session) -> list:
        d = await self._get(session, "https://api.dexscreener.com/token-profiles/latest/v1")
        return [x for x in (d or []) if x.get("chainId") == "solana"]

    async def dex_boosted(self, session) -> list:
        d = await self._get(session, "https://api.dexscreener.com/token-boosts/latest/v1")
        return [x for x in (d or []) if x.get("chainId") == "solana"]

    async def rc_new_tokens(self, session) -> list:
        d = await self._get(session, "https://api.rugcheck.xyz/v1/stats/new_tokens")
        return d if isinstance(d, list) else []

    # ── FILTERED SCAN ────────────────────────────────────
    async def get_filtered_scan_mints(
        self, session,
        min_mc: float = 5_000,
        max_mc: float = 50_000,
        min_liq: float = 1_000,
        min_vol1h: float = 3_000,
        allowed_dex: set = None,
        max_results: int = 20,
    ) -> List[Tuple[float, str]]:
        if allowed_dex is None:
            allowed_dex = {
                "pump_fun", "pumpfun", "pump.fun",
                "raydium",
                "meteora",
                "orca",
            }

        raw_mints = await self.get_new_token_mints(session)
        if not raw_mints:
            return []

        all_pairs = []
        batch_size = 30
        batches = [raw_mints[i:i+batch_size]
                   for i in range(0, min(len(raw_mints), 90), batch_size)]
        fetch_tasks = [self.dex_tokens_batch(session, b) for b in batches]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        for batch_pairs in results:
            if isinstance(batch_pairs, list):
                all_pairs.extend(batch_pairs)

        candidates: List[Tuple[float, str]] = []
        seen_mints: set = set()

        for pair in all_pairs:
            if not isinstance(pair, dict):
                continue
            if pair.get("chainId") != "solana":
                continue
            base = pair.get("baseToken") or {}
            mint = base.get("address", "")
            if not mint or len(mint) < 30 or mint in seen_mints:
                continue

            mc     = float(pair.get("marketCap") or pair.get("fdv") or 0)
            liq    = float((pair.get("liquidity") or {}).get("usd") or 0)
            vol1h  = float((pair.get("volume") or {}).get("h1") or 0)
            chg5m  = float((pair.get("priceChange") or {}).get("m5") or 0)
            dex_id = (pair.get("dexId") or "").lower().replace(".", "_").replace("-", "_")

            if not (min_mc <= mc <= max_mc):
                continue
            if liq < min_liq:
                continue
            if vol1h < min_vol1h:
                continue
            if not any(allowed in dex_id or dex_id in allowed for allowed in allowed_dex):
                continue

            seen_mints.add(mint)
            candidates.append((chg5m, mint))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[:max_results]

    # ── Fetch utama ─────────────────────────────────────
    async def fetch_token(self, session, mint: str) -> Optional[Token]:
        dex_raw, gmgn_raw, rc_raw = await asyncio.gather(
            self.dex_token(session, mint),
            self.gmgn_token_info(session, mint),
            self.rugcheck_full(session, mint),
            return_exceptions=True,
        )
        if isinstance(dex_raw, Exception):
            dex_raw = None
        if isinstance(gmgn_raw, Exception):
            gmgn_raw = None
        if isinstance(rc_raw, Exception):
            rc_raw = None

        token = self._parse_dex(dex_raw)
        if not token:
            return None

        if rc_raw:
            token = self._apply_rugcheck(token, rc_raw)

        if gmgn_raw:
            token = self._apply_gmgn_data(token, gmgn_raw)

        # Helius fallback for top-10% (only if GMGN didn't provide)
        if token.top10_pct == 0 and self.cfg.HELIUS_API_KEY:
            helius_holders, helius_supply = await asyncio.gather(
                self.helius_get_largest_holders(session, mint),
                self.helius_get_token_supply(session, mint),
                return_exceptions=True,
            )
            if not isinstance(helius_holders, Exception) and helius_holders:
                if not isinstance(helius_supply, Exception) and helius_supply:
                    token = self._apply_helius_holders(token, helius_holders, helius_supply)

        # Helius DAS fallback for real holder count (only if GMGN didn't provide)
        if token.holder_count_gmgn == 0 and self.cfg.HELIUS_API_KEY:
            hc = await self.helius_get_token_holder_count(session, mint)
            if hc > 0:
                token.holder_count_gmgn = hc

        return token

    # ── Parse helpers ────────────────────────────────────
    def _parse_socials(self, pair):
        tw = tg = web = False
        info = pair.get("info") or {}
        for s in info.get("socials") or []:
            t_url = (s.get("type") or "").lower()
            url   = (s.get("url") or "").lower()
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
            if pair.get(k): tw = True
        for k in ("telegram", "telegramUrl"):
            if pair.get(k): tg = True
        for k in ("website", "websiteUrl"):
            if pair.get(k): web = True
        return tw, tg, web

    def _parse_pair(self, pair):
        try:
            base = pair.get("baseToken") or {}
            mint = base.get("address", "")
            if not mint or len(mint) < 30:
                return None

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
                mint=mint,
                name=base.get("name", "Unknown"),
                symbol=base.get("symbol", "???"),
                price=price,
                mc=mc,
                liq=liq,
                vol1h=float(vol.get("h1") or 0),
                vol6h=float(vol.get("h6") or 0),
                vol24h=float(vol.get("h24") or 0),
                chg5m=float(pc.get("m5") or 0),
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
        sol  = [p for p in pairs if isinstance(p, dict) and p.get("chainId") == "solana"]
        pool = sol or [p for p in pairs if isinstance(p, dict)]
        if not pool:
            return None
        best = max(pool, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))
        return self._parse_pair(best)

    def _apply_rugcheck(self, t: Token, rc: dict) -> Token:
        if not rc:
            return t
        t.is_rugged   = bool(rc.get("rugged"))
        t.mint_auth   = rc.get("mintAuthority")
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
            lp  = mkt.get("lp") or {}
            pct = float(lp.get("lpLockedPct") or 0)
            if pct > t.lp_burn:
                t.lp_burn = pct
            if (lp.get("lpBurned") or lp.get("burned") or
                    lp.get("isBurned") or lp.get("burn")):
                t.lp_burn = 100.0

        t.rc_risks = []
        for r in rc.get("risks") or []:
            name  = r.get("name", "")
            level = (r.get("level") or "").lower()
            desc  = r.get("description", "")
            val   = str(r.get("value") or "")
            if name:
                t.rc_risks.append((level, name, desc, val))

        t.top_holders = rc.get("topHolders") or []
        t.holder_count_rc = len(t.top_holders)

        return t