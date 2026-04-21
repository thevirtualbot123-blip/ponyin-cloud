"""
filter_engine.py — PONYIN AI AGENT v3.2
=========================================
Perbaikan kalibrasi berdasarkan kasus nyata:
  - $SIF: wash trading false positive → threshold lebih cerdas
  - $SIF: Top10 RugCheck memasukkan LP wallet → filter LP wallet
  - $ALAN: LP burn 0 tidak ter-flag → sekarang ter-flag
  - Bot notify SKIP singkat dari channel signal
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
    # Advanced
    wash_trading_flag: bool = False
    wash_trading_reason: str = ""
    cluster_risk: str = "UNKNOWN"
    cluster_reason: str = ""
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
            "has_website": self.has_website, "flags": self.flags,
            "verdict": self.verdict, "position_type": self.position_type,
            "wash_trading_flag": self.wash_trading_flag,
            "wash_trading_reason": self.wash_trading_reason,
            "cluster_risk": self.cluster_risk,
            "dev_farm_risk": self.dev_farm_risk,
            "smart_money_present": self.smart_money_present,
            "smart_money_pct": self.smart_money_pct,
            "timing_score": self.timing_score, "timing_reason": self.timing_reason,
            "holder_health": self.holder_health,
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
    passed: bool
    value: str
    note: str


class FilterEngine:

    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg

    def run(self, t: Token) -> Token:
        try:
            t = self._classify(t)
            t = self._clean_top10(t)        # FIX: exclude LP wallet dulu
            t = self._detect_wash_trading(t)
            t = self._detect_cluster(t)
            t = self._detect_dev_farm(t)
            t = self._detect_smart_money(t)
            t = self._timing_score(t)
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
            t.sizing_note = "Error saat filter — skip"
        return t

    # ── Classify ──────────────────────────────────────────
    def _classify(self, t: Token) -> Token:
        if   t.mc < 100_000:   t.position_type = "LOWCAP"
        elif t.mc < 2_000_000: t.position_type = "MIDCAP"
        else:                   t.position_type = "HIGHCAP"
        return t

    # ── FIX: Clean Top10 — exclude LP/bonding curve wallet ──
    def _clean_top10(self, t: Token) -> Token:
        """
        RugCheck kadang memasukkan wallet LP (liquidity pool) atau
        bonding curve ke dalam topHolders, yang membuat top10% kelihatan
        jauh lebih tinggi dari kenyataan.

        Kasus $SIF: RugCheck bilang 65.9%, channel signal bilang 25%.
        Perbedaan ini karena RugCheck menghitung LP wallet sebagai holder.

        Cara detect LP wallet di topHolders:
        - Holder dengan pct sangat tinggi (>20%) dan merupakan program/pool
        - Atau ada di rc_risks dengan label "bonding curve" / "liquidity"
        - RugCheck biasanya tandai ini dengan field khusus

        Jika tidak bisa distinguish, kita gunakan top10 yang lebih rendah
        antara: nilai asli vs nilai tanpa outlier tertinggi (jika >20%).
        """
        if not t.top_holders:
            return t

        holders  = t.top_holders[:20]
        raw_pcts = []
        for h in holders:
            pct = float(h.get("pct", 0) or 0)
            if 0 < pct <= 1.0:
                pct *= 100
            raw_pcts.append((pct, h))

        if not raw_pcts:
            return t

        # Deteksi LP wallet: pct sangat tinggi (>15%) dan bukan insider normal
        # Biasanya LP wallet hold token > 20% supply di early stage
        cleaned_pcts = []
        lp_wallet_detected = False
        for pct, h in raw_pcts:
            addr    = (h.get("address") or "").lower()
            insider = h.get("insider", False)
            # LP/pool address sering dikenali RugCheck, atau pct sangat tinggi
            # tanpa insider flag (bukan wallet personal)
            if pct > 20 and not insider:
                # Kemungkinan LP wallet atau bonding curve
                lp_wallet_detected = True
                continue
            cleaned_pcts.append(pct)

        if lp_wallet_detected and cleaned_pcts:
            # Pakai top 10 dari cleaned list
            top10_clean = sum(sorted(cleaned_pcts, reverse=True)[:10])
            if top10_clean < t.top10_pct * 0.7:
                # Perbedaan signifikan → pakai yang cleaned
                t.top10_pct    = round(top10_clean, 1)
                t.top10_source = f"RugCheck (LP excluded)"

        return t

    # ── FIX: Wash trading — lebih cerdas ──────────────────
    def _detect_wash_trading(self, t: Token) -> Token:
        """
        Wash trading detection yang lebih cerdas.

        Pelajaran dari $SIF:
        - Token fresh (<2h) dengan banyak buyers organik wajar punya
          Vol/MC tinggi → ini BUKAN wash trading
        - Wash trading = volume ARTIFICIAL: banyak volume tapi sedikit txn,
          atau avg tx size tidak masuk akal untuk retail

        Rules baru:
        1. Vol/MC > 5x DAN avg tx > $1000 → suspicious (bukan 3x)
        2. Vol ada tapi txn = 0 → pasti artificial
        3. Vol > 10x liq → impossible secara fisik
        4. Pump >100% dalam <30 menit DAN txn < 10 → manipulasi
        5. Token fresh + banyak txn organik = TIDAK wash trading
        """
        reasons     = []
        total_txn   = t.buys1h + t.sells1h
        is_fresh    = t.age_hours < 2.0
        has_organic = total_txn > 50  # banyak txn = organik

        # Rule 1: Vol ada tapi 0 txn = jelas artificial
        if t.vol1h > 500 and total_txn == 0:
            reasons.append(f"vol ${t.vol1h:,.0f} tapi 0 txn — artificial")

        # Rule 2: Avg tx terlalu besar (bukan retail)
        # Hanya flag jika txn sedikit (<30) dan volume besar
        if t.vol1h > 10000 and total_txn > 0 and total_txn < 30:
            avg_tx = t.vol1h / total_txn
            if avg_tx > 1000:
                reasons.append(
                    f"vol ${t.vol1h:,.0f} dengan {total_txn} txn "
                    f"(avg ${avg_tx:,.0f}/tx) — txn count mencurigakan"
                )

        # Rule 3: Vol > 10x liq = secara fisik tidak mungkin organik
        if t.liq > 0 and t.vol1h > t.liq * 10:
            reasons.append(
                f"vol ${t.vol1h:,.0f} = {t.vol1h/t.liq:.0f}x liq "
                f"(${t.liq:,.0f}) — impossible"
            )

        # Rule 4: Vol/MC sangat ekstrem (>5x) dengan txn sedikit
        # Jangan flag jika token fresh dengan banyak txn organik
        if t.mc > 0 and t.vol1h > 0:
            vol_mc = t.vol1h / t.mc
            if vol_mc > 5.0 and total_txn < 30:
                reasons.append(
                    f"Vol/MC {vol_mc:.1f}x (${t.vol1h:,.0f}/${t.mc:,.0f}) "
                    f"dengan {total_txn} txn — suspicious"
                )
            # Jika fresh + banyak txn: ini normal buying frenzy, bukan wash
            # $SIF case: Vol/MC 3.3x tapi ada 236 buys = organik

        # Rule 5: Pump besar sangat cepat dengan sedikit txn
        if t.chg1h > 100 and total_txn < 10 and t.mc > 20000:
            reasons.append(
                f"pump {t.chg1h:+.0f}% dengan {total_txn} txn saja — "
                f"pump tidak organik"
            )

        t.wash_trading_flag   = len(reasons) > 0
        t.wash_trading_reason = " | ".join(reasons) if reasons else ""
        return t

    # ── Cluster detection ─────────────────────────────────
    def _detect_cluster(self, t: Token) -> Token:
        if not t.top_holders:
            t.cluster_risk   = "UNKNOWN"
            t.cluster_reason = "Data tidak tersedia"
            return t

        holders = t.top_holders[:20]
        pcts, insider_count = [], 0
        for h in holders:
            pct = float(h.get("pct", 0) or 0)
            if 0 < pct <= 1.0: pct *= 100
            pcts.append(pct)
            if h.get("insider", False): insider_count += 1

        reasons = []
        risk    = "LOW"

        if insider_count >= 3:
            reasons.append(f"{insider_count} insider wallets")
            risk = "HIGH"
        elif insider_count >= 1:
            reasons.append(f"{insider_count} insider wallet")
            risk = "MEDIUM"

        if len(pcts) >= 5:
            valid_pcts = [p for p in pcts[:10] if p > 0]
            if valid_pcts:
                avg  = sum(valid_pcts) / len(valid_pcts)
                devs = [abs(p - avg) for p in valid_pcts]
                if devs and sum(devs)/len(devs) < 0.3 and avg > 1.0:
                    reasons.append("distribusi terlalu uniform — 1 entitas banyak wallet")
                    risk = "HIGH"

        top10_total = sum(pcts[:10])
        if top10_total > 70:
            reasons.append(f"top10 total {top10_total:.1f}% — extreme")
            risk = "CRITICAL"
        elif top10_total > 55:
            reasons.append(f"top10 {top10_total:.1f}%")
            if risk == "LOW": risk = "MEDIUM"

        max_single = max(pcts[:10]) if pcts else 0
        if max_single > 20:
            reasons.append(f"single holder {max_single:.1f}%")
            risk = "HIGH"

        t.cluster_risk   = risk
        t.cluster_reason = " | ".join(reasons) if reasons else "Distribusi normal"
        return t

    # ── Dev farm detection ────────────────────────────────
    def _detect_dev_farm(self, t: Token) -> Token:
        reasons = []
        risk    = "LOW"

        # FIX: LP burn 0 sekarang ter-flag (kasus $ALAN)
        if t.lp_burn == 0:
            reasons.append("LP tidak di-burn sama sekali — dev bisa cabut liq kapanpun")
            risk = "HIGH"
        elif t.lp_burn < 50:
            reasons.append(f"LP burn {t.lp_burn:.0f}% saja")
            risk = "MEDIUM"

        if t.mint_auth:
            reasons.append("Mint authority aktif")
            risk = "HIGH"

        if t.risk_norm > 6:
            reasons.append(f"RugCheck risk {t.risk_norm}/10")
            if risk == "LOW": risk = "MEDIUM"

        dev_kws = ["dev", "creator", "deployer", "farm", "bundle", "sniper"]
        for (lvl, name, desc, val) in t.rc_risks:
            if any(k in name.lower() or k in desc.lower() for k in dev_kws):
                reasons.append(f"[{lvl}] {name}")
                if lvl == "danger":             risk = "HIGH"
                elif lvl == "warn" and risk == "LOW": risk = "MEDIUM"

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
        if 20 <= hour or hour < 2:   base, r = 90, "US prime time (20:00-02:00 UTC)"
        elif 13 <= hour < 20:         base, r = 75, "EU/US overlap (13:00-20:00 UTC)"
        elif 10 <= hour < 13:         base, r = 65, "EU peak (10:00-13:00 UTC)"
        elif 6  <= hour < 10:         base, r = 55, "EU morning (06:00-10:00 UTC)"
        elif 2  <= hour < 6:          base, r = 20, "Dead hours (02:00-06:00 UTC)"
        else:                          base, r = 40, f"Hour {hour} UTC"
        t.timing_score  = max(0, min(100, base + wp))
        t.timing_reason = r + (" (weekend)" if dow >= 5 else "")
        return t

    # ── Liq trap ──────────────────────────────────────────
    def _liq_trap(self, t: Token) -> Token:
        if t.mc <= 0 or t.liq <= 0:
            t.liq_trap_risk = False
            return t
        ratio = t.liq / t.mc
        t.liq_trap_risk = ratio > 0.8 or (ratio < 0.02 and t.mc > 50000)
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
        if t.liq > 5000:
            signals.append(f"liq ${t.liq:,.0f} ada"); score += 1
        if t.has_twitter or t.has_telegram:
            signals.append("community aktif"); score += 1
        if t.holder_count_rc > 100:
            signals.append(f"{t.holder_count_rc} holders"); score += 1
        if t.smart_money_present:
            signals.append(f"smart money {t.smart_money_pct:.1f}%"); score += 2
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
        score += {"LOW":10,"MEDIUM":0,"HIGH":-15,"CRITICAL":-30}.get(t.cluster_risk, 0)
        if t.wash_trading_flag: score -= 20
        if   t.lp_burn >= 95: score += 15
        elif t.lp_burn >= 80: score += 8
        elif 0 < t.lp_burn < 50: score -= 10
        elif t.lp_burn == 0: score -= 5   # FIX: lp_burn=0 juga kurangi skor
        if t.smart_money_present: score += 10
        if t.liq_trap_risk:       score -= 15
        if   t.risk_norm < 2: score += 10
        elif t.risk_norm < 4: score += 5
        elif t.risk_norm > 6: score -= 15
        t.holder_health = max(0, min(100, score))
        return t

    # ── Apply filters ─────────────────────────────────────
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

        if t.is_rugged:
            bad("RUGGED", "Confirmed rugged", "RUGGED")
            t.flags, t.filter_details, t.verdict = flags, detail, "RUGGED"
            return t

        if t.wash_trading_flag:
            bad("Wash Trading", t.wash_trading_reason[:80], "SUSPICIOUS")

        if t.cluster_risk == "CRITICAL":
            bad("Cluster CRITICAL", t.cluster_reason[:70], "CRITICAL")

        if t.liq_trap_risk:
            ratio = t.liq_mc_ratio
            bad("Liq Trap", f"Ratio {ratio:.1%}", f"{ratio:.1%}")

        # S1 Authority
        if t.mint_auth:
            bad("S1 Mint Auth", "AKTIF → dev cetak token → dilusi", "ACTIVE")
        elif t.freeze_auth:
            bad("S1 Freeze Auth", "AKTIF → honeypot", "ACTIVE")
        else:
            danger = [n for (lvl,n,d,v) in t.rc_risks
                      if lvl=="danger" and any(k in n.lower()
                      for k in ["bundle","honeypot","sniper"])]
            if danger:
                bad("S1 Bundle/HP", danger[0], "DANGER")
            else:
                lp = f"{t.lp_burn:.0f}% burned" if t.lp_burn > 0 else "N/A"
                ok("S1 Authority", f"Revoked | LP {lp}", "Aman")

        # S2 MC & Liq
        if t.mc <= 0:
            bad("S2 MC", "Tidak ada data", "N/A")
        elif t.mc < cfg.MIN_MC:
            bad("S2 MC", f"${t.mc:,.0f} < min ${cfg.MIN_MC:,.0f}", f"${t.mc:,.0f}")
        elif t.mc > cfg.MAX_MC:
            bad("S2 MC", f"${t.mc:,.0f} > max ${cfg.MAX_MC:,.0f}", f"${t.mc:,.0f}")
        elif t.liq < cfg.MIN_LIQ:
            bad("S2 Liq", f"${t.liq:,.0f} < min ${cfg.MIN_LIQ:,.0f}", f"${t.liq:,.0f}")
        else:
            r = t.liq_mc_ratio
            if r < 0.04:
                bad("S2 Liq/MC", f"{r:.1%} < 4%", f"{r:.1%}")
            else:
                ok("S2 MC & Liq", f"MC ${t.mc:,.0f} | Liq ${t.liq:,.0f}", f"{r:.1%}")

        # S3 Top10
        if t.top10_pct == 0:
            info("S3 Top10", f"N/A ({t.top10_source})", "Cek Solscan")
        elif t.top10_pct > 70:
            bad("S3 Top10", f"{t.top10_pct:.1f}% > 70% → CABAL/BUNDLE", f"{t.top10_pct:.1f}%")
        elif t.top10_pct > cfg.MAX_TOP10_PCT:
            bad("S3 Top10", f"{t.top10_pct:.1f}% > {cfg.MAX_TOP10_PCT}%", f"{t.top10_pct:.1f}%")
        else:
            ok("S3 Top10", f"{t.top10_pct:.1f}% ({t.top10_source})", "Sehat")

        # S4 Risk & LP
        rn = t.risk_norm
        if rn > 7:
            bad("S4 Risk", f"{rn}/10 [{t.risk_label.upper()}] — BAHAYA", f"{rn}/10")
        elif rn > cfg.MAX_RISK_NORM:
            bad("S4 Risk", f"{rn}/10 > max {cfg.MAX_RISK_NORM}", f"{rn}/10")
        elif t.lp_burn == 0:
            # FIX: LP 0 = flag (kasus $ALAN — LP tidak di-burn)
            bad("S4 LP Burn",
                "LP tidak di-burn (0%) — dev bisa tarik liq kapanpun",
                "0%")
        elif 0 < t.lp_burn < 80:
            bad("S4 LP Burn", f"{t.lp_burn:.0f}% < 80%", f"{t.lp_burn:.0f}%")
        else:
            lp = f"{t.lp_burn:.0f}%" if t.lp_burn > 0 else "N/A"
            ok("S4 Risk & LP", f"{rn}/10 [{t.risk_label}] | LP {lp}", "OK")

        # S5 Cluster
        if t.cluster_risk == "HIGH":
            bad("S5 Cluster", t.cluster_reason[:60], "HIGH RISK")
        elif t.cluster_risk == "MEDIUM":
            info("S5 Cluster", "MEDIUM", t.cluster_reason[:60])
        else:
            ok("S5 Cluster", t.cluster_risk, "OK")

        # S6 Dev Farm
        if t.dev_farm_risk == "HIGH":
            bad("S6 Dev Farm", t.dev_farm_reason[:60], "HIGH RISK")
        elif t.dev_farm_risk == "MEDIUM":
            info("S6 Dev Farm", "MEDIUM", t.dev_farm_reason[:60])
        else:
            ok("S6 Dev Farm", "LOW", "OK")

        # Bonus
        soc = [s for s, b in [("TW",t.has_twitter),("TG",t.has_telegram),("Web",t.has_website)] if b]
        if soc: ok("Social", ", ".join(soc))
        else:   info("Social", "NONE", "Dev anonim")

        if t.smart_money_present:
            ok("Smart Money", f"{t.smart_money_pct:.1f}% non-insider", "GAKE ada ✓")

        total_tx = t.buys1h + t.sells1h
        if total_tx > 0:
            bsr = t.buy_sell_ratio
            label = f"{t.buys1h}B/{t.sells1h}S ({bsr:.0%})"
            if   bsr > 0.65:  ok("Buy/Sell",   label, "Buying pressure ✓")
            elif bsr < 0.35:  info("Buy/Sell",  label, "Sell dominan")
            else:              info("Buy/Sell",  label, "Balanced")

        tc = t.timing_score
        if   tc >= 70: ok("Timing",   f"{tc}/100", t.timing_reason)
        elif tc >= 40: info("Timing",  f"{tc}/100", t.timing_reason)
        else:           info("Timing", f"{tc}/100", t.timing_reason)

        if t.age_hours > 0:
            age = f"{t.age_hours:.1f}h"
            if   t.age_hours < 1:   ok("Age",   age, "Very fresh ✓")
            elif t.age_hours <= 12: ok("Age",   age, "Fresh ✓")
            elif t.bounce_potential: info("Age", age, f"Old + bounce: {t.bounce_reason[:30]}")
            else:                    info("Age", age, "Old — cek thesis")

        hh = t.holder_health
        if   hh >= 70: ok("Health",   f"{hh}/100", "Sehat")
        elif hh >= 50: info("Health",  f"{hh}/100", "Moderate")
        else:           info("Health", f"{hh}/100", "Concern")

        t.flags          = flags
        t.filter_details = detail

        if   flags == 0: t.verdict = "MASUK"
        elif flags == 1: t.verdict = "WATCH"
        else:             t.verdict = "SKIP"

        return t

    # ── Build plan + sizing ───────────────────────────────
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

        if t.position_type == "LOWCAP":
            tp1, tp2, sl, dca1, dca2, max_p = 30, 50, 20, 20, 35, 0.10
            note = f"LOWCAP: max {max_p*100:.0f}% portfolio (~{cfg.PORTFOLIO_SOL*max_p:.3f} SOL). Exit cepat di TP1."
        elif t.position_type == "MIDCAP":
            tp1, tp2, sl, dca1, dca2, max_p = 30, 70, 25, 20, 35, 0.20
            note = f"MIDCAP: max {max_p*100:.0f}% portfolio (~{cfg.PORTFOLIO_SOL*max_p:.3f} SOL). Hold lebih lama dari lowcap."
        else:
            tp1, tp2, sl, dca1, dca2, max_p = 20, 50, 15, 15, 25, 0.25
            note = f"HIGHCAP: max {max_p*100:.0f}% portfolio (~{cfg.PORTFOLIO_SOL*max_p:.3f} SOL). TA lebih relevan."

        if t.flags == 1:    max_p = round(max_p * 0.5, 3); note = f"1 flag → half size. {note}"
        if t.cluster_risk == "MEDIUM": max_p = round(max_p * 0.7, 3)
        if t.timing_score < 40: note += " ⚠ Timing kurang optimal."

        t.plan = {
            "entry": p, "tp1": p*(1+tp1/100), "tp2": p*(1+tp2/100),
            "sl": p*(1-sl/100), "dca1": p*(1-dca1/100), "dca2": p*(1-dca2/100),
            "tp1_pct": tp1, "tp2_pct": tp2, "sl_pct": sl,
            "dca1_pct": dca1, "dca2_pct": dca2, "max_port": max_p,
        }
        t.sizing_note = note
        return t
