#!/usr/bin/env python3
"""Generate a comprehensive HTML report for Momentum Quality Rotation (MQR).

Includes the FULL trade ledger (every buy and sell with P&L), equity curve,
exit analysis, and strategy details. Also runs the A/B comparison against
Sector Top-5 Momentum + PEGY on the same rolling windows.

Usage:
  cd backend && ./venv/bin/python ../strategies/momentum_quality_report.py
"""

import os
import sys
import json
import warnings
import statistics
from datetime import datetime

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "sarina00")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5431")
os.environ.setdefault("DB_NAME", "sp1500_1d")

from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.strategies.momentum_quality_rotation import MomentumQualityRotation
from app.services.strategies.sector_top5_pegy import SectorTop5MomentumPEGY

AS_OF = "2021-01-01"
END = "2025-12-31"
CAPITAL = 100_000.0

REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "reports")
os.makedirs(REPORT_DIR, exist_ok=True)


def _fmt_money(v):
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_pct(v):
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return str(v)


def _color(v):
    try:
        return "#10b981" if float(v) >= 0 else "#ef4444"
    except (TypeError, ValueError):
        return "#94a3b8"


def build_trade_table(trades):
    """Build HTML rows for the full trade ledger (buys + sells)."""
    rows = []
    for t in trades:
        side = t.get("side", "")
        ticker = t.get("ticker", "")
        entry = t.get("entry_date", "")
        exit_d = t.get("exit_date", "")
        entry_p = t.get("entry_price", 0)
        exit_p = t.get("exit_price", 0)
        ret = t.get("return_pct", 0)
        pnl = t.get("pnl_dollars", 0)
        hold = t.get("holding_days", 0)
        reason = t.get("exit_reason", "")
        side_cls = "buy" if side == "BUY" else "sell"
        side_label = "BUY" if side == "BUY" else "SELL"
        rows.append(f"""<tr class="{side_cls}">
            <td>{ticker}</td>
            <td>{side_label}</td>
            <td>{entry}</td>
            <td>{exit_d}</td>
            <td>{_fmt_money(entry_p)}</td>
            <td>{_fmt_money(exit_p)}</td>
            <td>{hold}</td>
            <td style="color:{_color(ret)}">{_fmt_pct(ret)}</td>
            <td style="color:{_color(pnl)}">{_fmt_money(pnl)}</td>
            <td>{reason}</td>
        </tr>""")
    return "\n".join(rows)


def build_equity_svg(daily_equity):
    """Build an inline SVG equity curve."""
    if not daily_equity:
        return "<p>No equity data</p>"
    vals = [d["value"] for d in daily_equity]
    dates = [d["date"] for d in daily_equity]
    W, H = 1000, 300
    pad = 40
    vmin, vmax = min(vals), max(vals)
    rng = (vmax - vmin) or 1
    pts = []
    for i, v in enumerate(vals):
        x = pad + (i / max(len(vals) - 1, 1)) * (W - 2 * pad)
        y = H - pad - ((v - vmin) / rng) * (H - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(pts)
    # baseline (start value)
    y0 = H - pad - ((vals[0] - vmin) / rng) * (H - 2 * pad)
    return f"""<svg viewBox="0 0 {W} {H}" width="100%" style="background:#0f172a;border-radius:8px">
        <line x1="{pad}" y1="{y0:.1f}" x2="{W-pad}" y2="{y0:.1f}" stroke="#334155" stroke-dasharray="4,4"/>
        <polyline points="{polyline}" fill="none" stroke="#10b981" stroke-width="2"/>
        <text x="{pad}" y="{H-pad+20}" fill="#64748b" font-size="11">{dates[0]}</text>
        <text x="{W-pad-70}" y="{H-pad+20}" fill="#64748b" font-size="11">{dates[-1]}</text>
        <text x="{pad}" y="20" fill="#94a3b8" font-size="12">Equity: {_fmt_money(vals[0])} → {_fmt_money(vals[-1])}</text>
    </svg>"""


def build_exit_analysis(trades):
    """Build exit reason breakdown table."""
    sells = [t for t in trades if t.get("side") == "SELL"]
    from collections import defaultdict
    by_reason = defaultdict(list)
    for t in sells:
        r = t.get("exit_reason", "Unknown").split("(")[0].strip()
        by_reason[r].append(t)
    rows = []
    total = len(sells) or 1
    for reason, ts in sorted(by_reason.items(), key=lambda x: -len(x[1])):
        wins = [t for t in ts if t.get("pnl_dollars", 0) > 0]
        wr = len(wins) / len(ts) * 100 if ts else 0
        pnl = sum(t.get("pnl_dollars", 0) for t in ts)
        rows.append(f"""<tr>
            <td>{reason}</td>
            <td>{len(ts)}</td>
            <td>{len(ts)/total*100:.1f}%</td>
            <td>{wr:.1f}%</td>
            <td style="color:{_color(pnl)}">{_fmt_money(pnl)}</td>
        </tr>""")
    return "\n".join(rows)


def main():
    print("=" * 70)
    print("  MQR REPORT + A/B vs Sector Top-5 PEGY")
    print("=" * 70)

    # ── Full-period MQR run ──────────────────────────────────────────
    print("Running MQR full-period backtest...")
    adapter = StrategyBacktestAdapter(MomentumQualityRotation())
    result = adapter.run(as_of=AS_OF, end=END, capital=CAPITAL)
    s = result["summary"]
    trades = result["trades"]
    daily_equity = result["daily_equity"]
    print(f"  MQR: CAGR={s.get('cagr_pct',0):.1f}% ret={s.get('total_return_pct',0):.1f}% "
          f"trades={s.get('total_trades',0)} dd={s.get('max_drawdown_pct',0):.1f}%")

    # ── A/B rolling comparison ────────────────────────────────────────
    print("Running A/B rolling comparison (MQR vs Sector Top-5 PEGY)...")
    import pandas as pd
    from app.db.database import engine
    with engine.connect() as c:
        spy = pd.read_sql('SELECT "Date" FROM spy WHERE "Date" >= \'2021-06-01\' AND "Date" <= \'2025-12-31\' ORDER BY "Date"', c)
    dates = [str(d)[:10] for d in spy["Date"]]
    starts = dates[::40]
    ab_rows = []
    mqr_cagrs, pegy_cagrs = [], []
    mqr_dds, pegy_dds = [], []
    for st in starts:
        try:
            idx = dates.index(st)
        except ValueError:
            continue
        end = dates[min(idx + 252, len(dates) - 1)]
        if end <= st:
            continue
        r1 = StrategyBacktestAdapter(MomentumQualityRotation()).run(as_of=st, end=end, capital=CAPITAL)["summary"]
        r2 = StrategyBacktestAdapter(SectorTop5MomentumPEGY()).run(as_of=st, end=end, capital=CAPITAL)["summary"]
        mqr_cagrs.append(r1.get("cagr_pct", 0)); pegy_cagrs.append(r2.get("cagr_pct", 0))
        mqr_dds.append(r1.get("max_drawdown_pct", 0)); pegy_dds.append(r2.get("max_drawdown_pct", 0))
        ab_rows.append(f"""<tr>
            <td>{st}</td><td>{end}</td>
            <td style="color:{_color(r1.get('cagr_pct',0))}">{_fmt_pct(r1.get('cagr_pct',0))}</td>
            <td style="color:{_color(r2.get('cagr_pct',0))}">{_fmt_pct(r2.get('cagr_pct',0))}</td>
            <td style="color:{_color(r1.get('max_drawdown_pct',0))}">{_fmt_pct(r1.get('max_drawdown_pct',0))}</td>
            <td style="color:{_color(r2.get('max_drawdown_pct',0))}">{_fmt_pct(r2.get('max_drawdown_pct',0))}</td>
        </tr>""")
    ab_rows_html = "\n".join(ab_rows)
    mqr_cagr_mean = statistics.mean(mqr_cagrs) if mqr_cagrs else 0
    pegy_cagr_mean = statistics.mean(pegy_cagrs) if pegy_cagrs else 0
    mqr_dd_mean = statistics.mean(mqr_dds) if mqr_dds else 0
    pegy_dd_mean = statistics.mean(pegy_dds) if pegy_dds else 0
    print(f"  A/B done: {len(ab_rows)} windows. MQR CAGR mean={mqr_cagr_mean:.1f}% vs PEGY={pegy_cagr_mean:.1f}%")

    # ── Build HTML ───────────────────────────────────────────────────
    trade_rows = build_trade_table(trades)
    equity_svg = build_equity_svg(daily_equity)
    exit_rows = build_exit_analysis(trades)

    # Strategy code
    code_text = ""
    try:
        with open(os.path.join(os.path.dirname(__file__), "..", "backend", "app", "services", "strategies", "momentum_quality_rotation.py"), encoding="utf-8") as f:
            code_text = f.read()
    except Exception:
        pass

    params = {
        "Period": f"{AS_OF} → {END}",
        "Capital": f"${CAPITAL:,.0f}",
        "Max Holdings": 5,
        "Max per Sector": 2,
        "Market Cap Min": "$5B",
        "Max Volatility": "5% (14d)",
        "Hard Stop": "20%",
        "Trailing Stop": "12%",
        "Take Profit": "50%",
        "Time Stop": "120d",
        "Min Hold": "14d",
        "Protect Winners": True,
        "Bear Exposure": "50% (SPY < SMA200)",
    }
    params_html = "".join(
        f'<div class="param-item"><span class="param-key">{k}</span><span class="param-val">{v}</span></div>'
        for k, v in params.items()
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Momentum Quality Rotation — Report</title>
<style>
  body {{ font-family:-apple-system,Segoe UI,Roboto,sans-serif; background:#0b1220; color:#e2e8f0; margin:0; padding:24px; }}
  h1 {{ color:#f8fafc; }} h2 {{ color:#94a3b8; border-bottom:1px solid #1e293b; padding-bottom:8px; margin-top:36px; }}
  .hero {{ background:linear-gradient(135deg,#0f172a,#1e293b); border:1px solid #334155; border-radius:12px; padding:24px; margin-bottom:24px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; }}
  .card {{ background:#0f172a; border:1px solid #1e293b; border-radius:8px; padding:16px; text-align:center; }}
  .card .val {{ font-size:22px; font-weight:700; }} .card .lbl {{ font-size:12px; color:#64748b; margin-top:4px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th,td {{ padding:6px 10px; text-align:left; border-bottom:1px solid #1e293b; }}
  th {{ background:#1e293b; color:#94a3b8; position:sticky; top:0; }}
  tr.buy td {{ background:rgba(16,185,129,0.06); }} tr.sell td {{ background:rgba(239,68,68,0.05); }}
  .params-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:8px; }}
  .param-item {{ background:#0f172a; border:1px solid #1e293b; border-radius:6px; padding:8px 12px; }}
  .param-key {{ color:#64748b; font-size:12px; display:block; }} .param-val {{ font-weight:600; }}
  .ab-badge {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:700; }}
  .scroll {{ max-height:600px; overflow-y:auto; border:1px solid #1e293b; border-radius:8px; }}
  .note {{ color:#94a3b8; font-size:13px; }}
</style></head><body>

<div class="hero">
  <h1>📈 Momentum Quality Rotation (MQR)</h1>
  <div class="note">Top-5 momentum rotation with a market regime filter (SPY &lt; SMA200 → 50% exposure).</div>
  <div class="cards">
    <div class="card"><div class="val" style="color:{_color(s.get('cagr_pct',0))}">{_fmt_pct(s.get('cagr_pct',0))}</div><div class="lbl">CAGR</div></div>
    <div class="card"><div class="val" style="color:{_color(s.get('total_return_pct',0))}">{_fmt_pct(s.get('total_return_pct',0))}</div><div class="lbl">Total Return</div></div>
    <div class="card"><div class="val">{_fmt_money(s.get('final_portfolio',0))}</div><div class="lbl">Final Portfolio</div></div>
    <div class="card"><div class="val" style="color:{_color(s.get('alpha_pct',0))}">{_fmt_pct(s.get('alpha_pct',0))}</div><div class="lbl">Alpha vs SPY</div></div>
    <div class="card"><div class="val">{s.get('sharpe_ratio',0):.2f}</div><div class="lbl">Sharpe</div></div>
    <div class="card"><div class="val">{s.get('win_rate',0):.1f}%</div><div class="lbl">Win Rate</div></div>
    <div class="card"><div class="val">{s.get('profit_factor',0):.2f}</div><div class="lbl">Profit Factor</div></div>
    <div class="card"><div class="val" style="color:#ef4444">{_fmt_pct(s.get('max_drawdown_pct',0))}</div><div class="lbl">Max Drawdown</div></div>
    <div class="card"><div class="val">{s.get('total_trades',0)}</div><div class="lbl">Total Trades</div></div>
  </div>
</div>

<h2>📉 Equity Curve</h2>
{equity_svg}

<h2>⚙️ Strategy Parameters</h2>
<div class="params-grid">{params_html}</div>

<h2>📋 Full Trade Ledger ({len(trades)} trades — every buy &amp; sell)</h2>
<div class="scroll">
<table>
  <thead><tr><th>Ticker</th><th>Side</th><th>Entry Date</th><th>Exit Date</th><th>Entry $</th><th>Exit $</th><th>Hold (d)</th><th>Return</th><th>P&amp;L $</th><th>Exit Reason</th></tr></thead>
  <tbody>{trade_rows}</tbody>
</table>
</div>

<h2>🚪 Exit Analysis</h2>
<table>
  <thead><tr><th>Exit Reason</th><th>Count</th><th>% of Total</th><th>Win Rate</th><th>Total P&amp;L</th></tr></thead>
  <tbody>{exit_rows}</tbody>
</table>

<h2>⚔️ A/B: MQR vs Sector Top-5 PEGY (rolling 1-year windows)</h2>
<div class="note">Same windows, same capital. MQR adds the market regime filter; PEGY adds a fundamental screen.</div>
<table>
  <thead><tr><th>Start</th><th>End</th><th>MQR CAGR</th><th>PEGY CAGR</th><th>MQR MaxDD</th><th>PEGY MaxDD</th></tr></thead>
  <tbody>{ab_rows_html}</tbody>
</table>
<div class="cards" style="margin-top:16px">
  <div class="card"><div class="val" style="color:{_color(mqr_cagr_mean)}">{_fmt_pct(mqr_cagr_mean)}</div><div class="lbl">MQR mean CAGR</div></div>
  <div class="card"><div class="val" style="color:{_color(pegy_cagr_mean)}">{_fmt_pct(pegy_cagr_mean)}</div><div class="lbl">PEGY mean CAGR</div></div>
  <div class="card"><div class="val" style="color:#ef4444">{_fmt_pct(mqr_dd_mean)}</div><div class="lbl">MQR mean MaxDD</div></div>
  <div class="card"><div class="val" style="color:#ef4444">{_fmt_pct(pegy_dd_mean)}</div><div class="lbl">PEGY mean MaxDD</div></div>
</div>

<h2>📄 Strategy Source</h2>
<details><summary>View code</summary><pre style="background:#0f172a;padding:16px;border-radius:8px;overflow-x:auto;font-size:12px">{code_text}</pre></details>

<div class="note" style="margin-top:24px">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · Backtest period {AS_OF} → {END} · Past performance does not guarantee future results.</div>
</body></html>"""

    out_path = os.path.join(REPORT_DIR, "momentum_quality_rotation.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  📈 HTML report: {out_path}")

    # Also save the A/B summary JSON
    ab_summary = {
        "n_windows": len(ab_rows),
        "mqr_cagr_mean": mqr_cagr_mean,
        "pegy_cagr_mean": pegy_cagr_mean,
        "mqr_dd_mean": mqr_dd_mean,
        "pegy_dd_mean": pegy_dd_mean,
    }
    with open(os.path.join(REPORT_DIR, "momentum_quality_ab.json"), "w") as f:
        json.dump(ab_summary, f, indent=2)
    print(f"  📊 A/B summary: {os.path.join(REPORT_DIR, 'momentum_quality_ab.json')}")


if __name__ == "__main__":
    main()
