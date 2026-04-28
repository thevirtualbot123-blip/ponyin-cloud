"""
data_fetcher.py — PONYIN AI AGENT v8.1
Fixes:
  - GMGN top10 parsing dari proxy response (format beda dari direct)
  - Debug logging untuk semua GMGN keys
  - Jangan override GMGN top10 dengan RugCheck/Helius
  - HAPUS gmgn_via_bridge (Node.js bridge tidak diperlukan)
  - HAPUS _gmgn_fetch (tls_client tidak reliable di Railway)
  - GANTI dengan GMGNClient (curl-cffi + proxy support)

Requirements baru di requirements.txt:
    curl-cffi>=0.6.0
    (hapus: tls_client, fake_useragent)

ENV Railway:
    GMGN_API_KEY=your_key_here
    GMGN_PROXY_URL=https://your-worker.workers.dev
    (Hapus GMGN_BRIDGE_URL — tidak dipakai lagi)
"""
import asyncio, aiohttp, logging, re
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, List, Tuple
from collections import defaultdict
from filter_engine import Token
from gmgn_client import GMGNClient

log = logging.getLogger("PONYIN.Fetcher")
HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}
CA_PATTERN = re.compile(r'[1-9A-HJ-NP-Za-km-z]{32,44}')


class DataFetcher:

    def __init__(self, cfg=None):
        from config import AgentConfig
        self.cfg  = cfg or AgentConfig()
        self.gmgn = GMGNClient(api_key=self.cfg.GMGN_API_KEY, proxy_url=getattr(self.cfg, 'GMGN_PROXY_URL', ''))

    @asynccontextmanager
    async def session(self):
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False),
            timeout=aiohttp.ClientTimeout(total=20),
        ) as sess:
            yield sess

    async def _get(self, session, url, headers=HDR, timeout=12):
        try:
            async with session.get(
                url, headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as r:
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
        if not isinstance(data, dict):
            return {}
        inner = data.get("token")
        if isinstance(inner, dict):
            return inner
        return data

    # ── DexScreener ─────────────────────────────────────────────────
    async def dex_token(self, session, mint: str) -> Optional[dict]:
        return await self._get(
            session,
            f"https://api.dexscreener.com/tokens/v1/solana/{mint}"
        )

    async def dex_tokens_batch(self, session, mints: List[str]) -> list:
        if not mints:
            return []
        batch_str = ",".join(mints[:30])
        data = await self._get(
            session,
            f"https://api.dexscreener.com/tokens/v1/solana/{batch_str}"
        )
        if not data:
            return []
        return data if isinstance(data, list) else (data.get("pairs") or [])

    # ── GMGN via curl-cffi langsung (tanpa bridge) ───────────────────
    async def gmgn_token_info(self, session, mint: str) -> Optional[dict]:
        """curl-cffi bypass Cloudflare. session param dipertahankan utk compat."""
        return await self.gmgn.token_info(mint)

    async def gmgn_new_tokens(self, session) -> List[str]:
        return await self.gmgn.new_token_mints()

    async def gmgn_new_tokens_via_bridge(self, session) -> List[str]:
        """Deprecated — bridge dihapus. Return [] utk backward compat."""
        return []

    # ── Helius DAS ───────────────────────────────────────────────────
    SYSTEM_ADDRS = frozenset({
        "11111111111111111111111111111111",
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
        "1nc1nerator11111111111111111111111111111111",
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
        "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
        "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
        "HWy1jotHpo6UqeQxx49dpYYdQB8wj9Qk9MdxwjLvDHB8",
        "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
        "9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP",
        "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
        "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",
        "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EkAW7cP",
        "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",
    })

    async def helius_get_all_holders(self, session, mint: str) -> List[dict]:
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
                    data     = await r.json()
                    result   = data.get("result", {})
                    accounts = result.get("token_accounts", [])
                    if not accounts:
                        break
                    for acc in accounts:
                        all_accounts.append({
                            "owner":    acc.get("owner", ""),
                            "amount":   acc.get("amount", "0"),
                            "uiAmount": float(acc.get("uiAmount", 0) or 0),
                        })
                    if len(accounts) < 1000:
                        break
                    page += 1
                    if page > 10:
                        log.warning(f"Helius pagination cap {mint[:12]}")
                        break
            except Exception as e:
                log.warning(f"Helius p{page} error {mint[:12]}: {e}")
                break
        log.info(f"Helius: {len(all_accounts)} raw accounts for {mint[:12]}")
        return all_accounts

    async def helius_get_token_supply(self, session, mint: str) -> Optional[dict]:
        if not self.cfg.HELIUS_API_KEY:
            return None
        payload = {
            "jsonrpc": "2.0", "id": 1,
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

    def _calculate_top10_from_helius(self, t, accounts, supply_data):
        if not accounts:
            return t
        supply_info  = supply_data.get("value") if supply_data else {}
        decimals     = int(supply_info.get("decimals", 9))
        divisor      = 10 ** decimals if decimals >= 0 else 1
        total_supply = float(supply_info.get("uiAmount") or 0)
        if total_supply <= 0:
            raw_supply = supply_info.get("amount", "0") or "0"
            try:
                total_supply = int(raw_supply) / divisor
            except (ValueError, TypeError):
                pass
        if total_supply <= 0:
            log.warning(f"Helius supply zero/missing {t.mint[:12]}")
            return t

        owner_totals: defaultdict = defaultdict(float)
        for acc in accounts:
            owner = acc.get("owner", "")
            if not owner or owner in self.SYSTEM_ADDRS:
                continue
            ui = float(acc.get("uiAmount") or 0)
            if ui == 0:
                raw = acc.get("amount", "0") or "0"
                try:
                    ui = int(raw) / divisor
                except (ValueError, TypeError):
                    ui = 0
            if ui > 0:
                owner_totals[owner] += ui

        if not owner_totals:
            return t

        sorted_owners = sorted(owner_totals.items(), key=lambda x: x[1], reverse=True)
        top10_sum     = sum(amt for _, amt in sorted_owners[:10])
        top10_pct     = (top10_sum / total_supply) * 100

        # FIX v8.1: JANGAN override kalau sudah ada GMGN data
        if t.top10_source == "GMGN" and t.top10_pct > 0:
            log.info(f"Helius skipped — GMGN top10 already set: {t.top10_pct}%")
            t.holder_count_gmgn = len(sorted_owners)
            return t

        t.top10_pct           = round(min(top10_pct, 100.0), 1)
        t.top10_source        = f"Helius({len(sorted_owners)}h)"
        t.holder_count_gmgn   = len(sorted_owners)
        log.info(f"Helius TOP10 {t.mint[:12]}: {t.top10_pct}% from {len(sorted_owners)} holders")
        return t

    def _update_holder_count_from_helius(self, t, accounts):
        owners = {
            acc.get("owner", "")
            for acc in accounts
            if acc.get("owner", "") and acc.get("owner", "") not in self.SYSTEM_ADDRS
        }
        if owners:
            t.holder_count_gmgn = len(owners)
        return t

    # ── RugCheck ─────────────────────────────────────────────────────
    async def rugcheck_full(self, session, mint: str) -> Optional[dict]:
        return await self._get(
            session,
            f"https://api.rugcheck.xyz/v1/tokens/{mint}/report"
        )

    # ── Discovery ────────────────────────────────────────────────────
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
        unique = list(dict.fromkeys(mints))
        log.info(
            f"Discovery: {len(unique)} unique mints "
            f"(profiles={len(profiles) if isinstance(profiles,list) else 0}, "
            f"boosted={len(boosted) if isinstance(boosted,list) else 0}, "
            f"rc={len(rc_new) if isinstance(rc_new,list) else 0}, "
            f"gmgn={len(gmgn_new) if isinstance(gmgn_new,list) else 0})"
        )
        return unique[:100]

    async def dex_latest_profiles(self, session) -> list:
        d = await self._get(session, "https://api.dexscreener.com/token-profiles/latest/v1")
        return [x for x in (d or []) if x.get("chainId") == "solana"]

    async def dex_boosted(self, session) -> list:
        d = await self._get(session, "https://api.dexscreener.com/token-boosts/latest/v1")
        return [x for x in (d or []) if x.get("chainId") == "solana"]

    async def rc_new_tokens(self, session) -> list:
        d = await self._get(session, "https://api.rugcheck.xyz/v1/stats/new_tokens")
        return d if isinstance(d, list) else []

    async def dex_search_new_solana(self, session) -> List[str]:
        mints: List[str] = []
        for q in ("pumpfun+solana", "pump.fun+solana", "raydium+solana"):
            data = await self._get(
                session,
                f"https://api.dexscreener.com/latest/dex/search?q={q}",
                timeout=10
            )
            if not data:
                continue
            pairs = data.get("pairs") or (data if isinstance(data, list) else [])
            for p in (pairs if isinstance(pairs, list) else []):
                if isinstance(p, dict) and p.get("chainId") == "solana":
                    addr = (p.get("baseToken") or {}).get("address", "")
                    if addr and len(addr) >= 32:
                        mints.append(addr)
        unique = list(dict.fromkeys(mints))
        log.info(f"DexSearch fallback: {len(unique)} mints")
        return unique[:60]

    # ── Filtered Scan ────────────────────────────────────────────────
    async def get_filtered_scan_mints(
        self, session,
        min_mc=5_000, max_mc=800_000,
        min_liq=1_000, min_vol1h=1_000,
        allowed_dex=None, max_results=20
    ) -> List[Tuple[float, str]]:
        if allowed_dex is None:
            allowed_dex = {
                "pump_fun", "pumpfun", "pump.fun", "pumpswap", "pump_swap",
                "raydium", "meteora", "orca", "lifinity", "phoenix"
            }
        raw_mints = await self.get_new_token_mints(session)
        if len(raw_mints) < 10:
            log.warning(f"Discovery hanya {len(raw_mints)} mint — DexSearch fallback")
            for m in await self.dex_search_new_solana(session):
                if m not in raw_mints:
                    raw_mints.append(m)
        if not raw_mints:
            log.warning("Scan: tidak ada mint dari semua sumber")
            return []

        all_pairs = []
        for i in range(0, min(len(raw_mints), 90), 30):
            pairs = await self.dex_tokens_batch(session, raw_mints[i:i+30])
            if pairs:
                all_pairs.extend(pairs)

        log.info(f"Scan: {len(all_pairs)} pairs dari DexScreener")
        rej = {"chain": 0, "mc_low": 0, "mc_high": 0, "liq": 0, "vol": 0, "dex": 0}
        candidates, seen = [], set()

        for pair in all_pairs:
            if not isinstance(pair, dict):
                continue
            if pair.get("chainId", "solana") != "solana":
                rej["chain"] += 1; continue
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
            cr    = int(pair.get("pairCreatedAt") or 0)
            age_h = (datetime.now().timestamp()*1000 - cr)/3_600_000 if cr else 99
            dex_id = (pair.get("dexId") or "").lower().replace(".", "_").replace("-", "_")

            if mc < min_mc:   rej["mc_low"]  += 1; continue
            if mc > max_mc:   rej["mc_high"] += 1; continue
            if liq < min_liq: rej["liq"]     += 1; continue

            vol_eff = vol1h or (vol5m * 12 if age_h < 1 and vol5m else vol24h / max(age_h, 1))
            if vol_eff < min_vol1h * 0.3:
                rej["vol"] += 1; continue

            if allowed_dex and not any(a == dex_id or a in dex_id or dex_id in a for a in allowed_dex):
                rej["dex"] += 1; continue

            seen.add(mint)
            candidates.append((chg5m, mint))

        log.info(
            f"Filter result: {len(candidates)} lolos | "
            f"Reject: chain={rej['chain']} mc_low={rej['mc_low']} "
            f"mc_high={rej['mc_high']} liq={rej['liq']} "
            f"vol={rej['vol']} dex={rej['dex']}"
        )
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[:max_results]

    # ── Fetch Utama ──────────────────────────────────────────────────
    async def fetch_token(self, session, mint: str) -> Optional[Token]:
        dex_raw, gmgn_raw, rc_raw = await asyncio.gather(
            self.dex_token(session, mint),
            self.gmgn_token_info(session, mint),
            self.rugcheck_full(session, mint),
            return_exceptions=True,
        )
        dex_raw  = None if isinstance(dex_raw,  Exception) else dex_raw
        gmgn_raw = None if isinstance(gmgn_raw, Exception) else gmgn_raw
        rc_raw   = None if isinstance(rc_raw,   Exception) else rc_raw

        log.info(
            f"Sources {mint[:12]}: "
            f"DEX={'OK' if dex_raw else 'FAIL'} | "
            f"GMGN={'OK' if gmgn_raw else 'FAIL'} | "
            f"RC={'OK' if rc_raw else 'FAIL'}"
        )

        token = self._parse_dex(dex_raw)
        if not token:
            if rc_raw:
                token = self._build_token_from_rugcheck(rc_raw, mint)
                if token:
                    log.info(f"DEX fail — RugCheck fallback {mint[:12]}")
            if not token:
                log.warning(f"fetch_token: semua sumber gagal {mint[:12]}")
                return None

        if gmgn_raw:
            token = self._apply_gmgn_data(token, gmgn_raw)

        if rc_raw:
            token = self._apply_rugcheck(token, rc_raw)

        if self.cfg.HELIUS_API_KEY:
            helius_accounts = await self.helius_get_all_holders(session, mint)
            if helius_accounts:
                helius_supply  = await self.helius_get_token_supply(session, mint)
                gmgn_has_top10 = token.top10_pct > 0 and token.top10_source == "GMGN"
                if not gmgn_has_top10:
                    token = self._calculate_top10_from_helius(token, helius_accounts, helius_supply or {})
                else:
                    token = self._update_holder_count_from_helius(token, helius_accounts)

        log.info(
            f"Final {mint[:12]}: MC=${token.mc:,.0f} | "
            f"Holders={token.holder_count_gmgn} | "
            f"Top10={token.top10_pct:.1f}% ({token.top10_source}) | "
            f"LP={token.lp_burn:.0f}% | Risk={token.risk_norm}/10"
        )
        return token

    # ── Parse helpers ────────────────────────────────────────────────
    def _parse_socials(self, pair):
        tw = tg = web = False
        info = pair.get("info") or {}
        for s in info.get("socials") or []:
            t_url = (s.get("type") or "").lower()
            url   = (s.get("url") or "").lower()
            if t_url in ("twitter", "x") or "twitter.com" in url or "x.com" in url: tw = True
            if t_url == "telegram" or "t.me" in url: tg = True
        for w in info.get("websites") or []:
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

    def _parse_pair(self, pair):
        try:
            base  = pair.get("baseToken") or {}
            mint  = base.get("address", "")
            if not mint or len(mint) < 30: return None
            price = float(pair.get("priceUsd") or 0)
            mc    = float(pair.get("marketCap") or pair.get("fdv") or 0)
            liq   = float((pair.get("liquidity") or {}).get("usd") or 0)
            vol   = pair.get("volume") or {}
            pc    = pair.get("priceChange") or {}
            txns  = pair.get("txns") or {}
            h1    = txns.get("h1") or {}
            cr    = pair.get("pairCreatedAt") or 0
            info  = pair.get("info") or {}
            lp_burned = any(
                "burn" in (b.get("label") or "").lower()
                for b in info.get("badges") or []
            )
            if cr:
                cd = datetime.fromtimestamp(cr / 1000)
                created = cd.strftime("%Y-%m-%d %H:%M")
                age_h   = (datetime.now() - cd).total_seconds() / 3600
            else:
                created, age_h = "unknown", 0.0
            tw, tg, web = self._parse_socials(pair)
            token = Token(
                mint=mint, name=base.get("name","Unknown"),
                symbol=base.get("symbol","???"),
                price=price, mc=mc, liq=liq,
                vol1h=float(vol.get("h1") or 0),
                vol6h=float(vol.get("h6") or 0),
                vol24h=float(vol.get("h24") or 0),
                chg5m=float(pc.get("m5") or 0),
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
        sol  = [p for p in pairs if isinstance(p,dict) and p.get("chainId")=="solana"]
        pool = sol or [p for p in pairs if isinstance(p,dict)]
        if not pool: return None
        best = max(pool, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))
        return self._parse_pair(best)

    def _build_token_from_rugcheck(self, rc: dict, mint: str) -> Optional[Token]:
        try:
            meta   = rc.get("tokenMeta") or {}
            name   = meta.get("name") or "Unknown"
            symbol = meta.get("symbol") or "???"
            price  = liq = 0.0
            for mkt in rc.get("markets") or []:
                lp        = mkt.get("lp") or {}
                price_raw = mkt.get("price") or mkt.get("priceUsd") or 0
                if price_raw: price = float(price_raw)
                liq_raw   = lp.get("lpCurrentSupply") or mkt.get("liquidity") or 0
                if liq_raw: liq = max(liq, float(liq_raw))
            return Token(mint=mint, name=name, symbol=symbol, price=price, mc=0.0, liq=liq, dex="rugcheck-fallback")
        except Exception as e:
            log.debug(f"_build_token_from_rugcheck error {mint[:12]}: {e}")
            return None

    def _apply_rugcheck(self, t: Token, rc: dict) -> Token:
        if not rc: return t
        t.is_rugged   = bool(rc.get("rugged"))
        t.mint_auth   = rc.get("mintAuthority")
        t.freeze_auth = rc.get("freezeAuthority")
        t.top_holders = rc.get("topHolders") or []

        t.holder_count_rc = 0
        for key in ("holderCount","holders","totalHolders","holder_count"):
            val = rc.get(key)
            if val is not None:
                try: t.holder_count_rc = int(val); break
                except: continue

        # FIX v8.1: JANGAN override top10 kalau sudah dari GMGN
        if t.top10_source == "GMGN" and t.top10_pct > 0:
            log.info(f"RugCheck top10 skipped — GMGN already set: {t.top10_pct}%")
        elif t.top_holders and t.top10_pct == 0:
            total_pct = 0.0
            for h in t.top_holders[:10]:
                pct_h = float(h.get("pct", 0) or 0)
                if 0 < pct_h <= 1.0: pct_h *= 100
                if 0 < pct_h <= 100: total_pct += pct_h
            if 0 < total_pct <= 100:
                t.top10_pct    = round(total_pct, 1)
                t.top10_source = "RugCheck"

        for mkt in rc.get("markets") or []:
            lp = mkt.get("lp") or {}
            for pct_key in ("lpLockedPct","lpBurnedPct","burnedPercent","burnPct","lockedPct"):
                raw_pct = lp.get(pct_key)
                if raw_pct is not None:
                    try:
                        pct_val = float(raw_pct)
                        if 0 < pct_val <= 1.0: pct_val *= 100
                        if pct_val > t.lp_burn: t.lp_burn = pct_val
                    except: pass
            if lp.get("lpBurned") or lp.get("burned") or lp.get("isBurned") or lp.get("burn"):
                t.lp_burn = 100.0; t.gmgn_lp_burned = True
            try:
                lp_c = lp.get("lpCurrentSupply")
                lp_t = lp.get("lpTotalSupply")
                if lp_c is not None and lp_t is not None:
                    lp_c, lp_t = float(lp_c), float(lp_t)
                    if lp_c == 0 and lp_t > 0:
                        t.lp_burn = 100.0; t.gmgn_lp_burned = True
                    elif 0 < lp_c < lp_t:
                        pct_supply = round((1 - lp_c/lp_t)*100, 1)
                        if pct_supply > t.lp_burn: t.lp_burn = pct_supply
            except: pass

        raw = int(rc.get("score") or 0)
        if raw < 500:
            t.risk_norm, t.risk_label = round(raw/500*3, 1), "good"
        elif raw < 2000:
            t.risk_norm, t.risk_label = round(3 + (raw-500)/1500*4, 1), "warn"
        else:
            t.risk_norm, t.risk_label = min(10.0, round(7+(raw-2000)/3000*3, 1)), "danger"

        t.rc_risks = []
        for r in rc.get("risks") or []:
            name  = r.get("name", "")
            level = (r.get("level") or "").lower()
            desc  = r.get("description", "")
            val   = str(r.get("value") or "")
            if name:
                t.rc_risks.append((level, name, desc, val))
        return t

    def _apply_gmgn_data(self, t: Token, data: dict) -> Token:
        t.gmgn_data = data
        td = self._unwrap_gmgn(data)

        # DEBUG: log semua key yang ada di GMGN response
        log.info(f"GMGN keys for {t.mint[:12]}: {list(td.keys())[:30]}")

        # GMGN v2 format: top10 bisa di nested 'dev' atau 'pool' object
        dev_data = td.get("dev") or {}
        pool_data = td.get("pool") or {}

        # DEBUG: log nested keys
        if dev_data:
            log.info(f"GMGN dev keys for {t.mint[:12]}: {list(dev_data.keys())[:20]}")
        if pool_data:
            log.info(f"GMGN pool keys for {t.mint[:12]}: {list(pool_data.keys())[:20]}")

        # TOP10% — coba dari berbagai lokasi
        top10_found = False

        # 1. Coba dari root level (format lama)
        for key in ("top_10_holder_pct","top_10_holder_rate","top10HolderPercent",
                    "top10_holder_rate","topHolderRate", "top_10_holder_percent",
                    "top10_holder_percent", "top_holder_rate", "top10_pct"):
            raw = td.get(key)
            if raw is not None:
                try:
                    v = float(raw)
                    if 0 < v <= 1.0: v *= 100
                    if 0 < v <= 100:
                        t.top10_pct    = round(v, 1)
                        t.top10_source = "GMGN"
                        top10_found = True
                        log.info(f"GMGN top10 (root): {t.top10_pct}% for {t.mint[:12]} (key={key})")
                except Exception as e:
                    log.debug(f"GMGN top10 parse error: {e}")
                break

        # 2. Coba dari dev object (format baru)
        if not top10_found and dev_data:
            for key in ("top_10_holder_rate", "top10_holder_rate", "topHolderRate",
                        "top_10_holder_pct", "holder_rate", "top10_pct"):
                raw = dev_data.get(key)
                if raw is not None:
                    try:
                        v = float(raw)
                        if 0 < v <= 1.0: v *= 100
                        if 0 < v <= 100:
                            t.top10_pct    = round(v, 1)
                            t.top10_source = "GMGN"
                            top10_found = True
                            log.info(f"GMGN top10 (dev): {t.top10_pct}% for {t.mint[:12]} (key={key})")
                    except Exception as e:
                        log.debug(f"GMGN top10 dev parse error: {e}")
                    break

        # 3. Coba dari pool object
        if not top10_found and pool_data:
            for key in ("top_10_holder_rate", "top10_holder_rate", "topHolderRate"):
                raw = pool_data.get(key)
                if raw is not None:
                    try:
                        v = float(raw)
                        if 0 < v <= 1.0: v *= 100
                        if 0 < v <= 100:
                            t.top10_pct    = round(v, 1)
                            t.top10_source = "GMGN"
                            top10_found = True
                            log.info(f"GMGN top10 (pool): {t.top10_pct}% for {t.mint[:12]} (key={key})")
                    except Exception as e:
                        log.debug(f"GMGN top10 pool parse error: {e}")
                    break

        if not top10_found:
            log.warning(f"GMGN top10 NOT FOUND for {t.mint[:12]}. "
                       f"Root keys: {list(td.keys())[:15]} | "
                       f"Dev keys: {list(dev_data.keys())[:15] if dev_data else 'N/A'} | "
                       f"Pool keys: {list(pool_data.keys())[:15] if pool_data else 'N/A'}")

        # holder_count
        for key in ("holder_count","holder","holderCount","holders","holder_num"):
            raw = td.get(key)
            if raw is not None:
                try: 
                    t.holder_count_gmgn = int(raw)
                    log.info(f"GMGN holders: {t.holder_count_gmgn} for {t.mint[:12]} (key={key})")
                except: pass
                break

        # dev_hold_pct dari dev object
        if dev_data:
            dev_hold = dev_data.get("hold") or dev_data.get("hold_pct") or dev_data.get("holding_pct")
            if dev_hold is not None:
                try:
                    t.dev_hold_pct = float(dev_hold)
                    if 0 < t.dev_hold_pct <= 1.0: t.dev_hold_pct *= 100
                    log.info(f"GMGN dev_hold: {t.dev_hold_pct:.1f}% for {t.mint[:12]}")
                except: pass

        t.bundle_pct        = float(td.get("bundle_pct")             or td.get("bundler_pct")           or 0)
        t.sniper_count      = int(td.get("sniper_count")             or td.get("sniperCount")           or 0)
        t.smart_money_count = int(td.get("smart_degen_count")        or td.get("smartDegenCount")       or 0)
        t.kol_holders       = int(td.get("renowned_wallets")         or td.get("renowned_wallet_count") or 0)
        t.is_honeypot       = bool(td.get("is_honeypot")             or td.get("isHoneypot"))
        t.rug_ratio         = float(td.get("rug_ratio")              or td.get("dev_rug_ratio")         or 0)
        t.wash_trade_gmgn   = bool(td.get("wash_trade_flag")         or td.get("is_wash_trading"))
        t.fresh_wallet_rate = float(td.get("fresh_wallet_rate")      or td.get("freshWalletRate")       or 0)
        t.rat_trader_rate   = float(td.get("rat_trader_amount_rate") or td.get("ratTraderRate")         or 0)

        # LP burn dari GMGN
        if td.get("lp_burned") or td.get("is_lp_burned") or td.get("burned"):
            t.lp_burn = 100.0
            t.gmgn_lp_burned = True
            log.info(f"GMGN LP burned: 100% for {t.mint[:12]}")

        if t.smart_money_count > 0:
            t.smart_money_present = True
        return t
