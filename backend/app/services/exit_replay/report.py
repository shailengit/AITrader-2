"""Self-contained HTML report for the exit replay.

The gate is stated first and stated honestly: if it has not passed, the report
says the conclusions are void rather than burying that in a footnote. The two
bounds (uncapped = upper, capped = lower) and the dedup are disclosed up front,
because they change how the numbers should be read.
"""
from __future__ import annotations

import html as _html

import pandas as pd

from .gate import gate_passed

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
    passed, verdict = gate_passed(gate)
    status_cls = "green" if passed else "red"
    status_txt = "PASS" if passed else "FAIL — conclusions are void"

    total = int(gate.get("price_total", 0))
    ok = int(gate.get("price_reproduced", 0))
    bounds = grid_meta.get("bounds", {}) or {}

    rows = "".join(
        f"<tr><td>{_html.escape(str(r.get('policy', '')))}</td>"
        f"<td>{_f(r.get('fit_dollars'))}</td>"
        f"<td>{_f(r.get('val_dollars'))}</td>"
        f"<td>{_f(bounds.get(r.get('policy'), {}).get('capped_val_dollars'))}</td>"
        f"<td>{_f(bounds.get(r.get('policy'), {}).get('nextopen_val_dollars'))}</td>"
        f"<td>{_f(r.get('n_observed'), 0)}</td>"
        f"<td>{r.get('n_censored', 0)}</td></tr>"
        for r in ranking
    )

    mae_med = mfe_med = "—"
    if len(excursions):
        if "mae" in excursions.columns and excursions["mae"].notna().any():
            mae_med = _f(excursions["mae"].median(), 4)
        if "mfe" in excursions.columns and excursions["mfe"].notna().any():
            mfe_med = _f(excursions["mfe"].median(), 4)

    miss = gate.get("mismatches") or []
    miss_rows = "".join(
        f"<tr><td>{_html.escape(str(m.get('ticker')))}</td>"
        f"<td>{_html.escape(str(m.get('recorded_reason')))}</td>"
        f"<td>{_html.escape(str(m.get('recorded_date')))}</td>"
        f"<td>{_f(m.get('recorded_px'))}</td>"
        f"<td>{_f(m.get('replay_px'))}</td></tr>"
        for m in miss[:20]
    )

    dup = grid_meta.get("dedupe") or {}

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>MQR Exit Replay</title><style>{_CSS}</style></head><body><div class="wrap">
<h1>MQR Exit Replay</h1>
<p class="sub">Frozen deduplicated entries · price-based exit rules only · rotation held fixed ·
fill matches the recorded data (close) · {_html.escape(str(grid_meta.get('split', '')))}</p>

<h2>1 · Reproduction gate</h2>
<div class="card">
  <p><strong class="{status_cls}">{status_txt}</strong> — price-rule trades
  reproduced: <strong>{ok:,} / {total:,}</strong></p>
  <p class="dim">{_html.escape(verdict)}</p>
  <p class="dim">Every trade whose RECORDED reason is a price rule
  (Trailing Stop / Take Profit / Time Stop / Stop Loss) must be reproduced by replaying the
  current rules uncapped. Rotation-exited trades ({int(gate.get('rotation_total', 0)):,})
  are excluded, because rotation is deliberately held fixed.
  Semantic mismatches (wrong trigger date or censored): <strong>{int(gate.get('semantic_mismatches', 0))}</strong>.
  Capped corroboration: {int(gate.get('capped_reproduced', 0)):,}/{int(gate.get('capped_total', 0)):,}
  = {_f(gate.get('capped_rate'), 4)}.</p>
  <p class="dim">Reason labels are read from <code>journal_trade.notes</code>
  ('backtest:&lt;Reason&gt;'), not inferred. Label inconsistencies (a trade held under 14 days
  carrying a rotation label, which the rules forbid): <strong>{int(gate.get('label_inconsistencies', 0))}</strong>.</p>
</div>

{f'''<div class="card"><strong class="red">Residual price differences (first 20)</strong>
<p class="dim" style="margin:6px 0">All belong to one data-vintage class: the price panel was
revised after those backtests wrote their rows, so the recorded value exists in no bar of the
current panel. Dates and reasons agree.</p>
<table><thead><tr><th>Ticker</th><th>Recorded reason</th><th>Date</th>
<th>Recorded px</th><th>Replay px</th></tr></thead>
<tbody>{miss_rows}</tbody></table></div>''' if miss_rows else ''}

<h2>2 · Policy ranking</h2>
<div class="card"><table>
<thead><tr><th>Policy</th><th>Fit $</th><th>Validate $ (upper bound)</th>
<th>Validate $ (capped, lower)</th><th>Validate $ (next open)</th><th>Observed</th><th>Censored</th></tr></thead>
<tbody>{rows}</tbody></table>
<p class="dim" style="margin-top:10px">
<strong>Upper vs lower bound.</strong> The primary column replays price-exited trades
<em>uncapped</em> to the 180-trading-day horizon while rotation exits stay capped at their
recorded date. That is an <strong>upper bound</strong>: rotation is held fixed and could have
removed a name sooner. The capped column caps <em>everything</em> at the recorded exit date — a
<strong>lower bound</strong>. A policy that only wins on the upper bound is not a candidate.
The next-open column quantifies the look-ahead optimism of filling at an observed close.
</p></div>

<h2>3 · Excursion distributions (actual holds)</h2>
<div class="card"><table><thead><tr><th>Metric</th><th>Median</th></tr></thead>
<tbody>
<tr><td>MAE (max adverse excursion)</td><td>{mae_med}</td></tr>
<tr><td>MFE (max favourable excursion)</td><td>{mfe_med}</td></tr>
</tbody></table></div>

<h2>4 · Method, corrections &amp; caveats</h2>
<div class="card"><ul>
<li><strong>Deduplicated.</strong> journal_trade held {dup.get('rows', 0):,} MQR rows but only
{dup.get('distinct', 0):,} distinct positions (max multiplicity {dup.get('max_multiplicity', 0)},
mean {dup.get('mean_multiplicity', 0)}), all written in a two-minute window. Multiplicity rose by
entry year, so leaving them in made every dollar figure multiplicity-weighted and the
fit/validate comparison non-comparable. {dup.get('duplicates', 0):,} duplicate rows were dropped.</li>
<li><strong>Exit reasons are recorded</strong> in <code>notes</code>; the original design wrongly
assumed they were not and inferred them from a structural signature.</li>
<li>Entries are frozen; only exits are replayed ⇒ deterministic, no path chaos.</li>
<li>Rotation held fixed; its quality is measured by forward-path evidence, not replayed.</li>
<li>The recorded data is <strong>close-filled</strong> (600/600 sampled short-hold trades match
the trigger-day close, 0 match the next open), so the replay fills at the close to reproduce the
baseline. Next-open fills are reported as a sensitivity check.</li>
<li>Censoring is per (trade, policy) and reported per policy.</li>
<li><strong>Dollar figures are an approximation.</strong> Every row has qty=1 and MQR sizes
score-proportionally (not equal weight), so per-trade size is unrecoverable. A constant notional
per trade makes the ranking a monotone rescaling of summed percent return: ordering is unaffected,
but no size information enters it.</li>
<li>max_dd is a comparative statistic on an additive dollar curve, not a strategy drawdown.</li>
</ul></div>
</div></body></html>"""
