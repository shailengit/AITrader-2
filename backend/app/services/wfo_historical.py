"""
Walk-Forward Optimization (Historical) using VectorBT's native WFO capabilities.

This is the standard WFO approach where:
1. Data is split into multiple train/test windows
2. For each window:
   - Optimize parameters on training data
   - Apply best parameters to full test period
   - Collect performance metrics
3. Aggregate results across all windows

Key differences from True WFO:
- Uses full test periods (not single-day trades)
- Windows are independent (no position/state carryover)
- Uses VectorBT's native split/optimization functionality
"""

import contextlib
import io
import warnings
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd
import numpy as np

from app.services.true_wfo_implementation import (
    extract_dates_from_code,
    calculate_window_configs,
    modify_code_dates,
    modify_code_dates_and_params
)
from app.services.wfo_metrics import compute_benchmark_from_prices

logger = logging.getLogger(__name__)


def run_wfo_historical(
    code: str,
    modified_code: str,
    strategy_params: Dict[str, Any],
    config: Dict[str, Any],
    param_names: List[str],
    combinations: List[tuple],
    metric_name: str,
    result: Dict[str, Any],
    output_buffer: io.StringIO
) -> Dict[str, Any]:
    """
    Run Walk-Forward Optimization using VectorBT's native capabilities.
    """
    from app.services.data_service import DataService

    wfo_conf = config.get("wfo", {})
    train_days = wfo_conf.get("train_days")
    test_days = wfo_conf.get("test_days")
    split_method = wfo_conf.get("splitMethod", "ratio")
    n_windows = wfo_conf.get("windows", 3)
    split_type = wfo_conf.get("type", "rolling")

    # Extract dates from code
    dates = extract_dates_from_code(code)
    if not dates:
        result["output"] += "ERROR: Could not parse dates from code\n"
        return result

    start_date, end_date = dates
    result["output"] += f"Date range: {start_date} to {end_date}\n"

    # Calculate window configurations
    window_configs = calculate_window_configs(
        start_date, end_date, n_windows,
        split_type, wfo_conf
    )

    if not window_configs:
        result["output"] += "ERROR: No valid windows could be calculated\n"
        return result

    result["output"] += f"Processing {len(window_configs)} windows...\n"

    # Get ticker
    ticker = _extract_ticker_from_code(code)
    result["output"] += f"Ticker: {ticker}\n"

    # Storage for results
    window_results = []
    all_equity_curves = []
    all_trades = []
    all_test_stats = []

    for i, cfg in enumerate(window_configs):
        result["output"] += f"\n--- Window {i+1}/{len(window_configs)} ---\n"
        result["output"] += f"  Train: {cfg['train_start']} to {cfg['train_end']}\n"
        result["output"] += f"  Test:  {cfg['test_start']} to {cfg['test_end']}\n"

        try:
            # Step 1: Run optimization on training data
            train_code = modify_code_dates(modified_code, cfg['train_start'], cfg['train_end'])

            best_params, best_metric = _optimize_on_window(
                train_code, metric_name, param_names, combinations, output_buffer
            )

            if best_params is None:
                result["output"] += f"  Warning: Optimization failed for this window\n"
                continue

            result["output"] += f"  Best params: {best_params}\n"
            result["output"] += f"  Best metric: {best_metric:.4f}\n"

            # Step 2: Run strategy with best params on test data
            test_code = modify_code_dates_and_params(
                modified_code, cfg['test_start'], cfg['test_end'], best_params
            )

            test_result = _run_test_window(test_code, output_buffer)

            if test_result is None:
                result["output"] += f"  Warning: Test execution failed\n"
                continue

            # Collect results
            window_results.append({
                "window": i + 1,
                "train_start": cfg['train_start'],
                "train_end": cfg['train_end'],
                "test_start": cfg['test_start'],
                "test_end": cfg['test_end'],
                "best_params": best_params,
                "train_metric": float(best_metric) if best_metric is not None else 0.0,
                "test_return": test_result.get('total_return', 0),
                "test_sharpe": test_result.get('sharpe_ratio', 0),
                "test_trades": test_result.get('total_trades', 0),
            })

            # Accumulate equity curve
            if 'equity_curve' in test_result and test_result['equity_curve']:
                all_equity_curves.extend(test_result['equity_curve'])

            # Accumulate trades
            if 'trades' in test_result and test_result['trades']:
                all_trades.extend(test_result['trades'])

            # Accumulate stats
            if 'stats' in test_result and test_result['stats']:
                all_test_stats.append(test_result['stats'])

            result["output"] += f"  Test return: {test_result.get('total_return', 0):.2f}%\n"
            result["output"] += f"  Test trades: {test_result.get('total_trades', 0)}\n"

        except Exception as e:
            result["output"] += f"  Error processing window: {e}\n"
            import traceback
            result["output"] += f"  {traceback.format_exc()}\n"
            continue

    # Aggregate results
    result["windows"] = window_results
    result["mode"] = "wfo"  # Set mode for frontend

    if window_results:
        avg_train_metric = sum(w['train_metric'] for w in window_results) / len(window_results)
        avg_test_return = sum(w['test_return'] for w in window_results) / len(window_results)
        total_trades = sum(w['test_trades'] for w in window_results)

        # Build comprehensive stats dict
        stats = {
            "WFO Windows": len(window_results),
            "Avg Train Metric": avg_train_metric,
            "Avg Test Return [%]": avg_test_return,
            "Total Trades": total_trades,
            "Mode": "WFO Historical",
        }

        # Aggregate stats from all windows
        if all_test_stats:
            # Sum up trades
            total_trades = sum(s.get('Total Trades', 0) for s in all_test_stats)
            stats['Total Trades'] = total_trades

            # Calculate win rate
            total_win_rate = sum(s.get('Win Rate [%]', 0) for s in all_test_stats) / len(all_test_stats)
            stats['Win Rate [%]'] = total_win_rate

            # Get avg return
            avg_return = sum(s.get('Total Return [%]', 0) for s in all_test_stats) / len(all_test_stats)
            stats['Total Return [%]'] = avg_return

            # Get avg sharpe
            avg_sharpe = sum(s.get('Sharpe Ratio', 0) for s in all_test_stats) / len(all_test_stats)
            stats['Sharpe Ratio'] = avg_sharpe

            # Get avg max drawdown
            avg_dd = sum(s.get('Max Drawdown [%]', 0) for s in all_test_stats) / len(all_test_stats)
            stats['Max Drawdown [%]'] = avg_dd

            # Add other key metrics
            for key in ['Avg Winning Trade [%]', 'Avg Losing Trade [%]', 'Profit Factor']:
                values = [s.get(key, 0) for s in all_test_stats if key in s]
                if values:
                    stats[key] = sum(values) / len(values)

        # Add best params from final window
        if window_results[-1].get('best_params'):
            for p_name, p_val in window_results[-1]['best_params'].items():
                stats[f"Best {p_name}"] = p_val

        result["stats"] = stats
        result["output"] += f"\nWFO Complete: {len(window_results)} windows processed\n"
        result["output"] += f"Total trades: {total_trades}\n"
    else:
        result["output"] += "\nWarning: No windows completed successfully\n"

    if all_equity_curves:
        # Set oos_equity for the WFO chart (Out-of-Sample Equity Stitched)
        result["oos_equity"] = all_equity_curves
        result["equity"] = all_equity_curves
        result["best_equity"] = all_equity_curves
        result["output"] += f"OOS Equity curve: {len(all_equity_curves)} points\n"

        # Calculate drawdown from equity curve
        try:
            drawdown_dict = _calculate_drawdown_from_equity(all_equity_curves)
            result["drawdown"] = drawdown_dict
            result["output"] += f"Drawdown calculated: {len(drawdown_dict)} points\n"
        except Exception as e:
            result["output"] += f"Warning: Could not calculate drawdown: {e}\n"

        # --- Benchmark buy-and-hold over full date range ---
        try:
            initial_val = all_equity_curves[0]["value"]
            bench_equity, bench_stats, bench_dd = compute_benchmark_from_prices(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                initial_value=initial_val,
            )
            if bench_equity:
                result["benchmark_equity"] = bench_equity
                result["output"] += f"Benchmark equity: {len(bench_equity)} points\n"
            if bench_stats:
                if "stats" not in result:
                    result["stats"] = {}
                result["stats"].update(bench_stats)
            if bench_dd:
                result["benchmark_drawdown"] = bench_dd
                result["output"] += f"Benchmark drawdown: {len(bench_dd)} points\n"
        except Exception as bench_err:
            result["output"] += f"Warning: Could not compute benchmark: {bench_err}\n"

    if all_trades:
        result["trades"] = all_trades
        result["output"] += f"Trades: {len(all_trades)} markers\n"

    # Extract OHLCV for chart
    try:
        ohlcv_data = _extract_ohlcv_for_range(ticker, start_date, end_date)
        if ohlcv_data:
            result["ohlcv"] = ohlcv_data
            result["output"] += f"OHLCV data: {len(ohlcv_data)} bars\n"
            # Debug first entry
            if len(ohlcv_data) > 0:
                first = ohlcv_data[0]
                result["output"] += f"OHLCV sample: time={first['time']} (type={type(first['time']).__name__}), open={first['open']}, high={first['high']}, low={first['low']}, close={first['close']}\n"
        else:
            result["output"] += "Warning: No OHLCV data extracted\n"
    except Exception as e:
        result["output"] += f"Warning: Could not extract OHLCV: {e}\n"
        import traceback
        result["output"] += traceback.format_exc()

    return result


def _calculate_drawdown_from_equity(equity_curve: List[Dict]) -> Dict[str, float]:
    """Calculate drawdown percentage from equity curve."""
    if not equity_curve or len(equity_curve) < 2:
        return {}

    # Convert to DataFrame for easier calculation
    df = pd.DataFrame(equity_curve)
    if 'value' not in df.columns:
        return {}

    # Calculate running maximum (peak)
    df['peak'] = df['value'].cummax()

    # Calculate drawdown percentage
    df['drawdown'] = (df['value'] - df['peak']) / df['peak'] * 100

    # Convert to dict with time as key
    drawdown_dict = {}
    for _, row in df.iterrows():
        time_key = str(row['time'])
        drawdown_dict[time_key] = float(row['drawdown']) if not pd.isna(row['drawdown']) else 0.0

    return drawdown_dict


def _optimize_on_window(
    code: str,
    metric_name: str,
    param_names: List[str],
    combinations: List[tuple],
    output_buffer: io.StringIO
) -> Tuple[Optional[Dict], Optional[float]]:
    """Optimize strategy parameters on a single window."""
    import vectorbt as vbt  # lazy: heavy import
    from app.services.data_service import SafeDataService, safe_get_data

    try:
        with contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(output_buffer):
            exec_globals = {
                "vbt": vbt,
                "pd": pd,
                "np": np,
                "DataService": SafeDataService,
                "get_data": safe_get_data,
            }
            exec(code, exec_globals)

            if 'pf' not in exec_globals:
                return None, None

            pf = exec_globals['pf']

            def get_metric(wrapper_or_returns):
                if metric_name == "sharpe":
                    return wrapper_or_returns.sharpe_ratio()
                elif metric_name == "sortino":
                    return wrapper_or_returns.sortino_ratio()
                elif metric_name == "max_dd":
                    return wrapper_or_returns.max_drawdown()
                else:
                    return wrapper_or_returns.total_return()

            metrics = get_metric(pf)

            if isinstance(metrics, pd.Series):
                if len(metrics) == 0:
                    return None, None
                best_idx = int(metrics.values.argmax())
                best_metric = metrics.iloc[best_idx]
            elif hasattr(metrics, 'argmax'):
                best_idx = int(metrics.argmax())
                best_metric = metrics[best_idx] if hasattr(metrics, '__getitem__') else float(metrics)
            else:
                best_idx = 0
                best_metric = float(metrics)

            if len(combinations) > 0 and best_idx < len(combinations):
                best_params = dict(zip(param_names, combinations[best_idx]))
            else:
                best_params = {}

            return best_params, float(best_metric)

    except Exception as e:
        output_buffer.write(f"Optimization error: {e}\n")
        return None, None


def _run_test_window(code: str, output_buffer: io.StringIO) -> Optional[Dict]:
    """Run strategy on test window with best parameters."""
    import vectorbt as vbt  # lazy: heavy import
    from app.services.data_service import SafeDataService, safe_get_data

    try:
        with contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(output_buffer):
            exec_globals = {
                "vbt": vbt,
                "pd": pd,
                "np": np,
                "DataService": SafeDataService,
                "get_data": safe_get_data,
            }
            exec(code, exec_globals)

            if 'pf' not in exec_globals:
                return None

            pf = exec_globals['pf']

            # Get portfolio value for equity curve
            pf_value = pf.value()
            if isinstance(pf_value, pd.DataFrame):
                pf_value = pf_value.iloc[:, 0] if pf_value.shape[1] > 0 else pf_value.squeeze()

            # Get stats from portfolio
            stats_series = pf.stats()

            # Convert stats to dict
            stats_dict = {}
            if hasattr(stats_series, 'to_dict'):
                stats_dict = stats_series.to_dict()

            # Extract key metrics
            total_return = stats_dict.get('Total Return [%]', 0)
            sharpe = stats_dict.get('Sharpe Ratio', 0)
            max_dd = stats_dict.get('Max Drawdown [%]', 0)
            total_trades = stats_dict.get('Total Trades', 0)
            win_rate = stats_dict.get('Win Rate [%]', 0)

            # Build equity curve
            equity_curve = []
            if isinstance(pf_value, pd.Series):
                for t, v in pf_value.items():
                    ts = t.timestamp() if hasattr(t, 'timestamp') else pd.to_datetime(t).timestamp()
                    equity_curve.append({"time": float(ts), "value": float(v)})

            # Extract trades using proper method
            trades = _extract_trades_from_portfolio(pf)

            return {
                'total_return': total_return,
                'sharpe_ratio': sharpe,
                'max_drawdown': max_dd,
                'total_trades': total_trades,
                'win_rate': win_rate,
                'equity_curve': equity_curve,
                'trades': trades,
                'stats': stats_dict,
            }

    except Exception as e:
        output_buffer.write(f"Test execution error: {e}\n")
        import traceback
        output_buffer.write(traceback.format_exc())
        return None


def _extract_trades_from_portfolio(pf) -> List[Dict]:
    """Extract trades from portfolio using proper method from executor."""
    trades: List[Dict[str, Any]] = []

    try:
        # Get trades from portfolio - try different attributes
        trade_records = None

        # Try pf.trades.records first
        if hasattr(pf, 'trades') and pf.trades is not None:
            try:
                trade_records = pf.trades.records
            except Exception as e:
                pass

        # If no trades, try orders
        if (trade_records is None or len(trade_records) == 0) and hasattr(pf, 'orders') and pf.orders is not None:
            try:
                trade_records = pf.orders.records
            except Exception as e:
                pass

        if trade_records is None:
            return trades

        # Handle numpy arrays
        if isinstance(trade_records, np.ndarray):
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
        elif hasattr(trade_records, 'to_dict'):
            trade_list = trade_records.to_dict('records')
        else:
            trade_list = list(trade_records)

        if not trade_list or len(trade_list) == 0:
            return trades

        # Get the index from the portfolio using pf.close (like executor does)
        close_series = pf.close
        if isinstance(close_series, pd.DataFrame):
            close_series = close_series.iloc[:, 0]

        index = close_series.index

        for trade in trade_list:
            try:
                entry_idx = int(trade.get('entry_idx', 0))
                exit_idx = int(trade.get('exit_idx', 0))
                size = float(trade.get('size', 0))
                entry_price = float(trade.get('entry_price', 0))
                exit_price = float(trade.get('exit_price', 0))
                pnl = trade.get('pnl', 0)

                entry_ts = 0
                if entry_idx < len(index):
                    entry_time = index[entry_idx]
                    if hasattr(entry_time, 'timestamp'):
                        entry_ts = entry_time.timestamp()
                    else:
                        entry_ts = pd.to_datetime(entry_time).timestamp()

                exit_ts = 0
                if exit_idx < len(index):
                    exit_time = index[exit_idx]
                    if hasattr(exit_time, 'timestamp'):
                        exit_ts = exit_time.timestamp()
                    else:
                        exit_ts = pd.to_datetime(exit_time).timestamp()

                if entry_ts > 0:
                    trades.append({
                        'time': float(entry_ts),
                        'price': float(entry_price),
                        'type': 'buy',
                        'size': float(abs(size)),
                        'pnl': float(pnl) if not pd.isna(pnl) else 0
                    })

                if exit_ts > 0:
                    trades.append({
                        'time': float(exit_ts),
                        'price': float(exit_price),
                        'type': 'sell',
                        'size': float(abs(size)),
                        'pnl': float(pnl) if not pd.isna(pnl) else 0
                    })

            except Exception as e:
                continue

        trades.sort(key=lambda x: x['time'])  # type: ignore[arg-type,return-value]
        return trades

    except Exception as e:
        return trades


def _extract_ticker_from_code(code: str) -> str:
    """Extract ticker from strategy code."""
    import re

    patterns = [
        r"vbt\.YFData\.download\(['\"]([A-Z]+)['\"]",
        r"DataService\.get_ohlcv_data\(['\"]([A-Z]+)['\"]",
        r"['\"]([A-Z]+)['\"]\s*,\s*start",
    ]

    for pattern in patterns:
        match = re.search(pattern, code)
        if match:
            return match.group(1)

    return "AAPL"


def _extract_ohlcv_for_range(ticker: str, start_date: str, end_date: str) -> List[Dict]:
    """Extract OHLCV data for the full date range."""
    from app.services.data_service import DataService

    try:
        logger.info(f"Extracting OHLCV for {ticker} from {start_date} to {end_date}")
        data = DataService.get_ohlcv_data(ticker, start_date=start_date, end_date=end_date)

        if data is None:
            logger.warning("DataService returned None")
            return []

        if not isinstance(data, pd.DataFrame):
            logger.warning(f"DataService returned {type(data)}, not DataFrame")
            return []

        if len(data) == 0:
            logger.warning("DataService returned empty DataFrame")
            return []

        # The DataService returns columns: Open, High, Low, Close, Volume (capitalized)
        # with Date as the index
        # Create a mapping for the expected columns
        col_map = {}
        for c in data.columns:
            c_lower = c.lower()
            if c_lower == 'open':
                col_map['open'] = c
            elif c_lower == 'high':
                col_map['high'] = c
            elif c_lower == 'low':
                col_map['low'] = c
            elif c_lower == 'close':
                col_map['close'] = c
            elif c_lower == 'volume':
                col_map['volume'] = c

        # Check if we have the required 'close' column
        if 'close' not in col_map:
            logger.warning(f"No 'close' column found. Available columns: {list(data.columns)}")
            return []

        logger.info(f"OHLCV column mapping: {col_map}")

        # Get the series for each column
        s_close = data[col_map['close']]
        s_open = data[col_map['open']] if 'open' in col_map else s_close
        s_high = data[col_map['high']] if 'high' in col_map else s_close
        s_low = data[col_map['low']] if 'low' in col_map else s_close
        s_vol = data[col_map['volume']] if 'volume' in col_map else None

        idx = s_close.index
        ohlcv_records = []

        for i in range(len(idx)):
            try:
                t = idx[i]
                # Ensure timestamp is in seconds (Unix timestamp)
                if hasattr(t, 'timestamp'):
                    ts = float(t.timestamp())
                else:
                    ts = float(pd.to_datetime(t).timestamp())

                ohlcv_records.append({
                    "time": ts,
                    "open": float(s_open.iloc[i]),
                    "high": float(s_high.iloc[i]),
                    "low": float(s_low.iloc[i]),
                    "close": float(s_close.iloc[i]),
                    "volume": float(s_vol.iloc[i]) if s_vol is not None else 0
                })
            except Exception as e:
                logger.debug(f"Error processing OHLCV row {i}: {e}")
                continue

        logger.info(f"Extracted {len(ohlcv_records)} OHLCV records")
        return ohlcv_records

    except Exception as e:
        return []
