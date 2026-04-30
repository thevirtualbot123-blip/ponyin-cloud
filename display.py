"""
display.py — PONYIN AI AGENT v3.4
Fixes:
  - print_signal now reads TP1/TP2/SL percentages from plan (not hardcoded 30/50/20)
  - add_pnl_section logic preserved.
"""
import logging
from datetime import datetime
from colorama import Fore, Style, Back

log = logging.getLogger("PONYIN.Display")
G=Fore.GREEN; Y=Fore.YELLOW; R=Fore.RED; B=Fore.BLUE; C=Fore.CYAN; D=Style.DIM; N=Style.RESET_ALL


class Display:

    def print_signal(self, token, decision, source: str):
        mint  = token.mint
        price = token.price
        mc    = token.mc
        liq   = token.liq
        ch1h  = token.chg1h
        ch5m  = token.chg5m
        hld   = token.holder_count_gmgn if token.holder_count_gmgn > 0 else token.holder_count_rc
        vol1h = token.vol1h
        risk  = token.risk_norm
        top10 = token.top10_pct
        lp_b  = token.lp_burn
        gmgn_lp = token.gmgn_lp_burned
        fl    = token.flags
        v     = token.verdict
        det   = token.filter_details or []
        plan  = token.plan or {}

        ch1h_s = f"{ch1h:+.1f}%" if ch1h != 0 else "n/a"
        ch5m_s = f"{ch5m:+.1f}%" if ch5m != 0 else "n/a"

        def p(k,v,c=""): print(f"  {c}{B}{k:<17}{N}{v}")

        # Title bar
        print()
        if "MASUK" in v:   title_color = G
        elif "WATCH" in v: title_color = Y
        else:              title_color = R
        print(f"{Back.BLACK}{title_color}{token.name} ({token.symbol}) [{token.position_type}]{N}")

        # Main
        p("Mint", mint[:24]+"...")
        p("Price", f"${price:,.8f}" if price else "N/A")
        p("MC / Liq", f"${mc:,.0f}  /  ${liq:,.0f}")
        p("Vol 1H", f"${vol1h:,.0f}")
        p("1H / 5M", f"{ch1h_s}  /  {ch5m_s}")
        if hld > 0:   p("Holders", str(hld))
        if top10 > 0: p("Top10", f"{top10:.1f}% ({token.top10_source})")
        p("Risk", f"{risk}/10 [{token.risk_label}]")
        if token.lp_burn >= 95 and gmgn_lp:
            p("LP Burn", f"100% (GMGN) ✓")
        else:
            p("LP Burn", f"{lp_b:.0f}% {'✓' if lp_b>=80 else '⚠'}")
        p("Verdict", f"{v}  |  {fl} flags")

        # Plan
        if plan:
            def fp(v):
                if v < 0.001: return f"${v:.8f}"
                return f"${v:.6f}"
            tp1_p = plan.get("tp1_pct", 30)
            tp2_p = plan.get("tp2_pct", 50)
            sl_p  = plan.get("sl_pct",  20)
            print(f"\n  {Y}📋 Plan:{N}")
            print(f"    Entry:     {fp(plan.get('entry'))}")
            print(f"    TP1 +{tp1_p:.0f}%:    {fp(plan.get('tp1'))} → jual 50%")
            print(f"    TP2 +{tp2_p:.0f}%:    {fp(plan.get('tp2'))} → jual 40%")
            print(f"    Moonbag:   10%")
            print(f"    SL  -{sl_p:.0f}%:     {fp(plan.get('sl'))}")

        # Decision
        print(f"\n  {Y}🧠 Decision:{N}  {decision.action} | {decision.confidence*100:.0f}% | "
              f"Conviction: {decision.conviction}")
        print(f"    Reason:    {decision.reason}")
        print(f"    Sizing:    {decision.sizing_note}")
        if decision.mode == "AI":
            print(f"    Mode:      {C}AI-powered{N}")
        else:
            print(f"    Mode:      {D}Rule-based (fast & free){N}")

        # Filter
        if det:
            print(f"\n  {Y}🚦 Filter Details:{N}")
            for d in det:
                if d.passed is True:
                    mark = G + "✓ " + N
                elif d.passed is False:
                    mark = R + "✗ " + N
                else:
                    mark = D + "i " + N
                if d.value and d.value != "None":
                    print(f"    {mark}{B}{d.step:<17}{N}{d.value:<20}  {D}{d.note}{N}")
                else:
                    print(f"    {mark}{B}{d.step:<17}{N}{D}{d.note}{N}")

        # Sizing
        if token.sizing_note:
            print(f"\n  {Y}📏 Sizing:{N}  {token.sizing_note}")
        if token.holder_health < 40:
            print(f"\n  {R}⚠️ Holder health {token.holder_health}/100 — moderate concern{N}")
        elif token.holder_health >= 75:
            print(f"\n  {G}✅ Holder health {token.holder_health}/100 — excellent{N}")
        else:
            print(f"\n  {D}Holder health {token.holder_health}/100{N}")

        print(f"\n  {D}═══════════════════════════════════════════════════════════════{N}")

    def add_pnl_section(self, signal_data: dict):
        if not signal_data: return
        mc  = signal_data.get("mc", 0)
        ent = signal_data.get("entry", 0)
        vol = signal_data.get("vol1h", 0)
        liq = signal_data.get("liq", 0)
        print(f"\n  {Y}💰 P&L Strategy:{N}")
        if liq > 0 and ent > 0:
            cap = ent * liq * 0.02
            print(f"    Cap: ${min(cap, 100):,.0f} | Liq/MC: {liq/mc:.1%} (auto)" if mc > 0 else "    N/A")
        if ent > 0 and vol > 0:
            slippage = "1-2%" if vol/liq > 1 else "0.5-1%" if liq > 0 else "?"
            print(f"    Slippage: {slippage}")
        if vol > 0 and mc > 0:
            vol_cap = min(vol*0.3, 500)
            print(f"    Vol Cap: ${vol_cap:,.0f}")
        print(f"\n  {D}(Disclaimer: non-financial, DYOR, NFA){N}")
