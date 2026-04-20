"""
filter_engine.py — ELPonyin 4-Step Filter + Wash Trading Detection.

TAMBAHAN v2:
  - Wash trading detection: fees/volume ratio
  - Volume authenticity check
  - Pibble-type manipulation detection
"""
import re
from dataclasses import dataclass, field
from typing import Optional, List
from config import AgentConfig

@dataclass
class Token:
    mint: str = ""
    name: str = "Unknown"
    symbol: str = "???"
    price: float = 0.0
    mc: float = 0.0
    liq: float = 0.0
    vol1h: float = 0.0
    vol6h: float = 0.0
    vol24h: float = 0.0
    chg1h: float = 0.0
    chg6h: float = 0.0
    chg24h: float = 0.0
    buys1h: int = 0
    sells1h: int = 0
    # Holder data
    top_holders: list = field(default_factory=list)
    top10_pct: float = 0.0
    top10_source: str = "N/A"
    holder_count_rc: int = 0
    # Risk
    risk_raw: int = 0
    risk_norm: float = 0.0
    risk_label: str = "unknown"
    mint_auth: Optional[str] = None
    freeze_auth: Optional[str] = None
    lp_burn: float = 0.0
    is_rugged: bool = False
    rc_risks: list = field(default_factory=list)
    # Social
    has_twitter: bool = False
    has_telegram: bool = False
    has_website: bool = False
    # Meta
    dex: str = ""
    pair_addr: str = ""
    created: str = ""
    age_hours: float = 0.0
    # Wash trading flag (v2)
    wash_trading_flag: bool = False
    wash_trading_reason: str = ""
    # Filter result
    flags: int = 0
    verdict: str = ""
    filter_details: list = field(default_factory=list)
    plan: dict = field(default_factory=dict)

    @property
    def buy_sell_ratio(self) -> float:
        total = self.buys1h + self.sells1h
        return self.buys1h / total if total > 0 else 0.0

    @property
    def liq_mc_ratio(self) -> float:
        return self.liq / self.mc if self.mc > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "mint": self.mint, "name": self.name, "symbol": self.symbol,
            "price": self.price, "mc": self.mc, "liq": self.liq,
            "vol1h": self.vol1h, "top10_pct": self.top10_pct,
            "risk_norm": self.risk_norm, "flags": self.flags,
            "verdict": self.verdict, "wash_trading_flag": self.wash_trading_flag,
        }

@dataclass
class FilterDetail:
    step: str
    passed: bool    # True=pass, False=fail, None=info
    value: str
    note: str


class FilterEngine:
    """
    ELPonyin 4-Step + Wash Trading Detection.

    WASH TRADING DETECTION (Pibble-type manipulation):
    ────────────────────────────────────────────────
    Indikator wash trading:
    1. Volume sangat tinggi relatif ke MC tapi jumlah txn sedikit
    2. Buys + sells per jam sangat rendah untuk volume sebesar itu
    3. Vol/MC ratio anomali tinggi tanpa buyer organik
    4. Fees terlalu rendah untuk volume yang dilaporkan

    Normal healthy coin:
    - 100-300 txn per jam untuk $50K volume
    - avg tx size $50-$500
    - fees ~0.3% of volume
    """

    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg

    def _detect_wash_trading(self, t: Token) -> tuple:
        """
        Detect wash trading / volume manipulation.
        Return: (is_wash: bool, reason: str)
        """
        reasons = []

        total_txn_1h = t.buys1h + t.sells1h
        vol1h = t.vol1h

        # Check 1: Volume ada tapi txn sangat sedikit
        if vol1h > 5000 and total_txn_1h < 10:
            avg_tx = vol1h / total_txn_1h if total_txn_1h > 0 else vol1h
            reasons.append(
                f"Volume ${vol1h:,.0f}/1h tapi hanya {total_txn_1h} txn "
                f"(avg ${avg_tx:,.0f}/tx — tidak natural)"
            )

        # Check 2: Vol/MC ratio anomali
        # Normal: vol 1h = 5-50% dari MC. Di atas 200% = suspicious.
        if t.mc > 0 and vol1h > 0:
            vol_mc_ratio = vol1h / t.mc
            if vol_mc_ratio > 3.0:  # volume > 300% MC dalam 1 jam
                reasons.append(
                    f"Vol/MC ratio {vol_mc_ratio:.1f}x "
                    f"(${vol1h:,.0f} vol / ${t.mc:,.0f} MC) — anomali tinggi"
                )

        # Check 3: txn per jam sangat rendah untuk token yang "ramai"
        # Jika MC > 50K tapi txn < 5 per jam → suspicious
        if t.mc > 50000 and total_txn_1h < 5 and total_txn_1h > 0:
            reasons.append(
                f"MC ${t.mc:,.0f} tapi hanya {total_txn_1h} txn/jam — "
                f"tidak proporsional (kemungkinan bot volume)"
            )

        # Check 4: Jika ada volume tapi 0 txn — jelas manipulasi
        if vol1h > 1000 and total_txn_1h == 0:
            reasons.append(
                f"Vol ${vol1h:,.0f}/1h dengan 0 txn tercatat — "
                f"data tidak konsisten (wash trading)"
            )

        # Check 5: Pibble-type — high MC, low fee indicator
        # Dari Pibble: MC $120K, total fees 1.07 SOL (~$150)
        # Normal: fees untuk $120K MC seharusnya jauh lebih tinggi
        # Proxy: jika chg1h sangat tinggi tapi txn sedikit
        if t.chg1h > 100 and total_txn_1h < 20 and t.mc > 50000:
            reasons.append(
                f"Pump {t.chg1h:+.0f}% dalam 1h dengan {total_txn_1h} txn — "
                f"terlihat digerakkan oleh sedikit wallet besar"
            )

        is_wash = len(reasons) >= 1
        reason  = " | ".join(reasons) if reasons else ""
        return is_wash, reason

    def run(self, t: Token) -> Token:
        cfg    = self.cfg
        flags  = 0
        detail = []

        def bad(step, reason, val):
            nonlocal flags
            flags += 1
            detail.append(FilterDetail(step, False, str(val), reason))

        def ok(step, val, note=""):
            detail.append(FilterDetail(step, True, str(val), note))

        def info(step, val, note=""):
            detail.append(FilterDetail(step, None, str(val), note))

        # ── INSTANT DISQUALIFIER ───────────────────────────
        if t.is_rugged:
            bad("RUGGED", "Confirmed rugged oleh RugCheck", "RUGGED ⛔")
            t.flags, t.filter_details, t.verdict = flags, detail, "RUGGED"
            return t

        # ── WASH TRADING DETECTION (v2) ────────────────────
        is_wash, wash_reason = self._detect_wash_trading(t)
        t.wash_trading_flag   = is_wash
        t.wash_trading_reason = wash_reason

        if is_wash:
            bad("⚠ Wash Trading",
                wash_reason or "Volume manipulation detected",
                "SUSPICIOUS")

        # ── S1: Mint/Freeze Authority ──────────────────────
        if t.mint_auth:
            bad("S1 – Mint Authority",
                "AKTIF → dev bisa cetak token baru → dilusi → SKIP MUTLAK",
                "ACTIVE ⛔")
        elif t.freeze_auth:
            bad("S1 – Freeze Authority",
                "AKTIF → dev bisa freeze wallet → honeypot",
                "ACTIVE ⛔")
        else:
            danger = [n for (lvl, n, d, v) in t.rc_risks
                      if lvl == "danger" and any(k in n.lower()
                      for k in ["bundle","insider","honeypot","sniper"])]
            if danger:
                bad("S1 – Bundle/Honeypot", f"Terdeteksi: {danger[0]}", "DANGER")
            else:
                lp = f"{t.lp_burn:.0f}% burned" if t.lp_burn > 0 else "N/A"
                ok("S1 – Authority & LP", f"Revoked | LP {lp}", "Aman")

        # ── S2: Market Cap & Liquidity ─────────────────────
        if t.mc <= 0:
            bad("S2 – Market Cap", "Data MC tidak ada", "N/A")
        elif t.mc < cfg.MIN_MC:
            bad("S2 – Market Cap",
                f"MC ${t.mc:,.0f} < min ${cfg.MIN_MC:,.0f}",
                f"${t.mc:,.0f}")
        elif t.mc > cfg.MAX_MC:
            bad("S2 – Market Cap",
                f"MC ${t.mc:,.0f} > max ${cfg.MAX_MC:,.0f}",
                f"${t.mc:,.0f}")
        elif t.liq < cfg.MIN_LIQ:
            bad("S2 – Liquidity",
                f"Liq ${t.liq:,.0f} < min ${cfg.MIN_LIQ:,.0f} → exit tipis",
                f"${t.liq:,.0f}")
        else:
            ratio = t.liq_mc_ratio
            if ratio < 0.04:
                bad("S2 – Liq/MC",
                    f"Ratio {ratio:.1%} < 4% → dump risk",
                    f"{ratio:.1%}")
            else:
                ok("S2 – MC & Liq",
                   f"MC ${t.mc:,.0f} | Liq ${t.liq:,.0f}",
                   f"Ratio {ratio:.1%}")

        # ── S3: Top Holder Concentration ──────────────────
        if t.top10_pct == 0:
            info("S3 – Top10",
                 f"N/A ({t.top10_source})",
                 "Cek manual Solscan")
        elif t.top10_pct > 70:
            bad("S3 – Top10",
                f"{t.top10_pct:.1f}% > 70% → CABAL/BUNDLE → dump risk",
                f"{t.top10_pct:.1f}%")
        elif t.top10_pct > cfg.MAX_TOP10_PCT:
            bad("S3 – Top10",
                f"{t.top10_pct:.1f}% > {cfg.MAX_TOP10_PCT}% → terkonsentrasi",
                f"{t.top10_pct:.1f}%")
        else:
            ok("S3 – Top10",
               f"{t.top10_pct:.1f}% ({t.top10_source})",
               "Distribusi sehat")

        # ── S4: Risk Score ─────────────────────────────────
        rn = t.risk_norm
        if rn > 7:
            bad("S4 – Risk",
                f"Score {rn}/10 [{t.risk_label.upper()}] — BERBAHAYA",
                f"{rn}/10")
        elif rn > cfg.MAX_RISK_NORM:
            bad("S4 – Risk",
                f"Score {rn}/10 > max {cfg.MAX_RISK_NORM}",
                f"{rn}/10")
        elif 0 < t.lp_burn < 80:
            bad("S4 – LP Burn",
                f"LP {t.lp_burn:.0f}% < 80% → dev bisa tarik liq",
                f"{t.lp_burn:.0f}%")
        else:
            lp = f"{t.lp_burn:.0f}%" if t.lp_burn > 0 else "N/A"
            ok("S4 – Risk & LP",
               f"Risk {rn}/10 [{t.risk_label}] | LP {lp}",
               "Acceptable")

        # ── S5: Socials ────────────────────────────────────
        soc = []
        if t.has_twitter:  soc.append("Twitter")
        if t.has_telegram: soc.append("Telegram")
        if t.has_website:  soc.append("Website")
        if not soc:
            info("S5 – Socials", "NONE", "Dev anonim — extra hati-hati")
        elif t.has_twitter:
            ok("S5 – Socials", ", ".join(soc), "Social presence ada")
        else:
            info("S5 – Socials", ", ".join(soc), "Tidak ada Twitter/X")

        # ── BONUS: Buy/Sell ────────────────────────────────
        total_tx = t.buys1h + t.sells1h
        if total_tx > 0:
            bsr = t.buy_sell_ratio
            bsr_str = f"{t.buys1h}B/{t.sells1h}S ({bsr:.0%})"
            if bsr > 0.65:
                ok("Bonus – Buy/Sell", bsr_str, "Buying pressure ✓")
            elif bsr < 0.35:
                info("Bonus – Buy/Sell", bsr_str, "Lebih banyak sell")
            else:
                info("Bonus – Buy/Sell", bsr_str, "Balanced")

        # ── BONUS: Age ────────────────────────────────────
        if t.age_hours > 0:
            age = f"{t.age_hours:.1f}h"
            if t.age_hours < 1:
                ok("Bonus – Age", age, "Very fresh ✓")
            elif t.age_hours <= 12:
                ok("Bonus – Age", age, "Fresh ✓")
            elif t.age_hours <= cfg.MAX_AGE_HOURS:
                info("Bonus – Age", age, "Cek thesis masih valid")
            else:
                info("Bonus – Age", age, f"Sudah tua (>{cfg.MAX_AGE_HOURS}h)")

        # ── VERDICT & PLAN ─────────────────────────────────
        t.flags          = flags
        t.filter_details = detail

        if flags == 0:
            t.verdict = "MASUK"
        elif flags == 1:
            t.verdict = "WATCH"
        else:
            t.verdict = "SKIP"

        if flags < 2 and t.price > 0:
            p = t.price
            t.plan = {
                "entry": p,
                "tp1":   p * (1 + cfg.TP1_PCT / 100),
                "tp2":   p * (1 + cfg.TP2_PCT / 100),
                "sl":    p * (1 - cfg.SL_PCT  / 100),
                "dca1":  p * (1 - cfg.DCA1_PCT / 100),
                "dca2":  p * (1 - cfg.DCA2_PCT / 100),
            }

        return t
