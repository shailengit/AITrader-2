"""Render backtest runs as Obsidian notes: one note per run plus a batch index.

Pure rendering (no DB), so it is unit-testable and reusable by an API endpoint
later. The notes are deliberately plain Markdown with YAML frontmatter: that is
what Obsidian indexes, and it means the same files are readable by any tool.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

#: Rows kept in the note's full trade table; the rest stay in the database.
MAX_TABLE_ROWS = 500


def safe_name(value: str) -> str:
    """Filesystem- and wikilink-safe name: spaces -> dashes, no path characters."""
    s = re.sub(r"[^A-Za-z0-9._ -]+", "", str(value or "")).strip()
    s = re.sub(r"\s+", "-", s)
    return s or "unnamed"


def _fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return str(value)


def _yaml_str(value: Any) -> str:
    return '"' + str(value).replace('"', '\\"') + '"'


def _frontmatter(d: Dict[str, Any]) -> List[str]:
    return [
        "---",
        "tags: [tradecraft, backtest]",
        f"strategy: {_yaml_str(d.get('strategy_name'))}",
        f"batch: {_yaml_str(d.get('batch'))}",
        f"run: {d.get('run_index')}",
        f"start: {d.get('start_date')}",
        f"end: {d.get('end_date')}",
        f"cagr: {_fmt(d.get('cagr_pct'))}",
        f"sharpe: {_fmt(d.get('sharpe_ratio'))}",
        f"max_drawdown: {_fmt(d.get('max_drawdown_pct'))}",
        f"trades: {d.get('n_sells', d.get('total_trades', 0))}",
        f"win_rate: {_fmt(d.get('win_rate'))}",
        "---",
        "",
    ]


def _trade_rows(trades: List[Dict[str, Any]], limit: int = MAX_TABLE_ROWS) -> List[str]:
    def sort_key(t):
        return (str(t.get("entry_date") or ""), str(t.get("exit_date") or ""),
                str(t.get("ticker") or ""))
    rows = [
        "| Entry | Exit | Ticker | Side | Entry px | Exit px | Return % | Hold (d) | Reason | P&L |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for t in sorted(trades, key=sort_key)[:limit]:
        rows.append(
            f"| {str(t.get('entry_date'))[:10]} | {str(t.get('exit_date') or '')[:10]} "
            f"| {t.get('ticker')} | {t.get('side')} "
            f"| {_fmt(t.get('entry_price'))} | {_fmt(t.get('exit_price'))} "
            f"| {_fmt(t.get('return_pct'))} | {t.get('holding_days')} "
            f"| {t.get('exit_reason') or ''} | {_fmt(t.get('pnl_dollars'))} |")
    return rows


def render_run_note(d: Dict[str, Any]) -> str:
    run = int(d.get("run_index") or 0)
    lines = _frontmatter(d)
    lines += [f"# Run {run:03d}", "", f"Batch: [[00 Index]] · {d.get('batch')}", "",
              "## KPIs", "",
              "| Metric | Value |", "|---|---|",
              f"| Start | {d.get('start_date')} |",
              f"| End | {d.get('end_date')} |",
              f"| CAGR | {_fmt(d.get('cagr_pct'), suffix='%')} |",
              f"| Sharpe | {_fmt(d.get('sharpe_ratio'))} |",
              f"| Max drawdown | {_fmt(d.get('max_drawdown_pct'), suffix='%')} |",
              f"| Trades (round trips) | {d.get('n_sells', d.get('total_trades', 0))} |",
              f"| Win rate | {_fmt(d.get('win_rate'), 1, '%')} |",
              ""]

    exits = d.get("exit_reasons") or {}
    lines += ["## Exit reasons", "", "| Reason | n | P&L | Win rate | Avg hold (d) |", "|---|---|---|---|---|"]
    for reason, v in sorted(exits.items(), key=lambda kv: -(kv[1].get("pnl") or 0)):
        lines.append(
            f"| {reason} | {v.get('n', 0)} | {_fmt(v.get('pnl'))} "
            f"| {_fmt(v.get('win_rate'), 1, '%')} | {_fmt(v.get('avg_holding_days'), 1)} |")
    lines.append("")

    hold = d.get("holding_days") or {}
    if hold:
        lines += ["## Holding period", "",
                  f"mean {_fmt(hold.get('mean'), 1)}d · median {hold.get('median')}d "
                  f"· p10 {hold.get('p10')}d · p90 {hold.get('p90')}d · max {hold.get('max')}d", ""]

    for title, key in (("Top winners", "top_winners"), ("Worst contributors", "top_losers")):
        items = d.get(key) or []
        if not items:
            continue
        lines += [f"## {title}", "",
                  "| Ticker | Entry | Exit | Return % | Hold (d) | Reason | P&L |",
                  "|---|---|---|---|---|---|---|"]
        for t in items:
            lines.append(
                f"| {t.get('ticker')} | {str(t.get('entry_date'))[:10]} "
                f"| {str(t.get('exit_date') or '')[:10]} | {_fmt(t.get('return_pct'))} "
                f"| {t.get('holding_days')} | {t.get('exit_reason') or ''} "
                f"| {_fmt(t.get('pnl_dollars'))} |")
        lines.append("")

    trades = d.get("trades") or []
    if trades:
        lines += ["## Trades", ""] + _trade_rows(trades)
        if len(trades) > MAX_TABLE_ROWS:
            lines += ["", f"_Showing {MAX_TABLE_ROWS} of {len(trades)} rows; the full "
                          f"history is available from the TradeCraft database._"]
        lines.append("")

    lines += ["## Observations", "", "- ", ""]
    return "\n".join(lines)


def render_index(rows: List[Dict[str, Any]], strategy_name: str,
                 batch: str) -> str:
    lines = [f"# {strategy_name}", "", f"Batch `{batch}` · {len(rows)} runs", "",
             "| Run | Start | CAGR | Sharpe | Max DD | Trades | Win % |",
             "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: int(x.get("run_index") or 0)):
        run = int(r.get("run_index") or 0)
        lines.append(
            f"| [[Run {run:03d}]] | {r.get('start_date')} "
            f"| {_fmt(r.get('cagr_pct'))} | {_fmt(r.get('sharpe_ratio'))} "
            f"| {_fmt(r.get('max_drawdown_pct'))} | {r.get('total_trades')} "
            f"| {_fmt(r.get('win_rate'), 1)} |")
    lines.append("")
    if rows:
        best = max(rows, key=lambda x: float(x.get("cagr_pct") or -1e9))
        worst = min(rows, key=lambda x: float(x.get("cagr_pct") or 1e9))
        lines += ["## Extremes", "",
                  f"- Best CAGR: [[Run {int(best.get('run_index') or 0):03d}]] "
                  f"({_fmt(best.get('cagr_pct'), suffix='%')})",
                  f"- Worst CAGR: [[Run {int(worst.get('run_index') or 0):03d}]] "
                  f"({_fmt(worst.get('cagr_pct'), suffix='%')})", ""]
    return "\n".join(lines)


def export_runs(details: List[Dict[str, Any]], strategy_name: str, batch: str,
                out_dir: Path) -> List[Path]:
    """Write `Run NNN.md` for each run plus `00 Index.md`; returns the paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []

    prepared = []
    for d in details:
        note = dict(d)
        note["strategy_name"] = strategy_name
        note["batch"] = batch
        prepared.append(note)

    index = render_index(prepared, strategy_name, batch)
    index_path = out_dir / "00 Index.md"
    index_path.write_text(index, encoding="utf-8")
    written.append(index_path)

    for d in prepared:
        run = int(d.get("run_index") or 0)
        path = out_dir / f"Run {run:03d}.md"
        path.write_text(render_run_note(d), encoding="utf-8")
        written.append(path)
    return written
