"""
filter_engine.py — PONYIN AI AGENT v4.0
=========================================
Kalibrasi mendalam berdasarkan backtest nyata:

  $SIF    → seharusnya MASUK (false positive wash + LP wallet)
  $DNUT   → WATCH benar
  $PVE    → WATCH benar (cluster terbukti drop)
  $TERMINAL → seharusnya MASUK (Cluster HIGH terlalu agresif, 38% top10 OK)
  $ToStar → WATCH benar (lalu rug)

Perbaikan v4:
  1. Cluster detection di-redesign: scoring berbasis poin, bukan binary
  2. Wash trading: hanya flag jika BENAR-BENAR artificial (bukan organic frenzy)
  3. LP wallet exclusion dari Top10 lebih akurat
  4. Holder count sebagai signal kesehatan
  5. Momentum score: chg positif = bullish signal
  6. Composite scoring sebelum verdict final
"""

import re
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
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
    # Advanced signals
    wash_trading_flag: bool = False
    wash_trading_reason: str = ""
    cluster_risk: str = "UNKNOWN"
    cluster_reason: str = ""
    cluster_score: int = 0          # 0-100, makin rendah makin baik
    dev_farm_risk: str = "UNKNOWN"
    dev_farm_reason: str = ""
    smart_money_present: bool = False
    smart_money_pct: float = 0.0
    timing_score: int = 0
    timing_reason: str = ""
    bounce_potential: bool = False
    bounce_reason: str = ""
    liq_trap_risk: bool = False
    holder_health: int = 50
    holder_count: int = 0           # dari DexScreener/channel
    momentum_score: int = 50        # 0-100 berdasarkan chg & volume
    position_type: str = "LOWCAP"
    flags: int = 0
    verdict: str = "PENDING"
    filter_details: list = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    sizing_note: str = ""

    @property
    def buy_sell_ratio(self) -> float:
        total = self.buys1h + self.sells1h
        return self.buys1h / total if total > 0 else 0.5

    @property
    def liq_mc_ratio(self) -> float:
        return self.liq / self.mc if self.mc > 0 else 0.0

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
            "timing_score": self.timing_score, "timing_reason": self.timing_reason,
            "holder_health": self.holder_health,
            "holder_count": self.holder_count,
            "momentum_score": self.momentum_score,
            "bounce_potential": self.bounce_potential,
            "liq_trap_risk": self.liq_trap_risk,
            "plan": self.plan, "sizing_note": self.sizing_note,
            "age_hours": self.age_hours, "dex": self.dex,
            "buys1h": self.buys1h, "sells1h": self.sells1h,
            "holder_count_rc": self.holder_count_rc,
        }


@dataclass
class FilterDetail:
    step: str
    passed: bool    # True=ok, False=bad, None=info
    value: str
    note: str


class FilterEngine:

    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg

    def run(self, t: Token) -> Token:
        try:
            t = self._classify(t)
            t = self._clean_top10(t)
            t = self._detect_wash_trading(t)
            t = self._detect_cluster_v4(t)
            t = self._detect_dev_farm(t)
            t = self._detect_smart_money(t)
            t = self._timing_score(t)
            t = self._momentum_score(t)
            t = self._liq_trap(t)
            t = self._bounce_potential(t)
            t = self._holder_health(t)
            t = self._apply_filters(t)
            t = self._build_plan(t)
        except Exception as e:
            import logging
            logging.getLogger("PONYIN.Filter").error(
                f"Filter error {t.mint[:12]}: {e}", exc_info=True
            )
            t.verdict     = "ERROR"
            t.flags       = 99
            t.sizing_note = "Error saat filter — cek manual"
        return t

    # ── Classify position type ────────────────────────────
    def _classify(self, t: Token) -> Token:
        if   t.mc < 100_000:   t.position_type = "LOWCAP"
        elif t.mc < 2_000_000: t.position_type = "MIDCAP"
        else:                   t.position_type = "HIGHCAP"
        return t

    # ── Clean Top10: exclude LP/bonding curve wallet ──────
    def _clean_top10(self, t: Token) -> Token:
        """
        Fix $SIF false positive: RugCheck memasukkan LP wallet ke topHolders.
        LP wallet biasanya pct > 20% dan bukan personal wallet (tidak ada insider flag).
        Setelah exclude: $SIF 65.9% → ~25% (sesuai data channel).
        """
        if not t.top_holders:
            return t

        raw = []
        for h in t.top_holders[:20]:
            pct = float(h.get("pct", 0) or 0)
            if 0 < pct <= 1.0:
                pct *= 100
            raw.append((pct, h))

        if not raw:
            return t

        # Detect LP wallet: pct sangat tinggi tanpa insider flag
        # LP pool di early stage biasanya hold > 15% supply
        cleaned   = []
        lp_found  = False
        for pct, h in raw:
            is_insider = h.get("insider", False)
            # Threshold 15%: wallet non-insider dengan > 15% = likely LP
            if pct > 15.0 and not is_insider:
                lp_found = True
                continue  # exclude
            cleaned.append(pct)

        if lp_found and cleaned:
            top10_new = round(sum(sorted(cleaned, reverse=True)[:10]), 1)
            # Hanya update jika perbedaan signifikan (>15 poin)
            if t.top10_pct > 0 and (t.top10_pct - top10_new) > 15:
                t.top10_pct    = top10_new
                t.top10_source = "RugCheck (LP excluded)"

        return t

    # ── Wash trading v4 — hanya flag yang BENAR-BENAR artificial ──
    def _detect_wash_trading(self, t: Token) -> Token:
        """
        v4 Calibration dari kasus nyata:

        $SIF: Vol $107K, MC $30K, 169 holders, 236B/20S → ORGANIK
          Vol/MC 3.3x tinggi tapi ada ratusan buyers = frenzy beli, bukan wash.

        $TERMINAL: Vol $221K, MC $87K, chg +153% → ORGANIK
          Ini runner yang lagi pump, bukan wash.

        Wash trading SESUNGGUHNYA:
          - Volume tinggi tapi TXN sangat sedikit (< 15 txn)
          - Atau zero txn tapi ada volume
          - Atau vol > 20x liq (physically impossible)

        BUKAN wash trading:
          - Token fresh dengan banyak buyers (>50 txn) = organic frenzy
          - Token pump organik (chg > 50% dengan txn banyak)
        """
        reasons    = []
        total_txn  = t.buys1h + t.sells1h
        has_many   = total_txn >= 50  # banyak txn = organik

        # Rule 1: Volume ada tapi ZERO txn = pasti artificial
        if t.vol1h > 1000 and total_txn == 0:
            reasons.append(f"vol ${t.vol1h:,.0f} dengan 0 txn — artificial pasti")

        # Rule 2: Rata-rata tx sangat besar DAN txn sangat sedikit
        # Hanya flag jika txn < 15 (bukan 30 — terlalu sensitif)
        elif t.vol1h > 5000 and 0 < total_txn < 15:
            avg = t.vol1h / total_txn
            if avg > 2000:  # avg > $2000/tx = suspicious untuk lowcap
                reasons.append(
                    f"avg tx ${avg:,.0f} dengan hanya {total_txn} txn — "
                    f"bukan pola retail organik"
                )

        # Rule 3: Vol > 20x liq = secara fisik tidak mungkin organik
        if t.liq > 0 and t.vol1h > t.liq * 20:
            reasons.append(
                f"vol ${t.vol1h:,.0f} = {t.vol1h/t.liq:.0f}x liq — physically impossible"
            )

        # Rule 4: Vol/MC ekstrem (> 8x) DAN txn sedikit DAN bukan pump organik
        # $SIF Vol/MC 3.3x dengan 236 txn = NOT triggered
        # $TERMINAL Vol/MC 2.5x dengan banyak txn = NOT triggered
        if t.mc > 0 and t.vol1h > 0 and not has_many:
            vol_mc = t.vol1h / t.mc
            if vol_mc > 8.0 and total_txn < 20:
                reasons.append(
                    f"Vol/MC {vol_mc:.1f}x (${t.vol1h:,.0f}/${t.mc:,.0f}) "
                    f"dengan {total_txn} txn — extreme"
                )

        t.wash_trading_flag   = len(reasons) > 0
        t.wash_trading_reason = " | ".join(reasons) if reasons else ""
        return t

    # ── Cluster detection v4 — scoring-based, bukan binary ────
    def _detect_cluster_v4(self, t: Token) -> Token:
        """
        v4: Sistem scoring 0-100 untuk cluster risk.
        Masalah v3: semua token dapat Cluster HIGH padahal karakternya beda.

        $TERMINAL: Top10 38.3%, 0 insiders, distribusi normal → LOW/MEDIUM
        $ToStar  : Top10 11.1%, 0 insiders tapi tetap rug → perlu lihat faktor lain
        $PVE     : Top10 11.59%, Cluster HIGH → drop benar

        Pelajaran: uniform distribution check terlalu sensitif.
        Top10 rendah bukan berarti aman jika ada invisible concentration.

        Score system:
          0-30   = LOW (aman)
          31-55  = MEDIUM (perlu perhatian)
          56-79  = HIGH (1 flag)
          80-100 = CRITICAL (langsung 2 flag)
        """
        if not t.top_holders:
            t.cluster_risk   = "UNKNOWN"
            t.cluster_reason = "Data tidak tersedia"
            t.cluster_score  = 50  # neutral
            return t

        holders = t.top_holders[:20]
        pcts, insider_count, insider_pct = [], 0, 0.0
        for h in holders:
            pct = float(h.get("pct", 0) or 0)
            if 0 < pct <= 1.0:
                pct *= 100
            pcts.append(pct)
            if h.get("insider", False):
                insider_count += 1
                insider_pct   += pct

        score   = 0
        reasons = []

        # Factor 1: Insider wallets (dari RugCheck — ini verified)
        if insider_count >= 6:
            score += 40
            reasons.append(f"{insider_count} insider wallets ({insider_pct:.1f}%)")
        elif insider_count >= 3:
            score += 25
            reasons.append(f"{insider_count} insiders ({insider_pct:.1f}%)")
        elif insider_count >= 1:
            score += 12
            reasons.append(f"{insider_count} insider wallet")

        # Factor 2: Top10 concentration (setelah LP exclusion)
        top10_total = sum(pcts[:10])
        if top10_total > 75:
            score += 45; reasons.append(f"top10 {top10_total:.0f}% (extreme)")
        elif top10_total > 65:
            score += 30; reasons.append(f"top10 {top10_total:.0f}% (tinggi)")
        elif top10_total > 50:
            score += 15; reasons.append(f"top10 {top10_total:.0f}% (moderate)")
        elif top10_total > 0:
            score += 0   # < 50% = fine

        # Factor 3: Single whale dominan
        max_single = max(pcts[:10]) if pcts else 0
        if max_single > 30:
            score += 25; reasons.append(f"whale {max_single:.1f}% (1 holder)")
        elif max_single > 20:
            score += 15; reasons.append(f"single holder {max_single:.1f}%")
        elif max_single > 15:
            score += 5

        # Factor 4: Semua holder sama persis (uniform = satu entitas banyak wallet)
        # Hanya flag jika benar-benar identik, bukan sekadar dekat
        if len(pcts) >= 8:
            valid = [p for p in pcts[:10] if p > 0.5]
            if len(valid) >= 6:
                max_p, min_p = max(valid), min(valid)
                # Range < 0.5% dengan banyak holder = suspicious
                if (max_p - min_p) < 0.5 and min_p > 1.5:
                    score += 20
                    reasons.append(
                        f"uniform ({min_p:.1f}%-{max_p:.1f}%) — "
                        f"kemungkinan 1 entitas"
                    )

        # Clamp score
        score = min(100, max(0, score))
        t.cluster_score = score

        if score >= 80:
            t.cluster_risk = "CRITICAL"
        elif score >= 56:
            t.cluster_risk = "HIGH"
        elif score >= 31:
            t.cluster_risk = "MEDIUM"
        else:
            t.cluster_risk = "LOW"

        t.cluster_reason = (
            " | ".join(reasons) if reasons
            else f"Score {score}/100 — distribusi normal"
        )
        return t

    # ── Dev farm detection ────────────────────────────────
    def _detect_dev_farm(self, t: Token) -> Token:
        reasons = []
        risk    = "LOW"

        if t.lp_burn == 0:
            reasons.append("LP tidak di-burn (0%) — dev bisa tarik liq kapanpun")
            risk = "HIGH"
        elif t.lp_burn < 50:
            reasons.append(f"LP burn {t.lp_burn:.0f}% — kurang dari 50%")
            risk = "MEDIUM"

        if t.mint_auth:
            reasons.append("Mint authority AKTIF — dev bisa cetak token")
            risk = "HIGH"

        if t.risk_norm > 6:
            reasons.append(f"RugCheck risk {t.risk_norm}/10 tinggi")
            if risk == "LOW": risk = "MEDIUM"

        dev_kws = ["dev", "creator", "deployer", "farm", "bundle",
                   "sniper", "insider", "early buyer"]
        for (lvl, name, desc, val) in t.rc_risks:
            if any(k in (name+desc).lower() for k in dev_kws):
                reasons.append(f"[{lvl}] {name}")
                if lvl == "danger":               risk = "HIGH"
                elif lvl == "warn" and risk=="LOW": risk = "MEDIUM"

        t.dev_farm_risk   = risk
        t.dev_farm_reason = " | ".join(reasons) if reasons else "Tidak ada sinyal"
        return t

    # ── Smart money ───────────────────────────────────────
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
        t.smart_money_pct     = round(total, 1)
        return t

    # ── Timing score ──────────────────────────────────────
    def _timing_score(self, t: Token) -> Token:
        hour = datetime.utcnow().hour
        dow  = datetime.utcnow().weekday()
        wp   = -15 if dow >= 5 else 0
        if   20 <= hour or hour < 2:  base, r = 90, "US prime time (20-02 UTC)"
        elif 13 <= hour < 20:          base, r = 75, "EU/US overlap (13-20 UTC)"
        elif 10 <= hour < 13:          base, r = 65, "EU peak (10-13 UTC)"
        elif 6  <= hour < 10:          base, r = 55, "EU morning (06-10 UTC)"
        elif 2  <= hour < 6:           base, r = 20, "Dead hours (02-06 UTC)"
        else:                           base, r = 40, f"Hour {hour} UTC"
        t.timing_score  = max(0, min(100, base + wp))
        t.timing_reason = r + (" (weekend)" if dow >= 5 else "")
        return t

    # ── Momentum score (NEW v4) ───────────────────────────
    def _momentum_score(self, t: Token) -> Token:
        """
        Momentum berdasarkan price action dan volume.
        $TERMINAL: chg +153%, Vol $221K → momentum sangat tinggi
        $ToStar: chg -4.9% → momentum negatif

        Score 0-100:
          0-30  = bearish (pertimbangkan skip)
          31-60 = neutral
          61-80 = bullish (good entry)
          81-100 = very bullish (runner aktif)
        """
        score = 50  # neutral base

        # Price change 1h
        c1 = t.chg1h
        if   c1 >  100: score += 30
        elif c1 >   50: score += 20
        elif c1 >   20: score += 12
        elif c1 >    5: score += 6
        elif c1 >    0: score += 2
        elif c1 >  -10: score -= 3
        elif c1 >  -20: score -= 10
        else:            score -= 20

        # Buy/sell ratio
        bsr = t.buy_sell_ratio
        if   bsr > 0.75: score += 15
        elif bsr > 0.60: score += 8
        elif bsr > 0.45: score += 2
        elif bsr < 0.30: score -= 10
        elif bsr < 0.40: score -= 5

        # Volume vs liquidity (organic volume = bullish)
        if t.liq > 0 and t.vol1h > 0:
            vl = t.vol1h / t.liq
            if   vl > 3.0: score += 10
            elif vl > 1.0: score += 5
            elif vl > 0.3: score += 2

        t.momentum_score = max(0, min(100, score))
        return t

    # ── Liq trap ──────────────────────────────────────────
    def _liq_trap(self, t: Token) -> Token:
        if t.mc <= 0 or t.liq <= 0:
            t.liq_trap_risk = False
            return t
        ratio = t.liq / t.mc
        # Liq > 80% MC = suspicious rugpull setup
        t.liq_trap_risk = ratio > 0.80
        return t

    # ── Bounce potential ──────────────────────────────────
    def _bounce_potential(self, t: Token) -> Token:
        if t.age_hours < 24:
            t.bounce_potential = False
            t.bounce_reason    = ""
            return t
        signals, score = [], 0
        if t.chg24h < -30 and t.vol24h > 5000:
            signals.append(f"correction {t.chg24h:.0f}% + vol ${t.vol24h:,.0f}")
            score += 2
        if t.liq > 5000:      signals.append(f"liq ${t.liq:,.0f}"); score += 1
        if t.has_twitter or t.has_telegram: signals.append("community"); score += 1
        if t.holder_count_rc > 100: signals.append(f"{t.holder_count_rc} holders"); score += 1
        if t.smart_money_present: signals.append(f"SM {t.smart_money_pct:.1f}%"); score += 2
        t.bounce_potential = score >= 3
        t.bounce_reason    = " | ".join(signals)
        return t

    # ── Holder health score ───────────────────────────────
    def _holder_health(self, t: Token) -> Token:
        score = 50
        if t.top10_pct > 0:
            if   t.top10_pct < 20: score += 25
            elif t.top10_pct < 35: score += 15
            elif t.top10_pct < 50: score += 5
            elif t.top10_pct < 65: score -= 10
            else:                   score -= 25
        # Cluster score (0-100, lower=better)
        cs = t.cluster_score
        if   cs < 20: score += 10
        elif cs < 40: score += 0
        elif cs < 60: score -= 10
        elif cs < 80: score -= 20
        else:          score -= 30
        if t.wash_trading_flag: score -= 20
        if   t.lp_burn >= 95: score += 15
        elif t.lp_burn >= 80: score += 8
        elif t.lp_burn == 0:  score -= 10
        elif t.lp_burn < 50:  score -= 5
        if t.smart_money_present: score += 8
        if t.liq_trap_risk:       score -= 15
        if   t.risk_norm < 2: score += 10
        elif t.risk_norm < 4: score += 5
        elif t.risk_norm > 6: score -= 15
        # Bonus: holder count (banyak holder = distribusi lebih sehat)
        hc = t.holder_count_rc
        if   hc > 500: score += 10
        elif hc > 200: score += 5
        elif hc > 100: score += 2
        elif 0 < hc < 50: score -= 10
        t.holder_health = max(0, min(100, score))
        return t

    # ── Apply filters (v4 calibrated) ────────────────────
    def _apply_filters(self, t: Token) -> Token:
        cfg   = self.cfg
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

        # ── INSTANT DISQUALIFIER ──────────────────────────
        if t.is_rugged:
            bad("RUGGED", "Confirmed rugged", "RUGGED ⛔")
            t.flags, t.filter_details, t.verdict = flags, detail, "RUGGED"
            return t

        # Wash trading (hanya jika benar-benar artificial)
        if t.wash_trading_flag:
            bad("Wash Trading", t.wash_trading_reason[:80], "ARTIFICIAL")

        # Liq trap
        if t.liq_trap_risk:
            ratio = t.liq_mc_ratio
            bad("Liq Trap", f"Liq/MC {ratio:.1%} > 80% — rugpull setup", f"{ratio:.1%}")

        # Cluster CRITICAL saja yang jadi hard flag
        # HIGH hanya jadi 1 flag (WATCH), bukan langsung SKIP
        if t.cluster_risk == "CRITICAL":
            bad("Cluster CRITICAL",
                f"Score {t.cluster_score}/100 — {t.cluster_reason[:60]}",
                "CRITICAL ⛔")

        # ── S1: Authority ─────────────────────────────────
        if t.mint_auth:
            bad("S1 Mint Auth", "AKTIF → dev cetak token kapanpun → dilusi", "ACTIVE ⛔")
        elif t.freeze_auth:
            bad("S1 Freeze Auth", "AKTIF → bisa freeze holder → honeypot", "ACTIVE ⛔")
        else:
            danger = [n for (lvl,n,d,v) in t.rc_risks
                      if lvl=="danger" and any(k in n.lower()
                      for k in ["bundle","honeypot","sniper"])]
            if danger:
                bad("S1 Bundle/HP", f"RugCheck: {danger[0]}", "DANGER ⛔")
            else:
                lp = f"{t.lp_burn:.0f}% burned" if t.lp_burn > 0 else "N/A"
                ok("S1 Authority", f"Revoked | LP {lp}", "Aman dari dilusi ✓")

        # ── S2: MC & Liquidity ────────────────────────────
        if t.mc <= 0:
            bad("S2 MC", "Data tidak tersedia", "N/A")
        elif t.mc < cfg.MIN_MC:
            bad("S2 MC", f"${t.mc:,.0f} < min ${cfg.MIN_MC:,.0f}", f"${t.mc:,.0f}")
        elif t.mc > cfg.MAX_MC:
            bad("S2 MC", f"${t.mc:,.0f} > max ${cfg.MAX_MC:,.0f}", f"${t.mc:,.0f}")
        elif t.liq < cfg.MIN_LIQ:
            bad("S2 Liq", f"${t.liq:,.0f} < min ${cfg.MIN_LIQ:,.0f} → exit tipis",
                f"${t.liq:,.0f}")
        else:
            r = t.liq_mc_ratio
            if r < 0.04:
                bad("S2 Liq/MC", f"{r:.1%} < 4% → dump risk", f"{r:.1%}")
            else:
                ok("S2 MC & Liq",
                   f"MC ${t.mc:,.0f} | Liq ${t.liq:,.0f} ({r:.1%})",
                   "Range valid ✓")

        # ── S3: Top10 Holder ──────────────────────────────
        if t.top10_pct == 0:
            info("S3 Top10", f"N/A ({t.top10_source})", "Cek Solscan manual")
        elif t.top10_pct > 70:
            bad("S3 Top10",
                f"{t.top10_pct:.1f}% > 70% → CABAL/BUNDLE → dump risk",
                f"{t.top10_pct:.1f}%")
        elif t.top10_pct > cfg.MAX_TOP10_PCT:
            bad("S3 Top10",
                f"{t.top10_pct:.1f}% > {cfg.MAX_TOP10_PCT}%",
                f"{t.top10_pct:.1f}%")
        else:
            ok("S3 Top10",
               f"{t.top10_pct:.1f}% ({t.top10_source})",
               "Distribusi sehat ✓")

        # ── S4: Risk & LP ─────────────────────────────────
        rn = t.risk_norm
        if rn > 7:
            bad("S4 Risk", f"{rn}/10 [{t.risk_label.upper()}] — BAHAYA", f"{rn}/10 ⛔")
        elif rn > cfg.MAX_RISK_NORM:
            bad("S4 Risk", f"{rn}/10 > max {cfg.MAX_RISK_NORM}", f"{rn}/10")
        elif t.lp_burn == 0:
            bad("S4 LP Burn",
                "0% — dev belum burn LP, bisa tarik liq kapanpun",
                "0% ⚠")
        elif 0 < t.lp_burn < 80:
            bad("S4 LP Burn", f"{t.lp_burn:.0f}% < 80% minimum", f"{t.lp_burn:.0f}%")
        else:
            lp = f"{t.lp_burn:.0f}%" if t.lp_burn > 0 else "N/A"
            ok("S4 Risk & LP",
               f"Risk {rn}/10 [{t.risk_label}] | LP {lp}",
               "Acceptable ✓")

        # ── S5: Cluster (v4 — HIGH = 1 flag, CRITICAL = hard stop di atas) ──
        cs = t.cluster_score
        cr = t.cluster_risk
        if cr == "HIGH":
            bad("S5 Cluster",
                f"Score {cs}/100 — {t.cluster_reason[:60]}",
                f"HIGH ({cs}/100)")
        elif cr == "MEDIUM":
            info("S5 Cluster",
                 f"Score {cs}/100",
                 t.cluster_reason[:60])
        elif cr == "LOW":
            ok("S5 Cluster",
               f"Score {cs}/100",
               "Distribusi aman ✓")
        else:
            info("S5 Cluster", "UNKNOWN", "Data tidak cukup")

        # ── S6: Dev Farm ──────────────────────────────────
        if t.dev_farm_risk == "HIGH":
            bad("S6 Dev Farm",
                t.dev_farm_reason[:60],
                "HIGH RISK ⚠")
        elif t.dev_farm_risk == "MEDIUM":
            info("S6 Dev Farm", "MEDIUM", t.dev_farm_reason[:60])
        else:
            ok("S6 Dev Farm", "LOW", "Tidak ada sinyal dev farm ✓")

        # ── BONUS: Socials ────────────────────────────────
        soc = [s for s,b in [("TW",t.has_twitter),("TG",t.has_telegram),
                               ("Web",t.has_website)] if b]
        if soc: ok("Social", ", ".join(soc), "Social presence ✓")
        else:   info("Social", "NONE", "Dev anonim — extra hati-hati")

        # ── BONUS: Momentum (v4 NEW) ──────────────────────
        ms = t.momentum_score
        if   ms >= 75: ok("Momentum",  f"{ms}/100", f"Bullish kuat — chg {t.chg1h:+.1f}%")
        elif ms >= 55: ok("Momentum",  f"{ms}/100", f"Bullish — chg {t.chg1h:+.1f}%")
        elif ms >= 35: info("Momentum", f"{ms}/100", f"Neutral — chg {t.chg1h:+.1f}%")
        else:          info("Momentum", f"{ms}/100", f"Bearish — chg {t.chg1h:+.1f}%")

        # ── BONUS: Smart money ────────────────────────────
        if t.smart_money_present:
            ok("Smart Money",
               f"{t.smart_money_pct:.1f}% non-insider",
               "GAKE masih hold ✓")

        # ── BONUS: Buy/Sell ratio ─────────────────────────
        total_tx = t.buys1h + t.sells1h
        if total_tx > 0:
            bsr = t.buy_sell_ratio
            label = f"{t.buys1h}B/{t.sells1h}S ({bsr:.0%})"
            if   bsr > 0.65: ok("Buy/Sell",   label, "Buying pressure ✓")
            elif bsr < 0.35: info("Buy/Sell",  label, "Sell dominan ⚠")
            else:             info("Buy/Sell",  label, "Balanced")

        # ── BONUS: Timing ─────────────────────────────────
        tc = t.timing_score
        if   tc >= 70: ok("Timing",   f"{tc}/100", t.timing_reason)
        elif tc >= 40: info("Timing",  f"{tc}/100", t.timing_reason)
        else:           info("Timing", f"{tc}/100", f"⚠ {t.timing_reason}")

        # ── BONUS: Age ────────────────────────────────────
        if t.age_hours > 0:
            age = (f"{t.age_hours*60:.0f}m" if t.age_hours < 1
                   else f"{t.age_hours:.1f}h")
            if   t.age_hours < 0.25: info("Age", age, "Very fresh (<15m) — extra hati-hati")
            elif t.age_hours < 1:    ok("Age",   age, "Fresh <1h ✓")
            elif t.age_hours <= 12:  ok("Age",   age, "Fresh ✓")
            elif t.bounce_potential:  info("Age", age, f"Old + bounce: {t.bounce_reason[:30]}")
            else:                     info("Age", age, "Old — cek thesis valid")

        # ── BONUS: Holder count (v4 NEW) ─────────────────
        hc = t.holder_count_rc
        if hc > 0:
            if   hc > 500:
                ok("Holders",   f"{hc} wallets", "Distribusi luas ✓")
            elif hc > 200:
                ok("Holders",   f"{hc} wallets", "Cukup tersebar ✓")
            elif hc > 100:
                info("Holders", f"{hc} wallets", "Moderate")
            elif hc > 50:
                info("Holders", f"{hc} wallets",
                     "⚠ Sedikit — konsentrasi mungkin lebih tinggi dari kelihatannya")
            else:
                info("Holders", f"{hc} wallets",
                     "⚠ Sangat sedikit (<50) — high risk exit liquidity tipis")

        # ── BONUS: Holder health ──────────────────────────
        hh = t.holder_health
        if   hh >= 75: ok("Holder Health",   f"{hh}/100", "Sangat sehat ✓")
        elif hh >= 55: ok("Holder Health",   f"{hh}/100", "Sehat ✓")
        elif hh >= 40: info("Holder Health",  f"{hh}/100", "Moderate")
        else:           info("Holder Health", f"{hh}/100", "Concern — lihat detail")

        # ── VERDICT ───────────────────────────────────────
        t.flags          = flags
        t.filter_details = detail

        if   flags == 0: t.verdict = "MASUK"
        elif flags == 1: t.verdict = "WATCH"
        else:             t.verdict = "SKIP"

        return t

    # ── Build plan + sizing (Sambelikan method) ───────────
    def _build_plan(self, t: Token) -> Token:
        cfg = self.cfg
        t.sizing_note = ""

        if t.flags >= 2 or t.verdict in ("RUGGED", "ERROR"):
            t.plan        = {}
            t.sizing_note = "Jangan masuk."
            return t

        p = t.price
        if p <= 0:
            t.sizing_note = "Price tidak tersedia."
            return t

        # Parameter berdasarkan position type (Sambelikan)
        if t.position_type == "LOWCAP":
            tp1, tp2, sl, dca1, dca2, max_p = 30, 50, 20, 20, 35, 0.10
            note = (f"LOWCAP: max {max_p*100:.0f}% portfolio "
                    f"(~{cfg.PORTFOLIO_SOL*max_p:.3f} SOL). "
                    f"Exit cepat di TP1, jangan greedy.")
        elif t.position_type == "MIDCAP":
            tp1, tp2, sl, dca1, dca2, max_p = 30, 70, 25, 20, 35, 0.20
            note = (f"MIDCAP: max {max_p*100:.0f}% portfolio "
                    f"(~{cfg.PORTFOLIO_SOL*max_p:.3f} SOL). "
                    f"Hold lebih lama dari lowcap.")
        else:
            tp1, tp2, sl, dca1, dca2, max_p = 20, 50, 15, 15, 25, 0.25
            note = (f"HIGHCAP: max {max_p*100:.0f}% portfolio "
                    f"(~{cfg.PORTFOLIO_SOL*max_p:.3f} SOL). "
                    f"TA lebih relevan.")

        # Adjust jika ada 1 flag (WATCH)
        if t.flags == 1:
            max_p = round(max_p * 0.5, 3)
            note  = f"1 flag → half size. {note}"

        # Adjust berdasarkan cluster
        if t.cluster_risk == "MEDIUM":
            max_p = round(max_p * 0.8, 3)
        if t.cluster_risk == "HIGH":
            max_p = round(max_p * 0.6, 3)

        # Timing warning
        if t.timing_score < 40:
            note += " ⚠ Timing kurang optimal — pertimbangkan tunggu."

        # Momentum boost
        if t.momentum_score >= 75 and t.flags == 0:
            note += " 🚀 Momentum kuat — bisa entry lebih besar dalam batas max."

        t.plan = {
            "entry": p,
            "tp1":   p * (1 + tp1  / 100),
            "tp2":   p * (1 + tp2  / 100),
            "sl":    p * (1 - sl   / 100),
            "dca1":  p * (1 - dca1 / 100),
            "dca2":  p * (1 - dca2 / 100),
            "tp1_pct": tp1, "tp2_pct": tp2, "sl_pct": sl,
            "dca1_pct": dca1, "dca2_pct": dca2, "max_port": max_p,
        }
        t.sizing_note = note
        return t
