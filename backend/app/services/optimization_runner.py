import vectorbt as vbt
import pandas as pd
import numpy as np
import io
import sys
import contextlib
import re
import traceback
import itertools
import warnings
from datetime import datetime

# Suppress VBT warnings during optimization (expected with param arrays and WFO)
warnings.filterwarnings('ignore', message='.*multiple columns.*')
warnings.filterwarnings('ignore', message='.*Aggregating using.*')
warnings.filterwarnings('ignore', message='.*requires frequency to be set.*')
warnings.filterwarnings('ignore', message='.*Changing the frequency will create a copy.*')

# Import True WFO helpers
from app.services.true_wfo_implementation import (
    extract_dates_from_code,
    calculate_window_configs,
    modify_code_dates,
    modify_code_dates_and_params
)
from app.services.executor import _apply_ticker_override
from app.services.signal_extractor import extract_ticker_from_code
from app.services.wfo_metrics import compute_ohlcv_from_data
from typing import List, Optional


def _override_dates_in_code(code: str, config: dict) -> str:
    """Replace start/end dates in strategy code with config dates if provided."""
    wfo = config.get("wfo", {})
    start_date = wfo.get("start_date")
    end_date = wfo.get("end_date")
    if not start_date or not end_date:
        return code

    modified = code
    # Replace standalone start / end variable assignments
    modified = re.sub(
        r"""^(\s*start\s*=\s*['"])\d{4}-\d{2}-\d{2}(['"])""",
        rf"\g<1>{start_date}\g<2>",
        modified,
        flags=re.MULTILINE
    )
    modified = re.sub(
        r"""^(\s*end\s*=\s*['"])\d{4}-\d{2}-\d{2}(['"])""",
        rf"\g<1>{end_date}\g<2>",
        modified,
        flags=re.MULTILINE
    )
    return modified


def run_optimization(code: str, strategy_params: dict, config: dict, tickers: Optional[List[str]] = None):
    """
    Executes Optimization using VBT-native array parameter injection.

    Uses vectorbt's built-in broadcasting when arrays are passed to
    indicator .run() methods. Based on Pattern #5 from CONTEXT.md.
    """
    output_buffer = io.StringIO()
    result = {
        "mode": config.get("mode", "simple"),
        "best_equity": [],
        "oos_equity": [],
        "benchmark_equity": [],
        "heatmap": [],
        "windows": [],
        "output": ""
    }

    try:
        # 1. Parameter Grid Generation
        param_names = []
        param_values_list = []

        for name, def_val in strategy_params.items():
            vals = []
            if isinstance(def_val, dict) and "start" in def_val:
                start = float(def_val["start"])
                stop = float(def_val["stop"])
                step = float(def_val["step"])
                # Inclusive arange
                vals = np.arange(start, stop + step/1000, step).tolist()
                # Round for cleaner display
                vals = [round(x, 4) if isinstance(x, float) else x for x in vals]
                if int(step) == step and int(start) == start:
                    vals = [int(x) for x in vals]
            else:
                try:
                    vals = eval(str(def_val)) if isinstance(def_val, str) and def_val.strip().startswith("[") else def_val
                    if not isinstance(vals, list):
                        vals = [vals]
                except:
                    vals = [def_val]

            param_names.append(name)
            param_values_list.append(vals)

        # Generate Cartesian Product for result mapping
        combinations = list(itertools.product(*param_values_list))
        n_sims = len(combinations)
        result["output"] += f"Parameter Grid: {n_sims} combinations\n"


        # 2. Cartesian Product Parameter Injection
        # When we have parameters like fast_window=[10,20,30,40,50] and slow_window=[100,120,140,...,200]
        # We need the parameter arrays passed to VBT to have EQUAL LENGTH.
        # VBT's MA.run(price, [10,20,30,40,50]) creates 5 column output
        # VBT's MA.run(price, [100,120,...,200]) creates 6 column output
        # Comparing 5-col vs 6-col fails with shape mismatch!
        #
        # SOLUTION: Expand each parameter to the full Cartesian product.
        # combinations = [(10,100), (10,120), ..., (50,200)] = 30 entries
        # fast_window = [10,10,10,10,10,10, 20,20,20,20,20,20, ...] = 30 values
        # slow_window = [100,120,140,160,180,200, 100,120,...] = 30 values
        # Now both MA.run() calls produce 30-column outputs that align perfectly!

        # Apply ticker override if provided
        code = _apply_ticker_override(code, tickers)

        # Apply date override from config so OptimizationConfig dates take effect
        code = _override_dates_in_code(code, config)

        modified_code = code
        injection_success = False

        if len(param_values_list) > 0 and len(combinations) > 0:
            for i, name in enumerate(param_names):
                # Extract the i-th component from each combination
                # This creates an array of length n_combinations where values repeat appropriately
                aligned_values = [c[i] for c in combinations]

                # Inject this aligned array into the code
                replacement = f"{name} = np.array({aligned_values})"

                pattern = re.compile(rf"^\s*{name}\s*=\s*.*$", re.MULTILINE)
                if pattern.search(modified_code):
                    modified_code = pattern.sub(replacement, modified_code)
                    result["output"] += f"Injected '{name}' with {len(aligned_values)} values (aligned to full grid)\n"
                    injection_success = True
                else:
                    # Try to suggest similar variable names
                    all_assignments = re.findall(r"^\s*(\w+)\s*=\s*\d+", code, re.MULTILINE)
                    suggestions = [v for v in all_assignments if v.startswith(name[:4]) or name.startswith(v[:4])]
                    warning = f"Warning: Could not find parameter '{name}' in code."
                    if suggestions:
                        warning += f" Did you mean one of: {suggestions}?"
                    result["output"] += warning + "\n"


        # 3. Code Transformation for VBT Compatibility
        # Convert raw comparison operators to VBT-safe patterns when dealing with .ma outputs
        # This handles scripts that use `fast_ema > slow_sma` instead of VBT methods

        # Pattern: `some_ma.ma > other_ma.ma` -> VBT handles this with broadcasting
        # But the issue is when comparing vbt.MA objects directly
        # Transform `var = indicator.ma > other.ma` patterns for safety
        # Note: Only apply if there's actual parameter injection happening

        if injection_success:
            # No transformation needed - VBT's run() with arrays handles this
            # The script must use VBT methods like ma_above(), ma_crossed_above()
            # OR the comparison operators will work if both sides have same columns
            pass

        # 3. Execution
        try:
            with contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(output_buffer):
                # Build execution globals with required imports
                from app.services.data_service import SafeDataService, safe_get_data
                # vectorbt 1.0.0 requires a global frequency for time-based
                # metrics/optimization; otherwise it raises
                # "Index frequency is None. Pass it as `freq`...".
                try:
                    vbt.settings.array_wrapper.freq = "D"
                except Exception:
                    pass
                exec_globals = {
                    "vbt": vbt,
                    "pd": pd,
                    "np": np,
                    "DataService": SafeDataService,
                    "get_data": safe_get_data,
                }
                exec(modified_code, exec_globals)

                if 'pf' not in exec_globals:
                    raise ValueError("Strategy code must define a 'pf' object.")
                pf = exec_globals['pf']

                if pf.wrapper.shape[0] == 0:
                    raise ValueError("Portfolio is empty. Check data download.")
        except ValueError as e:
            if "cannot join with no overlapping index names" in str(e):
                raise ValueError(
                    "Optimization Error: Strategy code uses operators (>, <, &) that don't work with multiple parameter combinations. "
                    "For optimization, use VBT methods like ma_above(), ma_below(), and vbt.And() instead of direct comparisons. "
                    "Example: Replace 'entries = (fast_ma.ma > slow_ma.ma) & (rsi.rsi < 30)' with "
                    "'entries = vbt.And(fast_ma.ma_above(slow_ma.ma), rsi.rsi_below(30))'"
                )
            raise

        # 4. Mode Handling
        mode = config.get("mode", "simple")
        metric_name = config.get("metric", "total_return")

        def get_metric(wrapper_or_returns):
            if metric_name == "sharpe": return wrapper_or_returns.sharpe_ratio()
            if metric_name == "sortino": return wrapper_or_returns.sortino_ratio()
            if metric_name == "max_dd": return wrapper_or_returns.max_drawdown()
            return wrapper_or_returns.total_return()

        if mode == "simple":
            result["output"] += "Running Simple Optimization (VBT Native)...\n"
            metrics = get_metric(pf)

            # Handle scalar result (single simulation)
            if isinstance(metrics, (int, float, np.number)):
                metrics = pd.Series([metrics], index=[0])

            heatmap_data = []
            if not param_names:
                if len(metrics) > 0:
                    result["heatmap"] = [{"param": "default", "metric": float(metrics.iloc[0])}]
            else:
                # VBT creates columns based on parameter values
                # Metrics index/columns match the parameter array order
                loop_count = min(len(combinations), len(metrics))

                # Limit heatmap entries to prevent localStorage quota exceeded
                # Only store top results to keep data size manageable
                max_heatmap_entries = 100

                for i in range(loop_count):
                    val = metrics.iloc[i]
                    combo = combinations[i]
                    entry = {"metric": float(val) if not np.isnan(val) else 0.0}
                    for p_idx, p_name in enumerate(param_names):
                        entry[p_name] = combo[p_idx]
                    heatmap_data.append(entry)

                    # Stop after max entries to prevent quota exceeded
                    if len(heatmap_data) >= max_heatmap_entries:
                        result["output"] += f"Warning: Heatmap limited to {max_heatmap_entries} entries to prevent storage overflow\n"
                        break

                result["heatmap"] = heatmap_data

            # Best Param Extraction
            if len(metrics) > 0:
                best_idx_int = int(np.nanargmax(metrics.values))
                best_metric = metrics.iloc[best_idx_int]
                result["output"] += f"Best Index: {best_idx_int}, Metric: {best_metric:.4f}\n"

                if best_idx_int < len(combinations):
                    best_combo = combinations[best_idx_int]
                    for p_idx, p_name in enumerate(param_names):
                        result["output"] += f"  {p_name}: {best_combo[p_idx]}\n"

                # Best Equity Curve
                try:
                    # Get portfolio value as DataFrame/Series
                    pf_value = pf.value()

                    if isinstance(pf_value, pd.DataFrame):
                        # Multiple columns - select the best one by index
                        if pf_value.shape[1] > best_idx_int:
                            best_equity = pf_value.iloc[:, best_idx_int]
                        else:
                            best_equity = pf_value.iloc[:, 0]
                    elif isinstance(pf_value, pd.Series):
                        best_equity = pf_value
                    else:
                        # Scalar or unknown - skip
                        best_equity = None

                    if best_equity is not None:
                        result["best_equity"] = [
                            {"time": t.timestamp(), "value": float(v)}
                            for t, v in best_equity.items()
                        ]

                        # Also set 'equity' in Dashboard format (time as Unix timestamp)
                        result["equity"] = [
                            {"time": t.timestamp(), "value": float(v)}
                            for t, v in best_equity.items()
                        ]


                        result["output"] += f"Equity curve extracted: {len(best_equity)} points\n"
                except Exception as eq_err:
                    result["output"] += f"Warning: Could not extract equity curve: {eq_err}\n"

                # Extract stats for the best parameter combination
                try:
                    # Select only the best column from the portfolio
                    # This avoids the "aggregating using mean" issue
                    pf_value = pf.value()
                    if isinstance(pf_value, pd.DataFrame) and pf_value.shape[1] > best_idx_int:
                        # Get the column name for the best index
                        best_col = pf_value.columns[best_idx_int]
                        # Select just that column from the portfolio
                        best_pf = pf[best_col]
                        stats_series = best_pf.stats()
                    else:
                        # Single column or fallback
                        best_pf = pf
                        stats_series = pf.stats()

                    # Also try to get trade-specific stats for better reporting
                    try:
                        if hasattr(best_pf, 'trades') and best_pf.trades is not None:
                            trades = best_pf.trades
                            if hasattr(trades, 'returns'):
                                trade_returns = trades.returns
                                if trade_returns is not None and len(trade_returns) > 0:
                                    winning = trade_returns[trade_returns > 0]
                                    if len(winning) > 0:
                                        stats_series['Avg Winning Trade [%]'] = winning.mean() * 100
                                        # Duration for winning trades
                                        if hasattr(trades, 'duration'):
                                            durations = trades.duration
                                            if durations is not None:
                                                win_durations = durations[trade_returns > 0]
                                                if len(win_durations) > 0:
                                                    avg_win_dur = win_durations.mean()
                                                    if hasattr(avg_win_dur, 'total_seconds'):
                                                        stats_series['Avg Winning Trade Duration'] = avg_win_dur
                                    losing = trade_returns[trade_returns < 0]
                                    if len(losing) > 0:
                                        stats_series['Avg Losing Trade [%]'] = losing.mean() * 100
                                        if hasattr(trades, 'duration'):
                                            durations = trades.duration
                                            if durations is not None:
                                                lose_durations = durations[trade_returns < 0]
                                                if len(lose_durations) > 0:
                                                    avg_lose_dur = lose_durations.mean()
                                                    if hasattr(avg_lose_dur, 'total_seconds'):
                                                        stats_series['Avg Losing Trade Duration'] = avg_lose_dur
                    except Exception as trade_stats_err:
                        pass  # Trade stats are optional

                    try:
                        raw_stats = stats_series.astype(object).where(pd.notnull(stats_series), None).to_dict()
                        result["stats"] = _clean_stats_for_json(raw_stats)
                    except Exception as stats_clean_err:
                        result["output"] += f"Warning: Could not clean stats: {stats_clean_err}\n"
                        # Fallback: just convert to dict directly
                        result["stats"] = dict(stats_series)

                    # Add the best parameter info to stats
                    if best_idx_int < len(combinations):
                        best_combo = combinations[best_idx_int]
                        for p_idx, p_name in enumerate(param_names):
                            result["stats"][f"Best {p_name}"] = best_combo[p_idx]

                    result["output"] += f"Stats extracted for best parameter (idx={best_idx_int})\n"

                    # --- BENCHMARK STATS ---
                    # Calculate benchmark (buy & hold) stats
                    try:
                        if hasattr(best_pf, 'close'):
                            price = best_pf.close
                            if isinstance(price, pd.DataFrame):
                                price = price.iloc[:, 0]
                            elif isinstance(price, pd.Series):
                                pass  # Already a Series
                            else:
                                price = None

                            if price is not None and len(price) > 0:
                                bench_pf = vbt.Portfolio.from_holding(price, freq='1D')
                                raw_bench_stats = bench_pf.stats().astype(object).where(pd.notnull(bench_pf.stats()), None).to_dict()
                                bench_stats = _clean_stats_for_json(raw_bench_stats)

                                for k, v in bench_stats.items():
                                    result["stats"][f"Benchmark {k}"] = v

                                # Explicitly add Benchmark Sharpe Ratio
                                try:
                                    bench_sharpe = bench_pf.sharpe_ratio(freq='1D')
                                    if hasattr(bench_sharpe, 'item'):
                                        bench_sharpe = bench_sharpe.item()
                                    result["stats"]["Benchmark Sharpe Ratio"] = bench_sharpe
                                except:
                                    pass

                                # Benchmark drawdown series
                                bench_dd = (bench_pf.drawdown() * 100).replace({np.nan: None})
                                result["benchmark_drawdown"] = {str(k): v for k, v in bench_dd.to_dict().items()}
                                result["output"] += "Benchmark stats extracted\n"
                    except Exception as bench_err:
                        result["output"] += f"Warning: Benchmark extraction failed: {bench_err}\n"

                except Exception as stats_err:
                    result["output"] += f"Warning: Could not extract stats: {stats_err}\n"

                # Extract trades for the best parameter combination - using executor.py approach
                try:
                    # Get the best portfolio - either from stats section or reconstruct it
                    pf_for_trades = None

                    # Try to get from existing best_pf variable
                    try:
                        pf_for_trades = best_pf  # type: ignore[possibly-unbound]
                    except NameError:
                        pass

                    # If best_pf doesn't exist, try to get it from the main portfolio
                    if pf_for_trades is None:
                        pf_value = pf.value()
                        if isinstance(pf_value, pd.DataFrame) and pf_value.shape[1] > best_idx_int:
                            pf_for_trades = pf.iloc[:, best_idx_int]
                        else:
                            pf_for_trades = pf

                    if pf_for_trades is not None:
                        # Extract trades using the same logic as executor.py
                        trades = []
                        trade_records = None

                        # Try pf.trades.records first
                        if hasattr(pf_for_trades, 'trades') and pf_for_trades.trades is not None:
                            try:
                                trade_records = pf_for_trades.trades.records
                                result["output"] += f"Found pf.trades.records\n"
                            except Exception as e:
                                result["output"] += f"Warning: Could not access trades: {e}\n"

                        # If no trades, try orders
                        if (trade_records is None or len(trade_records) == 0) and hasattr(pf_for_trades, 'orders') and pf_for_trades.orders is not None:
                            try:
                                trade_records = pf_for_trades.orders.records
                                result["output"] += f"Found pf.orders.records\n"
                            except Exception as e:
                                result["output"] += f"Warning: Could not access orders: {e}\n"

                        if trade_records is None:
                            result["trades"] = []
                            result["output"] += "No trade or order records found\n"
                        else:
                            # Handle numpy arrays (VectorBT returns numpy array, not DataFrame)
                            try:
                                if isinstance(trade_records, np.ndarray):
                                    # Convert numpy array to list of dicts
                                    trade_list = []
                                    for record in trade_records:
                                        trade_list.append({
                                            'entry_idx': record['entry_idx'],
                                            'exit_idx': record['exit_idx'],
                                            'size': record['size'],
                                            'entry_price': record['entry_price'],
                                            'exit_price': record['exit_price'],
                                            'pnl': record.get('pnl', 0) if hasattr(record, 'get') else 0
                                        })
                                    result["output"] += f"Converted {len(trade_list)} trades from numpy array\n"
                                elif hasattr(trade_records, 'to_dict'):
                                    trade_list = trade_records.to_dict('records')
                                else:
                                    trade_list = list(trade_records)
                            except Exception as e:
                                result["output"] += f"Error converting trade records: {e}\n"
                                trade_list = []

                            if not trade_list or len(trade_list) == 0:
                                result["trades"] = []
                                result["output"] += "No trade records to process\n"
                            else:
                                # Get the index (dates/times) from the portfolio
                                close_series = pf_for_trades.close
                                if isinstance(close_series, pd.DataFrame):
                                    close_series = close_series.iloc[:, 0]

                                index = close_series.index

                                for trade in trade_list:
                                    try:
                                        # Extract entry info
                                        entry_idx = int(trade.get('entry_idx', 0))
                                        exit_idx = int(trade.get('exit_idx', 0))
                                        size = float(trade.get('size', 0))
                                        entry_price = float(trade.get('entry_price', 0))
                                        exit_price = float(trade.get('exit_price', 0))
                                        pnl = trade.get('pnl', 0)

                                        # Get entry time
                                        entry_ts = 0
                                        if entry_idx < len(index):
                                            entry_time = index[entry_idx]
                                            if hasattr(entry_time, 'timestamp'):
                                                entry_ts = entry_time.timestamp()
                                            else:
                                                entry_ts = pd.to_datetime(entry_time).timestamp()

                                        # Get exit time
                                        exit_ts = 0
                                        if exit_idx < len(index):
                                            exit_time = index[exit_idx]
                                            if hasattr(exit_time, 'timestamp'):
                                                exit_ts = exit_time.timestamp()
                                            else:
                                                exit_ts = pd.to_datetime(exit_time).timestamp()

                                        # Add entry (buy) marker
                                        if entry_ts > 0:
                                            trades.append({
                                                'time': float(entry_ts),
                                                'price': float(entry_price),
                                                'type': 'buy',
                                                'size': float(abs(size)),
                                                'pnl': float(pnl) if not pd.isna(pnl) else 0
                                            })

                                        # Add exit (sell) marker
                                        if exit_ts > 0:
                                            trades.append({
                                                'time': float(exit_ts),
                                                'price': float(exit_price),
                                                'type': 'sell',
                                                'size': float(abs(size)),
                                                'pnl': float(pnl) if not pd.isna(pnl) else 0
                                            })

                                    except Exception as e:
                                        result["output"] += f"Error processing trade record: {e}\n"
                                        continue

                                # Sort by time
                                trades.sort(key=lambda x: x['time'])
                                result["trades"] = trades
                                result["output"] += f"Extracted {len(trades)} trade markers for best run\n"
                    else:
                        result["trades"] = []
                        result["output"] += "Warning: Could not get portfolio for trade extraction\n"
                except Exception as trade_err:
                    result["trades"] = []
                    result["output"] += f"Warning: Could not extract trades: {trade_err}\n"

                # Extract OHLCV data if available
                try:
                    ohlcv_records = []

                    # Primary: fetch from local data service using explicit code dates/ticker
                    try:
                        ticker = extract_ticker_from_code(code)
                        dates = extract_dates_from_code(code)
                        if ticker and dates:
                            start_date, end_date = dates
                            service_records = compute_ohlcv_from_data(ticker, start_date, end_date)
                            if len(service_records) >= 2:
                                ohlcv_records = service_records
                                result["output"] += f"OHLCV data fetched from service: {len(ohlcv_records)} bars\n"
                    except Exception as svc_err:
                        result["output"] += f"Debug: OHLCV service fetch skipped: {svc_err}\n"

                    # Fallback: extract from strategy's data variable
                    if not ohlcv_records and 'data' in exec_globals:
                        d = exec_globals['data']
                        source_df = None

                        # Unwrap vbt.Data
                        if hasattr(d, 'get'):
                            try:
                                unwrapped = d.get()
                                if isinstance(unwrapped, pd.DataFrame):
                                    source_df = unwrapped
                            except:
                                pass
                        # DataFrame.get() exists but requires a key argument,
                        # so the unwrap above may fail silently. Fall back directly.
                        if source_df is None and isinstance(d, pd.DataFrame):
                            source_df = d

                        if source_df is not None:
                            # Handle MultiIndex columns
                            if isinstance(source_df.columns, pd.MultiIndex):
                                source_df.columns = ['_'.join(map(str, col)).strip() for col in source_df.columns.values]

                            # Find columns
                            lower_cols = {c.lower(): c for c in source_df.columns}

                            def find_col(keyword):
                                for c_lower, c_orig in lower_cols.items():
                                    if keyword in c_lower:
                                        return source_df[c_orig]
                                return None

                            s_open = find_col('open')
                            s_high = find_col('high')
                            s_low = find_col('low')
                            s_close = find_col('close')
                            s_vol = find_col('volume')

                            if s_close is not None:
                                if s_open is None: s_open = s_close
                                if s_high is None: s_high = s_close
                                if s_low is None: s_low = s_close

                                idx = s_close.index

                                for i in range(len(idx)):
                                    try:
                                        t = idx[i]
                                        ts = t.timestamp() if hasattr(t, 'timestamp') else pd.to_datetime(t).timestamp()
                                        ohlcv_records.append({
                                            "time": float(ts),
                                            "open": float(s_open.values[i]),
                                            "high": float(s_high.values[i]),
                                            "low": float(s_low.values[i]),
                                            "close": float(s_close.values[i]),
                                            "volume": float(s_vol.values[i]) if s_vol is not None else 0
                                        })
                                    except:
                                        continue

                                result["output"] += f"OHLCV data extracted: {len(ohlcv_records)} bars\n"

                    if ohlcv_records:
                        result["ohlcv"] = ohlcv_records

                except Exception as ohlcv_err:
                    result["output"] += f"Warning: Could not extract OHLCV: {ohlcv_err}\n"

                # Extract drawdown data
                try:
                    pf_value = pf.value()
                    if isinstance(pf_value, pd.DataFrame):
                        best_value = pf_value.iloc[:, best_idx_int]
                    else:
                        best_value = pf_value

                    # Calculate drawdown
                    cummax = best_value.cummax()
                    drawdown = (best_value - cummax) / cummax * 100
                    drawdown_clean = drawdown.replace({np.nan: None})
                    result["drawdown"] = {str(k): v for k, v in drawdown_clean.to_dict().items()}

                except Exception as dd_err:
                    result["output"] += f"Warning: Could not extract drawdown: {dd_err}\n"

            else:
                result["output"] += "Warning: No metrics calculated.\n"

        elif mode == 'true_wfo':
            # --- TRUE WFO MODE (Continuous) ---
            result["output"] += "Running True Walk-Forward Optimization (Continuous)...\n"
            from app.services.continuous_wfo import run_continuous_true_wfo
            result = run_continuous_true_wfo(
                code, modified_code, strategy_params, config,
                param_names, combinations, metric_name, result, output_buffer
            )

        elif mode == 'wfo':
            # --- WFO HISTORICAL MODE (VectorBT Native) ---
            result["output"] += "Running Walk-Forward Optimization (Historical - VectorBT Native)...\n"
            from app.services.wfo_historical import run_wfo_historical
            result = run_wfo_historical(
                code, modified_code, strategy_params, config,
                param_names, combinations, metric_name, result, output_buffer
            )

    except Exception as e:
        result["output"] += f"Optimization Error: {str(e)}\n{traceback.format_exc()}"

    result["output"] += output_buffer.getvalue()

    # Clean up any inf/nan values before returning (for JSON serialization)
    result = _clean_float_values(result)

    return result


def _clean_float_values(obj):
    """Recursively clean inf/nan float values from result for JSON serialization"""
    import math
    if isinstance(obj, dict):
        return {k: _clean_float_values(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_float_values(v) for v in obj]
    elif isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            return None
        return obj
    return obj


def _clean_stats_for_json(stats_dict):
    """Clean VBT stats dict for JSON serialization - convert Timestamps/Timedeltas to strings"""
    import math
    import pandas as pd
    import numpy as np
    cleaned = {}

    def format_duration(total_secs, include_seconds=True):
        """Format total seconds into human-readable duration string"""
        if pd.isna(total_secs) or total_secs is None:
            return None
        try:
            total_secs = float(total_secs)
        except (TypeError, ValueError):
            return str(total_secs)

        days = int(total_secs // 86400)
        hours = int((total_secs % 86400) // 3600)
        minutes = int((total_secs % 3600) // 60)
        seconds = int(total_secs % 60)

        if days > 0:
            return f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
        elif hours > 0:
            return f"{hours}h {minutes:02d}:{seconds:02d}"
        elif minutes > 0:
            return f"{minutes}m {seconds:02d}s"
        else:
            return f"{seconds}s"

    for k, v in stats_dict.items():
        # Skip None/null/NaN values
        if v is None or (isinstance(v, float) and math.isnan(v)):
            cleaned[k] = None
            continue

        # Handle pandas NaT (Not a Time) for timedeltas - check with pd.isna
        try:
            if pd.isna(v):
                cleaned[k] = None
                continue
        except:
            pass

        # Timestamps - convert to string
        if hasattr(v, 'timestamp') and callable(getattr(v, 'timestamp')):
            try:
                cleaned[k] = str(v)
            except:
                cleaned[k] = None
            continue

        # Timedeltas - check multiple ways (pd.Timedelta, datetime.timedelta, etc.)
        is_timedelta = False
        try:
            # pandas Timedelta
            if isinstance(v, pd.Timedelta):
                is_timedelta = True
            # datetime.timedelta (check by presence of total_seconds)
            elif hasattr(v, 'total_seconds') and callable(getattr(v, 'total_seconds')):
                is_timedelta = True
            # numpy timedelta64
            elif isinstance(v, np.timedelta64):
                is_timedelta = True
        except:
            pass

        if is_timedelta:
            try:
                # Convert to total seconds
                if isinstance(v, pd.Timedelta):
                    total_secs = v.total_seconds()  # type: ignore[union-attr]
                elif hasattr(v, 'total_seconds'):
                    total_secs = v.total_seconds()  # type: ignore[union-attr]
                elif isinstance(v, np.timedelta64):
                    total_secs = v / np.timedelta64(1, 's')
                else:
                    total_secs = 0

                # Format Duration and Period fields
                if 'Duration' in k or 'Period' in k or 'period' in k.lower():
                    cleaned[k] = format_duration(total_secs)
                else:
                    # Other timedeltas - format as days + time
                    cleaned[k] = format_duration(total_secs)
            except Exception as e:
                # Fallback: convert to string
                cleaned[k] = str(v)
            continue

        # Numeric types (float, int, numpy types) - keep as numbers, but clean inf/nan
        if isinstance(v, (float, int, np.floating, np.integer, np.number)):
            try:
                if isinstance(v, (float, np.floating, np.number)):
                    if math.isinf(v) or math.isnan(v):
                        cleaned[k] = None
                    else:
                        cleaned[k] = float(v)
                else:
                    cleaned[k] = int(v) if isinstance(v, (int, np.integer)) else float(v)
            except:
                cleaned[k] = None
            continue

        # For any other type, convert to string
        cleaned[k] = str(v) if v is not None else None

    return cleaned
