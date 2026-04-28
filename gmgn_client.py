"""
gmgn_client.py — PONYIN GMGN Client v1.0
=========================================
Drop-in replacement untuk gmgn_via_bridge + _gmgn_fetch di data_fetcher.py.

Solusi: curl-cffi dengan Chromium TLS fingerprint — bisa bypass Cloudflare
tanpa perlu Node.js bridge sama sekali.

Install:
    pip install curl-cffi

Cara integrasi di data_fetcher.py:
    1. Hapus folder gmgn_bridge (Node.js tidak lagi diperlukan)
    2. Import dan pakai GMGNClient di DataFetcher
    3. Lihat contoh integrasi di bagian bawah file ini
"""

import asyncio
import logging
import random
from typing import Optional, List

log = logging.getLogger("PONYIN.GMGN")

# ── Endpoint catalog ─────────────────────────────────────────────────
BASE = "https://gmgn.ai"

ENDPOINTS_TOKEN_INFO = [
    # POST — paling lengkap, return bundle/sniper/smart money
    {
        "method": "POST",
        "url": f"{BASE}/api/v1/mutil_window_token_info",
        "payload_key": "addresses",   # payload: {"chain":"sol","addresses":[mint]}
    },
    # GET v1
    {
        "method": "GET",
        "url": f"{BASE}/defi/quotation/v1/token/sol/{{mint}}",
    },
    # GET v1 alternate
    {
        "method": "GET",
        "url": f"{BASE}/defi/quotation/v1/tokens/sol/{{mint}}",
    },
]

ENDPOINTS_SECURITY = [
    # Security endpoint — honeypot, mint auth, freeze auth
    {
        "method": "GET",
        "url": f"{BASE}/api/v1/token_security/sol/{{mint}}",
    },
]

ENDPOINTS_NEW_TOKENS = [
    f"{BASE}/defi/quotation/v1/rank/sol/new_creation/1h"
    "?limit=50&orderby=created_timestamp&direction=desc",

    f"{BASE}/defi/quotation/v1/rank/sol/pump_rank/1h"
    "?limit=50&orderby=volume&direction=desc&filters[]=not_wash_trading",
]

# ── Headers ──────────────────────────────────────────────────────────
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

def _make_headers(api_key: str = "") -> dict:
    h = {
        "accept":             "application/json, text/plain, */*",
        "accept-language":    "en-US,en;q=0.9",
        "dnt":                "1",
        "priority":           "u=1, i",
        "referer":            "https://gmgn.ai/?chain=sol",
        "sec-ch-ua":          '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile":   "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest":     "empty",
        "sec-fetch-mode":     "cors",
        "sec-fetch-site":     "same-origin",
        "user-agent":         random.choice(_UA_POOL),
        "content-type":       "application/json",
    }
    if api_key:
        h["x-route-key"] = api_key
    return h


# ── Impersonation identifiers untuk curl-cffi ────────────────────────
_IMPERSONATE_POOL = [
    "chrome124", "chrome123", "chrome120",
    "chrome110", "chrome107",
]


class GMGNClient:
    """
    GMGN API client menggunakan curl-cffi.
    Thread-safe. Setiap call buat session baru untuk rotate fingerprint.

    Penggunaan:
        client = GMGNClient(api_key="...")
        data = await client.token_info("mint_address")
        security = await client.token_security("mint_address")
        new_tokens = await client.new_token_mints()
    """

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self._lock = asyncio.Lock()

    def _sync_get(self, url: str) -> Optional[dict]:
        """Sync GET dengan curl-cffi (dijalankan di executor)."""
        try:
            from curl_cffi import requests as cffi_requests
            impersonate = random.choice(_IMPERSONATE_POOL)
            resp = cffi_requests.get(
                url,
                headers=_make_headers(self.api_key),
                impersonate=impersonate,
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
            log.warning(f"GMGN GET {resp.status_code}: {url[:70]}")
        except ImportError:
            log.warning("curl-cffi tidak terinstall — GMGN dinonaktifkan. pip install curl-cffi")
        except Exception as e:
            log.warning(f"GMGN GET error {url[:60]}: {e}")
        return None

    def _sync_post(self, url: str, payload: dict) -> Optional[dict]:
        """Sync POST dengan curl-cffi."""
        try:
            from curl_cffi import requests as cffi_requests
            impersonate = random.choice(_IMPERSONATE_POOL)
            resp = cffi_requests.post(
                url,
                json=payload,
                headers=_make_headers(self.api_key),
                impersonate=impersonate,
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
            log.warning(f"GMGN POST {resp.status_code}: {url[:70]}")
        except ImportError:
            log.warning("curl-cffi tidak terinstall — GMGN dinonaktifkan. pip install curl-cffi")
        except Exception as e:
            log.warning(f"GMGN POST error {url[:60]}: {e}")
        return None

    async def _get(self, url: str) -> Optional[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self._sync_get(url))

    async def _post(self, url: str, payload: dict) -> Optional[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self._sync_post(url, payload))

    # ── Public API ───────────────────────────────────────────────────

    async def diagnose(self) -> str:
        """
        Test koneksi GMGN dan return status string.
        Panggil saat startup untuk tahu apakah GMGN bisa dipakai.
        """
        test_mint = "So11111111111111111111111111111111111111112"  # Wrapped SOL — selalu ada
        try:
            from curl_cffi import requests as cffi_requests  # noqa: F401
        except ImportError:
            return "❌ curl-cffi tidak terinstall (pip install curl-cffi)"

        result = await self._get(f"{BASE}/defi/quotation/v1/token/sol/{test_mint}")
        if result:
            return "✅ GMGN OK — curl-cffi bypass berhasil"

        result2 = await self._post(
            f"{BASE}/api/v1/mutil_window_token_info",
            {"chain": "sol", "addresses": [test_mint]}
        )
        if result2:
            return "✅ GMGN OK via POST"

        return (
            "❌ GMGN GAGAL — kemungkinan Cloudflare memblok IP Railway/VPS.\n"
            "   Solusi: pakai proxy (HTTPS_PROXY env), atau bot akan fallback ke RugCheck top10."
        )

    async def token_info(self, mint: str) -> Optional[dict]:
        """
        Fetch token info dari GMGN.
        Return dict sudah di-unwrap (inner token object).
        Field yang tersedia (jika ada):
            holder_count, top_10_holder_rate, bundle_pct,
            sniper_count, smart_degen_count, renowned_wallets,
            dev_hold_pct, wash_trade_flag, is_honeypot,
            rug_ratio, fresh_wallet_rate, rat_trader_amount_rate
        """
        # 1. Coba POST (paling lengkap)
        post_url = f"{BASE}/api/v1/mutil_window_token_info"
        payload  = {"chain": "sol", "addresses": [mint]}
        raw = await self._post(post_url, payload)
        if raw:
            extracted = self._extract_token_from_post(raw, mint)
            if extracted:
                log.info(f"GMGN POST OK: {mint[:12]}")
                return extracted

        # 2. Fallback GET endpoints
        for url_template in [
            f"{BASE}/defi/quotation/v1/token/sol/{{mint}}",
            f"{BASE}/defi/quotation/v1/tokens/sol/{{mint}}",
        ]:
            url = url_template.format(mint=mint)
            raw = await self._get(url)
            if raw:
                extracted = self._extract_token_from_get(raw, mint)
                if extracted:
                    log.info(f"GMGN GET OK: {mint[:12]} via {url_template[:50]}")
                    return extracted

        log.debug(f"GMGN: semua endpoint gagal untuk {mint[:12]}")
        return None

    async def token_security(self, mint: str) -> Optional[dict]:
        """
        Fetch security data: honeypot, mint auth, freeze auth.
        Return raw dict dari GMGN security endpoint.
        """
        url = f"{BASE}/api/v1/token_security/sol/{mint}"
        raw = await self._get(url)
        if raw and isinstance(raw, dict):
            code = raw.get("code", -1)
            if code == 0 and raw.get("data"):
                return raw["data"]
            # Beberapa format langsung return data
            if "is_honeypot" in raw or "mintAuthority" in raw:
                return raw
        return None

    async def new_token_mints(self) -> List[str]:
        """
        Discovery token baru/trending dari GMGN.
        Return list of mint addresses.
        """
        mints: List[str] = []
        for url in ENDPOINTS_NEW_TOKENS:
            raw = await self._get(url)
            if not raw:
                continue
            items = self._extract_items(raw)
            for item in (items or []):
                addr = (
                    item.get("address") or
                    item.get("token_address") or
                    item.get("mint") or ""
                )
                if addr and len(addr) >= 32:
                    mints.append(addr)

        unique = list(dict.fromkeys(mints))
        if unique:
            log.info(f"GMGN discovery: {len(unique)} tokens")
        return unique[:60]

    # ── Response parsers ─────────────────────────────────────────────

    def _extract_token_from_post(self, raw: dict, mint: str) -> Optional[dict]:
        """Parse response dari POST mutil_window_token_info."""
        if not isinstance(raw, dict):
            return None
        code = raw.get("code", -1)
        if code != 0:
            return None
        data = raw.get("data")
        if isinstance(data, list) and len(data) > 0:
            return data[0]
        if isinstance(data, dict):
            # Kadang format: {"data": {"tokens": [...]}}
            tokens = data.get("tokens")
            if isinstance(tokens, list) and len(tokens) > 0:
                return tokens[0]
            return data
        return None

    def _extract_token_from_get(self, raw: dict, mint: str) -> Optional[dict]:
        """Parse response dari GET token endpoints."""
        if not isinstance(raw, dict):
            return None
        code = raw.get("code", -1)
        if code == 0 and raw.get("data"):
            data = raw["data"]
            # Unwrap "token" key jika ada
            if isinstance(data, dict) and "token" in data:
                return data["token"]
            return data
        # Format langsung (tanpa code wrapper)
        if "address" in raw or "mint" in raw or "holder_count" in raw:
            return raw
        return None

    def _extract_items(self, raw: dict) -> Optional[list]:
        """Extract list items dari berbagai format response GMGN."""
        if not isinstance(raw, dict):
            return None
        # Format: {"code":0,"data":[...]} atau {"code":0,"data":{"rank":[...]}}
        data = raw.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("rank", "tokens", "items", "list"):
                val = data.get(key)
                if isinstance(val, list):
                    return val
        # Format langsung list
        for key in ("rank", "tokens", "items", "data", "list"):
            val = raw.get(key)
            if isinstance(val, list):
                return val
        return None


# ── Integrasi ke DataFetcher ─────────────────────────────────────────
#
# Di data_fetcher.py, ganti seluruh fungsi gmgn_via_bridge dan _gmgn_fetch
# dengan kode berikut:
#
# ─── Di __init__ DataFetcher: ────────────────────────────────────────
#
#     from gmgn_client import GMGNClient
#     self.gmgn = GMGNClient(api_key=self.cfg.GMGN_API_KEY)
#
# ─── Ganti gmgn_token_info: ──────────────────────────────────────────
#
#     async def gmgn_token_info(self, session, mint: str) -> Optional[dict]:
#         return await self.gmgn.token_info(mint)
#
# ─── Ganti gmgn_new_tokens dan gmgn_new_tokens_via_bridge: ───────────
#
#     async def gmgn_new_tokens(self, session) -> List[str]:
#         return await self.gmgn.new_token_mints()
#
#     async def gmgn_new_tokens_via_bridge(self, session) -> List[str]:
#         return []  # tidak diperlukan lagi
#
# ─── Di requirements.txt, tambahkan: ─────────────────────────────────
#
#     curl-cffi>=0.6.0
#
# ─── Di Railway environment variables: ───────────────────────────────
#
#     GMGN_API_KEY=your_key_here
#     (Hapus GMGN_BRIDGE_URL — tidak dipakai lagi)
#
# ─── Folder gmgn_bridge (Node.js) bisa dihapus sepenuhnya ────────────
