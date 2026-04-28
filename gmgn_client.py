"""
gmgn_client.py — PONYIN GMGN Client v2.1
Debug mode: log semua request/response untuk tracing.
"""
import asyncio
import logging
import random
import json
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
        self._direct_failed = False

    # ── Headers ──────────────────────────────────────────────────────
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

    # ── Direct mode (curl-cffi) ─────────────────────────────────────
    def _sync_get_direct(self, url: str) -> Optional[dict]:
        try:
            from curl_cffi import requests as cffi_requests
            impersonate = random.choice(_IMPERSONATE_POOL)
            log.info(f"GMGN direct GET: {url[:70]}")
            resp = cffi_requests.get(
                url,
                headers=self._make_headers(),
                impersonate=impersonate,
                timeout=15,
            )
            log.info(f"GMGN direct status: {resp.status_code}")
            if resp.status_code == 200:
                return resp.json()
            log.warning(f"GMGN direct GET {resp.status_code}: {url[:70]} | body: {resp.text[:200]}")
        except Exception as e:
            log.warning(f"GMGN direct GET error {url[:60]}: {e}")
        return None

    def _sync_post_direct(self, url: str, payload: dict) -> Optional[dict]:
        try:
            from curl_cffi import requests as cffi_requests
            impersonate = random.choice(_IMPERSONATE_POOL)
            log.info(f"GMGN direct POST: {url[:70]}")
            resp = cffi_requests.post(
                url,
                json=payload,
                headers=self._make_headers(),
                impersonate=impersonate,
                timeout=15,
            )
            log.info(f"GMGN direct status: {resp.status_code}")
            if resp.status_code == 200:
                return resp.json()
            log.warning(f"GMGN direct POST {resp.status_code}: {url[:70]} | body: {resp.text[:200]}")
        except Exception as e:
            log.warning(f"GMGN direct POST error {url[:60]}: {e}")
        return None

    # ── Proxy mode (aiohttp → Worker) ───────────────────────────────
    async def _get_proxy(self, path: str, query: str = "") -> Optional[dict]:
        import aiohttp
        url = f"{self.proxy_url}?path={path}"
        if query:
            url += f"&{query}"
        log.info(f"GMGN proxy GET: {url[:90]}")
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    text = await r.text()
                    log.info(f"GMGN proxy status: {r.status} | len={len(text)}")
                    if r.status == 200:
                        try:
                            return json.loads(text)
                        except json.JSONDecodeError:
                            log.warning(f"GMGN proxy invalid JSON: {text[:200]}")
                            return None
                    log.warning(f"GMGN proxy GET {r.status}: {text[:200]}")
        except Exception as e:
            log.warning(f"GMGN proxy GET error {path[:50]}: {e}")
        return None

    async def _post_proxy(self, path: str, payload: dict) -> Optional[dict]:
        import aiohttp
        url = f"{self.proxy_url}?path={path}"
        log.info(f"GMGN proxy POST: {url[:90]}")
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as r:
                    text = await r.text()
                    log.info(f"GMGN proxy status: {r.status} | len={len(text)}")
                    if r.status == 200:
                        try:
                            return json.loads(text)
                        except json.JSONDecodeError:
                            log.warning(f"GMGN proxy invalid JSON: {text[:200]}")
                            return None
                    log.warning(f"GMGN proxy POST {r.status}: {text[:200]}")
        except Exception as e:
            log.warning(f"GMGN proxy POST error {path[:50]}: {e}")
        return None

    # ── Public API dengan retry ─────────────────────────────────────
    async def token_info(self, mint: str) -> Optional[dict]:
        # Try 1: Proxy POST
        if self._use_proxy:
            raw = await self._post_proxy(
                "/api/v1/mutil_window_token_info",
                {"chain": "sol", "addresses": [mint]}
            )
            if raw:
                extracted = self._extract_token_from_post(raw, mint)
                if extracted:
                    log.info(f"GMGN proxy POST OK: {mint[:12]}")
                    return extracted

        # Try 2: Proxy GET fallback
        if self._use_proxy:
            for path in ["/defi/quotation/v1/token/sol/", "/defi/quotation/v1/tokens/sol/"]:
                raw = await self._get_proxy(path + mint)
                if raw:
                    extracted = self._extract_token_from_get(raw, mint)
                    if extracted:
                        log.info(f"GMGN proxy GET OK: {mint[:12]}")
                        return extracted

        # Try 3: Direct curl-cffi (fallback)
        if not self._direct_failed:
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
                    log.info(f"GMGN direct POST OK: {mint[:12]}")
                    return extracted

            for path in ["/defi/quotation/v1/token/sol/", "/defi/quotation/v1/tokens/sol/"]:
                raw = await loop.run_in_executor(
                    None,
                    lambda: self._sync_get_direct(f"{BASE}{path}{mint}")
                )
                if raw:
                    extracted = self._extract_token_from_get(raw, mint)
                    if extracted:
                        log.info(f"GMGN direct GET OK: {mint[:12]}")
                        return extracted

        log.warning(f"GMGN: ALL methods failed for {mint[:12]}")
        return None

    async def token_security(self, mint: str) -> Optional[dict]:
        path = f"/api/v1/token_security/sol/{mint}"
        if self._use_proxy:
            raw = await self._get_proxy(path)
            if raw:
                return self._parse_security(raw)

        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(
            None,
            lambda: self._sync_get_direct(f"{BASE}{path}")
        )
        if raw:
            return self._parse_security(raw)
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

    # ── Parsers ─────────────────────────────────────────────────────
    def _parse_security(self, raw: dict) -> Optional[dict]:
        if not isinstance(raw, dict):
            return None
        code = raw.get("code", -1)
        if code == 0 and raw.get("data"):
            return raw["data"]
        if "is_honeypot" in raw or "mintAuthority" in raw:
            return raw
        return None

    def _extract_token_from_post(self, raw: dict, mint: str) -> Optional[dict]:
        if not isinstance(raw, dict):
            log.debug(f"GMGN post: not dict, got {type(raw)}")
            return None
        code = raw.get("code", -1)
        if code != 0:
            log.debug(f"GMGN post: code={code}, msg={raw.get('msg','')}")
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
            log.debug(f"GMGN get: not dict, got {type(raw)}")
            return None
        code = raw.get("code", -1)
        if code == 0 and raw.get("data"):
            data = raw["data"]
            if isinstance(data, dict) and "token" in data:
                return data["token"]
            return data
        if "address" in raw or "mint" in raw or "holder_count" in raw:
            return raw
        log.debug(f"GMGN get: unrecognized format, keys={list(raw.keys())[:10]}")
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
