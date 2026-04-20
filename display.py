"""
display.py — Signal-only display. Clean, actionable, tidak cluttered.
"""
from datetime import datetime
from filter_engine import Token
from decision_engine import Decision

G="\033[92m"; RD="\033[91m"; Y="\033[93m"; C="\033[96m"
B="\033[1m";  D="\033[2m";   M="\033[95m"; R="\033[0m"

class Display:

    def fp(self, p: float) -> str:
        if p == 0: return "$0"
        if p < 0.00001: return f"${p:.10f}"
        if p < 0.001:   return f"${p:.8f}"
        if p < 1:       return f"${p:.6f}"
        return f"${p:.4f}"

    def fchg(self, c: float) -> str:
        return f"{G if c>=0 else RD}{c:+.1f}%{R}"

    def print_signal(self, t: Token, d: Decision, source: str):
        """Print signal lengkap — ini output utama agent"""

        # Verdict color
        if t.verdict == "MASUK":
            vc, vi = G, "✅"
        elif t.verdict == "WATCH":
            vc, vi = Y, "⚠️"
        else:
            vc, vi = RD, "❌"

        # Wash trading warning
        wash_warn = ""
        if t.wash_trading_flag:
            wash_warn = f"\n  {RD}{B}⚠ WASH TRADING DETECTED:{R} {t.wash_trading_reason[:80]}"

        sep = f"{vc}{'═'*66}{R}"
        print(f"\n{sep}")
        print(f"  {vi} {B}{vc}{t.verdict}{R}  {B}{t.name} (${t.symbol}){R}")
        print(f"  {D}{t.mint}{R}")
        if wash_warn:
            print(wash_warn)

        # Market data
        print(f"\n  {D}MARKET{R}")
        print(f"  Price : {self.fp(t.price)}  MC: ${t.mc:,.0f}  Liq: ${t.liq:,.0f}")
        print(f"  Vol1h : ${t.vol1h:,.0f}  Chg1h: {self.fchg(t.chg1h)}  Age: {t.age_hours:.1f}h")
        txn_str = f"{t.buys1h}B / {t.sells1h}S" if (t.buys1h or t.sells1h) else "N/A"
        print(f"  Txn1h : {txn_str}  DEX: {t.dex}")

        # On-chain
        rcolor = G if t.risk_norm<=3 else (Y if t.risk_norm<=6 else RD)
        top10_str = f"{t.top10_pct:.1f}% ({t.top10_source})" if t.top10_pct > 0 else f"{Y}N/A — cek Solscan{R}"
        lp_str    = f"{G}{t.lp_burn:.0f}%{R}" if t.lp_burn >= 80 else (f"{Y}{t.lp_burn:.0f}%{R}" if t.lp_burn > 0 else f"{Y}N/A{R}")
        mint_str  = f"{RD}ACTIVE ⛔{R}" if t.mint_auth else f"{G}Revoked{R}"
        soc = []
        if t.has_twitter:  soc.append("TW")
        if t.has_telegram: soc.append("TG")
        if t.has_website:  soc.append("Web")
        soc_str = f"{G}{', '.join(soc)}{R}" if soc else f"{Y}None{R}"

        print(f"\n  {D}ON-CHAIN{R}")
        print(f"  Risk  : {rcolor}{t.risk_norm}/10 [{t.risk_label}]{R}  LP: {lp_str}  Mint: {mint_str}")
        print(f"  Top10 : {top10_str}")
        print(f"  Social: {soc_str}")

        # RugCheck risks (hanya danger/warn)
        bad_risks = [(lvl,nm) for (lvl,nm,d2,v) in t.rc_risks if lvl in ("danger","warn")]
        if bad_risks:
            print(f"\n  {D}RISKS{R}")
            for lvl, nm in bad_risks[:3]:
                icon = f"{RD}⛔{R}" if lvl=="danger" else f"{Y}⚠{R}"
                print(f"  {icon} {nm}")

        # Filter details
        print(f"\n  {D}FILTER ({t.flags} flag{'s' if t.flags!=1 else ''}){R}")
        for det in t.filter_details:
            if det.passed is True:    icon = f"{G}✓{R}"
            elif det.passed is False: icon = f"{RD}✗{R}"
            else:                     icon = f"{Y}i{R}"
            print(f"  {icon} {det.step}: {det.value}")
            if det.passed is False:
                print(f"    {RD}→ {det.note}{R}")

        # Decision
        mode_str = f"{C}[AI]{R}" if d.mode == "AI" else f"{D}[Rule]{R}"
        act_c = G if d.action=="ENTER" else (Y if d.action=="WATCH" else RD)
        print(f"\n  {mode_str} {act_c}{B}{d.action}{R} [{d.conviction}] conf:{d.confidence:.0%}")
        print(f"  {D}{d.reason}{R}")

        # Trading plan — HANYA jika MASUK/WATCH
        if d.action in ("ENTER", "WATCH") and t.plan:
            pl = t.plan
            print(f"\n  {C}TRADING PLAN (eksekusi MANUAL){R}")
            print(f"  Entry  : {self.fp(pl['entry'])}")
            print(f"  {G}TP1 +30%: {self.fp(pl['tp1'])} → jual 50% posisi{R}")
            print(f"  {G}TP2 +50%: {self.fp(pl['tp2'])} → jual 40% posisi{R}")
            print(f"  {Y}Moonbag : sisa 10%{R}")
            print(f"  {RD}SL  -20%: {self.fp(pl['sl'])} → cut loss{R}")
            print(f"  DCA #1  : {self.fp(pl['dca1'])} (-20%) jika on-chain valid")
            if d.sizing_note:
                print(f"  Sizing  : {D}{d.sizing_note}{R}")

        # Links
        print(f"\n  {D}🔗 https://dexscreener.com/solana/{t.mint}")
        print(f"     https://rugcheck.xyz/tokens/{t.mint}{R}")
        print(sep)

        # Extra warning jika SKIP karena wash trading
        if t.wash_trading_flag and t.verdict != "MASUK":
            print(f"{RD}{B}  ⚠ MANIPULASI TERDETEKSI — JANGAN ENTRY{R}")
            print(f"  {D}Volume tidak organik. Lihat txn count vs volume.{R}\n")
