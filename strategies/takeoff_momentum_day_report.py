"""Generate the HTML performance report for the Takeoff Momentum Day-Trade strategy.

Reads the exported data JSON (docs/reports/takeoff_momentum_day_data.json) and
produces a self-contained dark-theme HTML report with:
  - Hero stat cards
  - Strategy details (collapsible)
  - Daily P&L table
  - Trade list with exit reasons
  - Exit analysis
  - Equity curve (SVG)

Usage:
  cd backend && ./venv/bin/python ../strategies/takeoff_momentum_day_report.py
"""

import os, sys, json, html
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE, "..", "docs", "reports", "takeoff_momentum_day_data.json")
OUT_PATH = os.path.join(BASE, "..", "docs", "reports", "takeoff_momentum_day_report.html")


def _fmt(x, nd=2):
    try:
        return f"{x:,.{nd}f}"
    except Exception:
        return str(x)


def _pct(x):
    try:
        return f"{x:+.2f}%"
    except Exception:
        return str(x)


def _cls(x):
    return "positive" if x > 0 else ("negative" if x < 0 else "")


def build_html(data):
    s = data["summary"]
    trades = data["trades"]
    equity = data["daily_equity"]
    trade_days = data.get("trade_days", [])

    # Daily P&L
    from collections import defaultdict
    byday = defaultdict(list)
    for t in trades:
        if t["side"] == "SELL":
            byday[t["exit_date"]].append(t)

    daily_rows = ""
    for d in sorted(byday):
        day_pnl = sum(t["pnl_dollars"] for t in byday[d])
        cls = _cls(day_pnl)
        sub = ""
        for t in byday[d]:
            sub += (
                f"<tr><td></td><td>{html.escape(t['ticker'])}</td>"
                f"<td>{_fmt(t['entry_price'])}</td><td>{_fmt(t['exit_price'])}</td>"
                f"<td class='{_cls(t['return_pct'])}'>{_pct(t['return_pct'])}</td>"
                f"<td class='{_cls(t['pnl_dollars'])}'>${_fmt(t['pnl_dollars'])}</td>"
                f"<td>{html.escape(t['exit_reason'])}</td></tr>"
            )
        daily_rows += (
            f"<tr><td><b>{d}</b></td><td colspan='4'>{len(byday[d])} trades</td>"
            f"<td class='{cls}'><b>${_fmt(day_pnl)}</b></td><td></td></tr>{sub}"
        )

    # Trade list
    trade_rows = ""
    for t in trades:
        if t["side"] == "SELL":
            trade_rows += (
                f"<tr><td>{html.escape(t['ticker'])}</td><td>{t['entry_date']}</td>"
                f"<td>{t.get('entry_time','')}</td><td>{_fmt(t['entry_price'])}</td>"
                f"<td>{_fmt(t['exit_price'])}</td>"
                f"<td class='{_cls(t['return_pct'])}'>{_pct(t['return_pct'])}</td>"
                f"<td class='{_cls(t['pnl_dollars'])}'>${_fmt(t['pnl_dollars'])}</td>"
                f"<td>{html.escape(t['exit_reason'])}</td></tr>"
            )

    # Exit analysis
    reasons = s.get("exit_reasons", {})
    total_sells = sum(reasons.values()) or 1
    exit_rows = ""
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        pct = c / total_sells * 100
        exit_rows += (
            f"<tr><td>{html.escape(r)}</td><td>{c}</td><td>{pct:.0f}%</td>"
            f"<td><div class='bar'><div class='bar-fill' style='width:{pct:.0f}%'></div></div></td></tr>"
        )

    # Equity curve SVG
    eq_pts = []
    for e in equity:
        eq_pts.append((e["date"], e["value"]))
    svg = _build_equity_svg(eq_pts)

    # Top/bottom trades
    sells = [t for t in trades if t["side"] == "SELL"]
    top_w = sorted(sells, key=lambda t: t["pnl_dollars"], reverse=True)[:5]
    top_l = sorted(sells, key=lambda t: t["pnl_dollars"])[:5]
    topw_rows = "".join(
        f"<tr><td>{html.escape(t['ticker'])}</td><td class='{_cls(t['return_pct'])}'>{_pct(t['return_pct'])}</td>"
        f"<td class='{_cls(t['pnl_dollars'])}'>${_fmt(t['pnl_dollars'])}</td><td>{html.escape(t['exit_reason'])}</td></tr>"
        for t in top_w
    )
    topl_rows = "".join(
        f"<tr><td>{html.escape(t['ticker'])}</td><td class='{_cls(t['return_pct'])}'>{_pct(t['return_pct'])}</td>"
        f"<td class='{_cls(t['pnl_dollars'])}'>${_fmt(t['pnl_dollars'])}</td><td>{html.escape(t['exit_reason'])}</td></tr>"
        for t in top_l
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Takeoff Momentum Day-Trade — Strategy Report</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Inter', -apple-system, sans-serif; background: #0a0a0f; color: #e2e8f0; line-height: 1.6; }}
  .container {{ max-width: 1100px; margin: 0 auto; padding: 40px 24px; }}
  h1 {{ font-size: 2.2rem; font-weight: 800; background: linear-gradient(135deg, #22d3ee, #10b981); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 8px; }}
  h2 {{ font-size: 1.4rem; font-weight: 700; color: #22d3ee; margin: 40px 0 16px; padding-bottom: 8px; border-bottom: 2px solid #1e293b; }}
  .subtitle {{ color: #64748b; font-size: 0.95rem; margin-bottom: 32px; }}
  .hero {{ background: linear-gradient(135deg, #0f172a, #1e293b); border: 1px solid #334155; border-radius: 16px; padding: 32px; margin-bottom: 32px; text-align: center; }}
  .hero-number {{ font-size: 3.2rem; font-weight: 800; background: linear-gradient(135deg, #22d3ee, #10b981); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
  .hero-label {{ color: #94a3b8; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1px; margin-top: 4px; }}
  .hero-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-top: 24px; }}
  .hero-stat {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 18px; text-align: center; }}
  .hero-stat-value {{ font-size: 1.4rem; font-weight: 700; color: #22d3ee; }}
  .hero-stat-label {{ font-size: 0.78rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }}
  .card {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 24px; margin-bottom: 16px; }}
  .card-title {{ font-size: 1rem; font-weight: 600; color: #e2e8f0; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
  th {{ text-align: left; padding: 10px 12px; color: #64748b; font-weight: 500; text-transform: uppercase; font-size: 0.72rem; letter-spacing: 0.5px; border-bottom: 1px solid #1e293b; }}
  td {{ padding: 9px 12px; border-bottom: 1px solid #1e293b; }}
  tr:hover td {{ background: #1a2332; }}
  .positive {{ color: #10b981; }}
  .negative {{ color: #ef4444; }}
  .bar {{ width: 100%; height: 18px; background: #1e293b; border-radius: 4px; overflow: hidden; }}
  .bar-fill {{ height: 100%; background: linear-gradient(90deg, #22d3ee, #10b981); }}
  .note {{ color: #94a3b8; font-size: 0.85rem; background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
  details {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 16px 20px; margin-bottom: 16px; }}
  summary {{ cursor: pointer; font-weight: 600; color: #22d3ee; }}
  pre {{ background: #0a0a0f; border: 1px solid #1e293b; border-radius: 8px; padding: 16px; overflow-x: auto; font-size: 0.8rem; color: #a5b4fc; margin-top: 12px; }}
</style>
</head>
<body>
<div class="container">
  <h1>Takeoff Momentum Day-Trade</h1>
  <div class="subtitle">Daily EMA5/200 momentum screen + intraday 1-minute execution &middot; {len(trade_days)} trade days &middot; generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>

  <div class="hero">
    <div class="hero-number">{_pct(s['total_return_pct'])}</div>
    <div class="hero-label">Total Return</div>
    <div class="hero-grid">
      <div class="hero-stat"><div class="hero-stat-value">${_fmt(s['final_portfolio'])}</div><div class="hero-stat-label">Final Value</div></div>
      <div class="hero-stat"><div class="hero-stat-value">{_fmt(s['sharpe_ratio'])}</div><div class="hero-stat-label">Sharpe</div></div>
      <div class="hero-stat"><div class="hero-stat-value">{_fmt(s['win_rate'],1)}%</div><div class="hero-stat-label">Win Rate</div></div>
      <div class="hero-stat"><div class="hero-stat-value">{_fmt(s['max_drawdown_pct'],1)}%</div><div class="hero-stat-label">Max DD</div></div>
      <div class="hero-stat"><div class="hero-stat-value">{_fmt(s['profit_factor'])}</div><div class="hero-stat-label">Profit Factor</div></div>
      <div class="hero-stat"><div class="hero-stat-value">{s['total_trades']}</div><div class="hero-stat-label">Trades</div></div>
    </div>
  </div>

  <div class="note">
    <b>Data constraint:</b> 1-minute data currently covers only 2026-07-30 &rarr; 2026-08-07 (~7 trading days).
    This is a proof-of-concept backtest; the small sample is not statistically significant.
    SPY benchmark: {_pct(s['spy_return_pct'])} &middot; Alpha: {_pct(s['alpha_pct'])}.
  </div>

  <h2>Daily P&amp;L</h2>
  <div class="card">
    <table>
      <tr><th>Date</th><th>Ticker</th><th>Entry</th><th>Exit</th><th>Return</th><th>P&amp;L</th><th>Exit Reason</th></tr>
      {daily_rows}
    </table>
  </div>

  <h2>Equity Curve</h2>
  <div class="card">{svg}</div>

  <h2>Trade List</h2>
  <div class="card">
    <table>
      <tr><th>Ticker</th><th>Date</th><th>Entry Time</th><th>Entry</th><th>Exit</th><th>Return</th><th>P&amp;L</th><th>Exit Reason</th></tr>
      {trade_rows}
    </table>
  </div>

  <h2>Exit Analysis</h2>
  <div class="card">
    <table>
      <tr><th>Exit Reason</th><th>Count</th><th>% of Trades</th><th>Distribution</th></tr>
      {exit_rows}
    </table>
  </div>

  <h2>Top &amp; Bottom Trades</h2>
  <div class="card">
    <div class="card-title">Top 5 Winners</div>
    <table><tr><th>Ticker</th><th>Return</th><th>P&amp;L</th><th>Exit Reason</th></tr>{topw_rows}</table>
    <div class="card-title" style="margin-top:20px">Top 5 Losers</div>
    <table><tr><th>Ticker</th><th>Return</th><th>P&amp;L</th><th>Exit Reason</th></tr>{topl_rows}</table>
  </div>

  <h2>Strategy Details</h2>
  <details>
    <summary>Entry / Exit / Sizing rules</summary>
    <pre>
Daily composite screen (day D):
  Momentum 70%  - EMA5 crosses above EMA200, close[yesterday] > EMA5[yesterday],
                  ranked by 5-day angle between EMA5 and EMA200.
  Volatility 10% - Bollinger (20,2) squeeze (low bandwidth = building energy).
  Volume    20%  - volume surge: volume[D] >= 1.5x prior-5-day average.
  Filters: price > $10, avg 20d daily dollar volume > $50M; ETFs excluded.
  Select top 5, max 2 per sector.

Intraday execution (day D+1, 1-minute bars):
  Entry: close of first 1-min bar whose close > prior day close (confirmation).
  Exits (priority): +4% take-profit -> -1% stop-loss -> 2% trailing ->
    3:55 PM end-of-day liquidation. No overnight positions.
Sizing: score-weighted across the day's picks over $100k capital.
    </pre>
  </details>
</div>
</body>
</html>"""


def _build_equity_svg(points):
    if not points:
        return "<p>No equity data.</p>"
    W, H, PAD = 1000, 300, 40
    vals = [p[1] for p in points]
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(points)
    def x(i): return PAD + (W - 2 * PAD) * i / max(n - 1, 1)
    def y(v): return H - PAD - (H - 2 * PAD) * (v - lo) / rng
    path = " ".join(f"L{x(i)},{y(v):.1f}" for i, (_, v) in enumerate(points))
    path = f"M{x(0)},{y(points[0][1]):.1f} " + path
    labels = "".join(
        f"<text x='{x(i)}' y='{H-8}' font-size='10' fill='#64748b' text-anchor='middle'>{p[0][5:]}</text>"
        for i, p in enumerate(points)
    )
    return f"""<svg viewBox="0 0 {W} {H}" width="100%" style="background:#0a0a0f">
  <path d="{path}" fill="none" stroke="#22d3ee" stroke-width="2.5"/>
  <circle cx="{x(0)}" cy="{y(points[0][1]):.1f}" r="4" fill="#10b981"/>
  {labels}
</svg>"""


def main():
    if not os.path.isfile(DATA_PATH):
        print(f"Data file not found: {DATA_PATH}")
        print("Run ../strategies/takeoff_momentum_day.py first to generate it.")
        sys.exit(1)
    with open(DATA_PATH) as f:
        data = json.load(f)
    html_out = build_html(data)
    with open(OUT_PATH, "w") as f:
        f.write(html_out)
    print(f"✅ Report written to {OUT_PATH} ({len(html_out):,} bytes)")


if __name__ == "__main__":
    main()
