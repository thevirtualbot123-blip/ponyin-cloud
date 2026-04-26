"""config.py — Konfigurasi PONYIN AI AGENT v7.0"""
import os
from dataclasses import dataclass

@dataclass
class AgentConfig:

    TG_API_ID:   str = os.getenv("TELEGRAM_API_ID",   "")
    TG_API_HASH: str = os.getenv("TELEGRAM_API_HASH", "")
    TG_PHONE:    str = os.getenv("TELEGRAM_PHONE",    "")
    TG_SESSION:  str = os.getenv("TG_SESSION",        "ponyin_agent")

    _SIGNAL_CHANNELS_RAW: str = os.getenv("SIGNAL_CHANNELS", "")

    @property
    def SIGNAL_CHANNELS(self):
        raw = self._SIGNAL_CHANNELS_RAW
        return [c.strip() for c in raw.split(",") if c.strip()] if raw else []

    BOT_TOKEN:   str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    BOT_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID",  "")

    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    @property
    def AI_ENABLED(self) -> bool:
        return bool(self.ANTHROPIC_API_KEY)

    MIN_MC:        float = float(os.getenv("MIN_MC",    "8000"))
    MAX_MC:        float = float(os.getenv("MAX_MC",    "800000"))
    MIN_LIQ:       float = float(os.getenv("MIN_LIQ",  "3000"))
    MAX_TOP10_PCT: float = float(os.getenv("MAX_TOP10", "55"))
    MAX_RISK_NORM: float = float(os.getenv("MAX_RISK",  "5.0"))
    MAX_AGE_HOURS: float = float(os.getenv("MAX_AGE_H", "48"))

    TP1_PCT:  float = float(os.getenv("TP1",  "30"))
    TP2_PCT:  float = float(os.getenv("TP2",  "50"))
    SL_PCT:   float = float(os.getenv("SL",   "20"))
    DCA1_PCT: float = float(os.getenv("DCA1", "20"))
    DCA2_PCT: float = float(os.getenv("DCA2", "35"))

    PORTFOLIO_SOL: float = float(os.getenv("PORTFOLIO_SOL", "1.0"))
    MAX_POSITIONS: int   = int(os.getenv("MAX_POSITIONS",   "3"))
    SIZE_HIGH:     float = float(os.getenv("SIZE_HIGH",  "0.25"))
    SIZE_MEDIUM:   float = float(os.getenv("SIZE_MEDIUM","0.15"))
    SIZE_LOW:      float = float(os.getenv("SIZE_LOW",   "0.08"))

    SCAN_INTERVAL:     int  = int(os.getenv("SCAN_INTERVAL",    "120"))
    MONITOR_INTERVAL:  int  = int(os.getenv("MONITOR_INTERVAL", "60"))
    AUTO_SCAN_ENABLED: bool = os.getenv("AUTO_SCAN", "false").lower() == "true"