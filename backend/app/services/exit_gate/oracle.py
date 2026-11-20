"""Hindsight reference gate -- an upper bound on what a veto could be worth.

DANGER: this gate consumes forward returns. It is a measurement instrument, not
a policy. Never wire it into a live or deploy-able strategy; it exists so the
project can ask "if a perfect forecaster ran the gate, would it be worth
building a real one?" before spending days on a model.

Slot-aware by construction: the alternative to holding is the best feasible
candidate the freed slot could buy today, falling back to cash (0.0) when
nothing is buyable. A frozen-entry version of this comparison ignores that and
overstates the gain -- the error phase 2 paid for.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from app.services.exit_gate.types import ExitContext, VetoDecision

Key = tuple[str, str]          # (ticker_lower, date_str)


def build_forward_returns(
    price_cache: Mapping[str, Mapping[str, float]],
    calendar: Sequence[str],
    horizon: int,
) -> dict[Key, Optional[float]]:
    """close(t+horizon) / close(t) - 1 per (ticker, date), using the trading calendar.

    `horizon` is in trading days. Dates with fewer than `horizon` future
    sessions are recorded as None so a caller cannot mistake "unknown" for
    "zero" -- censoring must stay visible.
    """
    idx = {d: i for i, d in enumerate(calendar)}
    last = len(calendar) - 1
    out: dict[Key, Optional[float]] = {}
    for tk, series in price_cache.items():
        for d, px in series.items():
            i = idx.get(d)
            if i is None:
                continue
            j = i + horizon
            if j > last:
                out[(tk, d)] = None
                continue
            end_px = series.get(calendar[j])
            if px is None or end_px is None or px <= 0:
                out[(tk, d)] = None
            else:
                out[(tk, d)] = float(end_px) / float(px) - 1.0
    return out


@dataclass(frozen=True)
class OracleGate:
    """Veto when holding beat the best available replacement. Hindsight only."""

    forward: Mapping[Key, Optional[float]]
    horizon: int
    margin: float = 0.0

    @property
    def gate_id(self) -> str:
        return f"oracle:h{self.horizon}"

    def _fwd(self, ticker: str, date: str) -> Optional[float]:
        return self.forward.get((ticker.lower(), date))

    def decide(self, ctx: ExitContext) -> VetoDecision:
        hold = self._fwd(ctx.ticker, ctx.as_of_date)
        if hold is None:
            return VetoDecision(veto=False, gate_id=self.gate_id,
                                reason="no observable forward return")
        repl = 0.0
        for ticker, _score in ctx.top_candidates:
            r = self._fwd(ticker, ctx.as_of_date)
            if r is not None and r > repl:
                repl = r
        veto = hold > repl + self.margin
        return VetoDecision(veto=veto, confidence=1.0, gate_id=self.gate_id,
                            reason=f"hold {hold:+.3f} vs replace {repl:+.3f}")
