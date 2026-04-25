"""
data_fetcher.py — PONYIN AI AGENT v5.1 (Helius fixed + Solscan fallback updated)

Bugfix v5.1:
  - FIX KRITIS: _apply_helius_holders rumus pct salah (overflow milyaran %)
  - FIX KRITIS: pct variabel tidak selalu diassign di loop → NameError
  - FIX: helius_get_token_supply sekarang return dict {amount, decimals, ui_amount}
  - FIX: solscan_holders ganti ke endpoint yang masih aktif
  - FIX: tambah get_new_token_mints (dipanggil di agent.py /scan)
  - FIX: helius fallback lebih robust dengan logging detail
"""
import asyncio, aiohttp, logging, re
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, List, Dict
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
            timeout=aiohttp.ClientTimeout(total=20),
        ) as sess:
            yield sess

    async def _get(self, session, url, headers=HDR, timeout=12):
        try:
            async with session.get(url, headers=headers, timeout=timeout) as r:
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

    # ─────────────────────────────────────────────────────────────────
    # DEX SCREENER
    # ─────────────────────────────────────────────────────────────────
    async def dex_token(self, session, mint):
        return await self._get(session, f"https://api.dexscreener.com/tokens/v1/solana/{mint}")

    async def get_new_token_mints(self, session, limit: int = 30) -> List[str]:
        """
        Ambil token baru dari DexScreener (Solana).
        Dipakai oleh /scan command di agent.py.
        """
        url = "https://api.dexscreener.com/token-profiles/latest/v1"
        data = await self._get(session, url)
        mints = []
        if isinstance(data, list):
            for item in data:
                addr = item.get("tokenAddress", "")
                chain = item.get("chainId", "")
                if chain == "solana" and len(addr) >= 32:
                    mints.append(addr)
        elif isinstance(data, dict):
            for pair in (data.get("pairs") or []):
                base = pair.get("baseToken") or {}
                addr = base.get("address", "")
                chain = pair.get("chainId", "")
                if chain == "solana" and len(addr) >= 32:
                    mints.append(addr)

        # Fallback: DexScreener latest pairs
        if not mints:
            url2 = "https://api.dexscreener.com/latest/dex/pairs/solana"
            data2 = await self._get(session, url2)
            if isinstance(data2, dict):
                for pair in (data2.get("pairs") or []):
                    base = pair.get("baseToken") or {}
                    addr = base.get("address", "")
                    if len(addr) >= 32:
                        mints.append(addr)

        seen, result = set(), []
        for m in mints:
            if m not in seen:
                seen.add(m)
                result.append(m)
        log.info(f"get_new_token_mints: {len(result)} token ditemukan")
        return result[:limit]

    # ─────────────────────────────────────────────────────────────────
    # HELIUS RPC
    # ─────────────────────────────────────────────────────────────────
    async def helius_get_largest_holders(self, session, mint):
        """
        Helius getTokenLargestAccounts.
        Returns result dict {"value": [...]} atau None jika gagal.
        Setiap holder punya field: address, amount (raw str), uiAmount (float), decimals.
        """
        if not self.cfg.HELIUS_RPC_URL:
            log.debug("Helius: RPC URL tidak dikonfigurasi")
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
                timeout=aiohttp.ClientTimeout(total=12),
            ) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    err = data.get("error")
                    if err:
                        log.warning(f"Helius RPC error untuk {mint[:16]}: {err}")
                        return None
                    result = data.get("result")
                    if result and result.get("value"):
                        log.debug(f"Helius: {len(result['value'])} holder untuk {mint[:16]}")
                    else:
                        log.debug(f"Helius: result kosong untuk {mint[:16]}")
                    return result
                log.warning(f"Helius HTTP {r.status} untuk {mint[:16]}")
                return None
        except asyncio.TimeoutError:
            log.debug(f"Helius holders timeout: {mint[:16]}")
            return None
        except Exception as e:
            log.debug(f"Helius holders error: {e}")
            return None

    async def helius_get_token_supply(self, session, mint) -> Optional[Dict]:
        """
        Helius getTokenSupply.
        Returns dict {"raw": int, "decimals": int, "ui_amount": float} atau None.

        BUGFIX v5.1: sebelumnya hanya return int(raw) yang menyebabkan rumus
        persentase di _apply_helius_holders overflow miliaran persen.
        Sekarang return dict lengkap termasuk ui_amount.
        """
        if not self.cfg.HELIUS_RPC_URL:
            return None

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenSupply",
            "params": [mint],
        }
        try:
            async with session.post(
                self.cfg.HELIUS_RPC_URL, json=payload,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    if data.get("error"):
                        return None
                    value = data.get("result", {}).get("value", {})
                    if not value:
                        return None

                    raw       = int(value.get("amount", 0))
                    decimals  = int(value.get("decimals", 9))
                    # uiAmount sudah dikonversi oleh RPC (raw / 10^decimals)
                    ui_amount = value.get("uiAmount")
                    if ui_amount is None:
                        ui_str    = value.get("uiAmountString", "0")
                        ui_amount = float(ui_str) if ui_str else 0.0

                    return {
                        "raw":      raw,
                        "decimals": decimals,
                        "ui_amount": float(ui_amount),
                    }
        except asyncio.TimeoutError:
            log.debug(f"Helius supply timeout: {mint[:16]}")
            return None
        except Exception as e:
            log.debug(f"Helius supply error: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────
    # SOLSCAN FALLBACK
    # ─────────────────────────────────────────────────────────────────
    async def solscan_holders(self, session, mint, limit: int = 20):
        """
        Fallback holder dari Solscan.

        BUGFIX v5.1: public-api.solscan.io sudah deprecated.
        Coba 2 endpoint alternatif yang masih aktif.
        """
        endpoints = [
            # Endpoint baru Solscan v2
            f"https://api-v2.solscan.io/v2/token/holders?address={mint}&page=1&page_size={limit}",
            # Endpoint lama (kadang masih jalan)
            f"https://api.solscan.io/token/holders?tokenAddress={mint}&offset=0&size={limit}",
        ]

        for url in endpoints:
            try:
                async with session.get(
                    url,
                    headers={**HDR, "origin": "https://solscan.io", "referer": "https://solscan.io/"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    if r.status == 200:
                        data = await r.json(content_type=None)

                        # Format Solscan v2: {"data": {"items": [...]}}
                        if isinstance(data, dict) and "data" in data:
                            items = data["data"].get("items") or data["data"]
                            if isinstance(items, list) and items:
                                log.debug(f"Solscan v2: {len(items)} holder")
                                return items

                        # Format lama: list langsung atau {"data": [...]}
                        if isinstance(data, list) and data:
                            log.debug(f"Solscan legacy: {len(data)} holder")
                            return data

                    log.debug(f"Solscan HTTP {r.status}: {url[:70]}")
            except asyncio.TimeoutError:
                log.debug(f"Solscan timeout: {url[:50]}")
            except Exception as e:
                log.debug(f"Solscan error: {e}")

        log.debug(f"Solscan: semua endpoint gagal untuk {mint[:16]}")
        return None

    # ─────────────────────────────────────────────────────────────────
    # APPLY HOLDER DATA
    # ─────────────────────────────────────────────────────────────────
    def _apply_helius_holders(self, t: Token, holders_data, supply_info: Optional[Dict]) -> Token:
        """
        Terapkan data holder dari Helius ke Token.

        BUGFIX v5.1 — 2 bug kritis diperbaiki:
        1. Rumus lama: pct = amount_raw / supply_ui * 100
           → SALAH: amount_raw bisa 10^9 kali lebih besar dari supply_ui
           → BENAR: gunakan ui_amount (sudah dikonversi) dari kedua sisi

        2. Variabel pct tidak selalu diassign di loop:
           → Jika supply_info None/0, 'pct' tidak pernah diassign
           → total_pct += pct → NameError atau nilai stale dari iterasi sebelumnya
        """
        if not holders_data or "value" not in holders_data:
            log.debug("Helius holders: data kosong atau tidak ada 'value'")
            return t

        holder_list = holders_data["value"]
        if not holder_list:
            log.debug("Helius holders: list kosong")
            return t

        t.helius_holders_available = True
        t.holder_list_helius       = holder_list
        t.holder_count_helius      = len(holder_list)

        # Token masih di bonding curve / tidak ada pair: skip kalkulasi %
        if t.liq <= 0 or t.mc <= 0:
            t.top10_source = "Helius (bonding/dead — skip kalkulasi %)"
            return t

        # Validasi supply
        if not supply_info:
            log.debug(f"Helius: supply_info None untuk {t.mint[:16]} — skip % calc")
            t.top10_source = f"Helius ({len(holder_list)} holders, supply N/A)"
            return t

        supply_ui = supply_info.get("ui_amount", 0.0)
        if supply_ui <= 0:
            log.debug(f"Helius: supply ui_amount=0 untuk {t.mint[:16]}")
            t.top10_source = f"Helius ({len(holder_list)} holders, supply=0)"
            return t

        # ── Hitung top10 % menggunakan uiAmount (unit yang sama) ────
        # BUGFIX: dulu pakai amount_raw / supply_ui → overflow
        # Sekarang: holder_uiAmount / supply_ui (keduanya dalam unit token)
        total_pct = 0.0
        for h in holder_list[:10]:
            # uiAmount sudah dikonversi oleh RPC (amount_raw / 10^decimals)
            ui = h.get("uiAmount")
            if ui is None:
                # Fallback: hitung manual dari raw amount
                raw_h    = int(h.get("amount", 0))
                decimals = supply_info.get("decimals", 9)
                ui       = raw_h / (10 ** decimals)
            pct = (float(ui) / supply_ui) * 100.0   # ← BUGFIX: keduanya pakai unit yang sama
            total_pct += pct

        log.debug(
            f"Helius top10 calc: {len(holder_list)} holders, "
            f"supply_ui={supply_ui:,.0f}, total_pct={total_pct:.2f}%"
        )

        if 0.0 < total_pct <= 100.0:
            t.top10_pct    = round(total_pct, 1)
            t.top10_source = f"Helius ({len(holder_list)} holders)"
        else:
            # Nilai di luar range normal — log untuk debug tapi jangan crash
            log.warning(
                f"Helius pct out of range {total_pct:.2f}% untuk {t.mint[:16]} "
                f"(supply_ui={supply_ui:.0f})"
            )
            t.top10_source = f"Helius (invalid pct {total_pct:.1f}%)"

        return t

    def _apply_solscan_holders(self, t: Token, holders_list: list) -> Token:
        """
        Terapkan data holder dari Solscan ke Token.
        Handle format v2 dan legacy.
        """
        if not holders_list:
            return t

        t.solscan_holders_available = True
        total_pct = 0.0
        valid_count = 0

        for h in holders_list[:10]:
            # Format Solscan v2: {"owner": "...", "amount": "...", "decimals": 9}
            pct = 0.0
            if "percentage" in h:
                pct = float(h["percentage"])
            elif "amount" in h and "total_supply" in h:
                try:
                    pct = float(h["amount"]) / float(h["total_supply"]) * 100
                except (ZeroDivisionError, ValueError):
                    pass

            if 0.0 < pct <= 100.0:
                total_pct   += pct
                valid_count += 1

        t.holder_count_solscan = len(holders_list)

        if valid_count > 0 and 0.0 < total_pct <= 100.0:
            t.top10_pct    = round(total_pct, 1)
            t.top10_source = f"Solscan ({len(holders_list)} holders)"
        else:
            t.top10_source = f"Solscan ({len(holders_list)} holders, pct N/A)"

        return t

    # ─────────────────────────────────────────────────────────────────
    # RUGCHECK
    # ─────────────────────────────────────────────────────────────────
    async def rugcheck_full(self, session, mint):
        return await self._get(session, f"https://api.rugcheck.xyz/v1/tokens/{mint}/report")

    # ─────────────────────────────────────────────────────────────────
    # FETCH TOKEN (entry point utama)
    # ─────────────────────────────────────────────────────────────────
    async def fetch_token(self, session, mint) -> Optional[Token]:
        """
        Fetch dan assemble semua data token:
        1. DexScreener (price, MC, liq, vol, social)
        2. Helius (top holders %)  → fallback Solscan
        3. RugCheck (risk score, LP burn, topHolders)
        """
        # Step 1: Data dasar dari DexScreener
        dex_data = await self.dex_token(session, mint)
        token    = self._parse_dex(dex_data)
        if not token:
            log.debug(f"fetch_token: token tidak ditemukan di DexScreener: {mint[:16]}")
            return None

        helius_holders = None
        helius_supply  = None
        solscan_data   = None
        rc_data        = None

        # Step 2a: Helius untuk holder data
        if self.cfg.HELIUS_ENABLED:
            log.debug(f"Fetching Helius data untuk {mint[:16]}...")
            try:
                results = await asyncio.gather(
                    self.helius_get_largest_holders(session, mint),
                    self.helius_get_token_supply(session, mint),
                    return_exceptions=True,
                )
                helius_holders = results[0] if not isinstance(results[0], Exception) else None
                helius_supply  = results[1] if not isinstance(results[1], Exception) else None

                if helius_holders and helius_supply:
                    log.info(
                        f"Helius OK: {len(helius_holders.get('value', []))} holders, "
                        f"supply={helius_supply.get('ui_amount', 0):,.0f}"
                    )
                else:
                    log.debug(
                        f"Helius partial: holders={'OK' if helius_holders else 'FAIL'}, "
                        f"supply={'OK' if helius_supply else 'FAIL'}"
                    )
            except Exception as e:
                log.warning(f"Helius gather error: {e}")
        else:
            log.debug("Helius disabled — HELIUS_API_KEY tidak diset")

        # Step 2b: Solscan sebagai fallback jika Helius gagal
        if not helius_holders:
            log.debug(f"Helius gagal, mencoba Solscan untuk {mint[:16]}...")
            solscan_data = await self.solscan_holders(session, mint)
            if solscan_data:
                log.debug(f"Solscan OK: {len(solscan_data)} holders")

        # Step 3: RugCheck untuk risk score dan LP burn
        log.debug(f"Fetching RugCheck untuk {mint[:16]}...")
        rc_data = await self.rugcheck_full(session, mint)
        if rc_data:
            log.debug(f"RugCheck OK: risk={rc_data.get('score', '?')}")
        else:
            log.debug(f"RugCheck gagal untuk {mint[:16]}")

        # Step 4: Apply semua data ke token
        if helius_holders:
            # BUGFIX: sekarang pass supply_info dict, bukan raw int
            self._apply_helius_holders(token, helius_holders, helius_supply)
        elif solscan_data:
            self._apply_solscan_holders(token, solscan_data)

        if rc_data:
            self._apply_rugcheck(token, rc_data)

        log.info(
            f"fetch_token done: {token.symbol} | "
            f"top10={token.top10_pct}% ({token.top10_source}) | "
            f"risk={token.risk_norm}/10 | lp={token.lp_burn}%"
        )
        return token

    # ─────────────────────────────────────────────────────────────────
    # PARSER HELPERS (tidak berubah dari v5.0)
    # ─────────────────────────────────────────────────────────────────
    def _parse_socials(self, pair):
        tw = tg = web = False
        info = pair.get("info") or {}
        for s in (info.get("socials") or []):
            t   = (s.get("type") or "").lower()
            url = (s.get("url")  or "").lower()
            if t in ("twitter", "x") or "twitter.com" in url or "x.com" in url:
                tw = True
            if t == "telegram" or "t.me" in url:
                tg = True
        for w in (info.get("websites") or []):
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

            price = float(pair.get("priceUsd")   or 0)
            mc    = float(pair.get("marketCap")   or pair.get("fdv") or 0)
            liq   = float((pair.get("liquidity") or {}).get("usd") or 0)
            vol   = pair.get("volume")     or {}
            pc    = pair.get("priceChange") or {}
            txns  = pair.get("txns")        or {}
            h1    = txns.get("h1")          or {}

            cr = pair.get("pairCreatedAt") or 0
            if cr:
                cd      = datetime.fromtimestamp(cr / 1000)
                created = cd.strftime("%Y-%m-%d %H:%M")
                age_h   = (datetime.now() - cd).total_seconds() / 3600
            else:
                created, age_h = "unknown", 0.0

            tw, tg, web = self._parse_socials(pair)

            return Token(
                mint=mint,
                name=base.get("name",   "Unknown"),
                symbol=base.get("symbol", "???"),
                price=price,   mc=mc,  liq=liq,
                vol1h=float(vol.get("h1")  or 0),
                vol6h=float(vol.get("h6")  or 0),
                vol24h=float(vol.get("h24") or 0),
                chg1h=float(pc.get("h1")   or 0),
                chg6h=float(pc.get("h6")   or 0),
                chg24h=float(pc.get("h24") or 0),
                buys1h=int(h1.get("buys")  or 0),
                sells1h=int(h1.get("sells") or 0),
                has_twitter=tw, has_telegram=tg, has_website=web,
                dex=pair.get("dexId", ""),
                pair_addr=pair.get("pairAddress", ""),
                created=created, age_hours=age_h,
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

    def _apply_rugcheck(self, t: Token, rc) -> Token:
        if not rc:
            return t

        t.is_rugged   = bool(rc.get("rugged"))
        t.mint_auth   = rc.get("mintAuthority")
        t.freeze_auth = rc.get("freezeAuthority")

        raw      = int(rc.get("score") or 0)
        t.risk_raw = raw
        if raw < 500:
            t.risk_norm, t.risk_label = round(raw / 500 * 3, 1), "good"
        elif raw < 2000:
            t.risk_norm, t.risk_label = round(3 + (raw - 500) / 1500 * 4, 1), "warn"
        else:
            t.risk_norm, t.risk_label = min(10.0, round(7 + (raw - 2000) / 3000 * 3, 1)), "danger"

        for mkt in (rc.get("markets") or []):
            lp  = mkt.get("lp") or {}
            pct = float(lp.get("lpLockedPct") or 0)
            if pct > t.lp_burn:
                t.lp_burn = pct
            if lp.get("lpBurned") or lp.get("burned"):
                t.lp_burn = 100.0

        t.rc_risks = []
        for r in (rc.get("risks") or []):
            name  = r.get("name",  "")
            level = (r.get("level") or "").lower()
            desc  = r.get("description", "")
            val   = str(r.get("value") or "")
            if name:
                t.rc_risks.append((level, name, desc, val))

        # Top10 dari RugCheck — hanya jika sumber lain belum ada
        if t.top10_pct == 0:
            top_h = rc.get("topHolders") or []
            t.top_holders   = top_h
            t.holder_count_rc = len(top_h)
            if top_h:
                total = 0.0
                for h in top_h[:10]:
                    pct = float(h.get("pct") or 0)
                    # RugCheck kadang return decimal (0–1) atau persen (0–100)
                    if 0 < pct <= 1.0:
                        pct *= 100
                    total += pct
                if total > 0:
                    t.top10_pct    = round(total, 1)
                    t.top10_source = f"RugCheck ({len(top_h)})"
        else:
            # Tetap simpan data RugCheck untuk cluster analysis
            t.top_holders    = rc.get("topHolders") or []
            t.holder_count_rc = len(t.top_holders)

        return t
