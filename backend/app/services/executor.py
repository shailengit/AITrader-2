"""
Enhanced code execution module for QuantGen.
Refactored for better security, error handling, and code organization.

Features:
- Input validation and security checks
- Sandboxed code execution
- Structured error handling
- Modular data extraction
- Resource management
- Comprehensive logging
"""

import sys
import io
import math
import contextlib
import traceback
import logging
import ast

# Import advanced security analyzer
from app.services.code_security import analyze_code, regex_scan_code
import re
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime
import signal

import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# Import indicator modules
from app.services.indicator_detector import detect_indicators
from app.services.indicator_extractor import extract_indicators
from app.services.signal_extractor import extract_ticker_from_code
from app.services.true_wfo_implementation import extract_dates_from_code
from app.services.wfo_metrics import compute_ohlcv_from_data

# Configure logging
logger = logging.getLogger(__name__)

# Security configuration
MAX_EXECUTION_TIME = 30  # seconds
MAX_MEMORY_MB = 512  # maximum memory usage
FORBIDDEN_IMPORTS = [
    'os', 'sys', 'subprocess', 'requests', 'urllib', 'socket',
    'threading', 'multiprocessing', 'pickle', 'shelve', 'dbm',
    'sqlite3', 'anydbm', 'redis', 'pymongo', 'elasticsearch'
]

SAFE_MODULES = [
    'vectorbt', 'pandas', 'numpy', 'matplotlib', 'math',
    'datetime', 'time', 'random', 'itertools', 'functools',
    'collections', 're', 'copy', 'app',
    'ta', 'ta.trend', 'ta.momentum', 'ta.volatility', 'ta.volume',
    'pandas_ta',
]

# Execution result dataclass
@dataclass
class ExecutionResult:
    """Structured execution result"""
    success: bool
    output: str
    error: Optional[str] = None
    validation: Optional[Dict[str, Any]] = None
    stats: Optional[Dict[str, Any]] = None
    equity: Optional[List[Dict[str, Any]]] = None
    ohlcv: Optional[List[Dict[str, Any]]] = None
    drawdown: Optional[Dict[str, Any]] = None
    benchmark_drawdown: Optional[Dict[str, Any]] = None
    execution_time: Optional[float] = None
    memory_usage: Optional[int] = None
    trades: Optional[List[Dict[str, Any]]] = None

# Custom exceptions
class ExecutionError(Exception):
    """Base execution error"""
    def __init__(self, message: str, error_type: str = "ExecutionError"):
        self.message = message
        self.error_type = error_type
        super().__init__(self.message)

class SecurityError(ExecutionError):
    """Security validation error"""
    def __init__(self, message: str):
        super().__init__(message, "SecurityError")

class TimeoutError(ExecutionError):
    """Execution timeout error"""
    def __init__(self):
        super().__init__("Execution timed out", "TimeoutError")

class ValidationError(ExecutionError):
    """Code validation error"""
    def __init__(self, message: str):
        super().__init__(message, "ValidationError")

class DataExtractionError(ExecutionError):
    """Data extraction error"""
    def __init__(self, message: str):
        super().__init__(message, "DataExtractionError")

class CodeValidator:
    """Validates code for security and correctness before execution"""

    @staticmethod
    def validate_code_syntax(code: str) -> None:
        """Validate Python syntax using AST"""
        if not code or not code.strip():
            raise ValidationError("Code is empty")

        # Log first 200 chars for debugging
        logger.debug(f"Validating code syntax (first 200 chars): {code[:200]}...")

        try:
            ast.parse(code)
        except SyntaxError as e:
            # Show problematic line
            lines = code.split('\n')
            error_line_num = e.lineno if e.lineno and e.lineno <= len(lines) else 1
            error_line = lines[error_line_num - 1] if error_line_num <= len(lines) else "N/A"
            logger.error(f"Syntax error on line {error_line_num}: {error_line}")
            raise ValidationError(
                f"Invalid Python syntax at line {error_line_num}: {str(e)}\n"
                f"Problem line: {error_line[:100]}"
            )

    @staticmethod
    def check_forbidden_imports(code: str) -> None:
        """Check for forbidden import statements"""
        forbidden_patterns = [
            rf'\bimport\s+({"|".join(FORBIDDEN_IMPORTS)})\b',
            rf'\bfrom\s+({"|".join(FORBIDDEN_IMPORTS)})\b',
        ]

        for pattern in forbidden_patterns:
            if re.search(pattern, code, re.IGNORECASE | re.MULTILINE):
                raise SecurityError(
                    f"Forbidden import detected. Only vectorbt, pandas, numpy, and matplotlib are allowed."
                )

    @staticmethod
    def check_dangerous_patterns(code: str) -> None:
        """Check for dangerous code patterns"""
        dangerous_patterns = [
            r'\beval\s*\(',
            r'\bexec\s*\(',
            r'\bopen\s*\(',
            r'\bfile\s*\(',
            r'\binput\s*\(',
            r'\braw_input\s*\(',
            r'\b__import__\s*\(',
            r'\bglobals\s*\(',
            r'\blocals\s*\(',
            r'\bvars\s*\(',
            r'\bdir\s*\(',
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, code):
                raise SecurityError(f"Dangerous pattern detected: {pattern}")

    @staticmethod
    def validate_vectorbt_requirements(code: str) -> None:
        """Check for required VectorBT patterns"""
        required_patterns = [
            r'import\s+vectorbt\s+as\s+vbt',
            r'vbt\.Portfolio\.from_signals'
        ]

        missing_patterns = []
        for pattern in required_patterns:
            if not re.search(pattern, code, re.IGNORECASE):
                missing_patterns.append(pattern)

        # Check for data loading - DataService, get_data (convenience), or YFData
        has_data_service = re.search(r'DataService\.get_ohlcv_data', code) is not None
        has_get_data = re.search(r'\bget_data\s*\(', code) is not None
        has_yfdata = re.search(r'vbt\.YFData\.download', code) is not None

        if not has_data_service and not has_get_data and not has_yfdata:
            missing_patterns.append('get_data() OR DataService.get_ohlcv_data OR vbt.YFData.download')

        if missing_patterns:
            raise ValidationError(
                f"Missing required patterns: {missing_patterns}. "
                f"Code must use vectorbt library properly with data loading."
            )

    @classmethod
    def validate_code(cls, code: str) -> Dict[str, Any]:
        """Comprehensive code validation"""
        validation_result: Dict[str, Any] = {
            "valid": True,
            "warnings": [],
            "errors": [],
            "suggestions": []
        }

        try:
            # Security checks
            cls.check_forbidden_imports(code)
            cls.check_dangerous_patterns(code)

            # Syntax validation
            cls.validate_code_syntax(code)

            # VectorBT requirements
            cls.validate_vectorbt_requirements(code)

            # Suggestions
            if 'print(' not in code:
                validation_result["suggestions"].append(
                    "Consider adding print(pf.stats()) for debugging"
                )

            # Check for parameters section
            if re.search(r'\bparam\w*\b', code, re.IGNORECASE) and '# Parameters' not in code:
                validation_result["suggestions"].append(
                    "Consider adding a '# Parameters' section for optimization support"
                )

        except (SecurityError, ValidationError) as e:
            validation_result["valid"] = False
            validation_result["errors"].append(f"{e.error_type}: {e.message}")
        except Exception as e:
            validation_result["valid"] = False
            validation_result["errors"].append(f"Validation error: {str(e)}")

        logger.info("Code validation completed. Valid: %s", validation_result['valid'])
        return validation_result

class TimeoutHandler:
    """Handles execution timeouts"""

    def __init__(self, timeout_seconds: float = MAX_EXECUTION_TIME):
        self.timeout_seconds = timeout_seconds
        self.old_handler = None
        self.use_signal = timeout_seconds >= 1  # Use signal.alarm only for >= 1 second

    def __enter__(self):
        if self.use_signal:
            def timeout_handler(signum, frame):
                raise TimeoutError()

            self.old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(int(self.timeout_seconds))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.use_signal:
            signal.alarm(0)  # Cancel the alarm
            signal.signal(signal.SIGALRM, self.old_handler)

class ResourceMonitor:
    """Monitors resource usage during execution"""

    def __init__(self):
        self.start_time = None
        self.start_memory = None

    def __enter__(self):
        import psutil
        import os

        self.start_time = datetime.now()
        process = psutil.Process(os.getpid())
        self.start_memory = process.memory_info().rss / 1024 / 1024  # MB
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        import psutil
        import os

        end_time = datetime.now()
        process = psutil.Process(os.getpid())
        end_memory = process.memory_info().rss / 1024 / 1024  # MB

        self.execution_time = (end_time - self.start_time).total_seconds()  # type: ignore[operator]
        self.memory_usage = end_memory - self.start_memory  # type: ignore[operator]

        # Log resource usage
        logger.info(f"Execution time: {self.execution_time:.2f}s")
        logger.info(f"Memory usage: {self.memory_usage:.2f}MB")

class CodeExecutor:
    """Handles secure code execution in a controlled environment"""

    @staticmethod
    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        """Replacement for __import__ that only allows safe modules"""
        if name in SAFE_MODULES or any(name.startswith(m + '.') for m in SAFE_MODULES):
            return __import__(name, globals, locals, fromlist, level)
        raise ImportError(f"Import of module '{name}' is not allowed for security reasons")

    @staticmethod
    def execute_with_timeout(code: str, timeout_seconds: int = MAX_EXECUTION_TIME) -> Tuple[Any, str]:
        """Execute code with timeout and stdout capture"""
        import vectorbt as vbt  # lazy: heavy import, only needed when running a strategy
        from app.services.markov.signal_provider import MarkovSignalProvider  # lazy: pulls in torch
        stdout_buffer = io.StringIO()

        # Define execution globals
        # Import SafeDataService for strategy execution
        from app.services.data_service import SafeDataService, safe_get_data

        # vectorbt 1.0.0 requires a global frequency for time-based metrics.
        try:
            vbt.settings.array_wrapper.freq = "D"
        except Exception:
            pass

        exec_globals = {
            "vbt": vbt,
            "pd": pd,
            "np": np,
            "plt": plt,
            "DataService": SafeDataService,
            "get_data": safe_get_data,
            "MarkovSignalProvider": MarkovSignalProvider,
            "__builtins__": {
                # Restrict builtins for security
                "abs": abs, "all": all, "any": any, "bool": bool,
                "complex": complex, "dict": dict, "enumerate": enumerate,
                "filter": filter, "float": float, "int": int, "len": len,
                "list": list, "map": map, "max": max, "min": min,
                "range": range, "round": round, "set": set, "sum": sum,
                "zip": zip,
                # Essential builtins
                "print": print, "str": str, "tuple": tuple, "isinstance": isinstance,
                "getattr": getattr, "hasattr": hasattr, "type": type, "repr": repr,
                "sorted": sorted, "reversed": reversed, "slice": slice, "iter": iter,
                "next": next, "hash": hash, "id": id, "chr": chr, "ord": ord,
                "bin": bin, "hex": hex, "oct": oct, "divmod": divmod, "pow": pow,
                "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
                "IndexError": IndexError, "KeyError": KeyError, "AttributeError": AttributeError,
                "ImportError": ImportError, "NameError": NameError, "RuntimeError": RuntimeError,
                "AssertionError": AssertionError,
                # Safe import
                "__import__": CodeExecutor.safe_import
            }
        }

        try:
            with TimeoutHandler(timeout_seconds):
                with contextlib.redirect_stdout(stdout_buffer):
                    exec(code, exec_globals)

            return exec_globals, stdout_buffer.getvalue()

        except TimeoutError:
            raise TimeoutError()
        except Exception as e:
            error_details = traceback.format_exc()
            raise ExecutionError(f"Execution failed: {str(e)}\n{error_details}")
        finally:
            stdout_buffer.close()


def _json_safe(v: Any) -> Any:
    """Coerce non-finite floats (inf/-inf/nan) to None so JSON serialization
    never fails with 'Out of range float values are not JSON compliant'."""
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def _serialize_pandas_object(obj: Any) -> Any:
    """Convert pandas objects to JSON-serializable Python objects.

    Handles:
    - Series with MultiIndex (converts tuple keys to strings)
    - DataFrames (converts to dict with proper key handling)
    - NaN values (converts to None)
    """
    if obj is None:
        return None

    if isinstance(obj, (int, float, str, bool)):
        # JSON cannot represent non-finite floats (inf/-inf/nan) — coerce to None.
        if isinstance(obj, float) and not math.isfinite(obj):
            return None
        return obj

    if isinstance(obj, pd.Series):
        # Convert Series to dict, handling MultiIndex by flattening tuple keys
        if isinstance(obj.index, pd.MultiIndex):
            result = {}
            for key, value in obj.items():
                if isinstance(key, tuple):
                    # Convert tuple key to string like "key1|key2|key3"
                    flattened_key = '|'.join(str(k) for k in key)
                    result[flattened_key] = value
                else:
                    result[str(key)] = value
            # Replace NaN/inf with None and convert to proper types
            return {k: _json_safe(v) for k, v in result.items()}
        else:
            # Single index Series
            dict_obj = obj.astype(object).where(pd.notnull(obj), None).to_dict()
            return {str(k): _json_safe(v) for k, v in dict_obj.items()}

    if isinstance(obj, pd.DataFrame):
        # Convert DataFrame to dict
        d = obj.astype(object).where(pd.notnull(obj), None).to_dict(orient='dict')
        return {str(k): {str(k2): _json_safe(v2) for k2, v2 in v.items()} for k, v in d.items()}

    if isinstance(obj, (list, tuple)):
        return [_serialize_pandas_object(item) for item in obj]

    if isinstance(obj, dict):
        return {str(k): _serialize_pandas_object(v) for k, v in obj.items()}

    # For numpy types and other types
    try:
        if hasattr(obj, 'item'):
            return _json_safe(obj.item())
        return str(obj)
    except Exception:
        return str(obj)


class StatsExtractor:
    """Extracts statistics from portfolio object"""

    @staticmethod
    def extract_basic_stats(pf) -> Dict[str, Any]:
        """Extract basic portfolio statistics"""
        try:
            # Try with explicit frequency first
            try:
                stats_series = pf.stats(settings=dict(freq='1D'))
            except:
                stats_series = pf.stats()

            # Convert to dictionary, handling NaN values and MultiIndex
            stats_dict = _serialize_pandas_object(stats_series)

            # Force calculate missing metrics
            metrics_to_force = {
                "Sharpe Ratio": "sharpe_ratio",
                "Sortino Ratio": "sortino_ratio",
                "Calmar Ratio": "calmar_ratio",
                "Max Drawdown [%]": "max_drawdown"
            }

            for display_name, method_name in metrics_to_force.items():
                if display_name not in stats_dict or stats_dict[display_name] is None:
                    try:
                        method = getattr(pf, method_name)
                        try:
                            val = method(freq='1D')
                        except:
                            val = method()

                        if hasattr(val, 'item'):
                            val = val.item()

                        # Handle Max Drawdown formatting
                        if method_name == "max_drawdown":
                            val = val * 100 if abs(val) <= 1.0 else val

                        stats_dict[display_name] = val
                    except Exception as e:
                        logger.debug(f"Could not calculate {display_name}: {e}")

            return stats_dict

        except Exception as e:
            logger.error(f"Error extracting basic stats: {e}")
            raise DataExtractionError(f"Failed to extract statistics: {str(e)}")

    @staticmethod
    def extract_benchmark_comparison(pf) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """Extract benchmark comparison data. Returns (strategy_drawdown, benchmark_drawdown, bench_stats)."""
        import vectorbt as vbt  # lazy: heavy import
        try:
            if not hasattr(pf, 'close'):
                return {}, {}, {}

            price = pf.close
            if isinstance(price, pd.DataFrame):
                price = price.iloc[:, 0]

            # Create benchmark portfolio (buy and hold)
            bench_pf = vbt.Portfolio.from_holding(price, freq='1D')
            bench_stats = _serialize_pandas_object(bench_pf.stats())

            # Add benchmark Sharpe Ratio
            try:
                bench_sharpe = bench_pf.sharpe_ratio(freq='1D')
                if hasattr(bench_sharpe, 'item'):
                    bench_sharpe = bench_sharpe.item()
                bench_stats["Benchmark Sharpe Ratio"] = bench_sharpe
            except Exception as e:
                logger.debug(f"Could not calculate benchmark Sharpe ratio: {e}")

            # Add benchmark Max Drawdown
            try:
                bench_max_dd = bench_pf.max_drawdown()
                if hasattr(bench_max_dd, 'item'):
                    bench_max_dd = bench_max_dd.item()
                # Convert to percentage format consistent with strategy stats
                bench_max_dd_pct = bench_max_dd * 100 if abs(bench_max_dd) <= 1.0 else bench_max_dd
                bench_stats["Benchmark Max Drawdown [%]"] = bench_max_dd_pct
            except Exception as e:
                logger.debug(f"Could not calculate benchmark Max Drawdown: {e}")

            # Extract drawdown series as numeric Unix timestamps
            try:
                strategy_dd = pf.drawdown() * 100
                benchmark_dd = bench_pf.drawdown() * 100

                def dd_to_ts_dict(dd: pd.Series) -> Dict[float, float]:
                    if len(dd) == 0:
                        return {}
                    return {
                        (k.timestamp() if hasattr(k, 'timestamp') else float(k)): (float(v) if pd.notna(v) else None)
                        for k, v in dd.replace({np.nan: None}).items()
                    }

                strategy_drawdown = dd_to_ts_dict(strategy_dd)
                benchmark_drawdown = dd_to_ts_dict(benchmark_dd)

                return strategy_drawdown, benchmark_drawdown, bench_stats
            except Exception as e:
                logger.debug(f"Could not extract drawdown data: {e}")
                return {}, {}, bench_stats

        except Exception as e:
            logger.error(f"Error in benchmark comparison: {e}")
            return {}, {}, {}

class EquityExtractor:
    """Extracts equity curve data from portfolio"""

    @staticmethod
    def extract_equity_curve(pf) -> List[Dict[str, Any]]:
        """Extract portfolio equity curve as Unix timestamps."""
        try:
            value_data = pf.value()
            equity_data = []

            # Handle DataFrame input (extract first column)
            if isinstance(value_data, pd.DataFrame):
                value_series = value_data.iloc[:, 0]
            else:
                value_series = value_data

            for ts, val in value_series.items():
                try:
                    t_numeric = ts.timestamp() if hasattr(ts, 'timestamp') else pd.to_datetime(ts).timestamp()
                    equity_data.append({
                        "time": float(t_numeric),
                        "value": float(val) if pd.notna(val) else None
                    })
                except Exception as e:
                    logger.debug(f"Error processing equity point: {e}")
                    continue

            logger.info(f"Extracted {len(equity_data)} equity curve points")
            return equity_data

        except Exception as e:
            logger.error(f"Error extracting equity curve: {e}")
            raise DataExtractionError(f"Failed to extract equity curve: {str(e)}")

class OHLCVExtractor:
    """Extracts OHLCV data from various sources"""

    @staticmethod
    def find_data_source(exec_globals: Dict[str, Any]) -> Optional[Any]:
        """Find the primary data source from execution context"""
        # Priority 1: Look for explicit 'data' variable
        if 'data' in exec_globals:
            data = exec_globals['data']
            logger.info("Found 'data' variable in execution context")
            return data

        # Priority 2: Look for other common data variables
        for var_name in ['price_data', 'market_data', 'prices', 'ohlcv']:
            if var_name in exec_globals:
                logger.info(f"Found '{var_name}' variable in execution context")
                return exec_globals[var_name]

        return None

    @staticmethod
    def unwrap_data_source(data) -> Optional[pd.DataFrame]:
        """Unwrap data source to get DataFrame"""
        try:
            # Check for DataFrame first (pd.DataFrame has .get() method for columns)
            if isinstance(data, pd.DataFrame):
                logger.info("Data source is already a DataFrame")
                return data
            elif hasattr(data, 'get'):
                # For vbt.YFData and similar objects
                unwrapped = data.get()
                if isinstance(unwrapped, pd.DataFrame):
                    logger.info("Successfully unwrapped data source")
                    return unwrapped

            logger.warning("Could not unwrap data source")
            return None

        except Exception as e:
            logger.error(f"Error unwrapping data source: {e}")
            return None

    @staticmethod
    def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Normalize DataFrame columns for consistent access"""
        try:
            # Handle MultiIndex columns
            if isinstance(df.columns, pd.MultiIndex):
                logger.info("Detected MultiIndex columns, normalizing")
                # Flatten MultiIndex columns
                df.columns = ['_'.join(map(str, col)).strip() for col in df.columns.values]

            return df

        except Exception as e:
            logger.error(f"Error normalizing columns: {e}")
            return df

    @staticmethod
    def extract_ohlcv_data(exec_globals: Dict[str, Any], pf, code: str = "") -> List[Dict[str, Any]]:
        """Extract OHLCV data with fallback logic.

        Prefers data fetched directly from the local data service using the
        strategy's ticker and date range so the chart covers the full backtest
        period. Falls back to the strategy's data variable or portfolio data.
        """
        ohlcv_records = []

        try:
            # Primary: fetch from local DB using explicit code dates/ticker
            if code:
                try:
                    ticker = extract_ticker_from_code(code)
                    dates = extract_dates_from_code(code)
                    if ticker and dates:
                        start_date, end_date = dates
                        service_records = compute_ohlcv_from_data(ticker, start_date, end_date)
                        if len(service_records) >= 2:
                            logger.info(
                                "Fetched %d OHLCV records from data service for %s (%s to %s)",
                                len(service_records), ticker, start_date, end_date,
                            )
                            return service_records
                except Exception as e:
                    logger.debug(f"Could not fetch OHLCV from data service: {e}")

            # Fallback 1: Try to find and extract from data variable
            data_source = OHLCVExtractor.find_data_source(exec_globals)

            if data_source is not None:
                df = OHLCVExtractor.unwrap_data_source(data_source)
                if df is not None:
                    df = OHLCVExtractor.normalize_columns(df)
                    ohlcv_records = OHLCVExtractor._extract_from_dataframe(df)
                    if ohlcv_records:
                        logger.info(f"Extracted {len(ohlcv_records)} OHLCV records from data source")
                        return ohlcv_records

            # Fallback 2: Extract from portfolio
            if hasattr(pf, 'close'):
                logger.info("Using portfolio close data as fallback")
                ohlcv_records = OHLCVExtractor._extract_from_portfolio(pf)

            return ohlcv_records

        except Exception as e:
            logger.error(f"Error extracting OHLCV data: {e}")
            return []

    @staticmethod
    def _extract_from_dataframe(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Extract OHLCV from DataFrame"""
        try:
            # Create column mapping (case-insensitive search)
            lower_cols = {c.lower(): c for c in df.columns}

            def find_col(keyword):
                for c_lower, c_orig in lower_cols.items():
                    if keyword in c_lower:
                        return df[c_orig]
                return None

            s_open = find_col('open')
            s_high = find_col('high')
            s_low = find_col('low')
            s_close = find_col('close')
            s_vol = find_col('volume')

            if s_close is None:
                logger.warning("No close price column found")
                return []

            # Fill missing OHLC with close price
            if s_open is None: s_open = s_close
            if s_high is None: s_high = s_close
            if s_low is None: s_low = s_close

            # Build records
            idx = s_close.index
            v_o = s_open.values
            v_h = s_high.values
            v_l = s_low.values
            v_c = s_close.values
            v_v = s_vol.values if s_vol is not None else np.zeros(len(v_c))

            records = []
            for i in range(len(idx)):
                try:
                    t = idx[i]
                    if hasattr(t, 'timestamp'):
                        ts = t.timestamp()
                    else:
                        ts = pd.to_datetime(t).timestamp()

                    records.append({
                        "time": float(ts),
                        "open": float(v_o[i]),
                        "high": float(v_h[i]),
                        "low": float(v_l[i]),
                        "close": float(v_c[i]),
                        "volume": float(v_v[i])
                    })
                except Exception as e:
                    logger.debug(f"Error processing OHLCV record: {e}")
                    continue

            logger.info(f"Extracted {len(records)} OHLCV records from DataFrame")
            return records

        except Exception as e:
            logger.error(f"Error extracting from DataFrame: {e}")
            return []

    @staticmethod
    def _extract_from_portfolio(pf) -> List[Dict[str, Any]]:
        """Extract minimal OHLCV data from portfolio (fallback)"""
        try:
            close_series = pf.close
            if isinstance(close_series, pd.DataFrame):
                close_series = close_series.iloc[:, 0]

            records = []
            for t, v in close_series.items():
                try:
                    ts = pd.to_datetime(t).timestamp()
                    records.append({
                        "time": float(ts),
                        "open": float(v),
                        "high": float(v),
                        "low": float(v),
                        "close": float(v),
                        "volume": 0
                    })
                except Exception as e:
                    logger.debug(f"Error processing portfolio record: {e}")
                    continue

            logger.info(f"Extracted {len(records)} OHLCV records from portfolio (fallback)")
            return records

        except Exception as e:
            logger.error(f"Error extracting from portfolio: {e}")
            return []

class TradeExtractor:
    """Extracts trade/position data for buy/sell markers"""

    @staticmethod
    def extract_trades(pf) -> List[Dict[str, Any]]:
        """Extract buy/sell signals from portfolio"""
        try:
            trades: List[Dict[str, Any]] = []

            # Get trades from portfolio - try different attributes
            trade_records = None

            # Try pf.trades.records first
            if hasattr(pf, 'trades') and pf.trades is not None:
                try:
                    trade_records = pf.trades.records
                    logger.info(f"Found pf.trades.records with {len(trade_records) if trade_records is not None else 0} records")
                except Exception as e:
                    logger.warning(f"Could not access pf.trades.records: {e}")

            # If no trades, try orders
            if (trade_records is None or len(trade_records) == 0) and hasattr(pf, 'orders') and pf.orders is not None:
                try:
                    trade_records = pf.orders.records
                    logger.info(f"Found pf.orders.records with {len(trade_records) if trade_records is not None else 0} records")
                except Exception as e:
                    logger.warning(f"Could not access pf.orders.records: {e}")

            if trade_records is None:
                logger.warning("No trade or order records found in portfolio")
                return trades

            # Handle numpy arrays (VectorBT returns numpy array, not DataFrame)
            try:
                import numpy as np
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
                    logger.info(f"Converted {len(trade_list)} trades from numpy array")
                elif hasattr(trade_records, 'to_dict'):
                    trade_list = trade_records.to_dict('records')
                else:
                    trade_list = list(trade_records)
            except Exception as e:
                logger.warning(f"Error converting trade records: {e}")
                trade_list = []

            if not trade_list or len(trade_list) == 0:
                logger.warning("No trade records to process")
                return trades

            # Get the index (dates/times) from the portfolio
            close_series = pf.close
            if isinstance(close_series, pd.DataFrame):
                close_series = close_series.iloc[:, 0]

            index = close_series.index
            logger.info(f"Processing {len(trade_list)} trades with index length {len(index)}")

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
                    logger.debug(f"Error processing trade record: {e}")
                    continue

            # Sort by time
            trades.sort(key=lambda x: x['time'])  # type: ignore[arg-type,return-value]

            logger.info(f"Extracted {len(trades)} trade markers (buy/sell signals)")
            return trades

        except Exception as e:
            logger.error(f"Error extracting trades: {e}")
            return []

def _apply_ticker_override(code: str, tickers: Optional[List[str]]) -> str:
    """Replace ticker assignment in code if tickers override is provided."""
    if not tickers or len(tickers) == 0:
        return code
    # Replace single ticker assignment: ticker = 'AAPL'
    override = tickers[0]
    modified = re.sub(
        r"^(\s*)ticker\s*=\s*['\"][^'\"]*['\"]",
        rf"\1ticker = '{override}'",
        code,
        flags=re.MULTILINE,
        count=1
    )
    if modified != code:
        logger.info(f"Overrode ticker to '{override}' in strategy code")
    return modified


def execute_strategy(code: str, tickers: Optional[List[str]] = None) -> Dict[str, Any]:
    sys.stderr.write('DEBUG: execute_strategy called!\n')
    """
    Execute strategy code with enhanced security, validation, and error handling.

    Args:
        code: Python code to execute
        tickers: Optional list of tickers to override the one in code

    Returns:
        Dict containing execution results and extracted data

    Raises:
        ExecutionError: If execution fails
    """
    start_time = datetime.now()
    resource_monitor = ResourceMonitor()

    logger.info(f"Starting strategy execution (length: {len(code)} chars)")

    # Apply ticker override before validation
    code = _apply_ticker_override(code, tickers)

    output = ""
    validation_result = None

    try:
        # Input validation
        if not code or len(code.strip()) < 50:
            raise ValidationError("Code too short or empty")

        if len(code) > 50000:
            raise ValidationError("Code too long (max 50000 characters)")

        # Security and validation checks
        validation_result = CodeValidator.validate_code(code)

        if not validation_result["valid"]:
            error_msg = "; ".join(validation_result["errors"])
            raise ValidationError(f"Code validation failed: {error_msg}")

        # Execute with resource monitoring
        with resource_monitor:
            exec_globals, output = CodeExecutor.execute_with_timeout(code)

        # Check for required objects
        if 'pf' not in exec_globals:
            raise ExecutionError("Strategy code must create a 'pf' (Portfolio) object")

        pf = exec_globals['pf']

        if not hasattr(pf, 'stats'):
            raise ExecutionError("Portfolio object missing required methods")

        if pf.wrapper.shape[0] == 0:
            raise ExecutionError("Portfolio is empty. Check data download and signal generation.")

        # Extract data from successful execution
        logger.info("Strategy executed successfully, extracting data...")

        # Extract statistics
        try:
            stats = StatsExtractor.extract_basic_stats(pf)
        except Exception as e:
            logger.warning(f"Stats extraction failed: {e}")
            stats = {}

        # Extract equity curve
        try:
            equity = EquityExtractor.extract_equity_curve(pf)
        except Exception as e:
            logger.warning(f"Equity extraction failed: {e}")
            equity = []

        # Extract drawdown data
        try:
            drawdown, benchmark_drawdown, bench_stats = StatsExtractor.extract_benchmark_comparison(pf)
            # Merge only explicitly-prefixed benchmark metrics into main stats
            if bench_stats:
                for k, v in bench_stats.items():
                    if k.startswith("Benchmark"):
                        stats[k] = v
        except Exception as e:
            logger.warning(f"Drawdown extraction failed: {e}")
            drawdown = {}
            benchmark_drawdown = {}

        # Extract OHLCV data
        try:
            ohlcv = OHLCVExtractor.extract_ohlcv_data(exec_globals, pf, code)
        except Exception as e:
            logger.warning(f"OHLCV extraction failed: {e}")
            ohlcv = []

        # Extract trade data (buy/sell markers)
        try:
            trades = TradeExtractor.extract_trades(pf)
        except Exception as e:
            logger.warning("Trade extraction failed: %s", e)
            trades = []

        # Extract indicator data (for charting)
        sys.stderr.write('DEBUG: Starting indicator extraction...\n')
        try:
            sys.stderr.write('DEBUG: Calling detect_indicators...\n')
            detected = detect_indicators(code)
            sys.stderr.write(f'DEBUG: Detected {detected}\n')
            if detected:
                indicators = extract_indicators(exec_globals, detected)
                logger.info(f"Extracted {len(indicators)} indicators")
            else:
                indicators = []
                logger.info("No indicators detected in strategy code")
        except Exception as e:
            logger.warning(f"Indicator extraction failed: {e}")
            indicators = []

        # Create structured result
        result = ExecutionResult(
            success=True,
            output=output,
            validation=validation_result,
            stats=stats,
            equity=equity,
            ohlcv=ohlcv,
            drawdown=drawdown,
            benchmark_drawdown=benchmark_drawdown,
            execution_time=resource_monitor.execution_time,
            memory_usage=int(resource_monitor.memory_usage),
            trades=trades
        )

        # Convert to dictionary for API compatibility
        result_dict = {
            "success": result.success,
            "output": result.output,
            "validation": result.validation,
            "stats": result.stats,
            "equity": result.equity,
            "ohlcv": result.ohlcv,
            "drawdown": result.drawdown,
            "benchmark_drawdown": result.benchmark_drawdown,
            "execution_time": result.execution_time,
            "memory_usage": result.memory_usage,
            "trades": result.trades,
            "indicators": indicators
        }

        logger.info(f"Strategy execution completed successfully in {result.execution_time:.2f}s")
        return result_dict

    except (SecurityError, ValidationError, TimeoutError, ExecutionError) as e:
        logger.error(f"Execution failed: {e.error_type} - {e.message}")

        # Create error result
        error_result = {
            "success": False,
            "error": f"{e.error_type}: {e.message}",
            "output": output,
            "validation": validation_result
        }

        return error_result

    except Exception as e:
        logger.error(f"Unexpected execution error: {str(e)}", exc_info=True)

        error_result = {
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "output": output,
            "traceback": traceback.format_exc()
        }

        return error_result

    finally:
        # Log execution summary
        end_time = datetime.now()
        total_time = (end_time - start_time).total_seconds()
        logger.info(f"Execution cycle completed in {total_time:.2f}s")
