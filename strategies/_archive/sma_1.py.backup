import vectorbt as vbt
import pandas as pd
import numpy as np

# Parameters
fast_window = 5
slow_window = 20

# Download data
data = vbt.YFData.download(
    'CIEN',
    start='2026-01-01',
    end='2026-05-01'
)

# Get close price
close = data.get('Close')

# Calculate moving averages
fast_ma = vbt.MA.run(close, window=fast_window)
slow_ma = vbt.MA.run(close, window=slow_window)

# Generate continuous signals for True Walk-Forward Optimization
# Buy when fast MA is above slow MA (continuous signal)
entries = fast_ma.ma_above(slow_ma.ma)
# Sell when fast MA is below slow MA (continuous signal)
exits = fast_ma.ma_below(slow_ma.ma)

# Create portfolio with direction='longonly' to handle position management
pf = vbt.Portfolio.from_signals(
    close,
    entries=entries,
    exits=exits,
    open=data.get('Open'),
    high=data.get('High'),
    low=data.get('Low'),
    direction='longonly',
    freq='1d'
)

# Print total return
print(pf.total_return())