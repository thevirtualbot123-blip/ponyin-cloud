"""
data_fetcher.py — Fetch token data dari GMGN dengan error handling.
"""
import asyncio
import logging
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from filter_engine import Token

log = logging.getLogger("PONYIN.DataFetcher")

@dataclass
class FetchedData:
    token: Token
    source: str
    raw_data: str

class DataFetcher:
    def __init__(self, cfg):
        self.cfg = cfg
        self.gmgn = None  # Akan diinisialisasi di start()
        self.semaphore = asyncio.Semaphore(getattr(cfg, 'MAX_CONCURRENT_REQUESTS', 5))

    async def start(self):
        """Initialize data fetcher and GMGN client."""
        from gmgn_client import GMGNClient
        self.gmgn = GMGNClient(self.cfg.GMGN_API_KEY)
        await self.gmgn.start()
        log.info("DataFetcher initialized with GMGN client")

    async def stop(self):
        """Cleanup resources."""
        if self.gmgn:
            await self.gmgn.close()

    async def fetch_new_tokens(self) -> List[FetchedData]:
        """Fetch new tokens from GMGN."""
        if not self.gmgn:
            log.error("GMGN client not initialized")
            return []
        
        try:
            # Ambil pool baru dari GMGN
            pools = await self.gmgn.get_new_pools(
                limit=getattr(self.cfg, 'FETCH_LIMIT', 10),
                sort_by="created_at",
                order="desc"
            )
            
            if not pools:
                log.info("No new pools from GMGN")
                return []
            
            log.info(f"Processing {len(pools)} pools from GMGN")
            
            results = []
            for pool in pools:
                try:
                    token = self._parse_pool_to_token(pool)
                    if token:
                        raw_str = json.dumps(pool, indent=2)[:500]
                        results.append(FetchedData(token=token, source="GMGN", raw_data=raw_str))
                except Exception as e:
                    log.error(f"Error parsing pool: {e}")
                    continue
            
            log.info(f"Successfully parsed {len(results)} tokens from GMGN")
            return results
            
        except Exception as e:
            log.error(f"Error in fetch_new_tokens: {e}", exc_info=True)
            return []

    def _parse_pool_to_token(self, pool: Dict[str, Any]) -> Optional[Token]:
        """Parse GMGN pool data to Token object."""
        try:
            # Ekstrak data dasar dengan safe access
            base_token = pool.get("base_token", {})
            quote_token = pool.get("quote_token", {})
            pool_info = pool.get("pool_info", {})
            
            # Address dan symbol
            address = base_token.get("address", "")
            symbol = base_token.get("symbol", "UNKNOWN")
            name = base_token.get("name", "Unknown Token")
            
            # Price dan Market Cap
            price_usd = float(pool_info.get("price_usd", 0) or 0)
            market_cap = float(pool_info.get("market_cap", 0) or 0)
            
            # Liquidity - CRITICAL: Pastikan tidak None atau 0
            liquidity_usd = pool_info.get("liquidity_usd")
            if liquidity_usd is None:
                liquidity_usd = float(pool_info.get("liquidity", 0) or 0)
            else:
                liquidity_usd = float(liquidity_usd)
            
            # Fallback jika masih 0 atau negatif
            if liquidity_usd <= 0:
                liquidity_usd = 1.0  # Minimum 1 USD untuk avoid division by zero
                log.warning(f"Liquidity was 0/None for {symbol}, set to 1.0")
            
            # Volume 1h dan price change
            volume_24h = float(pool_info.get("volume_24h", 0) or 0)
            # Estimasi volume 1h dari 24h (asumsi distribusi merata)
            volume_1h = volume_24h / 24.0
            
            price_change_24h = float(pool_info.get("price_change_24h", 0) or 0)
            # Estimasi 1h change
            price_change_1h = price_change_24h / 24.0
            
            # Transactions
            txns_24h = int(pool_info.get("txns_24h", 0) or 0)
            buys_24h = int(pool_info.get("buys_24h", 0) or 0)
            sells_24h = int(pool_info.get("sells_24h", 0) or 0)
            
            # Estimasi per jam
            buys_1h = max(1, buys_24h // 24)
            sells_1h = max(0, sells_24h // 24)
            
            # Holder concentration
            holder_count = int(pool_info.get("holder_count", 0) or 0)
            top_10_percent = float(pool_info.get("top_10_holder_percent", 0) or 0)
            
            # Risk score (0-10)
            risk_score = float(pool_info.get("risk_score", 5) or 5)
            
            # Age calculation
            created_at = pool_info.get("created_at", 0)
            import time
            current_time = time.time()
            age_hours = max(0, (current_time - created_at) / 3600) if created_at > 0 else 0
            
            # LP Burn
            lp_burn_percent = float(pool_info.get("lp_burn_percent", 0) or 0)
            
            # Mint authority
            mint_auth = base_token.get("mint_authority")
            if mint_auth == "" or mint_auth is None:
                mint_auth = "revoked"
            
            # Buy/sell ratio
            total_tx = buys_1h + sells_1h
            buy_sell_ratio = buys_1h / total_tx if total_tx > 0 else 0.5
            
            # Create Token object
            token = Token(
                address=address,
                token_address=address,
                name=name,
                symbol=symbol,
                price=price_usd,
                mc=market_cap,
                liq=liquidity_usd,  # Sudah dijamin > 0
                vol1h=volume_1h,
                chg1h=price_change_1h,
                buys1h=buys_1h,
                sells1h=sells_1h,
                top10_pct=top_10_percent,
                risk_norm=risk_score,
                age_hours=age_hours,
                lp_burn=lp_burn_percent,
                mint_auth=mint_auth,
                has_twitter=bool(base_token.get("twitter")),
                buy_sell_ratio=buy_sell_ratio,
                price_native=price_usd,
                plan=None,
                flags=0,
                filter_details=[],
                wash_trading_flag=False,
                wash_trading_reason=None
            )
            
            # Hitung plan entry jika harga valid
            if price_usd > 0:
                tp1_pct = getattr(self.cfg, 'TP1_PCT', 30)
                tp2_pct = getattr(self.cfg, 'TP2_PCT', 100)
                sl_pct = getattr(self.cfg, 'SL_PCT', 15)
                
                token.plan = {
                    'entry': price_usd,
                    'tp1': price_usd * (1 + tp1_pct / 100),
                    'tp2': price_usd * (1 + tp2_pct / 100),
                    'sl': price_usd * (1 - sl_pct / 100),
                }
            
            return token
            
        except Exception as e:
            log.error(f"Error parsing pool to token: {e}", exc_info=True)
            return None
