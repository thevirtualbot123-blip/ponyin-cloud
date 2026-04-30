"""
filter_engine.py — Advanced token filtering with multiple safety checks.
"""
import logging, math, statistics
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from config import AgentConfig

log = logging.getLogger("PONYIN.Filter")

def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safe division that handles zero denominators and None values."""
    if numerator is None or denominator is None:
        return default
    if denominator == 0:
        return default
    try:
        result = numerator / denominator
        # Cek apakah hasilnya infinity atau NaN
        if math.isinf(result) or math.isnan(result):
            return default
        return result
    except (TypeError, ValueError):
        return default

@dataclass
class FilterResult:
    step: str              # Nama filter step
    passed: bool           # Apakah lulus
    value: Any             # Nilai yang dicek
    threshold: Any         # Threshold yang digunakan
    message: str           # Detail pesan

@dataclass
class Token:
    address: str
    token_address: str
    name: str
    symbol: str
    price: float
    mc: float
    liq: float
    vol1h: float
    chg1h: float
    buys1h: int
    sells1h: int
    top10_pct: float
    risk_norm: float
    age_hours: float
    lp_burn: float
    mint_auth: Optional[str]
    has_twitter: bool
    buy_sell_ratio: float
    price_native: float
    # Optional fields
    plan: Optional[Dict[str, float]] = None
    flags: int = 0
    filter_details: List[FilterResult] = None
    wash_trading_flag: bool = False
    wash_trading_reason: Optional[str] = None
    
    def __post_init__(self):
        if self.filter_details is None:
            self.filter_details = []

@dataclass
class FilterConfig:
    """Configuration for all filters."""
    # Age filters
    MIN_AGE_HOURS: float = 0.1  # Minimal 6 minutes
    MAX_AGE_HOURS: float = 168  # Max 1 week
    
    # Liquidity filters
    MIN_LIQUIDITY_USD: float = 10000  # $10K min
    MIN_VOL_TO_LIQ_RATIO: float = 0.01  # 1% min
    MAX_VOL_TO_LIQ_RATIO: float = 2.0   # 200% max (avoid manipulation)
    
    # Market cap filters
    MIN_MARKET_CAP: float = 50000  # $50K min
    MAX_MARKET_CAP: float = 10000000  # $10M max
    
    # Holder concentration filters
    MAX_TOP10_PERCENT: float = 50  # Max 50% held by top 10
    MAX_SINGLE_HOLDER_PERCENT: float = 20  # Max 20% single holder
    
    # Transaction filters
    MIN_TRANSACTIONS_PER_HOUR: int = 10  # Min 10 txns/hour
    MIN_BUY_SELL_RATIO: float = 0.1  # Min 10% buys
    MAX_BUY_SELL_RATIO: float = 0.9  # Max 90% buys (avoid extreme imbalance)
    
    # Price change filters
    MIN_PRICE_CHANGE_ABS: float = 0.1  # Min 0.1% absolute change
    MAX_PRICE_CHANGE_ABS: float = 500  # Max 500% absolute change
    
    # Risk filters
    MAX_RISK_SCORE: float = 7.0  # Max 7/10 risk
    
    # LP filters
    MIN_LP_BURN_PERCENT: float = 50  # Min 50% LP burned

class FilterEngine:
    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg
        self.filter_config = FilterConfig(
            MIN_AGE_HOURS=cfg.MIN_AGE_HOURS,
            MIN_LIQUIDITY_USD=cfg.MIN_LIQUIDITY_USD,
            MIN_VOL_TO_LIQ_RATIO=cfg.MIN_VOL_TO_LIQ_RATIO,
            MAX_VOL_TO_LIQ_RATIO=cfg.MAX_VOL_TO_LIQ_RATIO,
            MAX_TOP10_PERCENT=cfg.MAX_TOP10_PERCENT,
            MAX_RISK_SCORE=cfg.MAX_RISK_SCORE,
            MIN_LP_BURN_PERCENT=cfg.MIN_LP_BURN_PERCENT,
        )

    def apply_filters(self, token: Token) -> Token:
        """Apply all filters to a token and return updated token with flags."""
        token.flags = 0
        token.filter_details = []
        token.wash_trading_flag = False
        token.wash_trading_reason = None
        
        # Apply all filters sequentially
        self._check_age_filter(token)
        self._check_liquidity_filter(token)
        self._check_market_cap_filter(token)
        self._check_holder_concentration_filter(token)
        self._check_transaction_metrics_filter(token)
        self._check_price_change_filter(token)
        self._check_risk_score_filter(token)
        self._check_lp_burn_filter(token)
        self._check_mint_authority_filter(token)
        self._check_wash_trading(token)
        
        # Log summary
        passed_filters = sum(1 for f in token.filter_details if f.passed)
        total_filters = len(token.filter_details)
        log.debug(f"Token {token.symbol}: {passed_filters}/{total_filters} filters passed, {token.flags} flags")
        
        return token

    def _add_flag(self, token: Token, result: FilterResult):
        """Add a flag and store filter result."""
        token.flags += 1
        token.filter_details.append(result)

    def _check_age_filter(self, token: Token):
        """Check if token is too young or too old."""
        if token.age_hours < self.filter_config.MIN_AGE_HOURS:
            self._add_flag(token, FilterResult(
                step="Age Check",
                passed=False,
                value=token.age_hours,
                threshold=self.filter_config.MIN_AGE_HOURS,
                message=f"Token too young: {token.age_hours:.2f}h < {self.filter_config.MIN_AGE_HOURS}h"
            ))
        elif token.age_hours > self.filter_config.MAX_AGE_HOURS:
            self._add_flag(token, FilterResult(
                step="Age Check",
                passed=False,
                value=token.age_hours,
                threshold=self.filter_config.MAX_AGE_HOURS,
                message=f"Token too old: {token.age_hours:.2f}h > {self.filter_config.MAX_AGE_HOURS}h"
            ))
        else:
            token.filter_details.append(FilterResult(
                step="Age Check",
                passed=True,
                value=token.age_hours,
                threshold=f"{self.filter_config.MIN_AGE_HOURS}-{self.filter_config.MAX_AGE_HOURS}h",
                message=f"Age OK: {token.age_hours:.2f}h"
            ))

    def _check_liquidity_filter(self, token: Token):
        """Check liquidity requirements."""
        # Minimum liquidity
        if token.liq < self.filter_config.MIN_LIQUIDITY_USD:
            self._add_flag(token, FilterResult(
                step="Liquidity Check",
                passed=False,
                value=token.liq,
                threshold=self.filter_config.MIN_LIQUIDITY_USD,
                message=f"Liquidity too low: ${token.liq:,.0f} < ${self.filter_config.MIN_LIQUIDITY_USD:,}"
            ))
        else:
            token.filter_details.append(FilterResult(
                step="Liquidity Check",
                passed=True,
                value=token.liq,
                threshold=f">${self.filter_config.MIN_LIQUIDITY_USD:,}",
                message=f"Liq OK: ${token.liq:,.0f}"
            ))
        
        # Volume to liquidity ratio (to detect manipulation)
        vol_to_liq_ratio = safe_div(token.vol1h, token.liq, 0.0)
        if vol_to_liq_ratio > self.filter_config.MAX_VOL_TO_LIQ_RATIO:
            self._add_flag(token, FilterResult(
                step="Volume/Liquidity Check",
                passed=False,
                value=vol_to_liq_ratio,
                threshold=self.filter_config.MAX_VOL_TO_LIQ_RATIO,
                message=f"Vol/Liq too high: {vol_to_liq_ratio:.2f}x > {self.filter_config.MAX_VOL_TO_LIQ_RATIO}x"
            ))
        elif vol_to_liq_ratio < self.filter_config.MIN_VOL_TO_LIQ_RATIO and token.vol1h > 0:
            # Only flag if there's volume but very low ratio
            self._add_flag(token, FilterResult(
                step="Volume/Liquidity Check",
                passed=False,
                value=vol_to_liq_ratio,
                threshold=self.filter_config.MIN_VOL_TO_LIQ_RATIO,
                message=f"Vol/Liq too low: {vol_to_liq_ratio:.2f}x < {self.filter_config.MIN_VOL_TO_LIQ_RATIO}x"
            ))
        else:
            token.filter_details.append(FilterResult(
                step="Volume/Liquidity Check",
                passed=True,
                value=vol_to_liq_ratio,
                threshold=f"{self.filter_config.MIN_VOL_TO_LIQ_RATIO}-{self.filter_config.MAX_VOL_TO_LIQ_RATIO}x",
                message=f"Vol/Liq OK: {vol_to_liq_ratio:.2f}x"
            ))

    def _check_market_cap_filter(self, token: Token):
        """Check market cap requirements."""
        if token.mc < self.filter_config.MIN_MARKET_CAP:
            self._add_flag(token, FilterResult(
                step="Market Cap Check",
                passed=False,
                value=token.mc,
                threshold=self.filter_config.MIN_MARKET_CAP,
                message=f"MC too low: ${token.mc:,.0f} < ${self.filter_config.MIN_MARKET_CAP:,}"
            ))
        elif token.mc > self.filter_config.MAX_MARKET_CAP:
            self._add_flag(token, FilterResult(
                step="Market Cap Check",
                passed=False,
                value=token.mc,
                threshold=self.filter_config.MAX_MARKET_CAP,
                message=f"MC too high: ${token.mc:,.0f} > ${self.filter_config.MAX_MARKET_CAP:,}"
            ))
        else:
            token.filter_details.append(FilterResult(
                step="Market Cap Check",
                passed=True,
                value=token.mc,
                threshold=f"${self.filter_config.MIN_MARKET_CAP:,}-${self.filter_config.MAX_MARKET_CAP:,}",
                message=f"MC OK: ${token.mc:,.0f}"
            ))

    def _check_holder_concentration_filter(self, token: Token):
        """Check top holder concentration."""
        if token.top10_pct > self.filter_config.MAX_TOP10_PERCENT:
            self._add_flag(token, FilterResult(
                step="Holder Concentration",
                passed=False,
                value=token.top10_pct,
                threshold=self.filter_config.MAX_TOP10_PERCENT,
                message=f"Top 10 holders too concentrated: {token.top10_pct:.1f}% > {self.filter_config.MAX_TOP10_PERCENT}%"
            ))
        else:
            token.filter_details.append(FilterResult(
                step="Holder Concentration",
                passed=True,
                value=token.top10_pct,
                threshold=f"≤{self.filter_config.MAX_TOP10_PERCENT}%",
                message=f"Holder distribution OK: {token.top10_pct:.1f}%"
            ))

    def _check_transaction_metrics_filter(self, token: Token):
        """Check transaction metrics."""
        total_tx = token.buys1h + token.sells1h
        if total_tx < self.filter_config.MIN_TRANSACTIONS_PER_HOUR:
            self._add_flag(token, FilterResult(
                step="Transaction Volume",
                passed=False,
                value=total_tx,
                threshold=self.filter_config.MIN_TRANSACTIONS_PER_HOUR,
                message=f"Low activity: {total_tx} txns < {self.filter_config.MIN_TRANSACTIONS_PER_HOUR} txns"
            ))
        else:
            token.filter_details.append(FilterResult(
                step="Transaction Volume",
                passed=True,
                value=total_tx,
                threshold=f"≥{self.filter_config.MIN_TRANSACTIONS_PER_HOUR}",
                message=f"Activity OK: {total_tx} txns"
            ))
        
        # Buy/sell ratio balance
        if token.buy_sell_ratio < self.filter_config.MIN_BUY_SELL_RATIO:
            self._add_flag(token, FilterResult(
                step="Buy/Sell Balance",
                passed=False,
                value=token.buy_sell_ratio,
                threshold=self.filter_config.MIN_BUY_SELL_RATIO,
                message=f"Too many sells: {token.buy_sell_ratio:.1%} buys < {self.filter_config.MIN_BUY_SELL_RATIO:.0%}"
            ))
        elif token.buy_sell_ratio > self.filter_config.MAX_BUY_SELL_RATIO:
            self._add_flag(token, FilterResult(
                step="Buy/Sell Balance",
                passed=False,
                value=token.buy_sell_ratio,
                threshold=self.filter_config.MAX_BUY_SELL_RATIO,
                message=f"Too many buys: {token.buy_sell_ratio:.1%} buys > {self.filter_config.MAX_BUY_SELL_RATIO:.0%}"
            ))
        else:
            token.filter_details.append(FilterResult(
                step="Buy/Sell Balance",
                passed=True,
                value=token.buy_sell_ratio,
                threshold=f"{self.filter_config.MIN_BUY_SELL_RATIO:.0%}-{self.filter_config.MAX_BUY_SELL_RATIO:.0%}",
                message=f"Balance OK: {token.buy_sell_ratio:.1%} buys"
            ))

    def _check_price_change_filter(self, token: Token):
        """Check price change magnitude."""
        abs_chg = abs(token.chg1h)
        if abs_chg < self.filter_config.MIN_PRICE_CHANGE_ABS:
            self._add_flag(token, FilterResult(
                step="Price Change Magnitude",
                passed=False,
                value=abs_chg,
                threshold=self.filter_config.MIN_PRICE_CHANGE_ABS,
                message=f"Price stable: {abs_chg:.2f}% < {self.filter_config.MIN_PRICE_CHANGE_ABS}%"
            ))
        elif abs_chg > self.filter_config.MAX_PRICE_CHANGE_ABS:
            self._add_flag(token, FilterResult(
                step="Price Change Magnitude",
                passed=False,
                value=abs_chg,
                threshold=self.filter_config.MAX_PRICE_CHANGE_ABS,
                message=f"Extreme volatility: {abs_chg:.2f}% > {self.filter_config.MAX_PRICE_CHANGE_ABS}%"
            ))
        else:
            token.filter_details.append(FilterResult(
                step="Price Change Magnitude",
                passed=True,
                value=abs_chg,
                threshold=f"{self.filter_config.MIN_PRICE_CHANGE_ABS}-{self.filter_config.MAX_PRICE_CHANGE_ABS}%",
                message=f"Volatility OK: {abs_chg:.2f}%"
            ))

    def _check_risk_score_filter(self, token: Token):
        """Check risk score."""
        if token.risk_norm > self.filter_config.MAX_RISK_SCORE:
            self._add_flag(token, FilterResult(
                step="Risk Score",
                passed=False,
                value=token.risk_norm,
                threshold=self.filter_config.MAX_RISK_SCORE,
                message=f"High risk: {token.risk_norm}/10 > {self.filter_config.MAX_RISK_SCORE}/10"
            ))
        else:
            token.filter_details.append(FilterResult(
                step="Risk Score",
                passed=True,
                value=token.risk_norm,
                threshold=f"≤{self.filter_config.MAX_RISK_SCORE}/10",
                message=f"Risk OK: {token.risk_norm}/10"
            ))

    def _check_lp_burn_filter(self, token: Token):
        """Check LP burn percentage."""
        if token.lp_burn < self.filter_config.MIN_LP_BURN_PERCENT:
            self._add_flag(token, FilterResult(
                step="LP Burn Check",
                passed=False,
                value=token.lp_burn,
                threshold=self.filter_config.MIN_LP_BURN_PERCENT,
                message=f"LP not burned enough: {token.lp_burn:.0f}% < {self.filter_config.MIN_LP_BURN_PERCENT}%"
            ))
        else:
            token.filter_details.append(FilterResult(
                step="LP Burn Check",
                passed=True,
                value=token.lp_burn,
                threshold=f"≥{self.filter_config.MIN_LP_BURN_PERCENT}%",
                message=f"LP Burn OK: {token.lp_burn:.0f}%"
            ))

    def _check_mint_authority_filter(self, token: Token):
        """Check mint authority status."""
        if token.mint_auth is not None and token.mint_auth != "revoked":
            # Flag sebagai RED FLAG KRITISIS
            self._add_flag(token, FilterResult(
                step="Mint Authority",
                passed=False,
                value="active" if token.mint_auth else "unknown",
                threshold="revoked",
                message=f"Mint authority still active! Address: {token.mint_auth[:8] if token.mint_auth else 'unknown'}"
            ))
        else:
            token.filter_details.append(FilterResult(
                step="Mint Authority",
                passed=True,
                value="revoked" if token.mint_auth == "revoked" else "not set",
                threshold="revoked",
                message="Mint authority revoked ✓"
            ))

    def _check_wash_trading(self, token: Token):
        """Enhanced wash trading detection."""
        # Calculate some metrics
        total_volume = token.vol1h
        total_tx = token.buys1h + token.sells1h
        buy_ratio = safe_div(token.buys1h, total_tx, 0.5)
        
        # Pattern indicators
        indicators = []
        
        # Check if volume is extremely high relative to liquidity
        vol_to_liq_ratio = safe_div(total_volume, token.liq, 0.0)
        if vol_to_liq_ratio > 5.0:  # More than 500% of liquidity traded
            indicators.append(f"Volume 5x+ liquidity ({vol_to_liq_ratio:.1f}x)")
        
        # Check for extreme buy/sell imbalance
        if abs(buy_ratio - 0.5) > 0.4:  # More than 90/10 split
            side = "buys" if buy_ratio > 0.5 else "sells"
            indicators.append(f"Extreme {side} imbalance ({buy_ratio:.0%} {side})")
        
        # Check for very low unique traders vs transactions
        # (Would need additional data, but we can infer from transaction patterns)
        
        # Check for suspicious timing patterns (would need historical data)
        
        if indicators:
            token.wash_trading_flag = True
            token.wash_trading_reason = "; ".join(indicators)
            log.warning(f"Wash trading detected for {token.symbol}: {token.wash_trading_reason}")
        else:
            token.wash_trading_flag = False
            token.wash_trading_reason = None
