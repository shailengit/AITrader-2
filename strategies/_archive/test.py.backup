import vectorbt as vbt
from app.services.data_service import DataService
import numpy as np

ticker = 'CLB'
start = '2000-01-01'
end = '2025-12-31'
data = DataService.get_ohlcv_data(ticker, start, end)
print(data.head())


close = data['Close']

# Parameters to optimize
fast_window = 20
slow_window = 200

# Create MA for each parameter combination
fast_ma = vbt.MA.run(close, window=fast_window)
slow_ma = vbt.MA.run(close, window=slow_window)


# Use VBT comparison methods for optimization compatibility
entries = fast_ma.ma_above(slow_ma.ma) & fast_ma.ma_below(close)
exits = fast_ma.ma_below(slow_ma.ma) & fast_ma.ma_above(close)

# Create portfolio with OHLC data
pf = vbt.Portfolio.from_signals(
    close,
    entries=entries,
    exits=exits,
    open=data['Open'],
    high=data['High'],
    low=data['Low'],
    direction='longonly',
    freq='1d'
)

# Print total return
print(pf.total_return())