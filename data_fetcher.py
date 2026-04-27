"""
data_fetcher.py — PONYIN AI AGENT v7.5 FINAL
Architecture:
  - Primary: DexScreener (price, mc, liq, vol, socials)
  - Primary: Helius DAS (holder count, top10% REAL from all accounts)
  - Secondary: RugCheck (security, LP burn, mint/freeze, risks)
  - Bonus: GMGN (smart money, bundle, sniper) — optional, fragile
  - Fallback: Heuristic analysis for bundle/smart money/sniper patterns
"""
import asyncio, aiohttp, logging, re, random
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, List, Tuple
from collections import defaultdict
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

    @staticmethod
    def _unwrap_gmgn(data: dict) -> dict:
        """Unwrap GMGN response — called from filter_engine too."""
        if not isinstance(data, dict):
            return {}
        # Try nested "token" key first, fallback to data itself
        inner = data.get("token")
        if isinstance(inner, dict):
            return inner
        return data

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

    # ── GMGN API (Optional — fragile, often fails) ──────
    async def _gmgn_fetch(self, url: str, mint: str, method: str = "GET",
                          payload: dict = None) -> Optional[dict]:
        import tls_client
        from fake_useragent import UserAgent

        ua = UserAgent()
        identifier = random.choice(["chrome_120", "chrome_122", "firefox_120"])

        client = tls_client.Session(
            client_identifier=identifier,
            random_tls_extension_order=True,
        )
        client.timeout_seconds = 60

        headers = {
            'Host': 'gmgn.ai',
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            'dnt': '1',
            'priority': 'u=1, i',
            'referer': 'https://gmgn.ai/?chain=sol',
            'content-type': 'application/json',
            'user-agent': ua.random,
        }

        if self.cfg.GMGN_API_KEY:
            headers['x-route-key'] = self.cfg.GMGN_API_KEY

        try:
            if method == "POST":
                response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: client.post(url, json=payload, headers=headers)
                )
            else:
                response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: client.get(url, headers=headers)
                )

            status = response.status_code
            if status == 200:
                data = response.json()
                code = data.get("code", -1)
                if code == 0 and data.get("data"):
                    return data["data"]
            elif status == 429:
                log.warning(f"GMGN rate limited for {mint[:12]}")
            else:
                log.debug(f"GMGN HTTP {status} for {mint[:12]}")
        except Exception as e:
            log.debug(f"GMGN exception {mint[:12]}: {e}")

        return None

    async def gmgn_token_info(self, session, mint: str) -> Optional[dict]:
        endpoints = [
            {"url": "https://gmgn.ai/api/v1/mutil_window_token_info", "method": "POST",
             "payload": {"chain": "sol", "addresses": [mint]}},
            {"url": f"https://gmgn.ai/defi/quotation/v1/token/sol/{mint}", "method": "GET"},
            {"url": f"https://gmgn.ai/defi/quotation/v1/tokens/sol/{mint}", "method": "GET"},
        ]
        for ep in endpoints:
            data = await self._gmgn_fetch(ep["url"], mint, ep["method"], ep.get("payload"))
            if data:
                if isinstance(data, list) and len(data) > 0:
                    return data[0]
                if isinstance(data, dict) and "tokens" in data:
                    tokens = data["tokens"]
                    if isinstance(tokens, list) and len(tokens) > 0:
                        return tokens[0]
                return data
        return None

    async def gmgn_new_tokens(self, session) -> List[str]:
        import tls_client
        from fake_useragent import UserAgent

        ua = UserAgent()
        client = tls_client.Session(
            client_identifier=random.choice(["chrome_120", "chrome_122"]),
            random_tls_extension_order=True,
        )
        headers = {
            'Host': 'gmgn.ai',
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            'dnt': '1',
            'priority': 'u=1, i',
            'referer': 'https://gmgn.ai/?chain=sol',
            'user-agent': ua.random,
        }
        if self.cfg.GMGN_API_KEY:
            headers['x-route-key'] = self.cfg.GMGN_API_KEY

        endpoints = [
            "https://gmgn.ai/defi/quotation/v1/rank/sol/new_creation/1h"
            "?limit=50&orderby=created_timestamp&direction=desc",
            "https://gmgn.ai/defi/quotation/v1/rank/sol/pump_rank/1h"
            "?limit=50&orderby=volume&direction=desc&filters[]=not_wash_trading",
        ]

        mints: List[str] = []
        for url in endpoints:
            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: client.get(url, headers=headers)
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

    # ── Helius DAS — GOLD STANDARD for on-chain data ────
    async def helius_get_all_holders(self, session, mint: str) -> List[dict]:
        """
        Fetch ALL token holders via Helius DAS with pagination.
        Returns deduped owner list for accurate top10% calculation.
        """
        if not self.cfg.HELIUS_API_KEY:
            return []

        all_accounts = []
        page = 1

        while True:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenAccounts",
                "params": {"mint": mint, "limit": 1000, "page": page},
            }
            try:
                async with session.post(
                    self.cfg.HELIUS_RPC_URL, json=payload,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as r:
                    if r.status != 200:
                        break
                    data = await r.json()
                    result = data.get("result", {})
                    accounts = result.get("token_accounts", [])
                    if not accounts:
                        break

                    for acc in accounts:
                        all_accounts.append({
                            "owner": acc.get("owner", ""),
                            "amount": acc.get("amount", "0"),
                            "uiAmount": float(acc.get("uiAmount", 0) or 0),
                        })

                    if len(accounts) < 1000:
                        break
                    page += 1
                    if page > 10:
                        log.warning(f"Helius pagination limit for {mint[:12]}")
                        break
            except Exception as e:
                log.warning(f"Helius page {page} error {mint[:12]}: {e}")
                break

        log.info(f"Helius fetched {len(all_accounts)} raw accounts for {mint[:12]}")
        return all_accounts

    def _calculate_top10_from_helius(self, t: Token, accounts: List[dict], supply_data: dict) -> Token:
        """
        Calculate REAL top10% from all Helius DAS accounts with owner dedup.
        """
        if not accounts:
            return t

        supply_info = supply_data.get("value") if supply_data else {}
        total_supply = float(supply_info.get("uiAmount", 0))

        if total_supply <= 0:
            log.warning(f"Helius supply zero for {t.mint[:12]}")
            return t

        # Dedup by owner (handle multiple ATAs)
        owner_totals = defaultdict(float)
        for acc in accounts:
            owner = acc.get("owner", "")
            if not owner:
                continue
            # Skip known system/contract addresses
            if owner in ("11111111111111111111111111111111",
                         "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                         "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"):
                continue
            owner_totals[owner] += acc.get("uiAmount", 0)

        # Sort by total descending
        sorted_owners = sorted(owner_totals.items(), key=lambda x: x[1], reverse=True)

        # Calculate top10%
        top10_sum = sum(amount for _, amount in sorted_owners[:10])
        top10_pct = (top10_sum / total_supply) * 100

        t.top10_pct = round(top10_pct, 1)
        t.top10_source = f"Helius({len(sorted_owners)} holders)"

        # Update holder count (real deduped count)
        t.holder_count_gmgn = len(sorted_owners)

        log.info(
            f"Helius TOP10 {t.mint[:12]}: {t.top10_pct}% "
            f"from {len(sorted_owners)} unique holders "
            f"(top10_sum={top10_sum:.2f}, supply={total_supply:.2f})"
        )

        return t

    async def helius_get_token_supply(self, session, mint: str) -> Optional[dict]:
        if not self.cfg.HELIUS_API_KEY:
            return None
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getTokenSupply",
            "params": [mint, {"commitment": "confirmed"}],
        }
        try:
            async with session.post(self.cfg.HELIUS_RPC_URL, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("result")
        except Exception as e:
            log.debug(f"Helius supply error: {e}")
        return None

    # ── RugCheck ─────────────────────────────────────────
    async def rugcheck_full(self, session, mint: str) -> Optional[dict]:
        return await self._get(session, f"https://api.rugcheck.xyz/v1/tokens/{mint}/report")

    # ── Discovery ────────────────────────────────────────
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
    async def dex_search_new_solana(self, session) -> List[str]:
        """Fallback: cari token baru Solana langsung dari DexScreener search."""
        mints: List[str] = []
        urls = [
            "https://api.dexscreener.com/latest/dex/search?q=pumpfun+solana",
            "https://api.dexscreener.com/latest/dex/search?q=pump.fun+solana",
            "https://api.dexscreener.com/latest/dex/search?q=raydium+solana",
        ]
        for url in urls:
            data = await self._get(session, url, timeout=10)
            if not data:
                continue
            pairs = data.get("pairs") or (data if isinstance(data, list) else [])
            for p in (pairs if isinstance(pairs, list) else []):
                if not isinstance(p, dict):
                    continue
                if p.get("chainId") == "solana":
                    addr = (p.get("baseToken") or {}).get("address", "")
                    if addr and len(addr) >= 32:
                        mints.append(addr)
        unique = list(dict.fromkeys(mints))
        log.info(f"DexSearch fallback: {len(unique)} mints")
        return unique[:60]

    async def get_filtered_scan_mints(
        self, session, min_mc=5_000, max_mc=50_000,
        min_liq=1_000, min_vol1h=3_000, allowed_dex=None, max_results=20
    ) -> List[Tuple[float, str]]:
        if allowed_dex is None:
            allowed_dex = {"pump_fun", "pumpfun", "pump.fun", "raydium", "meteora", "orca"}

        raw_mints = await self.get_new_token_mints(session)

        # ── FIX: fallback ke DexSearch jika discovery utama gagal/sedikit ──
        if len(raw_mints) < 10:
            log.warning(f"Discovery hanya {len(raw_mints)} mint, coba DexSearch fallback")
            dex_mints = await self.dex_search_new_solana(session)
            for m in dex_mints:
                if m not in raw_mints:
                    raw_mints.append(m)

        if not raw_mints:
            log.warning("Scan: tidak ada mint dari semua sumber discovery")
            return []

        log.info(f"Scan: total {len(raw_mints)} mint akan diperiksa")

        all_pairs = []
        for i in range(0, min(len(raw_mints), 90), 30):
            batch = raw_mints[i:i+30]
            pairs = await self.dex_tokens_batch(session, batch)
            if pairs:
                all_pairs.extend(pairs)

        log.info(f"Scan: {len(all_pairs)} pairs dari DexScreener batch")

        candidates = []
        seen = set()
        for pair in all_pairs:
            if not isinstance(pair, dict):
                continue
            # ── FIX: chainId bisa tidak ada kalau query ke /solana/ endpoint ──
            chain = pair.get("chainId", "solana")
            if chain and chain != "solana":
                continue

            base = pair.get("baseToken") or {}
            mint = base.get("address", "")
            if not mint or len(mint) < 30 or mint in seen:
                continue

            mc    = float(pair.get("marketCap") or pair.get("fdv") or 0)
            liq   = float((pair.get("liquidity") or {}).get("usd") or 0)
            vol1h = float((pair.get("volume") or {}).get("h1") or 0)
            vol5m = float((pair.get("volume") or {}).get("m5") or 0)
            vol24h= float((pair.get("volume") or {}).get("h24") or 0)
            chg5m = float((pair.get("priceChange") or {}).get("m5") or 0)
            created_at = int(pair.get("pairCreatedAt") or 0)
            age_h = ((datetime.now().timestamp() * 1000 - created_at) / 3_600_000
                     if created_at else 99)

            dex_raw = (pair.get("dexId") or "").lower()
            dex_id  = dex_raw.replace(".", "_").replace("-", "_")

            if not (min_mc <= mc <= max_mc):
                continue
            if liq < min_liq:
                continue

            # ── FIX: vol1h bisa 0 untuk token sangat fresh (< 1 jam) ──
            # Gunakan volume efektif: h1 > m5*12 (extrapolasi) > h24/24
            vol_effective = vol1h
            if vol_effective < min_vol1h:
                if age_h < 1.0 and vol5m > 0:
                    vol_effective = vol5m * 12  # ekstrapolasi 1 jam dari 5 menit
                elif vol24h > 0:
                    vol_effective = vol24h / max(age_h, 1.0)
            if vol_effective < min_vol1h * 0.3:  # threshold lebih longgar
                continue

            if allowed_dex:
                matched = any(
                    a == dex_id or a in dex_id or dex_id in a
                    for a in allowed_dex
                )
                if not matched:
                    log.debug(f"Skip dex {dex_id} (not in allowed_dex)")
                    continue

            seen.add(mint)
            candidates.append((chg5m, mint))

        candidates.sort(key=lambda x: x[0], reverse=True)
        log.info(f"Scan: {len(candidates)} kandidat lolos filter")
        return candidates[:max_results]

    # ── Fetch utama ─────────────────────────────────────
    async def fetch_token(self, session, mint: str) -> Optional[Token]:
        dex_raw, gmgn_raw, rc_raw = await asyncio.gather(
            self.dex_token(session, mint),
            self.gmgn_token_info(session, mint),
            self.rugcheck_full(session, mint),
            return_exceptions=True,
        )
        dex_raw = None if isinstance(dex_raw, Exception) else dex_raw
        gmgn_raw = None if isinstance(gmgn_raw, Exception) else gmgn_raw
        rc_raw = None if isinstance(rc_raw, Exception) else rc_raw

        log.info(
            f"Sources {mint[:12]}: "
            f"DEX={'OK' if dex_raw else 'FAIL'} | "
            f"GMGN={'OK' if gmgn_raw else 'FAIL'} | "
            f"RC={'OK' if rc_raw else 'FAIL'}"
        )

        token = self._parse_dex(dex_raw)
        if not token:
            return None

        # Apply RugCheck (LP burn, security, risks)
        if rc_raw:
            token = self._apply_rugcheck(token, rc_raw)

        # Apply GMGN (optional — smart money, bundle, sniper)
        if gmgn_raw:
            token = self._apply_gmgn_data(token, gmgn_raw)

        # ── PRIMARY: Helius DAS for REAL top10% and holder count ──
        if self.cfg.HELIUS_API_KEY:
            helius_accounts = await self.helius_get_all_holders(session, mint)
            if helius_accounts:
                helius_supply = await self.helius_get_token_supply(session, mint)
                token = self._calculate_top10_from_helius(token, helius_accounts, helius_supply or {})

        # Final validation
        log.info(
            f"Final {mint[:12]}: "
            f"MC=${token.mc:,.0f} | "
            f"Holders={token.holder_count_gmgn} | "
            f"Top10={token.top10_pct:.1f}% ({token.top10_source}) | "
            f"LP={token.lp_burn:.0f}% | "
            f"Risk={token.risk_norm}/10"
        )

        return token

    # ── Parse helpers ────────────────────────────────────
    def _parse_socials(self, pair):
        tw = tg = web = False
        info = pair.get("info") or {}
        for s in info.get("socials") or []:
            t_url = (s.get("type") or "").lower()
            url = (s.get("url") or "").lower()
            if t_url in ("twitter", "x") or "twitter.com" in url or "x.com" in url: tw = True
            if t_url == "telegram" or "t.me" in url: tg = True
        for w in info.get("websites") or []:
            url = (w.get("url") or "").lower()
            if url: web = True
            if "twitter.com" in url or "x.com" in url: tw = True
            if "t.me" in url: tg = True
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
            mc = float(pair.get("marketCap") or pair.get("fdv") or 0)
            liq = float((pair.get("liquidity") or {}).get("usd") or 0)
            vol = pair.get("volume") or {}
            pc = pair.get("priceChange") or {}
            txns = pair.get("txns") or {}
            h1 = txns.get("h1") or {}
            cr = pair.get("pairCreatedAt") or 0

            # Check LP burn badge from DexScreener
            info = pair.get("info") or {}
            lp_burned = False
            for badge in info.get("badges") or []:
                if "burn" in (badge.get("label") or "").lower():
                    lp_burned = True

            if cr:
                cd = datetime.fromtimestamp(cr / 1000)
                created, age_h = cd.strftime("%Y-%m-%d %H:%M"), (datetime.now() - cd).total_seconds() / 3600
            else:
                created, age_h = "unknown", 0.0
            tw, tg, web = self._parse_socials(pair)

            token = Token(
                mint=mint, name=base.get("name", "Unknown"),
                symbol=base.get("symbol", "???"), price=price, mc=mc, liq=liq,
                vol1h=float(vol.get("h1") or 0), vol6h=float(vol.get("h6") or 0),
                vol24h=float(vol.get("h24") or 0),
                chg5m=float(pc.get("m5") or 0), chg1h=float(pc.get("h1") or 0),
                chg6h=float(pc.get("h6") or 0), chg24h=float(pc.get("h24") or 0),
                buys1h=int(h1.get("buys") or 0), sells1h=int(h1.get("sells") or 0),
                has_twitter=tw, has_telegram=tg, has_website=web,
                dex=pair.get("dexId", ""), pair_addr=pair.get("pairAddress", ""),
                created=created, age_hours=age_h,
            )
            if lp_burned:
                token.lp_burn = 100.0
                token.gmgn_lp_burned = True
            return token
        except Exception as e:
            log.debug(f"Parse pair error: {e}")
            return None

    def _parse_dex(self, data):
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
        t.is_rugged = bool(rc.get("rugged"))
        t.mint_auth = rc.get("mintAuthority")
        t.freeze_auth = rc.get("freezeAuthority")

        t.top_holders = rc.get("topHolders") or []

        # Holder count — coba field yang valid
        t.holder_count_rc = 0
        for key in ("holderCount", "holders", "totalHolders", "holder_count"):
            val = rc.get(key)
            if val is not None:
                try:
                    t.holder_count_rc = int(val)
                    break
                except (ValueError, TypeError):
                    continue

        # ── FIX: Top10 dari RugCheck topHolders (fallback jika GMGN/Helius tidak ada) ──
        if t.top_holders and t.top10_pct == 0:
            total_pct = 0.0
            for h in t.top_holders[:10]:
                pct_h = float(h.get("pct", 0) or 0)
                if 0 < pct_h <= 1.0:
                    pct_h *= 100
                if 0 < pct_h <= 100:
                    total_pct += pct_h
            if 0 < total_pct <= 100:
                t.top10_pct = round(total_pct, 1)
                t.top10_source = "RugCheck"
                log.info(f"RugCheck TOP10 {t.mint[:12]}: {t.top10_pct}%")

        # ── FIX: LP Burn — deteksi lebih robust dari RugCheck markets ──
        for mkt in rc.get("markets") or []:
            lp = mkt.get("lp") or {}
            # Cek berbagai field persentase
            for pct_key in ("lpLockedPct", "lpBurnedPct", "burnedPercent", "burnPct", "lockedPct"):
                raw_pct = lp.get(pct_key)
                if raw_pct is not None:
                    try:
                        pct_val = float(raw_pct)
                        if 0 < pct_val <= 1.0:
                            pct_val *= 100
                        if pct_val > t.lp_burn:
                            t.lp_burn = pct_val
                    except (ValueError, TypeError):
                        pass
            # Cek boolean burned
            if (lp.get("lpBurned") or lp.get("burned") or
                    lp.get("isBurned") or lp.get("burn")):
                t.lp_burn = 100.0
                t.gmgn_lp_burned = True
            # Hitung dari supply: lpCurrentSupply == 0 berarti burned
            try:
                lp_c = lp.get("lpCurrentSupply")
                lp_t = lp.get("lpTotalSupply")
                if lp_c is not None and lp_t is not None:
                    lp_c, lp_t = float(lp_c), float(lp_t)
                    if lp_c == 0 and lp_t > 0:
                        t.lp_burn = 100.0
                        t.gmgn_lp_burned = True
                    elif 0 < lp_c < lp_t:
                        pct_supply = round((1 - lp_c / lp_t) * 100, 1)
                        if pct_supply > t.lp_burn:
                            t.lp_burn = pct_supply
            except (ValueError, TypeError):
                pass

        # Risk score
        raw = int(rc.get("score") or 0)
        if raw < 500: t.risk_norm, t.risk_label = round(raw/500*3, 1), "good"
        elif raw < 2000: t.risk_norm, t.risk_label = round(3+(raw-500)/1500*4, 1), "warn"
        else: t.risk_norm, t.risk_label = min(10.0, round(7+(raw-2000)/3000*3, 1)), "danger"

        t.rc_risks = []
        for r in rc.get("risks") or []:
            name = r.get("name", ""); level = (r.get("level") or "").lower()
            desc = r.get("description", ""); val = str(r.get("value") or "")
            if name: t.rc_risks.append((level, name, desc, val))
        return t

    def _apply_gmgn_data(self, t: Token, data: dict) -> Token:
        t.gmgn_data = data
        td = self._unwrap_gmgn(data)

        for key in ("top_10_holder_pct", "top_10_holder_rate", "top10HolderPercent",
                    "top10_holder_rate", "topHolderRate"):
            raw = td.get(key)
            if raw is not None:
                try:
                    v = float(raw)
                    if 0 < v <= 1.0: v *= 100
                    if 0 < v <= 100:
                        # Hanya pakai GMGN kalau Helius tidak ada
                        if t.top10_pct == 0:
                            t.top10_pct = round(v, 1)
                            t.top10_source = "GMGN"
                except (ValueError, TypeError):
                    pass
                break

        for key in ("holder_count", "holder", "holderCount", "holders", "holder_num"):
            raw = td.get(key)
            if raw is not None:
                try:
                    # Hanya pakai GMGN kalau Helius tidak ada
                    if t.holder_count_gmgn == 0:
                        t.holder_count_gmgn = int(raw)
                except (ValueError, TypeError):
                    pass
                break

        t.dev_hold_pct = float(td.get("dev_hold_pct") or td.get("dev_holding_pct") or 0)
        t.bundle_pct = float(td.get("bundle_pct") or td.get("bundler_pct") or 0)
        t.sniper_count = int(td.get("sniper_count") or td.get("sniperCount") or 0)
        t.smart_money_count = int(td.get("smart_degen_count") or td.get("smartDegenCount") or 0)
        t.kol_holders = int(td.get("renowned_wallets") or td.get("renowned_wallet_count") or 0)
        t.is_honeypot = bool(td.get("is_honeypot") or td.get("isHoneypot"))
        t.rug_ratio = float(td.get("rug_ratio") or td.get("dev_rug_ratio") or 0)
        t.wash_trade_gmgn = bool(td.get("wash_trade_flag") or td.get("is_wash_trading"))
        t.fresh_wallet_rate = float(td.get("fresh_wallet_rate") or td.get("freshWalletRate") or 0)
        t.rat_trader_rate = float(td.get("rat_trader_amount_rate") or td.get("ratTraderRate") or 0)

        if t.smart_money_count > 0:
            t.smart_money_present = True

        return t