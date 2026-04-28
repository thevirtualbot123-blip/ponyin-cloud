"""
gmgn_client.py — PONYIN GMGN Client v2.0
Dengan support Cloudflare Worker Proxy.
"""
import asyncio
import logging
import random
from typing import Optional, List

log = logging.getLogger("PONYIN.GMGN")

BASE = "https://gmgn.ai"

_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

_IMPERSONATE_POOL = ["chrome124", "chrome123", "chrome120", "chrome110", "chrome107"]


class GMGNClient:
    def __init__(self, api_key: str = "", proxy_url: str = ""):
        self.api_key = api_key
        self.proxy_url = proxy_url.rstrip("/") if proxy_url else ""
        self._use_proxy = bool(self.proxy_url)

    # ── Direct mode (curl-cffi) ─────────────────────────────────────
    def _sync_get_direct(self, url: str) -> Optional[dict]:
        try:
            from curl_cffi import requests as cffi_requests
            impersonate = random.choice(_IMPERSONATE_POOL)
            resp = cffi_requests.get(
                url,
                headers=self._make_headers(),
                impersonate=impersonate,
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
            log.debug(f"GMGN direct GET {resp.status_code}: {url[:70]}")
        except Exception as e:
            log.debug(f"GMGN direct GET error {url[:60]}: {e}")
        return None

    def _sync_post_direct(self, url: str, payload: dict) -> Optional[dict]:
        try:
            from curl_cffi import requests as cffi_requests
            impersonate = random.choice(_IMPERSONATE_POOL)
            resp = cffi_requests.post(
                url,
                json=payload,
                headers=self._make_headers(),
                impersonate=impersonate,
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
            log.debug(f"GMGN direct POST {resp.status_code}: {url[:70]}")
        except Exception as e:
            log.debug(f"GMGN direct POST error {url[:60]}: {e}")
        return None

    def _make_headers(self) -> dict:
        h = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "dnt": "1",
            "priority": "u=1, i",
            "referer": "https://gmgn.ai/?chain=sol",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": random.choice(_UA_POOL),
            "content-type": "application/json",
        }
        if self.api_key:
            h["x-route-key"] = self.api_key
        return h

    # ── Proxy mode (aiohttp → Worker) ───────────────────────────────
    async def _get_proxy(self, path: str, query: str = "") -> Optional[dict]:
        import aiohttp
        url = f"{self.proxy_url}?path={path}"
        if query:
            url += f"&{query}"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status == 200:
                        return await r.json(content_type=None)
                    log.debug(f"Proxy GET {r.status}: {path[:50]}")
        except Exception as e:
            log.debug(f"Proxy GET error {path[:50]}: {e}")
        return None

    async def _post_proxy(self, path: str, payload: dict) -> Optional[dict]:
        import aiohttp
        url = f"{self.proxy_url}?path={path}"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as r:
                    if r.status == 200:
                        return await r.json(content_type=None)
                    log.debug(f"Proxy POST {r.status}: {path[:50]}")
        except Exception as e:
            log.debug(f"Proxy POST error {path[:50]}: {e}")
        return None

    # ── Public API ──────────────────────────────────────────────────
    async def token_info(self, mint: str) -> Optional[dict]:
        # 1. Coba POST (paling lengkap)
        if self._use_proxy:
            raw = await self._post_proxy(
                "/api/v1/mutil_window_token_info",
                {"chain": "sol", "addresses": [mint]}
            )
        else:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(
                None,
                lambda: self._sync_post_direct(
                    f"{BASE}/api/v1/mutil_window_token_info",
                    {"chain": "sol", "addresses": [mint]}
                )
            )

        if raw:
            extracted = self._extract_token_from_post(raw, mint)
            if extracted:
                log.info(f"GMGN POST OK: {mint[:12]}")
                return extracted

        # 2. Fallback GET
        for path in ["/defi/quotation/v1/token/sol/", "/defi/quotation/v1/tokens/sol/"]:
            if self._use_proxy:
                raw = await self._get_proxy(path + mint)
            else:
                loop = asyncio.get_event_loop()
                raw = await loop.run_in_executor(
                    None,
                    lambda: self._sync_get_direct(f"{BASE}{path}{mint}")
                )
            if raw:
                extracted = self._extract_token_from_get(raw, mint)
                if extracted:
                    log.info(f"GMGN GET OK: {mint[:12]}")
                    return extracted

        log.debug(f"GMGN: semua endpoint gagal untuk {mint[:12]}")
        return None

    async def token_security(self, mint: str) -> Optional[dict]:
        path = f"/api/v1/token_security/sol/{mint}"
        if self._use_proxy:
            raw = await self._get_proxy(path)
        else:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(
                None,
                lambda: self._sync_get_direct(f"{BASE}{path}")
            )
        if raw and isinstance(raw, dict):
            code = raw.get("code", -1)
            if code == 0 and raw.get("data"):
                return raw["data"]
            if "is_honeypot" in raw or "mintAuthority" in raw:
                return raw
        return None

    async def new_token_mints(self) -> List[str]:
        endpoints = [
            "/defi/quotation/v1/rank/sol/new_creation/1h?limit=50&orderby=created_timestamp&direction=desc",
            "/defi/quotation/v1/rank/sol/pump_rank/1h?limit=50&orderby=volume&direction=desc&filters[]=not_wash_trading",
        ]
        mints = []
        for ep in endpoints:
            if self._use_proxy:
                raw = await self._get_proxy(ep)
            else:
                loop = asyncio.get_event_loop()
                raw = await loop.run_in_executor(
                    None,
                    lambda: self._sync_get_direct(f"{BASE}{ep}")
                )
            items = self._extract_items(raw)
            for item in (items or []):
                addr = item.get("address") or item.get("token_address") or item.get("mint") or ""
                if addr and len(addr) >= 32:
                    mints.append(addr)

        unique = list(dict.fromkeys(mints))
        if unique:
            log.info(f"GMGN discovery: {len(unique)} tokens")
        return unique[:60]

    # ── Parsers (sama seperti sebelumnya) ───────────────────────────
    def _extract_token_from_post(self, raw: dict, mint: str) -> Optional[dict]:
        if not isinstance(raw, dict):
            return None
        if raw.get("code") != 0:
            return None
        data = raw.get("data")
        if isinstance(data, list) and len(data) > 0:
            return data[0]
        if isinstance(data, dict):
            tokens = data.get("tokens")
            if isinstance(tokens, list) and len(tokens) > 0:
                return tokens[0]
            return data
        return None

    def _extract_token_from_get(self, raw: dict, mint: str) -> Optional[dict]:
        if not isinstance(raw, dict):
            return None
        if raw.get("code") == 0 and raw.get("data"):
            data = raw["data"]
            if isinstance(data, dict) and "token" in data:
                return data["token"]
            return data
        if "address" in raw or "mint" in raw or "holder_count" in raw:
            return raw
        return None

    def _extract_items(self, raw: dict) -> Optional[list]:
        if not isinstance(raw, dict):
            return None
        data = raw.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("rank", "tokens", "items", "list"):
                val = data.get(key)
                if isinstance(val, list):
                    return val
        for key in ("rank", "tokens", "items", "data", "list"):
            val = raw.get(key)
            if isinstance(val, list):
                return val
        return None
