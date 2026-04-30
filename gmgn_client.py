"""
gmgn_client.py — Client untuk GMGN API dengan error handling yang robust.
"""
import logging
import aiohttp
import asyncio
from typing import Dict, Any, Optional, List

log = logging.getLogger("PONYIN.GMGN")

class GMGNClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        # URL API GMGN yang benar
        self.base_url = "https://api.gmgn.ai"
        self.headers = {
            "accept": "application/json",
        }
        if api_key:
            self.headers["authorization"] = f"Bearer {api_key}"
        
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        """Initialize the client session."""
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(headers=self.headers, timeout=timeout)

    async def close(self):
        """Close the client session."""
        if self.session:
            await self.session.close()

    async def get_new_pools(self, limit: int = 10, sort_by: str = "created_at", 
                           order: str = "desc", chain: str = "solana") -> List[Dict[str, Any]]:
        """
        Get new token pools from GMGN.
        Returns list of pool data or empty list on error.
        """
        if not self.session:
            log.error("GMGN session not initialized")
            return []
            
        if not self.api_key:
            log.warning("GMGN API key not set")
            return []
        
        # Endpoint yang benar untuk GMGN
        url = f"{self.base_url}/defi/v1/token/new_pools"
        params = {
            "limit": min(limit, 50),  # Max 50
            "sort_by": sort_by,
            "order": order,
            "chain": chain
        }
        
        try:
            log.info(f"Fetching new pools from GMGN: {url}")
            async with self.session.get(url, params=params) as response:
                status = response.status
                
                if status == 401:
                    log.error("GMGN API 401 Unauthorized - check API key")
                    return []
                elif status == 429:
                    log.warning("GMGN API 429 Rate Limited")
                    return []
                elif status != 200:
                    text = await response.text()
                    log.error(f"GMGN API error {status}: {text[:200]}")
                    return []
                
                # Parse JSON
                try:
                    data = await response.json()
                except Exception as e:
                    log.error(f"Failed to parse GMGN JSON: {e}")
                    return []
                
                # Validasi response structure
                if not data or not isinstance(data, dict):
                    log.error("GMGN returned invalid response format (not a dict)")
                    return []
                
                # Cek apakah ada error dari GMGN
                if data.get("code") != 0:
                    msg = data.get("msg", "Unknown error")
                    log.error(f"GMGN API error: code={data.get('code')}, msg={msg}")
                    return []
                
                # Ekstrak data pools
                result_data = data.get("data", {})
                if not result_data or not isinstance(result_data, dict):
                    log.error("GMGN response missing 'data' field")
                    return []
                
                pools = result_data.get("pools", [])
                
                if not pools or not isinstance(pools, list):
                    log.warning("GMGN returned empty or invalid pools list")
                    return []
                
                log.info(f"Successfully fetched {len(pools)} pools from GMGN")
                return pools
                
        except asyncio.TimeoutError:
            log.error("GMGN request timeout")
            return []
        except aiohttp.ClientError as e:
            log.error(f"GMGN HTTP error: {e}")
            return []
        except Exception as e:
            log.error(f"GMGN unexpected error: {e}", exc_info=True)
            return []

    async def get_token_info(self, token_address: str, chain: str = "solana") -> Optional[Dict[str, Any]]:
        """
        Get detailed token info from GMGN.
        Returns token data dict or None on error.
        """
        if not self.session or not self.api_key:
            return None
        
        url = f"{self.base_url}/defi/v1/tokens/info"
        params = {
            "address": token_address,
            "chain": chain
        }
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status != 200:
                    log.error(f"GMGN token info error {response.status}")
                    return None
                
                data = await response.json()
                
                if not data or data.get("code") != 0:
                    log.error(f"GMGN token info error: {data}")
                    return None
                
                token_data = data.get("data", {})
                if not token_data:
                    log.warning(f"No data for token {token_address}")
                    return None
                
                return token_data
                
        except Exception as e:
            log.error(f"Error fetching token info: {e}")
            return None
