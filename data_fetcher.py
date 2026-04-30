"""
data_fetcher.py — Fetch token data from various sources with error handling.
"""
import asyncio, logging, json, aiohttp
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from filter_engine import Token, safe_div
from gmgn_client import GMGNClient
from config import AgentConfig

log = logging.getLogger("PONYIN.DataFetcher")

@dataclass
class FetchedData:
    token: Token
    source: str
    raw_data: str

class DataFetcher:
    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg
        self.gmgn = GMGNClient(cfg.GMGN_API_KEY)
        
        # Semaphore untuk membatasi concurrent requests
        self.semaphore = asyncio.Semaphore(cfg.MAX_CONCURRENT_REQUESTS)
        
        # Session untuk HTTP requests
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        """Initialize the data fetcher."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            connector=aiohttp.TCPConnector(limit=20)
        )

    async def stop(self):
        """Cleanup resources."""
        if self.session:
            await self.session.close()

    async def fetch_new_tokens(self) -> List[FetchedData]:
        """Fetch new tokens from all configured sources."""
        tasks = []
        
        # Add GMGN fetching task
        if self.cfg.GMGN_API_KEY:
            tasks.append(self._fetch_from_gmgn())
        
        # Tambahkan source lain di sini jika diperlukan
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Gabungkan semua hasil
        all_data = []
        for result in results:
            if isinstance(result, Exception):
                log.error(f"Error fetching from source: {result}")
                continue
            if result:
                all_data.extend(result)
                
        return all_data

    async def _fetch_from_gmgn(self) -> List[FetchedData]:
        """Fetch new tokens from GMGN API."""
        async with self.semaphore:
            try:
                # Ambil pool data dari GMGN
                pools = await self.gmgn.get_new_pools(
                    limit=self.cfg.FETCH_LIMIT,
                    sort_by="created_timestamp",
                    order="desc"
                )
                
                if not pools:
                    log.info("No new pools found from GMGN")
                    return []
                
                # Ambil detail untuk setiap pool
                detailed_pools = []
                for pool in pools:
                    try:
                        # Ambil detail pool
                        pool_detail = await self.gmgn.get_pool_detail(pool['address'])
                        
                        # Ambil token info dari chain
                        token_info = await self._get_token_info_from_chain(pool['token_address'])
                        
                        # Gabungkan data
                        combined_data = {**pool, **pool_detail, **(token_info or {})}
                        detailed_pools.append(combined_data)
                        
                        # Delay kecil untuk rate limiting
                        await asyncio.sleep(0.1)
                        
                    except Exception as e:
                        log.error(f"Error getting detail for pool {pool.get('address', 'unknown')}: {e}")
                        continue
                
                # Konversi ke Token objects
                fetched_data = []
                for pool_data in detailed_pools:
                    try:
                        token = self._parse_gmgn_data(pool_data)
                        if token:
                            raw_str = json.dumps(pool_data, indent=2)[:500]  # Batasi panjang raw
                            fetched_data.append(FetchedData(token, "GMGN", raw_str))
                    except Exception as e:
                        log.error(f"Error parsing GMGN data: {e}")
                        continue
                        
                log.info(f"Fetched {len(fetched_data)} tokens from GMGN")
                return fetched_data
                
            except Exception as e:
                log.error(f"Error fetching from GMGN: {e}")
                return []

    def _parse_gmgn_data(self, data: Dict[str, Any]) -> Optional[Token]:
        """Parse GMGN API response to Token object."""
        try:
            # Extract basic info
            address = data.get('address', '')
            token_addr = data.get('token_address', '')
            name = data.get('token_name', 'Unknown')
            symbol = data.get('token_symbol', 'UNKNOWN')
            
            # Safely extract numeric values with defaults
            price = float(data.get('price', 0) or 0)
            market_cap = float(data.get('market_cap', 0) or 0)
            
            # Safely extract liquidity with fallback
            liquidity = data.get('liquidity', {})
            liq_usd = float(liquidity.get('usd', 0) or 0)
            # Fallback jika liquidity kosong atau tidak valid
            if liq_usd <= 0:
                # Coba ambil dari field lain
                liq_field = data.get('liquidity_usd') or data.get('total_liquidity') or 1.0
                liq_usd = float(liq_field) if liq_field else 1.0
            
            # Volume and changes
            volume_1h = float(data.get('volume_1h', 0) or 0)
            price_change_1h = float(data.get('price_change_1h', 0) or 0)
            
            # Transactions
            tx_stats = data.get('tx_stats', {})
            buys_1h = int(tx_stats.get('buys_1h', 0) or 0)
            sells_1h = int(tx_stats.get('sells_1h', 0) or 0)
            
            # Top holders and risk
            top_holders = data.get('top_holders', [])
            top10_pct = float(data.get('top_10_holder_percent', 0) or 0)
            
            # Safely calculate risk (avoid division by zero)
            total_supply = float(data.get('total_supply', 1) or 1)
            risk_score = float(data.get('risk_score', 5) or 5)
            
            # Calculate age in hours
            created_ts = data.get('created_timestamp')
            age_hours = 0
            if created_ts:
                from datetime import datetime
                try:
                    # Convert timestamp to age
                    import time
                    current_ts = time.time()
                    age_seconds = current_ts - float(created_ts)
                    age_hours = max(0, age_seconds / 3600)
                except:
                    age_hours = 0
            
            # LP burn percentage
            lp_burn_percent = float(data.get('lp_burn_percent', 0) or 0)
            
            # Mint authority status
            mint_authority = data.get('mint_authority')
            if mint_authority is not None and mint_authority == "":
                mint_authority = "revoked"
                
            # Create Token instance
            token = Token(
                address=address,
                token_address=token_addr,
                name=name,
                symbol=symbol,
                price=price,
                mc=market_cap,
                liq=liq_usd,
                vol1h=volume_1h,
                chg1h=price_change_1h,
                buys1h=buys_1h,
                sells1h=sells_1h,
                top10_pct=top10_pct,
                risk_norm=risk_score,
                age_hours=age_hours,
                lp_burn=lp_burn_percent,
                mint_auth=mint_authority,
                has_twitter=bool(data.get('twitter')),
                buy_sell_ratio=safe_div(buys_1h, (buys_1h + sells_1h), 0.5),  # Default 0.5 jika 0/0
                price_native=price,  # Gunakan price sebagai native price
            )
            
            # Hitung plan entry jika harga valid
            if price > 0:
                cfg = self.cfg
                token.plan = {
                    'entry': price,
                    'tp1': price * (1 + cfg.TP1_PCT / 100),
                    'tp2': price * (1 + cfg.TP2_PCT / 100),
                    'sl': price * (1 - cfg.SL_PCT / 100),
                }
            
            return token
            
        except Exception as e:
            log.error(f"Error parsing GMGN data: {e}")
            return None

    async def _get_token_info_from_chain(self, token_address: str) -> Optional[Dict[str, Any]]:
        """Get additional token info directly from Solana chain if needed."""
        # Implementation would go here if we need direct RPC calls
        # For now, return None as GMGN usually provides sufficient data
        return None
