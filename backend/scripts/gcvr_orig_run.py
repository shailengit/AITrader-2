"""Original config variant (2018/LIMIT3000) for A/B — run directly."""
import os, sys, warnings
warnings.filterwarnings('ignore')
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath('.')), '.env'))
sys.path.insert(0, '.')

# This file is a copy of the strategy with the ORIGINAL precompute load:
# load_start="2018-01-01", LIMIT 3000.
from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
from app.services.strategies.golden_cross_volume_rotation import GoldenCrossVolumeRotation

s = StrategyBacktestAdapter(GoldenCrossVolumeRotation()).run(
    as_of='2020-01-01', end='2026-09-04', capital=100000)['summary']
print(f"ORIGINAL(2018,LIMIT3000): ret={s['total_return_pct']:.1f}% trades={s['total_trades']} "
      f"win={s['win_rate']:.1f}% cagr={s['cagr_pct']:.1f}%", flush=True)
