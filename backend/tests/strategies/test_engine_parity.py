"""Parity tests for the StrategyEngine refactor.

Compares the refactored strategies/golden_cross.py (using strategies/engine.py)
against the original strategies/daily_golden_cross_rotation.py to ensure no
regression in aggregate KPIs.
"""
import importlib.util
import os
import sys

import pytest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
STRATEGIES_DIR = os.path.join(REPO_ROOT, "strategies")


def _load_module(name: str, path: str):
    """Load a Python file as a module without it being a package member."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_strategy_config_imports():
    engine = _load_module("strategies_engine", os.path.join(STRATEGIES_DIR, "engine.py"))
    config = engine.StrategyConfig(as_of="2022-01-01", end="2024-01-01")
    assert config.as_of == "2022-01-01"
    assert config.end == "2024-01-01"
    assert config.max_holdings == 5  # default


def test_engine_smoke_runs():
    """Engine should run with a stub config and produce a summary dict."""
    engine = _load_module("strategies_engine", os.path.join(STRATEGIES_DIR, "engine.py"))

    def fake_precompute(tickers, start, end):
        return {"AAPL": {
            "close": [100.0, 101.0, 102.0],
            "dates": ["2022-01-01", "2022-01-02", "2022-01-03"],
            "crossovers": [],
            "market_cap": 1e12,
            "sector": "Tech",
        }}

    config = engine.StrategyConfig(
        as_of="2022-01-01", end="2022-01-03", capital=10_000.0,
        precompute_fn=fake_precompute,
        entry_score_fn=lambda c, s: 0.5,
        holding_score_fn=lambda t, d, h, s: 0.5,
        exit_check_fn=lambda t, d, h, db: None,
    )
    runner = engine.StrategyEngine(config)
    result = runner.run()
    assert "summary" in result
    assert "trades" in result
    assert "daily_equity" in result


def test_safe_import_valid_file(tmp_path):
    safe = _load_module("strategies_safe_import", os.path.join(STRATEGIES_DIR, "_archive", "_safe_import.py"))
    f = tmp_path / "valid_strategy.py"
    f.write_text("MY_CONST = 42\n")
    result = safe.safe_import_strategy(str(f))
    assert result.error is None
    assert result.module.MY_CONST == 42


def test_safe_import_syntax_error(tmp_path):
    safe = _load_module("strategies_safe_import", os.path.join(STRATEGIES_DIR, "_archive", "_safe_import.py"))
    f = tmp_path / "broken.py"
    f.write_text("def broken(:\n    pass\n")
    result = safe.safe_import_strategy(str(f))
    assert result.error is not None
    assert "SyntaxError" in result.error or "invalid syntax" in result.error.lower()


def test_safe_import_missing_file():
    safe = _load_module("strategies_safe_import", os.path.join(STRATEGIES_DIR, "_archive", "_safe_import.py"))
    result = safe.safe_import_strategy("/nonexistent/path/does_not_exist.py")
    assert result.error is not None
    assert result.module is None


def test_golden_cross_parity():
    """Refactored golden_cross.py must produce KPIs within tolerance of the baseline.

    Loads the baseline_kpis.json captured in Task 2, runs the new golden_cross
    over the same window, and asserts aggregate KPIs match.
    """
    import json

    BASELINE = os.path.join(os.path.dirname(__file__), "baseline_kpis.json")
    if not os.path.exists(BASELINE):
        pytest.skip("baseline_kpis.json not yet captured — run _capture_baseline.py first")

    with open(BASELINE) as f:
        baseline = json.load(f)

    # Load the new golden_cross module (it uses _load_module for its own deps)
    gc = _load_module("golden_cross_under_test", os.path.join(STRATEGIES_DIR, "golden_cross.py"))

    # Override the window to match the baseline
    cfg = gc.build_config(
        as_of=baseline["window"]["as_of"],
        end=baseline["window"]["end"],
        capital=100_000.0,
    )

    # Load the engine and run
    engine = _load_module("strategies_engine", os.path.join(STRATEGIES_DIR, "engine.py"))
    result = engine.StrategyEngine(cfg).run()
    kpis = result["summary"]

    # Total return within 1% relative (or 1pp absolute if base is near zero)
    base_ret = baseline["kpis"]["total_return_pct"]
    new_ret = kpis["total_return_pct"]
    tol = max(1.0, abs(base_ret) * 0.01)
    assert abs(new_ret - base_ret) <= tol, (
        f"total_return_pct regression: baseline={base_ret}, new={new_ret}, tol={tol}"
    )

    # Trade count within 5 absolute
    base_n = baseline["kpis"]["n_trades"]
    new_n = kpis["total_trades"]
    assert abs(new_n - base_n) <= 5, (
        f"n_trades regression: baseline={base_n}, new={new_n}"
    )

    # Win rate within 5pp absolute
    base_wr = baseline["kpis"]["win_rate"]
    new_wr = kpis["win_rate"]
    assert abs(new_wr - base_wr) <= 5.0, (
        f"win_rate regression: baseline={base_wr}, new={new_wr}"
    )

    # Exit reason distribution should be qualitatively similar
    base_reasons = baseline["exit_reason_counts"]
    new_reasons = kpis["exit_reasons"]
    if "Death Cross" in base_reasons and base_reasons["Death Cross"] > 10:
        assert "Death Cross" in new_reasons, "Death Cross exits missing"
        assert new_reasons["Death Cross"] > 0, "No Death Cross exits generated"
