"""VectorBT Helpers Module"""


def get_indicator_list():
    """
    Returns a list of built-in vectorbt indicators and their basic usage.
    """
    import vectorbt as vbt  # lazy: heavy import
    indicators = [
        {
            "name": "MA (Moving Average)",
            "snippet": "vbt.MA.run(price, window=10)"
        },
        {
            "name": "RSI (Relative Strength Index)",
            "snippet": "vbt.RSI.run(price, window=14)"
        },
        {
            "name": "BBANDS (Bollinger Bands)",
            "snippet": "vbt.BBANDS.run(price, window=20, alpha=2)"
        },
        {
            "name": "MACD",
            "snippet": "vbt.MACD.run(price, fast_window=12, slow_window=26, signal_window=9)"
        },
        {
            "name": "STOCH (Stochastic)",
            "snippet": "vbt.STOCH.run(high, low, close)"
        },
        {
            "name": "ATR (Average True Range)",
            "snippet": "vbt.ATR.run(high, low, close, window=14)"
        },
        {
            "name": "OBV (On-Balance Volume)",
            "snippet": "vbt.OBV.run(close, volume)"
        }
    ]
    return indicators
