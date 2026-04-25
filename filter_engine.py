"""
filter_engine.py — PONYIN AI AGENT v5.0
=========================================
- Helius untuk holder akurat
- Threshold longgar untuk token fresh
- Wash trading dikalibrasi ulang
"""
import re, logging
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
from config import AgentConfig

log = logging.getLogger("PONYIN.Filter")

def safe_div(a: float, b: float, default: float = 0.0) -> float:
    try:
        if b == 0 or b is None: return default
        return a / b
    except Exception:
        return default

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
    top_holders: list = field(default_factory=list)
    top10_pct: float = 0.0
    top10_source: str = "N/A"
    holder_count_rc: int = 0
    risk_raw: int = 0
    risk_norm: float = 0.0
    risk_label: str = "unknown"
    mint_auth: Optional[str] = None
    freeze_auth: Optional[str] = None
    lp_burn: float = 0.0
    is_rugged: bool = False
    rc_risks: list = field(default_factory=list)
    has_twitter: bool = False
    has_telegram: bool = False
    has_website: bool = False
    dex: str = ""
    pair_addr: str = ""
    created: str = ""
    age_hours: float = 0.0
    # Helius
    helius_holders_available: bool = False
    holder_list_helius: list = field(default_factory=list)
    holder_count_helius: int = 0
    # Advanced
    wash_trading_flag: bool = False
    wash_trading_reason: str = ""
    cluster_risk: str = "UNKNOWN"
    cluster_reason: str = ""
    cluster_score: int = 0
    dev_farm_risk: str = "UNKNOWN"
    dev_farm_reason: str = ""
    smart_money_present: bool = False
    smart_money_pct: float = 0.0
    timing_score: int = 50
    timing_reason: str = ""
    bounce_potential: bool = False
    bounce_reason: str = ""
    liq_trap_risk: bool = False
    holder_health: int = 50
    momentum_score: int = 50
    position_type: str = "LOWCAP"
    is_bonding_curve: bool = False
    fee_health: str = "HEALTHY"
    fee_health_reason: str = ""
    flags: int = 0
    verdict: str = "PENDING"
    filter_details: list = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    sizing_note: str = ""

    @property
    def buy_sell_ratio(self) -> float:
        total = self.buys1h + self.sells1h
        return safe_div(self.buys1h, total, 0.5)

    @property
    def liq_mc_ratio(self) -> float:
        return safe_div(self.liq, self.mc, 0.0)

    def to_dict(self) -> dict:
        return {
            "mint": self.mint, "name": self.name, "symbol": self.symbol,
            "price": self.price, "mc": self.mc, "liq": self.liq,
            "vol1h": self.vol1h, "vol24h": self.vol24h,
            "chg1h": self.chg1h, "chg24h": self.chg24h,
            "top10_pct": self.top10_pct, "top10_source": self.top10_source,
            "risk_norm": self.risk_norm, "risk_label": self.risk_label,
            "lp_burn": self.lp_burn, "mint_auth": self.mint_auth,
            "has_twitter": self.has_twitter, "has_telegram": self.has_telegram,
            "has_website": self.has_website,
            "flags": self.flags, "verdict": self.verdict,
            "position_type": self.position_type,
            "wash_trading_flag": self.wash_trading_flag,
            "wash_trading_reason": self.wash_trading_reason,
            "cluster_risk": self.cluster_risk,
            "cluster_score": self.cluster_score,
            "dev_farm_risk": self.dev_farm_risk,
            "smart_money_present": self.smart_money_present,
            "smart_money_pct": self.smart_money_pct,
            "timing_score": self.timing_score,
            "timing_reason": self.timing_reason,
            "holder_health": self.holder_health,
            "momentum_score": self.momentum_score,
            "holder_count_rc": self.holder_count_rc,
            "bounce_potential": self.bounce_potential,
            "liq_trap_risk": self.liq_trap_risk,
            "is_bonding_curve": self.is_bonding_curve,
            "fee_health": self.fee_health,
            "fee_health_reason": self.fee_health_reason,
            "plan": self.plan,
            "sizing_note": self.sizing_note,
            "age_hours": self.age_hours,
            "dex": self.dex,
            "buys1h": self.buys1h,
            "sells1h": self.sells1h,
        }

@dataclass
class FilterDetail:
    step: str
    passed: bool
    value: str
    note: str

class FilterEngine:

    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg

    def run(self, t: Token) -> Token:
        try:
            t = self._classify(t)
            t = self._detect_bonding_curve(t)
            t = self._clean_top10(t)
            t = self._detect_wash_trading(t)
            t = self._detect_cluster(t)
            t = self._detect_dev_farm(t)
            t = self._check_fee_health(t)
            t = self._detect_smart_money(t)
            t = self._timing_score(t)
            t = self._momentum_score(t)
            t = self._liq_trap(t)
            t = self._bounce_potential(t)
            t = self._holder_health(t)
            t = self._apply_filters(t)
            t = self._build_plan(t)
        except Exception as e:
            log.error(f"Filter error {t.mint[:12]}: {e}", exc_info=True)
            t.verdict = "ERROR"
            t.flags = 99
            t.sizing_note = "Error saat filter — cek manual"
        return t

    def _classify(self, t: Token) -> Token:
        if   t.mc < 100_000:   t.position_type = "LOWCAP"
        elif t.mc < 2_000_000: t.position_type = "MIDCAP"
        else:                   t.position_type = "HIGHCAP"
        return t

    def _detect_bonding_curve(self, t: Token) -> Token:
        if t.liq <= 0 and t.vol1h > 100 and t.mc > 0:
            t.is_bonding_curve = True
        else:
            t.is_bonding_curve = False
        return t

    def _clean_top10(self, t: Token) -> Token:
        # sederhana, tetap ada
        return t

    def _detect_wash_trading(self, t: Token) -> Token:
        reasons = []
        total_txn = t.buys1h + t.sells1h
        # Hanya curigai jika volume sangat ekstrem vs likuiditas
        if not t.is_bonding_curve and t.liq > 0 and t.vol1h > 0:
            ratio = safe_div(t.vol1h, t.liq)
            if ratio > 50 and t.vol1h > 20_000:
                reasons.append(f"Vol {ratio:.0f}x Liq (${t.vol1h:,.0f}/${t.liq:,.0f})")
            elif ratio > 35 and t.vol1h > 50_000:
                reasons.append(f"Extreme vol/liq {ratio:.0f}x")
        if t.vol1h > 10_000 and total_txn == 0 and not t.is_bonding_curve and t.liq > 0:
            reasons.append(f"Vol besar ({t.vol1h:,.0f}) dgn 0 txn")
        t.wash_trading_flag = len(reasons) > 0
        t.wash_trading_reason = " | ".join(reasons)
        return t

    def _detect_cluster(self, t: Token) -> Token:
        # sama seperti sebelumnya
        if not t.top_holders:
            t.cluster_risk = "UNKNOWN"; t.cluster_reason = "Data tidak tersedia"; t.cluster_score = 30
            return t
        holders = t.top_holders[:20]
        pcts, insider_count, insider_pct = [], 0, 0.0
        for h in holders:
            pct = float(h.get("pct", 0) or 0)
            if 0 < pct <= 1.0: pct *= 100
            pcts.append(pct)
            if h.get("insider", False):
                insider_count += 1; insider_pct += pct
        score = 0
        reasons = []
        if   insider_count >= 6: score += 40; reasons.append(f"{insider_count} insiders")
        elif insider_count >= 3: score += 25; reasons.append(f"{insider_count} insiders")
        elif insider_count >= 1: score += 12
        top10_total = sum(pcts[:10])
        if   top10_total > 75: score += 45; reasons.append(f"top10 {top10_total:.0f}%")
        elif top10_total > 65: score += 30
        elif top10_total > 55: score += 15
        max_h = max(pcts[:10]) if pcts else 0
        if   max_h > 30: score += 25; reasons.append(f"whale {max_h:.1f}%")
        elif max_h > 20: score += 15
        score = min(100, max(0, score))
        t.cluster_score = score
        if   score >= 80: t.cluster_risk = "CRITICAL"
        elif score >= 56: t.cluster_risk = "HIGH"
        elif score >= 31: t.cluster_risk = "MEDIUM"
        else:              t.cluster_risk = "LOW"
        t.cluster_reason = " | ".join(reasons) if reasons else f"Score {score}/100 normal"
        return t

    def _detect_dev_farm(self, t: Token) -> Token:
        reasons, risk = [], "LOW"
        if t.lp_burn == 0 and not t.is_bonding_curve: reasons.append("LP 0%"); risk = "HIGH"
        elif t.lp_burn < 50 and not t.is_bonding_curve: reasons.append(f"LP {t.lp_burn:.0f}%"); risk = "MEDIUM"
        if t.mint_auth: reasons.append("Mint auth"); risk = "HIGH"
        if t.risk_norm > 6:
            reasons.append(f"risk {t.risk_norm}/10")
            if risk == "LOW": risk = "MEDIUM"
        kws = ["dev","creator","deployer","farm","bundle","sniper"]
        for (lvl, nm, dc, vl) in t.rc_risks:
            if any(k in (nm + dc).lower() for k in kws):
                reasons.append(f"[{lvl}] {nm}")
                if lvl == "danger": risk = "HIGH"
                elif lvl == "warn" and risk=="LOW": risk = "MEDIUM"
        t.dev_farm_risk = risk
        t.dev_farm_reason = " | ".join(reasons) if reasons else "Clean"
        return t

    def _check_fee_health(self, t: Token) -> Token:
        t.fee_health = "HEALTHY"
        t.fee_health_reason = "OK"

        # Cari sumber holder terbaik
        if hasattr(t, 'holder_count_helius') and t.holder_count_helius > 0:
            holder_count = t.holder_count_helius
            source = "Helius"
        elif t.holder_count_rc > 0 and t.age_hours >= 6.0:
            holder_count = t.holder_count_rc
            source = "RugCheck(mature)"
        else:
            t.fee_health_reason = f"Fresh/no reliable data (age={t.age_hours:.1f}h)"
            return t

        reasons = []
        fh = "HEALTHY"
        if source == "Helius":
            if t.mc > 100_000 and holder_count < 80:
                reasons.append(f"MC ${t.mc:,.0f} tapi hanya {holder_count} holders")
                fh = "DANGER"
            elif t.mc > 50_000 and holder_count < 50:
                reasons.append(f"MC ${t.mc:,.0f} dengan {holder_count} holders")
                fh = "LOW"
        else:  # RugCheck
            if t.mc > 100_000 and holder_count < 50:
                reasons.append(f"MC ${t.mc:,.0f} dgn {holder_count} holders (RugCheck)")
                fh = "WARNING"

        t.fee_health = fh
        t.fee_health_reason = " | ".join(reasons) if reasons else "OK"
        return t

    def _detect_smart_money(self, t: Token) -> Token:
        if not t.top_holders:
            t.smart_money_present = False
            return t
        count, total = 0, 0.0
        for h in t.top_holders[:20]:
            pct = float(h.get("pct", 0) or 0)
            if 0 < pct <= 1.0: pct *= 100
            if not h.get("insider", False) and 1.0 < pct < 15.0:
                count += 1
                total += pct
        t.smart_money_present = count >= 2
        t.smart_money_pct = round(total, 1)
        return t

    def _timing_score(self, t: Token) -> Token:
        hour = datetime.utcnow().hour
        dow  = datetime.utcnow().weekday()
        wp = -15 if dow >= 5 else 0
        if   20 <= hour or hour < 2:  base, r = 90, "US prime (20-02 UTC)"
        elif 13 <= hour < 20:          base, r = 75, "EU/US overlap (13-20 UTC)"
        elif 10 <= hour < 13:          base, r = 65, "EU peak (10-13 UTC)"
        elif 6  <= hour < 10:          base, r = 55, "EU morning (06-10 UTC)"
        elif 2  <= hour < 6:           base, r = 20, "Dead hours (02-06 UTC)"
        else:                           base, r = 40, f"Hour {hour} UTC"
        t.timing_score = max(0, min(100, base + wp))
        t.timing_reason = r + (" (wknd)" if dow >= 5 else "")
        return t

    def _momentum_score(self, t: Token) -> Token:
        score = 50
        c1 = t.chg1h
        if   c1 > 100: score += 30
        elif c1 >  50: score += 20
        elif c1 >  20: score += 12
        elif c1 >   5: score += 6
        elif c1 >   0: score += 2
        elif c1 > -10: score -= 3
        elif c1 > -20: score -= 10
        else:           score -= 20
        bsr = t.buy_sell_ratio
        if   bsr > 0.75: score += 15
        elif bsr > 0.60: score += 8
        elif bsr > 0.45: score += 2
        elif bsr < 0.30: score -= 10
        elif bsr < 0.40: score -= 5
        if t.liq > 0 and t.vol1h > 0:
            vl = safe_div(t.vol1h, t.liq, 0)
            if   vl > 3.0: score += 10
            elif vl > 1.0: score += 5
        t.momentum_score = max(0, min(100, score))
        return t

    def _liq_trap(self, t: Token) -> Token:
        if t.mc <= 0 or t.liq <= 0 or t.is_bonding_curve:
            t.liq_trap_risk = False
            return t
        t.liq_trap_risk = safe_div(t.liq, t.mc, 0) > 0.80
        return t

    def _bounce_potential(self, t: Token) -> Token:
        if t.age_hours < 24:
            t.bounce_potential = False; t.bounce_reason = ""
            return t
        signals, score = [], 0
        if t.chg24h < -30 and t.vol24h > 5000:
            signals.append(f"correction {t.chg24h:.0f}%"); score += 2
        if t.liq > 5000: signals.append(f"liq ${t.liq:,.0f}"); score += 1
        if t.has_twitter or t.has_telegram: signals.append("community"); score += 1
        if t.holder_count_rc > 100: signals.append(f"{t.holder_count_rc} holders"); score += 1
        if t.smart_money_present: signals.append(f"SM {t.smart_money_pct:.1f}%"); score += 2
        t.bounce_potential = score >= 3
        t.bounce_reason = " | ".join(signals)
        return t

    def _holder_health(self, t: Token) -> Token:
        score = 50
        if t.top10_pct > 0:
            if   t.top10_pct < 20: score += 25
            elif t.top10_pct < 35: score += 15
            elif t.top10_pct < 50: score += 5
            elif t.top10_pct < 65: score -= 10
            else:                   score -= 25
        cs = t.cluster_score
        if   cs < 20: score += 10
        elif cs < 40: score += 0
        elif cs < 60: score -= 10
        elif cs < 80: score -= 20
        else:          score -= 30
        if t.wash_trading_flag: score -= 20
        if   t.lp_burn >= 95: score += 15
        elif t.lp_burn >= 80: score += 8
        elif t.lp_burn == 0 and not t.is_bonding_curve: score -= 10
        elif 0 < t.lp_burn < 50: score -= 5
        if t.smart_money_present: score += 8
        if t.liq_trap_risk:       score -= 15
        if   t.risk_norm < 2: score += 10
        elif t.risk_norm < 4: score += 5
        elif t.risk_norm > 6: score -= 15
        # holder count
        hc = t.holder_count_helius if hasattr(t, 'holder_count_helius') else t.holder_count_rc
        if hc > 0:
            if   hc > 500: score += 10
            elif hc > 200: score += 5
            elif hc > 100: score += 2
            elif hc < 50 and t.age_hours >= 6: score -= 10
        if t.fee_health == "DANGER": score -= 20
        elif t.fee_health == "LOW":  score -= 8
        t.holder_health = max(0, min(100, score))
        return t

    def _apply_filters(self, t: Token) -> Token:
        cfg = self.cfg
        flags = 0
        detail = []

        def bad(step, note, val):
            nonlocal flags
            flags += 1
            detail.append(FilterDetail(step, False, str(val), note))

        def ok(step, val, note=""):
            detail.append(FilterDetail(step, True, str(val), note))

        def info(step, val, note=""):
            detail.append(FilterDetail(step, None, str(val), note))

        if t.is_rugged:
            bad("RUGGED", "Confirmed rugged", "RUGGED ⛔")
            t.flags, t.filter_details, t.verdict = flags, detail, "RUGGED"
            return t

        if t.wash_trading_flag:
            bad("Wash Trading", t.wash_trading_reason[:80], "ARTIFICIAL")

        if t.liq_trap_risk:
            bad("Liq Trap", f"Liq/MC {t.liq_mc_ratio:.1%} > 80% — rugpull setup", f"{t.liq_mc_ratio:.1%}")

        if t.cluster_risk == "CRITICAL":
            bad("Cluster CRITICAL", f"Score {t.cluster_score}/100 — {t.cluster_reason[:50]}", "CRITICAL ⛔")

        # Fee health — hanya DANGER yang jadi flag berat (1 flag)
        if t.fee_health == "DANGER":
            bad("Fee/Holder", t.fee_health_reason[:60], "DANGER")
        elif t.fee_health == "WARNING":
            info("Fee/Holder", t.fee_health_reason[:60], "WARNING")

        # S1 Authority
        if t.mint_auth:
            bad("S1 Mint Auth", "AKTIF — dev cetak token", "ACTIVE ⛔")
        elif t.freeze_auth:
            bad("S1 Freeze Auth", "AKTIF — honeypot", "ACTIVE ⛔")
        else:
            ok("S1 Authority", f"Revoked | LP {t.lp_burn:.0f}% burned", "Aman ✓")

        # S2 MC & Liq
        if t.mc <= 0:
            bad("S2 MC", "Data tidak tersedia", "N/A")
        elif t.mc < cfg.MIN_MC:
            bad("S2 MC", f"${t.mc:,.0f} < min ${cfg.MIN_MC:,.0f}", f"${t.mc:,.0f}")
        elif t.mc > cfg.MAX_MC:
            bad("S2 MC", f"${t.mc:,.0f} > max ${cfg.MAX_MC:,.0f}", f"${t.mc:,.0f}")
        elif t.is_bonding_curve:
            info("S2 Liq (Bonding Curve)", f"MC ${t.mc:,.0f} | Liq ~$0", "⚠ Masih di pump.fun")
        elif t.liq <= 0 and t.vol1h <= 0 and t.age_hours > 1.0:
            bad("S2 Liq (Idle)", f"MC ${t.mc:,.0f} Liq $0 Vol $0 — token idle/mati", "IDLE ⚠")
        elif t.liq < cfg.MIN_LIQ:
            bad("S2 Liq", f"${t.liq:,.0f} < min ${cfg.MIN_LIQ:,.0f}", f"${t.liq:,.0f}")
        else:
            r = t.liq_mc_ratio
            if r < 0.04:
                bad("S2 Liq/MC", f"{r:.1%} < 4%", f"{r:.1%}")
            else:
                ok("S2 MC & Liq", f"MC ${t.mc:,.0f} | Liq ${t.liq:,.0f} ({r:.1%})", "✓")

        # S3 Top10
        if t.top10_pct == 0:
            info("S3 Top10", f"N/A ({t.top10_source})", "Cek Solscan")
        elif t.top10_pct > 70:
            bad("S3 Top10", f"{t.top10_pct:.1f}% > 70% — CABAL/BUNDLE", f"{t.top10_pct:.1f}%")
        elif t.top10_pct > cfg.MAX_TOP10_PCT:
            bad("S3 Top10", f"{t.top10_pct:.1f}% > {cfg.MAX_TOP10_PCT}%", f"{t.top10_pct:.1f}%")
        else:
            ok("S3 Top10", f"{t.top10_pct:.1f}% ({t.top10_source})", "Sehat ✓")

        # S4 Risk & LP
        rn = t.risk_norm
        if rn > 7:
            bad("S4 Risk", f"{rn}/10 [{t.risk_label.upper()}] BAHAYA", f"{rn}/10 ⛔")
        elif rn > cfg.MAX_RISK_NORM:
            bad("S4 Risk", f"{rn}/10 > max {cfg.MAX_RISK_NORM}", f"{rn}/10")
        elif t.lp_burn == 0 and not t.is_bonding_curve:
            bad("S4 LP Burn", "0% — dev bisa cabut liq kapanpun", "0% ⚠")
        elif 0 < t.lp_burn < 80:
            bad("S4 LP Burn", f"{t.lp_burn:.0f}% < 80%", f"{t.lp_burn:.0f}%")
        else:
            ok("S4 Risk & LP", f"{rn}/10 [{t.risk_label}] | LP {t.lp_burn:.0f}%", "OK ✓")

        # S5 Cluster
        cs, cr = t.cluster_score, t.cluster_risk
        if cr == "HIGH":
            bad("S5 Cluster", f"Score {cs}/100 — {t.cluster_reason[:50]}", f"HIGH ({cs})")
        elif cr == "MEDIUM":
            info("S5 Cluster", f"Score {cs}/100", t.cluster_reason[:50])
        elif cr == "LOW":
            ok("S5 Cluster", f"Score {cs}/100", "Distribusi aman ✓")
        else:
            info("S5 Cluster", "UNKNOWN", "Data kurang")

        # S6 Dev Farm
        if t.dev_farm_risk == "HIGH":
            bad("S6 Dev Farm", t.dev_farm_reason[:55], "HIGH ⚠")
        elif t.dev_farm_risk == "MEDIUM":
            info("S6 Dev Farm", "MEDIUM", t.dev_farm_reason[:55])
        else:
            ok("S6 Dev Farm", "LOW", "Clean ✓")

        # Bonus
        soc = [s for s,b in [("TW",t.has_twitter),("TG",t.has_telegram),("Web",t.has_website)] if b]
        if soc: ok("Social", ", ".join(soc), "✓")
        else:   info("Social", "NONE", "Dev anonim")

        ms = t.momentum_score
        if   ms >= 75: ok("Momentum",   f"{ms}/100", f"Bullish — {t.chg1h:+.1f}%")
        elif ms >= 55: ok("Momentum",   f"{ms}/100", f"OK — {t.chg1h:+.1f}%")
        elif ms >= 35: info("Momentum",  f"{ms}/100", f"Neutral — {t.chg1h:+.1f}%")
        else:          info("Momentum",  f"{ms}/100", f"Bearish — {t.chg1h:+.1f}%")

        if t.smart_money_present:
            ok("Smart Money", f"{t.smart_money_pct:.1f}%", "GAKE hold ✓")

        total_tx = t.buys1h + t.sells1h
        if total_tx > 0:
            bsr = t.buy_sell_ratio
            label = f"{t.buys1h}B/{t.sells1h}S ({bsr:.0%})"
            if   bsr > 0.65: ok("Buy/Sell",   label, "Buy pressure ✓")
            elif bsr < 0.35: info("Buy/Sell",  label, "Sell dominan ⚠")
            else:             info("Buy/Sell",  label, "Balanced")

        tc = t.timing_score
        if   tc >= 70: ok("Timing",   f"{tc}/100", t.timing_reason)
        elif tc >= 40: info("Timing",  f"{tc}/100", t.timing_reason)
        else:           info("Timing", f"{tc}/100", f"⚠ {t.timing_reason}")

        if t.age_hours > 0:
            age = f"{t.age_hours*60:.0f}m" if t.age_hours < 1 else f"{t.age_hours:.1f}h"
            if   t.age_hours < 0.25: info("Age", age, "Very fresh <15m")
            elif t.age_hours < 1:    ok("Age",   age, "Fresh <1h ✓")
            elif t.age_hours <= 12:  ok("Age",   age, "Fresh ✓")
            elif t.bounce_potential: info("Age",  age, f"Old + bounce")
            else:                    info("Age",  age, "Old — cek thesis")

        # Holder count ditampilkan
        hc = t.holder_count_helius if hasattr(t, 'holder_count_helius') else t.holder_count_rc
        if hc > 0:
            if   hc > 500: ok("Holders",   f"{hc}", "Luas ✓")
            elif hc > 200: ok("Holders",   f"{hc}", "Cukup ✓")
            elif hc > 100: info("Holders", f"{hc}", "Moderate")
            elif hc > 50:  info("Holders", f"{hc}", "⚠ Sedikit")
            else:          info("Holders", f"{hc}", "⚠ Sangat sedikit")

        if   t.fee_health == "HEALTHY": ok("Fee Health",   "OK", "✓")
        elif t.fee_health == "LOW":     info("Fee Health",  "LOW", t.fee_health_reason[:50])

        hh = t.holder_health
        if   hh >= 75: ok("Hldr Health",   f"{hh}/100", "Sangat sehat ✓")
        elif hh >= 55: ok("Hldr Health",   f"{hh}/100", "Sehat ✓")
        elif hh >= 40: info("Hldr Health",  f"{hh}/100", "Moderate")
        else:           info("Hldr Health", f"{hh}/100", "Concern")

        t.flags = flags
        t.filter_details = detail
        if   flags == 0: t.verdict = "MASUK"
        elif flags == 1: t.verdict = "WATCH"
        else:             t.verdict = "SKIP"

        return t

    def _build_plan(self, t: Token) -> Token:
        cfg = self.cfg
        t.sizing_note = ""
        if t.flags >= 2 or t.verdict in ("RUGGED", "ERROR"):
            t.plan = {}
            t.sizing_note = "Jangan masuk."
            return t
        p = t.price
        if p <= 0:
            t.sizing_note = "Price tidak tersedia."
            return t
        if t.position_type == "LOWCAP":
            tp1, tp2, sl, dca1, dca2, max_p = 30, 50, 20, 20, 35, 0.10
        elif t.position_type == "MIDCAP":
            tp1, tp2, sl, dca1, dca2, max_p = 30, 70, 25, 20, 35, 0.20
        else:
            tp1, tp2, sl, dca1, dca2, max_p = 20, 50, 15, 15, 25, 0.25
        if t.flags == 1:
            max_p *= 0.5
        if t.cluster_risk == "MEDIUM":
            max_p *= 0.8
        elif t.cluster_risk == "HIGH":
            max_p *= 0.6
        t.plan = {
            "entry": p,
            "tp1":   p * (1 + tp1/100),
            "tp2":   p * (1 + tp2/100),
            "sl":    p * (1 - sl/100),
            "dca1":  p * (1 - dca1/100),
            "dca2":  p * (1 - dca2/100),
            "tp1_pct": tp1, "tp2_pct": tp2, "sl_pct": sl,
            "dca1_pct": dca1, "dca2_pct": dca2, "max_port": max_p,
        }
        t.sizing_note = f"{t.position_type}: max {max_p*100:.0f}% port"
        return t