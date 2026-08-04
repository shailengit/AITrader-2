"""Run library v6 strategy with correct engine path."""
import os, sys, importlib.util

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# Set DB env
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "sarina00")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5431")
os.environ.setdefault("DB_NAME", "sp1500_1d")

# Read the v6 strategy
strategy_path = "library/buy-stocks-where-ema20-crosses-above-ema200.-rank-by-crossov.../v6/strategy.py"
with open(strategy_path) as f:
    content = f.read()

# Fix the engine path: from v6 dir, need ../../.. to reach strategies/
content = content.replace(
    '_engine_path = os.path.join(os.path.dirname(__file__), "..", "..", "engine.py")',
    '_engine_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "engine.py")'
)

# Also fix the import path for engine
content = content.replace(
    'sys.modules["strategies_engine_inline"] = _engine',
    'sys.modules["strategies_engine_inline"] = _engine'
)

exec(content, {"__file__": os.path.abspath(strategy_path), "__name__": "__main__"})
