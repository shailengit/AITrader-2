"""
Data service for TradeCraft.
Replaces yfinance with PostgreSQL database queries for historical OHLCV data.
Provides vectorbt-compatible DataFrames for backtesting.

Supports dual-database access:
  - sp1500_1d: Daily OHLCV data (1999-present)
  - sp1500_1m: 1-minute OHLCV data (2026-04-21 to present)
  Candle resampling (5m, 15m, 30m, 1h) is available from the minute database.
"""

import logging
from typing import List, Optional, Dict, Any

import pandas as pd
from sqlalchemy import create_engine, text

from app.db.database import engine, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
from app.utils.security import get_safe_table_name

logger = logging.getLogger(__name__)

# Second engine for 1-minute database
_engine_1m = create_engine(
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/sp1500_1m",
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

# Supported intervals for candle resampling
SUPPORTED_INTERVALS = {"1m", "5m", "15m", "30m", "1h"}

# Mapping to pandas resample rules (newer pandas deprecates 'm' for minutes)
RESAMPLE_RULE_MAP = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
}


class DataService:
    """
    Service for fetching historical market data from PostgreSQL.
    Replaces yfinance for QuantGen backtesting.
    """

    @staticmethod
    def get_ticker_table_name(ticker: str) -> str:
        """Convert ticker to lowercase table name."""
        return ticker.lower().replace('.', '-')

    @staticmethod
    def get_available_tickers() -> List[str]:
        """Get list of all available tickers in the database."""
        try:
            query = text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name NOT IN ('stock_metadata', 'stock_financials_quarterly', 'stock_financials_yearly')
            """)
            with engine.connect() as conn:
                result = conn.execute(query)
                return [row[0].upper() for row in result]
        except Exception as e:
            logger.error(f"Error getting available tickers: {e}")
            return []

    @staticmethod
    def _get_engine(frequency: str = "daily"):
        """Select the right database engine based on frequency."""
        if frequency == "minute":
            return _engine_1m
        return engine  # daily is default

    @staticmethod
    def get_ohlcv_data(
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
        frequency: str = "daily"
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data for a ticker from PostgreSQL.

        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL')
            start_date: Start date in 'YYYY-MM-DD' format (optional)
            end_date: End date in 'YYYY-MM-DD' format (optional)
            limit: Maximum number of rows to return (optional)
            frequency: 'daily' for sp1500_1d (default) or 'minute' for sp1500_1m

        Returns:
            pandas DataFrame with columns: Date, Open, High, Low, Close, Volume
            Returns None if ticker not found or error occurs.
        """
        table_name = get_safe_table_name(ticker)
        target_engine = DataService._get_engine(frequency)

        try:
            # Build query with optional date filters
            base_query = f'''
                SELECT "Date", "Open", "High", "Low", "Close", "Volume"
                FROM "{table_name}"
            '''

            conditions = []
            params = {}

            if start_date:
                conditions.append('"Date" >= :start_date')
                params['start_date'] = start_date

            if end_date:
                conditions.append('"Date" <= :end_date')
                params['end_date'] = end_date

            if conditions:
                base_query += " WHERE " + " AND ".join(conditions)

            base_query += ' ORDER BY "Date" ASC'

            if limit:
                base_query += f" LIMIT {limit}"

            query = text(base_query)

            with target_engine.connect() as conn:
                df = pd.read_sql(query, conn, params=params)

            if df.empty:
                logger.warning(f"No data found for ticker {ticker} ({frequency})")
                return None

            # Ensure Date column is datetime
            df['Date'] = pd.to_datetime(df['Date'])

            # Set Date as index for vectorbt compatibility
            df.set_index('Date', inplace=True)

            # Sort by date
            df.sort_index(inplace=True)

            logger.info(f"Fetched {len(df)} rows for {ticker} ({frequency}) from {df.index[0]} to {df.index[-1]}")
            return df

        except Exception as e:
            logger.error(f"Error fetching OHLCV data for {ticker} ({frequency}): {e}")
            return None

    @staticmethod
    def get_candles(
        ticker: str,
        start_date: str,
        end_date: str,
        interval: str = "15m"
    ) -> Optional[pd.DataFrame]:
        """
        Get OHLCV data resampled to the requested candle interval.

        Uses sp1500_1m for sub-daily intervals (1m, 5m, 15m, 30m, 1h).
        Raw 1-minute data is resampled using pandas resample().

        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL')
            start_date: Start date in 'YYYY-MM-DD' format
            end_date: End date in 'YYYY-MM-DD' format
            interval: Candle interval ('1m', '5m', '15m', '30m', '1h')

        Returns:
            pandas DataFrame resampled to the requested interval,
            or None if data not found.
        """
        if interval not in SUPPORTED_INTERVALS:
            raise ValueError(
                f"Unsupported interval '{interval}'. "
                f"Supported intervals: {', '.join(sorted(SUPPORTED_INTERVALS))}"
            )

        # Fetch raw 1-minute data
        df = DataService.get_ohlcv_data(ticker, start_date, end_date, frequency="minute")
        if df is None:
            return None

        # Pandas resample rule (use canonical form to avoid 'm' month vs minute ambiguity)
        resample_rule = RESAMPLE_RULE_MAP[interval]

        # OHLC aggregation dict
        ohlc_dict = {
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }

        # Resample
        df_resampled = df.resample(resample_rule).agg(ohlc_dict).dropna()

        logger.info(
            f"Resampled {ticker} 1m->{interval}: {len(df)} -> {len(df_resampled)} candles "
            f"({df_resampled.index[0]} to {df_resampled.index[-1]})"
        )
        return df_resampled

    @staticmethod
    def get_multi_ticker_data(
        tickers: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        frequency: str = "daily"
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch OHLCV data for multiple tickers.

        Args:
            tickers: List of ticker symbols
            start_date: Start date in 'YYYY-MM-DD' format
            end_date: End date in 'YYYY-MM-DD' format
            frequency: 'daily' (default) or 'minute'

        Returns:
            Dictionary mapping ticker to DataFrame
        """
        result = {}
        for ticker in tickers:
            df = DataService.get_ohlcv_data(ticker, start_date, end_date, frequency=frequency)
            if df is not None:
                result[ticker] = df
        return result

    @staticmethod
    def get_latest_price(ticker: str, frequency: str = "daily") -> Optional[float]:
        """Get the latest closing price for a ticker."""
        table_name = get_safe_table_name(ticker)
        target_engine = DataService._get_engine(frequency)

        try:
            query = text(f'SELECT "Close" FROM "{table_name}" ORDER BY "Date" DESC LIMIT 1')
            with target_engine.connect() as conn:
                result = conn.execute(query).fetchone()
                if result:
                    return float(result[0])
            return None
        except Exception as e:
            logger.error(f"Error getting latest price for {ticker} ({frequency}): {e}")
            return None

    @staticmethod
    def get_ticker_metadata(ticker: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a ticker from stock_metadata table."""
        try:
            query = text("""
                SELECT ticker, name, sector, industry, market_cap
                FROM stock_metadata
                WHERE ticker = :ticker
            """)
            with engine.connect() as conn:
                result = conn.execute(query, {"ticker": ticker.upper()}).fetchone()

            if result:
                return {
                    'ticker': result[0],
                    'name': result[1],
                    'sector': result[2],
                    'industry': result[3],
                    'market_cap': result[4]
                }
            return None
        except Exception as e:
            logger.error(f"Error getting metadata for {ticker}: {e}")
            return None

    @staticmethod
    def prepare_vectorbt_data(
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        frequency: str = "daily"
    ) -> Optional[pd.DataFrame]:
        """
        Prepare data in vectorbt-compatible format.

        Returns a DataFrame with the index as DatetimeIndex and columns:
        Open, High, Low, Close, Volume

        This matches the format returned by yfinance for vectorbt.
        """
        df = DataService.get_ohlcv_data(ticker, start_date, end_date, frequency=frequency)

        if df is None:
            return None

        # Ensure column names are correct (Open, High, Low, Close, Volume)
        # and index is DatetimeIndex named 'Date'
        df.index.name = 'Date'

        # vectorbt expects these exact column names
        required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(col in df.columns for col in required_columns):
            logger.error(f"DataFrame missing required columns. Have: {df.columns.tolist()}")
            return None

        # Set a frequency on the DatetimeIndex. vectorbt 1.0.0 requires a
        # frequency for time-based metrics and optimization (otherwise it
        # raises "Index frequency is None. Pass it as `freq`..."). Daily
        # stock data is business days; minute data is minute-frequency.
        if df.index.freq is None:
            try:
                # Use "D" (calendar day) — a fixed-duration offset that
                # vectorbt/pandas can convert to a timedelta. "B" (business
                # day) is NOT a fixed duration and raises
                # "invalid unit abbreviation: B" in timedelta parsing.
                df.index.freq = "D" if frequency == "daily" else "min"
            except Exception:
                # Irregular index (e.g. missing holidays) — fall back to
                # inferring a regular frequency; if that fails, leave as-is.
                try:
                    df.index.freq = df.index.inferred_freq
                except Exception:
                    pass

        return df


def _guard_dataframe(result: Optional[pd.DataFrame], ticker: str, start_date: Optional[str], end_date: Optional[str]) -> pd.DataFrame:
    """Raise a clear error when data loading returns None."""
    if result is not None:
        return result
    date_range = ""
    if start_date and end_date:
        date_range = f" from {start_date} to {end_date}"
    elif start_date:
        date_range = f" from {start_date}"
    elif end_date:
        date_range = f" up to {end_date}"
    raise ValueError(
        f"No data found for ticker '{ticker}'{date_range}. "
        f"Check that the ticker exists in the database and the date range is valid. "
        f"Available tickers can be retrieved with DataService.get_available_tickers()."
    )


class SafeDataService:
    """
    Wrapper around DataService that raises clear errors when data is missing.
    Use this in strategy execution contexts instead of DataService directly
    so that missing tickers produce actionable error messages rather than
    downstream 'NoneType' errors.
    """

    @staticmethod
    def get_ohlcv_data(
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
        frequency: str = "daily"
    ) -> pd.DataFrame:
        result = DataService.get_ohlcv_data(ticker, start_date, end_date, limit, frequency=frequency)
        return _guard_dataframe(result, ticker, start_date, end_date)

    @staticmethod
    def prepare_vectorbt_data(
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        frequency: str = "daily"
    ) -> pd.DataFrame:
        result = DataService.prepare_vectorbt_data(ticker, start_date, end_date, frequency=frequency)
        return _guard_dataframe(result, ticker, start_date, end_date)

    @staticmethod
    def get_multi_ticker_data(
        tickers: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        frequency: str = "daily"
    ) -> Dict[str, pd.DataFrame]:
        return DataService.get_multi_ticker_data(tickers, start_date, end_date, frequency=frequency)

    @staticmethod
    def get_candles(
        ticker: str,
        start_date: str,
        end_date: str,
        interval: str = "15m"
    ) -> pd.DataFrame:
        result = DataService.get_candles(ticker, start_date, end_date, interval)
        date_range = f" from {start_date} to {end_date}"
        if result is not None:
            return result
        raise ValueError(
            f"No data found for ticker '{ticker}'{date_range} at interval '{interval}'. "
            f"Minute data is only available from 2026-04-21 onwards. "
            f"Check that the ticker exists in the sp1500_1m database."
        )

    @staticmethod
    def get_ticker_table_name(ticker: str) -> str:
        return DataService.get_ticker_table_name(ticker)

    @staticmethod
    def get_available_tickers() -> List[str]:
        return DataService.get_available_tickers()

    @staticmethod
    def get_latest_price(ticker: str, frequency: str = "daily") -> Optional[float]:
        return DataService.get_latest_price(ticker, frequency=frequency)

    @staticmethod
    def get_ticker_metadata(ticker: str) -> Optional[Dict[str, Any]]:
        return DataService.get_ticker_metadata(ticker)


def safe_get_data(ticker: str, start_date: str, end_date: str, frequency: str = "daily") -> pd.DataFrame:
    """Convenience function that raises on missing data."""
    result = get_data(ticker, start_date, end_date, frequency=frequency)
    return _guard_dataframe(result, ticker, start_date, end_date)


# Convenience function for use in strategy code
def get_data(ticker: str, start_date: str, end_date: str, frequency: str = "daily") -> Optional[pd.DataFrame]:
    """
    Convenience function to get data for strategy execution.
    Drop-in replacement for yfinance.download().

    Usage in strategy code:
        # Instead of: yf.download('AAPL', start='2023-01-01', end='2024-01-01')
        # Use: data = get_data('AAPL', '2023-01-01', '2024-01-01')
    """
    return DataService.prepare_vectorbt_data(ticker, start_date, end_date, frequency=frequency)


def get_multi_data(tickers: List[str], start_date: str, end_date: str, frequency: str = "daily") -> Dict[str, pd.DataFrame]:
    """
    Convenience function to get data for multiple tickers.
    """
    return DataService.get_multi_ticker_data(tickers, start_date, end_date, frequency=frequency)