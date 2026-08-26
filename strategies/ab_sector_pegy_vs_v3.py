"""
A/B — Sector Top-5 Momentum + PEGY (80/20, gate 2.0)  vs  Sector Top-5 Rotation v3
===================================================================================
Runs BOTH strategies on the SAME 100 start dates (apples-to-apples), each to
2025-12-31, and produces a paired side-by-side HTML comparison report.

Signals are precomputed once per strategy over the full range and reused
across all runs (the same fast path the Strategy Lab batch runner uses).

Usage:
  cd backend && ./venv/bin/python ../strategies/ab_sector_pegy_vs_v3.py
"""

import os
import sys
import json
import warnings
from datetime import datetime
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "sarina00")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5431")
os.environ.setdefault("DB_NAME", "sp1500_1d")

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.db.database import engine as db_engine
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.strategies.sector_top5_pegy import SectorTop5MomentumPEGY
from app.services.strategies.sector_scanner_top5_rotation_v3 import (
    SectorScannerTop5RotationV3,
)

# ── A/B configuration ────────────────────────────────────────────────
N_RUNS = 100
START_MIN = "2022-01-01"      # PEGY needs ~2 annual reports; start once data is live
START_MAX = "2024-06-01"
END = "2025-12-31"
CAPITAL = 100_000.0

NAME_A = "Sector Top-5 Momentum + PEGY (80/20, gate 2.0)"
NAME_B = "Sector Top-5 Rotation v3 (Pure Momentum)"
PARAMS_A = {"PEGY gate": 2.0, "Momentum weight": 0.80, "PEGY weight": 0.20, "Exits": "HS20/TS10/TP50", "Rotation": "off"}
PARAMS_B = {"PEGY gate": None, "Momentum weight": 1.0, "PEGY weight": 0.0, "Exits": "HS20/TS10/TP50", "Rotation": "off"}


# ── Helpers ──────────────────────────────────────────────────────────

def trading_dates(start: str, end: str) -> list:
    with db_engine.connect() as conn:
        df = pd.read_sql(
            f'SELECT "Date" FROM spy WHERE "Date" >= \'{start}\' AND "Date" <= \'{end}\' ORDER BY "Date"',
            conn,
        )
    return [str(d)[:10] for d in df["Date"]]


def pick_start_dates(all_dates: list, n: int) -> list:
    """Evenly spaced start dates from the trading calendar (deterministic)."""
    idx = np.linspace(0, len(all_dates) - 1, n).astype(int)
    # dedupe + sort ascending
    return [all_dates[i] for i in sorted(set(idx.tolist()))][:n]


def precompute(strategy_cls, all_dates):
    s = strategy_cls()
    signals = s.precompute_signals(all_dates, db_engine)
    price_cache = s.get_precomputed_price_cache()
    if hasattr(s, "precompute_scores"):
        try:
            s.precompute_scores(all_dates, db_engine)
        except Exception:
            pass
    return s, signals, price_cache


def run_all(strategy, signals, price_cache, start_dates, end, cap):
    out = []
    for i, sd in enumerate(start_dates, 1):
        adapter = StrategyBacktestAdapter(strategy)
        r = adapter.run(as_of=sd, end=end, capital=cap,
                        precomputed_signals=signals, price_cache=price_cache)
        out.append({
            "start": sd, "end": end, "kpis": r["summary"], "equity": r["daily_equity"],
        })
    return out


def _downsample_equity(equity, points=300):
    if not equity:
        return []
    n = len(equity)
    if n <= points:
        return [{"date": d["date"], "value": d["value"]} for d in equity]
    idx = np.linspace(0, n - 1, points).astype(int)
    return [{"date": equity[i]["date"], "value": equity[i]["value"]} for i in sorted(set(idx.tolist()))]


def mean_equity_curve(runs, cap, points=200):
    """Average normalized equity vs hold-progress (0..1) across runs."""
    xs = np.linspace(0, 1, points)
    ys = []
    for r in runs:
        eq = r["equity"]
        if not eq:
            continue
        vals = np.array([d["value"] / cap for d in eq], dtype=float)
        if len(vals) < 2:
            continue
        t = np.linspace(0, 1, len(vals))
        interp = np.interp(xs, t, vals)
        ys.append(interp)
    if not ys:
        return xs, np.full(points, np.nan), np.full(points, np.nan)
    arr = np.array(ys)
    return xs, arr.mean(axis=0), arr.std(axis=0)


# ── Report ───────────────────────────────────────────────────────────
def _f(val, nd=1):
    return f"{val:,.{nd}f}" if val is not None else "—"


def _pct(val):
    return f"{val:+,.2f}%" if val is not None else "—"


def _stat(runs):
    ks = [r["kpis"] for r in runs]
    def col(k):
        return np.array([x.get(k, 0) or 0 for x in ks], dtype=float)
    return {
        "cagr": col("cagr_pct"), "tot": col("total_return_pct"),
        "alpha": col("alpha_pct"), "win": col("win_rate"),
        "sharpe": col("sharpe_ratio"), "dd": col("max_drawdown_pct"),
        "trades": col("total_trades"),
    }


def _stat_card(label, color, data):
    mean_val = float(np.mean(data['cagr']))
    med_val = float(np.median(data['cagr']))
    return f"""
    <div class="card" style="border-top:3px solid {color};">
      <div class="card-label">{label}</div>
      <div class="card-val">{_pct(mean_val)}</div>
      <div class="card-sub">Median {_pct(med_val)}</div>
    </div>"""


def _agg_rows(a, b):
    rows = []
    items = [
        ("CAGR", a["cagr"], b["cagr"], "pct"),
        ("Total Return", a["tot"], b["tot"], "pct"),
        ("Alpha vs SPY", a["alpha"], b["alpha"], "pct"),
        ("Win Rate", a["win"], b["win"], "pct_plain"),
        ("Sharpe", a["sharpe"], b["sharpe"], "num"),
        ("Max Drawdown", a["dd"], b["dd"], "pct_plain"),
        ("Trades", a["trades"], b["trades"], "int"),
    ]
    for label, av, bv, kind in items:
        def fmt(v):
            if kind == "pct":
                return f"{v.mean():+,.2f}%", f"med {np.median(v):+,.2f}%"
            if kind == "pct_plain":
                return f"{v.mean():,.1f}%", f"med {np.median(v):,.1f}%"
            if kind == "num":
                return f"{v.mean():.2f}", f"med {np.median(v):.2f}"
            return f"{v.mean():.0f}", f"med {np.median(v):.0f}"
        am, asub = fmt(av)
        bm, bsub = fmt(bv)
        better = "A" if av.mean() > bv.mean() else ("B" if bv.mean() > av.mean() else "—")
        rows.append(f"""
        <tr>
          <td>{label}</td>
          <td style="text-align:right;"><span class="strong">{am}</span> <span class="dim">({asub})</span></td>
          <td style="text-align:right;"><span class="strong">{bm}</span> <span class="dim">({bsub})</span></td>
          <td style="text-align:center;">{better}</td>
        </tr>""")
    return "\n".join(rows)


def build_report(runs_a, runs_b, start_dates, path):
    a, b = _stat(runs_a), _stat(runs_b)
    beats = sum(1 for ra, rb in zip(runs_a, runs_b) if ra["kpis"]["total_return_pct"] > rb["kpis"]["total_return_pct"])
    # mean equity curves
    xs_a, ma, sa = mean_equity_curve(runs_a, CAPITAL)
    xs_b, mb, sb = mean_equity_curve(runs_b, CAPITAL)

    # SVG overlay (normalized equity)
    W, H = 760, 260
    pad = 34
    all_vals = [v for arr in (ma, mb) for v in arr if not np.isnan(v)]
    vmin, vmax = (min(all_vals) if all_vals else 0.9), (max(all_vals) if all_vals else 1.1)
    span = (vmax - vmin) or 0.1
    def xy(vals):
        pts = []
        for i, v in enumerate(vals):
            if np.isnan(v):
                continue
            x = pad + (i / (len(vals) - 1)) * (W - 2 * pad)
            y = H - pad - ((v - vmin) / span) * (H - 2 * pad)
            pts.append(f"{x:.1f},{y:.1f}")
        return " ".join(pts)

    svg = f'''<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto;" role="img">
      <line x1="{pad}" y1="{H-pad}" x2="{W-pad}" y2="{H-pad}" stroke="#334155" stroke-width="1"/>
      <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{H-pad}" stroke="#334155" stroke-width="1"/>
      <line x1="{pad}" y1="{H-pad}" x2="{pad}" y2="{pad}" stroke="#64748b" stroke-dasharray="3,3"/>
      <polyline points="{xy(ma)}" fill="none" stroke="#22d3ee" stroke-width="2"/>
      <polyline points="{xy(mb)}" fill="none" stroke="#f59e0b" stroke-width="2"/>
      <text x="{pad}" y="{H-pad+18}" fill="#64748b" font-size="10">start</text>
      <text x="{W-pad-20}" y="{H-pad+18}" fill="#64748b" font-size="10">end</text>
    </svg>'''

    # rows
    rows = ""
    for i, sd in enumerate(start_dates):
        ra, rb = runs_a[i]["kpis"], runs_b[i]["kpis"]
        winner = "A" if (ra["total_return_pct"] or 0) >= (rb["total_return_pct"] or 0) else "B"
        rows += f"""
        <tr>
          <td>{sd}</td>
          <td class="{_cls(ra['total_return_pct'])}">{_pct(ra['total_return_pct'])}</td>
          <td class="{_cls(ra['alpha_pct'])}">{_pct(ra['alpha_pct'])}</td>
          <td>{ra['sharpe_ratio']:.2f}</td>
          <td>{ra['max_drawdown_pct']:.1f}%</td>
          <td>{int(ra['total_trades'])}</td>
          <td class="{_cls(rb['total_return_pct'])}">{_pct(rb['total_return_pct'])}</td>
          <td class="{_cls(rb['alpha_pct'])}">{_pct(rb['alpha_pct'])}</td>
          <td>{rb['sharpe_ratio']:.2f}</td>
          <td>{rb['max_drawdown_pct']:.1f}%</td>
          <td>{int(rb['total_trades'])}</td>
          <td class="{_cls(rb['total_return_pct'])}">{winner}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PEGY vs Pure v3 — A/B</title><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#0a0a0f; color:#e2e8f0; padding:24px; }}
  h1 {{ font-size:1.8rem; margin-bottom:4px; background:linear-gradient(135deg,#22d3ee,#10b981); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }}
  .subtitle {{ color:#64748b; font-size:.9rem; margin-bottom:20px; }}
  .legend {{ display:flex; gap:24px; margin:12px 0 20px; font-size:.85rem; }}
  .dot {{ display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:6px; vertical-align:middle; }}
  .cards {{ display:flex; gap:16px; margin-bottom:20px; flex-wrap:wrap; }}
  .card {{ background:#0f172a; border:1px solid #1e293b; border-radius:8px; padding:14px 18px; min-width:150px; }}
  .card-label {{ font-size:.7rem; color:#64748b; text-transform:uppercase; letter-spacing:.5px; }}
  .card-val {{ font-size:1.3rem; font-weight:700; }}
  .card-sub {{ font-size:.7rem; color:#64748b; margin-top:2px; }}
  .panel {{ background:#0f172a; border:1px solid #1e293b; border-radius:8px; padding:16px; margin-bottom:16px; }}
  .panel h3 {{ color:#22d3ee; font-size:1rem; margin-bottom:8px; }}
  table {{ width:100%; border-collapse:collapse; font-size:.78rem; }}
  th {{ text-align:left; padding:8px 6px; color:#64748b; font-weight:500; text-transform:uppercase; font-size:.66rem; border-bottom:2px solid #1e293b; }}
  td {{ padding:6px; border-bottom:1px solid #1e293b; }}
  tr:hover {{ background:#1a2332; }}
  .green {{ color:#10b981; }} .red {{ color:#ef4444; }}
  .grp {{ color:#94a3b8; background:#1a2332; text-transform:uppercase; font-size:.62rem; letter-spacing:.5px; }}
  .strong {{ font-weight:600; }} .dim {{ color:#64748b; font-size:.72rem; }}
  @media(max-width:900px){{ table {{ font-size:.7rem; }} }}
</style></head><body>

<h1>PEGY vs Momentum — A/B</h1>
<p class="subtitle">{N_RUNS} shared start dates · {START_MIN} → {END} · Capital ${CAPITAL:,.0f} · Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>

<div class="legend">
  <span><span class="dot" style="background:#22d3ee;"></span>{NAME_A}</span>
  <span><span class="dot" style="background:#f59e0b;"></span>{NAME_B}</span>
</div>

<div class="cards">
  {_stat_card("A — Mean CAGR", "#22d3ee", a)}
  {_stat_card("B — Mean CAGR", "#f59e0b", b)}
  <div class="card" style="border-top:3px solid #10b981;">
    <div class="card-label">Head-to-head</div>
    <div class="card-val">{beats} / {N_RUNS}</div>
    <div class="card-sub">runs A beats B by return</div>
  </div>
  <div class="card" style="border-top:3px solid #64748b;">
    <div class="card-label">Mean Sharpe</div>
    <div class="card-val" style="font-size:1rem;">
      <span style="color:#22d3ee">{a['sharpe'].mean():.2f}</span> vs
      <span style="color:#f59e0b">{b['sharpe'].mean():.2f}</span>
    </div>
    <div class="card-sub">A vs B</div>
  </div>
  <div class="card" style="border-top:3px solid #ef4444;">
    <div class="card-label">Mean Max DD</div>
    <div class="card-val" style="font-size:1rem;">
      <span style="color:#22d3ee">{a['dd'].mean():.1f}%</span> vs
      <span style="color:#f59e0b">{b['dd'].mean():.1f}%</span>
    </div>
  </div>
</div>

<div class="panel">
  <h3>📋 Aggregate metrics (mean across {N_RUNS} runs)</h3>
  <table>
    <thead>
      <tr>
        <th>Metric</th>
        <th style="text-align:right;">Strategy A (PEGY)</th>
        <th style="text-align:right;">Strategy B (Pure v3)</th>
        <th style="text-align:center;">Better</th>
      </tr>
    </thead>
    <tbody>{_agg_rows(a, b)}</tbody>
  </table>
</div>

<div class="panel">
  <h3>📈 Mean equity curve (normalized to 1.0 at start, averaged across runs)</h3>
  {svg}
</div>

<div class="panel">
  <h3>📊 Per-start-date comparison</h3>
  <table>
    <thead>
      <tr>
        <th colspan="6" class="grp">Strategy A — {NAME_A}</th>
        <th colspan="6" class="grp">Strategy B — {NAME_B}</th>
        <th></th>
      </tr>
      <tr>
        <th>Start</th><th>Ret</th><th>Alpha</th><th>Sharpe</th><th>MaxDD</th><th>Trd</th>
        <th>Ret</th><th>Alpha</th><th>Sharpe</th><th>MaxDD</th><th>Trd</th><th>Win</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>
</body></html>"""

    with open(path, "w") as f:
        f.write(html)
    return path


def _cls(v):
    return "green" if (v or 0) >= 0 else "red"


def main():
    print("=" * 78)
    print("  A/B — PEGY(80/20, gate 2.0)  vs  Pure v3")
    print(f"  {N_RUNS} shared start dates  [{START_MIN} → {START_MAX}], end {END}")
    print("=" * 78)

    all_dates = trading_dates(START_MIN, END)
    start_dates = pick_start_dates(all_dates, N_RUNS)
    print(f"  Precomputing over {len(all_dates)} days; running {len(start_dates)} start dates...")

    print("  Precompute A (PEGY)...")
    strat_a, sig_a, pc_a = precompute(SectorTop5MomentumPEGY, all_dates)
    print("  Precompute B (Pure v3)...")
    strat_b, sig_b, pc_b = precompute(SectorScannerTop5RotationV3, all_dates)

    print(f"  Running {len(start_dates)} runs for A...")
    runs_a = run_all(strat_a, sig_a, pc_a, start_dates, END, CAPITAL)
    print(f"  Running {len(start_dates)} runs for B...")
    runs_b = run_all(strat_b, sig_b, pc_b, start_dates, END, CAPITAL)

    # Save JSON (kpis + downsampled equity) so the report can be regenerated
    # without re-running the backtests.
    report_dir = os.path.join(os.path.dirname(__file__), "..", "docs", "reports")
    os.makedirs(report_dir, exist_ok=True)
    json_path = os.path.join(report_dir, "ab_sector_pegy_vs_v3.json")
    with open(json_path, "w") as f:
        json.dump({
            "start_dates": start_dates, "end": END, "capital": CAPITAL,
            "name_a": NAME_A, "name_b": NAME_B,
            "A": [r["kpis"] for r in runs_a],
            "B": [r["kpis"] for r in runs_b],
            "A_equity": [_downsample_equity(r["equity"]) for r in runs_a],
            "B_equity": [_downsample_equity(r["equity"]) for r in runs_b],
        }, f, indent=2)
    print(f"  📊 JSON saved: {json_path}")

    html_path = os.path.join(report_dir, "ab_sector_pegy_vs_v3.html")
    try:
        build_report(runs_a, runs_b, start_dates, html_path)
        status = f"  📈 HTML report: {html_path}"
    except Exception as e:
        import traceback
        status = f"  ❌ Report generation failed: {e}\n{traceback.format_exc()}"
    print("=" * 78)
    print("  ✅ DONE (backtests complete; data saved to JSON)")
    print(status)


def regen_report():
    """Regenerate the HTML report from the saved JSON (no re-run of backtests)."""
    report_dir = os.path.join(os.path.dirname(__file__), "..", "docs", "reports")
    json_path = os.path.join(report_dir, "ab_sector_pegy_vs_v3.json")
    with open(json_path) as f:
        data = json.load(f)
    runs_a = [
        {"start": sd, "end": data["end"], "kpis": k, "equity": e}
        for sd, k, e in zip(data["start_dates"], data["A"], data["A_equity"])
    ]
    runs_b = [
        {"start": sd, "end": data["end"], "kpis": k, "equity": e}
        for sd, k, e in zip(data["start_dates"], data["B"], data["B_equity"])
    ]
    path = build_report(runs_a, runs_b, data["start_dates"],
                        os.path.join(report_dir, "ab_sector_pegy_vs_v3.html"))
    print("Regenerated HTML:", path)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        regen_report()
    else:
        main()
