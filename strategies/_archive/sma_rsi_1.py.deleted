import vectorbt as vbt
import numpy as np
import pandas as pd

# Parameters
sma_short_window = 50
sma_long_window = 200
rsi_period = 14
rsi_overbought = 70
rsi_oversold = 30
stop_loss_pct = 0.05
take_profit_pct = 0.1

# Download historical data
data = vbt.YFData.download('AAPL', start='2020-01-01', end='2024-01-01')

# Access the Close price
close = data.get('Close')

# Calculate technical indicators
sma_short = vbt.MA.run(close, window=sma_short_window)
sma_long = vbt.MA.run(close, window=sma_long_window)
rsi = vbt.RSI.run(close, window=rsi_period)

# Generate entry and exit signals
entries = (sma_short.ma_above(sma_long)) & (rsi.rsi_below(rsi_oversold))
exits = (sma_short.ma_below(sma_long)) | (rsi.rsi_above(rsi_overbought))

# Create the portfolio
pf = vbt.Portfolio.from_signals(
    close,
    entries,
    exits,
    open=data.get('Open'),
    high=data.get('High'),
    low=data.get('Low'),
    sl_stop=stop_loss_pct,
    tp_stop=take_profit_pct
)

# Calculate buy-and-hold performance for comparison
bh_pf = vbt.Portfolio.from_holding(close)

# Print performance metrics
print("Strategy Performance:")
print(pf.stats())
print("\nBuy and Hold Performance:")
print(bh_pf.stats())