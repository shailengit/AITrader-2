"""A/B test: original (2018/LIMIT3000) vs fixed (2008/LIMIT5000) precompute.

Runs each config in a FRESH subprocess to avoid module-cache contamination,
and prints the 2020-2026 baseline for each.
"""
import subprocess, sys, os, textwrap

BACKEND = "/Users/shailendrakaushik/Documents/Python/AlgoTrading/TradeCraft-1/AITrader-2/backend"
SRC = os.path.join(BACKEND, "app/services/strategies/golden_cross_volume_rotation.py")
base = open(SRC).read()

# Build two variants
orig = base.replace('_load_start = "2008-01-01"', 'load_start = "2018-01-01"').replace("LIMIT 5000", "LIMIT 3000")
fixed = base  # already 2008/LIMIT5000

for name, code in [("ORIG(2018,LIMIT3000)", orig), ("FIXED(2008,LIMIT5000)", fixed)]:
    # write to a temp module in backend dir so `app` imports resolve
    tmp = os.path.join(BACKEND, "gcvr_ab_variant.py")
    open(tmp, "w").write(code)
    runner = textwrap.dedent(f"""
        import os, sys, warnings
        warnings.filterwarnings('ignore')
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath('.')), '.env'))
        sys.path.insert(0, '.')
        import gcvr_ab_variant as mod
        from app.services.strategy_backtest_adapter import StrategyBacktestAdapter
        s = StrategyBacktestAdapter(mod.GoldenCrossVolumeRotation()).run(as_of='2020-01-01',end='2026-09-04',capital=100000)['summary']
        print(f"RESULT ret={{s['total_return_pct']:.1f}} trades={{s['total_trades']}} win={{s['win_rate']:.1f}} cagr={{s['cagr_pct']:.1f}}")
    """)
    r = subprocess.run([sys.executable, "-c", runner], cwd=BACKEND,
                       capture_output=True, text=True, timeout=600)
    out = [l for l in r.stdout.splitlines() if l.startswith("RESULT")]
    print(f"{name}: {out[0] if out else 'NO RESULT'} | err={'yes' if r.returncode!=0 else 'no'}")
    if r.returncode != 0:
        print("  stderr tail:", r.stderr.strip().splitlines()[-3:])
    os.remove(tmp)
