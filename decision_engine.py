"""
decision_engine.py — Rule-based Decision Engine (No AI Credits Needed).

v2: Pure rule-based, tidak butuh Anthropic API.
AI mode disabled by default — hemat credits, akurat berdasarkan data.

Jika ANTHROPIC_API_KEY diset, AI akan dipakai HANYA untuk token
yang benar-benar lolos filter (0 flags) untuk reasoning tambahan.
Ini menghemat credits secara drastis.
"""
import json, logging, aiohttp
from dataclasses import dataclass
from typing import Optional
from filter_engine import Token
from config import AgentConfig

log = logging.getLogger("PONYIN.Decision")

@dataclass
class Decision:
    action: str          # "ENTER" | "WATCH" | "SKIP"
    confidence: float    # 0.0–1.0
    reason: str
    conviction: str      # "HIGH" | "MEDIUM" | "LOW"
    sizing_note: str     # catatan sizing untuk user
    entry_plan: str      # ringkasan entry plan
    mode: str            # "RULE" atau "AI"


class DecisionEngine:

    # System prompt ringkas — hemat tokens jika AI dipakai
    AI_PROMPT = """Kamu PONYIN AI. Analisis token Solana ini dan berikan keputusan singkat.
Rules: 0 flag = bisa masuk, 1 flag = watch kecil, 2+ = skip.
Mint auth active = SKIP MUTLAK. Wash trading = SKIP.
Output HANYA JSON: {"action":"ENTER"|"WATCH"|"SKIP","conviction":"HIGH"|"MEDIUM"|"LOW","reason":"1 kalimat","sizing":"catatan sizing"}"""

    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg
        # Disable AI jika tidak ada key
        self._ai_available = bool(cfg.AI_ENABLED)
        self._ai_failed    = False  # flag jika credits habis

    async def decide(self, token: Token, source: str, raw: str) -> Decision:
        """
        Decision engine. Rule-based by default.
        AI hanya dipakai jika: key ada, credits ok, token lolos (0 flags).
        """
        # Pakai AI HANYA untuk token yang lolos filter sempurna (0 flags)
        # dan AI tersedia dan belum pernah gagal credits
        if (self._ai_available and not self._ai_failed
                and token.flags == 0 and not token.wash_trading_flag):
            try:
                return await self._ai_decide(token)
            except Exception as e:
                err = str(e)
                if "credit" in err.lower() or "billing" in err.lower():
                    self._ai_failed = True
                    log.warning("AI credits habis — switch ke rule-based permanen")
                else:
                    log.debug(f"AI fallback: {e}")

        return self._rule_decide(token)

    async def _ai_decide(self, token: Token) -> Decision:
        """Minimal AI call — hanya untuk token 0 flag, hemat tokens"""
        top10 = f"{token.top10_pct:.1f}%" if token.top10_pct > 0 else "N/A"
        prompt = (
            f"Token: {token.name} ${token.symbol}\n"
            f"MC: ${token.mc:,.0f} | Liq: ${token.liq:,.0f}\n"
            f"Vol1h: ${token.vol1h:,.0f} | Chg1h: {token.chg1h:+.1f}%\n"
            f"Top10: {top10} | Risk: {token.risk_norm}/10 | LP: {token.lp_burn:.0f}%\n"
            f"Mint auth: {token.mint_auth or 'revoked'} | Age: {token.age_hours:.1f}h\n"
            f"Buys: {token.buys1h} Sells: {token.sells1h}\n"
            f"Filter flags: {token.flags} | Wash trading: {token.wash_trading_flag}"
        )

        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.cfg.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": "claude-haiku-4-5",
                    "max_tokens": 200,  # sangat hemat
                    "system": self.AI_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json(content_type=None)

        if data.get("error"):
            raise Exception(data["error"]["message"])

        text = "".join(b.get("text","") for b in (data.get("content") or []))
        # Extract JSON
        import re
        m = re.search(r'\{.*?\}', text, re.DOTALL)
        if not m:
            raise Exception("No JSON in response")

        r = json.loads(m.group())
        action = r.get("action", "SKIP")
        # Safety override
        if token.flags >= 2: action = "SKIP"

        return Decision(
            action=action,
            confidence=0.8 if action == "ENTER" else 0.6,
            reason=r.get("reason", "AI decision"),
            conviction=r.get("conviction", "MEDIUM"),
            sizing_note=r.get("sizing", "Sesuaikan conviction"),
            entry_plan=self._build_plan(token),
            mode="AI"
        )

    def _rule_decide(self, token: Token) -> Decision:
        """
        Pure rule-based — akurat, gratis, tidak perlu API.
        Berdasarkan ELPonyin + Spyzer rules secara eksplisit.
        """
        flags = token.flags
        wash  = token.wash_trading_flag

        # ── SKIP conditions ───────────────────────────────
        if flags >= 2 or wash:
            reasons = []
            if flags >= 2:
                reasons.append(f"{flags} red flags")
            if wash:
                reasons.append(f"wash trading: {token.wash_trading_reason[:60]}")
            return Decision(
                action="SKIP", confidence=0.95,
                reason=" + ".join(reasons),
                conviction="LOW", sizing_note="Jangan masuk",
                entry_plan="", mode="RULE"
            )

        # ── WATCH conditions (1 flag) ─────────────────────
        if flags == 1:
            flag_desc = token.filter_details[0].step if token.filter_details else "1 concern"
            for d in token.filter_details:
                if d.passed is False:
                    flag_desc = d.step
                    break
            return Decision(
                action="WATCH", confidence=0.6,
                reason=f"1 red flag ({flag_desc}) — observe dulu",
                conviction="LOW",
                sizing_note=f"Jika masuk: max {self.cfg.SIZE_LOW*100:.0f}% portfolio, TP1 = exit semua",
                entry_plan=self._build_plan(token),
                mode="RULE"
            )

        # ── 0 flags — evaluate conviction ─────────────────
        high, med, concern = [], [], []
        bsr = token.buy_sell_ratio

        if token.age_hours < 1:    high.append("very fresh (<1h)")
        elif token.age_hours < 4:  high.append(f"fresh ({token.age_hours:.1f}h)")

        if bsr > 0.65:    high.append(f"buying pressure {bsr:.0%}")
        elif bsr < 0.35 and bsr > 0: concern.append(f"sell pressure {bsr:.0%}")

        if token.top10_pct > 0 and token.top10_pct < 30:
            high.append(f"distribusi bagus ({token.top10_pct:.0f}%)")
        elif token.top10_pct > 45:
            concern.append(f"top10 tinggi ({token.top10_pct:.0f}%)")

        if token.lp_burn >= 95:   high.append("LP fully burned")
        elif token.lp_burn >= 80: med.append(f"LP {token.lp_burn:.0f}%")

        if token.risk_norm < 2:   high.append(f"risk sangat rendah ({token.risk_norm}/10)")
        elif token.risk_norm < 4: med.append(f"risk {token.risk_norm}/10")
        else:                     concern.append(f"risk {token.risk_norm}/10")

        if not token.has_twitter:  concern.append("no Twitter")
        if token.age_hours > 24:   concern.append(f"old ({token.age_hours:.0f}h)")

        if token.vol1h > token.liq * 0.3:
            high.append(f"volume/liq ok ({token.vol1h/token.liq:.1f}x)")

        # Score
        score = len(high)*2 + len(med) - len(concern)*1.5

        if score >= 4:
            conviction, sizing_pct, action = "HIGH", self.cfg.SIZE_HIGH, "ENTER"
            conf = min(0.88, 0.65 + score * 0.04)
        elif score >= 1:
            conviction, sizing_pct, action = "MEDIUM", self.cfg.SIZE_MEDIUM, "ENTER"
            conf = min(0.72, 0.50 + score * 0.04)
        else:
            conviction, sizing_pct, action = "LOW", self.cfg.SIZE_LOW, "WATCH"
            conf = 0.40

        positives = ", ".join(high + med) or "filter passed"
        concerns  = ", ".join(concern)  or "none"
        reason    = f"[{conviction}] {positives}"
        if concerns != "none":
            reason += f" | concerns: {concerns}"

        sizing = (
            f"{sizing_pct*100:.0f}% portfolio "
            f"(~{self.cfg.PORTFOLIO_SOL * sizing_pct:.3f} SOL) "
            f"— sesuaikan conviction kamu"
        )

        return Decision(
            action=action, confidence=conf, reason=reason,
            conviction=conviction, sizing_note=sizing,
            entry_plan=self._build_plan(token),
            mode="RULE"
        )

    def _build_plan(self, token: Token) -> str:
        if not token.plan or token.price <= 0:
            return ""
        p = token.plan
        cfg = self.cfg
        def fp(v):
            if v < 0.001: return f"${v:.8f}"
            return f"${v:.6f}"
        return (
            f"Entry: {fp(p['entry'])} | "
            f"TP1 +{cfg.TP1_PCT:.0f}%: {fp(p['tp1'])} → jual 50% | "
            f"TP2 +{cfg.TP2_PCT:.0f}%: {fp(p['tp2'])} → jual 40% | "
            f"Moonbag: 10% | "
            f"SL -{cfg.SL_PCT:.0f}%: {fp(p['sl'])}"
        )
