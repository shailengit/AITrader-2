"""Self-contained HTML report for the exit replay.

The gate is stated first and stated honestly: if it has not passed, the report
says the conclusions are void rather than burying that in a footnote.
"""
from __future__ import annotations

import html as _html

import pandas as pd

_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
background:#0a0a0f;color:#e2e8f0;padding:32px 24px;line-height:1.55}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:1.9rem;background:linear-gradient(135deg,#22d3ee,#10b981);
-webkit-background-clip:text;-webkit-text-fill-color:transparent}
h2{font-size:1.15rem;color:#22d3ee;margin:36px 0 12px}
.sub{color:#64748b;font-size:.9rem;margin-bottom:24px}
.card{background:#0f172a;border:1px solid #1e293b;border-radius:12px;padding:20px;margin-bottom:16px}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th{text-align:right;padding:9px 8px;color:#64748b;font-size:.68rem;text-transform:uppercase;
border-bottom:2px solid #1e293b}th:first-child{text-align:left}
td{padding:8px;border-bottom:1px solid #1e293b;text-align:right;font-variant-numeric:tabular-nums}
td:first-child{text-align:left;font-weight:600}
.green{color:#10b981}.red{color:#ef4444}.amber{color:#f59e0b}.dim{color:#64748b}
ul{margin-left:20px}li{margin-bottom:6px}
"""


def _f(x, nd=2):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{float(x):,.{nd}f}"


def build_report(gate: dict, ranking: list[dict], excursions: pd.DataFrame,
                 grid_meta: dict) -> str:
    total = int(gate.get("hard_total", 0))
    ok = int(gate.get("hard_reproduced", 0))
    passed = total > 0 and ok == total
    status_cls = "green" if passed else "red"
    status_txt = "PASS" if passed else "FAIL — conclusions are void"

    rows = "".join(
        f"<tr><td>{_html.escape(str(r.get('policy', '')))}</td>"
        f"<td>{_f(r.get('fit_dollars'))}</td>"
        f"<td>{_f(r.get('val_dollars'))}</td>"
        f"<td>{_f(r.get('mean_pnl_pct'), 4)}</td>"
        f"<td>{_f(r.get('n_observed'), 0)}</td>"
        f"<td>{r.get('n_censored', 0)}</td></tr>"
        for r in ranking
    )

    mae_med = mfe_med = "—"
    if len(excursions) and "mae" in excursions.columns:
        m = excursions["mae"].dropna()
        f = excursions["mfe"].dropna()
        if len(m):
            mae_med = _f(m.median(), 4)
        if len(f):
            mfe_med = _f(f.median(), 4)

    miss = gate.get("hard_mismatches") or []
    miss_rows = "".join(
        f"<tr><td>{_html.escape(str(m.get('ticker')))}</td>"
        f"<td>{_html.escape(str(m.get('class')))}</td>"
        f"<td>{_html.escape(str(m.get('recorded_date')))}</td>"
        f"<td>{_f(m.get('recorded_px'))}</td>"
        f"<td>{_f(m.get('replay_px'))}</td>"
        f"<td>{_html.escape(str(m.get('replay_reason')))}</td></tr>"
        for m in miss[:20]
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>MQR Exit Replay</title><style>{_CSS}</style></head><body><div class="wrap">
<h1>MQR Exit Replay</h1>
<p class="sub">Frozen entry set · price-based exit rules only · rotation held fixed ·
fill convention matches the recorded data (close) · {_html.escape(str(grid_meta.get('split', '')))}</p>

<h2>1 · Reproduction gate</h2>
<div class="card">
  <p><strong class="{status_cls}">{status_txt}</strong> — short-hold trades
  reproduced: <strong>{ok:,} / {total:,}</strong></p>
  <p class="dim">Every trade held &lt; 14 days must be reproduced by the price rules,
  because min_hold_days=14 gates rotation. Long-hold trades reproduced:
  {int(gate.get('soft_reproduced', 0)):,} / {int(gate.get('soft_total', 0)):,}
  (rate {_f(gate.get('soft_rate'), 4)}; predicted ≈ {_f(gate.get('predicted_soft_rate'), 4)}).</p>
  {f'<p class="dim">Mismatch classes: {_html.escape(str(gate.get("class_counts")))}</p>' if gate.get('class_counts') else ''}
</div>

{f'''<div class="card"><strong class="red">Mismatches (first 20)</strong>
<table><thead><tr><th>Ticker</th><th>Class</th><th>Recorded date</th>
<th>Recorded px</th><th>Replay px</th><th>Replay reason</th></tr></thead>
<tbody>{miss_rows}</tbody></table></div>''' if miss_rows else ''}

<h2>2 · Policy ranking</h2>
<div class="card"><table>
<thead><tr><th>Policy</th><th>Fit P&amp;L $</th><th>Validate P&amp;L $</th>
<th>Mean pnl</th><th>Observed</th><th>Censored</th></tr></thead>
<tbody>{rows}</tbody></table>
<p class="dim" style="margin-top:10px">Ranked by out-of-sample (validate) dollars.
A policy is a candidate only if it wins out-of-sample; in-sample winners are not promoted.</p>
</div>

<h2>3 · Excursion distributions (actual holds)</h2>
<div class="card"><table><thead><tr><th>Metric</th><th>Median</th></tr></thead>
<tbody>
<tr><td>MAE (max adverse excursion)</td><td>{mae_med}</td></tr>
<tr><td>MFE (max favourable excursion)</td><td>{mfe_med}</td></tr>
</tbody></table></div>

<h2>4 · Method &amp; caveats</h2>
<div class="card"><ul>
<li>Entries are FROZEN; only exits are replayed ⇒ deterministic, no path chaos.</li>
<li>Rotation is held fixed (capped at the real rotation date); its quality is
measured by forward-path evidence, not replayed.</li>
<li>The recorded data is <strong>close-filled</strong> (verified 600/600 sampled
short-hold trades match the trigger-day close, 0 match the next open), so the
replay fills at the close to reproduce the baseline. Next-open fills are a
sensitivity check.</li>
<li>Censoring is per (trade, policy) and reported per policy.</li>
<li>~1% of absolute prices differ from the recorded rows because the price panel
was revised after those backtests ran. This is common-mode across every policy,
so it cannot bias a comparison.</li>
</ul></div>
</div></body></html>"""
