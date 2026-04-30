"""
gmgn_client.py — Client untuk GMGN API dengan error handling.
"""
import logging, aiohttp, asyncio
from typing import Dict, Any, Optional, List
from config import AgentConfig

log = logging.getLogger("PONYIN.GMGN")

class GMGNClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://public-api.gmgn.ai"
        self.headers = {
            "accept": "application/json",
            "authorization": f"Bearer {api_key}"
        }
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        """Initialize the client session."""
        self.session = aiohttp.ClientSession(
            headers=self.headers,
            timeout=aiohttp.ClientTimeout(total=30)
        )

    async def close(self):
        """Close the client session."""
        if self.session:
            await self.session.close()

    async def get_new_pools(self, limit: int = 10, sort_by: str = "created_timestamp", 
                           order: str = "desc") -> List[Dict[str, Any]]:
        """Get new token pools from GMGN."""
        if not self.api_key:
            log.warning("GMGN API key not set, skipping GMGN data fetch")
            return []
            
        url = f"{self.base_url}/v1/pools/new"
        params = {
            "limit": limit,
            "sort_by": sort_by,
            "order": order
        }
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 401:
                    log.error("GMGN API unauthorized - check your API key")
                    return []
                elif response.status == 429:
                    log.warning("GMGN API rate limited")
                    return []
                elif response.status != 200:
                    log.error(f"GMGN API error {response.status}: {await response.text()}")
                    return []
                    
                data = await response.json(content_type=None)
                
                # Ekstrak pools dari response
                pools = data.get('data', {}).get('pools', [])
                if not pools:
                    # Beberapa response mungkin langsung array
                    pools = data.get('pools', []) if isinstance(data, dict) else data if isinstance(data, list) else []
                
                log.info(f"Fetched {len(pools)} pools from GMGN")
                return pools
                
        except asyncio.TimeoutError:
            log.error("GMGN API request timeout")
            return []
        except aiohttp.ClientError as e:
            log.error(f"GMGN API client error: {e}")
            return []
        except Exception as e:
            log.error(f"GMGN API unexpected error: {e}")
            return []

    async def get_pool_detail(self, pool_address: str) -> Dict[str, Any]:
        """Get detailed information for a specific pool."""
        if not self.api_key:
            return {}
            
        url = f"{self.base_url}/v1/pools/detail"
        params = {"address": pool_address}
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 401:
                    log.error("GMGN API unauthorized - check your API key")
                    return {}
                elif response.status == 404:
                    log.debug(f"Pool not found: {pool_address}")
                    return {}
                elif response.status == 429:
                    log.warning("GMGN API rate limited")
                    return {}
                elif response.status != 200:
                    log.error(f"GMGN pool detail error {response.status}: {await response.text()}")
                    return {}
                    
                data = await response.json(content_type=None)
                
                # Ambil data pool
                pool_data = data.get('data', {}).get('pool', {})
                if not pool_data:
                    pool_data = data if isinstance(data, dict) else {}
                
                # Ambil juga liquidity data jika ada
                liquidity_data = data.get('data', {}).get('liquidity', {})
                if liquidity_data:
                    # Gabungkan liquidity ke pool data
                    pool_data['liquidity'] = liquidity_data
                
                # Ambil juga transaction stats jika ada
                tx_stats = data.get('data', {}).get('tx_stats', {})
                if tx_stats:
                    pool_data['tx_stats'] = tx_stats
                
                # Ambil top holders jika ada
                top_holders = data.get('data', {}).get('top_holders', [])
                if top_holders:
                    pool_data['top_holders'] = top_holders
                    # Hitung top 10 holder percent
                    total_supply = pool_data.get('total_supply', 1)
                    if total_supply and total_supply > 0:
                        top10_sum = sum(float(h.get('balance', 0)) for h in top_holders[:10])
                        top10_pct = (top10_sum / total_supply) * 100
                        pool_data['top_10_holder_percent'] = top10_pct
                
                # Pastikan liquidity selalu ada dan valid
                if 'liquidity' not in pool_data:
                    # Coba ekstrak dari root data
                    if 'liquidity_usd' in pool_data:
                        pool_data['liquidity'] = {'usd': pool_data['liquidity_usd']}
                    elif 'total_liquidity' in pool_data:
                        pool_data['liquidity'] = {'usd': pool_data['total_liquidity']}
                    else:
                        # Fallback: buat liquidity default
                        pool_data['liquidity'] = {'usd': 1.0}  # Set minimum liquidity
                
                # Validasi dan perbaiki nilai liquidity
                liquidity = pool_data.get('liquidity', {})
                if isinstance(liquidity, (int, float)):
                    # Jika liquidity hanya angka, ubah ke dict
                    pool_data['liquidity'] = {'usd': float(liquidity)}
                elif isinstance(liquidity, dict):
                    # Pastikan usd field ada
                    if 'usd' not in liquidity or liquidity['usd'] is None:
                        liquidity['usd'] = 1.0
                    # Konversi ke float untuk mencegah type error
                    liquidity['usd'] = float(liquidity.get('usd', 1.0))
                
                return pool_data
                
        except asyncio.TimeoutError:
            log.error(f"GMGN pool detail timeout for {pool_address}")
            return {}
        except aiohttp.ClientError as e:
            log.error(f"GMGN pool detail client error for {pool_address}: {e}")
            return {}
        except Exception as e:
            log.error(f"GMGN pool detail unexpected error for {pool_address}: {e}")
            return {}
