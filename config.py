"""
config.py — Configuration management for PONYIN bot.
"""
import os
from typing import Optional

class AgentConfig:
    def __init__(self):
        # Telegram settings
        self.TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.TELEGRAM_CHAT_ID: str = os.getenv('TELEGRAM_CHAT_ID', '')
        
        # GMGN API
        self.GMGN_API_KEY: str = os.getenv('GMGN_API_KEY', '')
        
        # Anthropic API (optional - untuk AI reasoning)
        self.ANTHROPIC_API_KEY: str = os.getenv('ANTHROPIC_API_KEY', '')
        self.AI_ENABLED: bool = bool(self.ANTHROPIC_API_KEY)
        
        # Fetching settings
        self.FETCH_INTERVAL_SECONDS: int = int(os.getenv('FETCH_INTERVAL_SECONDS', '60'))
        self.FETCH_LIMIT: int = int(os.getenv('FETCH_LIMIT', '10'))
        self.MAX_CONCURRENT_REQUESTS: int = int(os.getenv('MAX_CONCURRENT_REQUESTS', '5'))
        
        # Portfolio settings
        self.PORTFOLIO_SOL: float = float(os.getenv('PORTFOLIO_SOL', '100.0'))
        
        # Sizing settings (percentages of portfolio)
        self.SIZE_HIGH: float = float(os.getenv('SIZE_HIGH', '0.05'))    # 5%
        self.SIZE_MEDIUM: float = float(os.getenv('SIZE_MEDIUM', '0.02'))  # 2%
        self.SIZE_LOW: float = float(os.getenv('SIZE_LOW', '0.01'))     # 1%
        
        # Risk management
        self.TP1_PCT: float = float(os.getenv('TP1_PCT', '30.0'))  # Take profit 1
        self.TP2_PCT: float = float(os.getenv('TP2_PCT', '100.0')) # Take profit 2
        self.SL_PCT: float = float(os.getenv('SL_PCT', '15.0'))    # Stop loss
        
        # Filter thresholds
        self.MIN_AGE_HOURS: float = float(os.getenv('MIN_AGE_HOURS', '0.1'))  # 6 minutes
        self.MIN_LIQUIDITY_USD: float = float(os.getenv('MIN_LIQUIDITY_USD', '10000'))
        self.MIN_VOL_TO_LIQ_RATIO: float = float(os.getenv('MIN_VOL_TO_LIQ_RATIO', '0.01'))
        self.MAX_VOL_TO_LIQ_RATIO: float = float(os.getenv('MAX_VOL_TO_LIQ_RATIO', '2.0'))
        self.MAX_TOP10_PERCENT: float = float(os.getenv('MAX_TOP10_PERCENT', '50.0'))
        self.MAX_RISK_SCORE: float = float(os.getenv('MAX_RISK_SCORE', '7.0'))
        self.MIN_LP_BURN_PERCENT: float = float(os.getenv('MIN_LP_BURN_PERCENT', '50.0'))
        
        # Validation
        self._validate()

    def _validate(self):
        """Validate configuration values."""
        errors = []
        
        if not self.TELEGRAM_BOT_TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN is required")
        if not self.TELEGRAM_CHAT_ID:
            errors.append("TELEGRAM_CHAT_ID is required")
        if not self.GMGN_API_KEY:
            errors.append("GMGN_API_KEY is required")
            
        # Validate numeric ranges
        if self.FETCH_INTERVAL_SECONDS < 10:
            errors.append("FETCH_INTERVAL_SECONDS should be at least 10")
        if self.PORTFOLIO_SOL <= 0:
            errors.append("PORTFOLIO_SOL must be positive")
        if not (0 < self.SIZE_HIGH <= 0.2):  # Max 20%
            errors.append("SIZE_HIGH should be between 0 and 0.2")
        if not (0 < self.TP1_PCT <= 500):  # Max 500%
            errors.append("TP1_PCT should be between 0 and 500")
        if not (0 < self.TP2_PCT <= 1000):  # Max 1000%
            errors.append("TP2_PCT should be between 0 and 1000")
        if not (0 < self.SL_PCT <= 50):  # Max 50%
            errors.append("SL_PCT should be between 0 and 50")
            
        if errors:
            raise ValueError(f"Configuration errors: {'; '.join(errors)}")

    def __repr__(self):
        return f"AgentConfig(telegram_enabled={bool(self.TELEGRAM_BOT_TOKEN)}, gmgn_enabled={bool(self.GMGN_API_KEY)}, ai_enabled={self.AI_ENABLED})"
