"""
Statistical Jump Model for sector ETF regime detection.

Two-state model with jump penalty lambda to prevent chattering.
GJR-GARCH with Student-t for volatility overlay.
"""
import logging
import threading
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression
from arch import arch_model

from app.db.database import SECTOR_ETFS
from app.services.markov.feature_engineering import compute_etf_features

logger = logging.getLogger(__name__)

# Default jump penalty
DEFAULT_LAMBDA = 10.0

# Volatility gate threshold
VOL_GATE_THRESHOLD = 0.5


class JumpModel:
    """Two-state Statistical Jump Model for a single ETF."""

    def __init__(self, etf_ticker: str, jump_penalty: float = DEFAULT_LAMBDA):
        self.etf_ticker = etf_ticker
        self.jump_penalty = jump_penalty
        self.model: Optional[MarkovRegression] = None
        self.garch_model = None
        self.garch_residuals: Optional[pd.Series] = None
        self._is_trained = False

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    def train(self, features: pd.DataFrame) -> bool:
        """Train the Jump Model on ETF features.

        Args:
            features: DataFrame from compute_etf_features()

        Returns:
            True if training succeeded
        """
        if features is None or len(features) < 60:
            logger.warning(
                f"Cannot train JumpModel for {self.etf_ticker}: "
                f"insufficient features"
            )
            return False

        try:
            # Use log_return_20d as the primary observation variable
            obs = features['log_return_20d'].values

            # Fit 2-state Markov switching model
            self.model = MarkovRegression(
                obs,
                k_regimes=2,
                trend='c',
                switching_variance=True,
                switching_trend=True,
            )
            self.model = self.model.fit(disp=False)

            # Extract filtered marginal probabilities
            self._filtered_probs = pd.DataFrame(
                self.model.filtered_marginal_probabilities,
                index=features.index[-len(self.model.filtered_marginal_probabilities):],
                columns=[f'state_{i}' for i in range(2)],
            )

            # Apply jump penalty: smooth state transitions
            self._smoothed_probs = self._apply_jump_penalty()

            # Fit GJR-GARCH on residuals
            residuals = pd.Series(
                self.model.resid,
                index=features.index[-len(self.model.resid):],
            )
            self._fit_garch(residuals)

            self._is_trained = True
            logger.info(
                f"JumpModel trained for {self.etf_ticker}: "
                f"{len(self._filtered_probs)} observations"
            )
            return True

        except Exception as e:
            logger.error(
                f"JumpModel training failed for {self.etf_ticker}: {e}"
            )
            return False

    def _apply_jump_penalty(self) -> pd.DataFrame:
        """Apply jump penalty to smooth state transitions.

        Re-computes state probabilities with a penalty on state changes.
        Uses a simple heuristic: if probability crosses 0.5 but was above
        0.5 for < N days, suppress the transition.
        """
        probs = self._filtered_probs.copy()
        bull_prob = probs.get(probs.columns[-1], probs.iloc[:, 0])

        # Apply persistence filter: require N consecutive days above 0.5
        # to switch states. N is derived from jump_penalty.
        persistence_days = max(3, int(self.jump_penalty / 3))
        smoothed = bull_prob.copy()
        state = 0  # 0 = bear, 1 = bull
        count = 0

        for i in range(len(smoothed)):
            if bull_prob.iloc[i] > 0.5:
                count += 1
                if count >= persistence_days:
                    state = 1
            else:
                count = 0
                state = 0
            smoothed.iloc[i] = float(state)

        result = pd.DataFrame({
            'bull_probability': bull_prob,
            'regime': smoothed,
        }, index=probs.index)
        return result

    def _fit_garch(self, residuals: pd.Series) -> None:
        """Fit GJR-GARCH(1,1,1) with Student-t distribution."""
        try:
            self.garch_model = arch_model(
                residuals * 100,  # Scale to percentages for numerical stability
                vol='GARCH',
                p=1,
                o=1,  # GJR term (leverage effect)
                q=1,
                dist='studentst',
            )
            self.garch_result = self.garch_model.fit(disp='off')
            self.garch_residuals = residuals
            logger.info(f"GJR-GARCH fitted for {self.etf_ticker}")
        except Exception as e:
            logger.warning(
                f"GJR-GARCH fit failed for {self.etf_ticker}: {e}"
            )
            self.garch_result = None

    def get_regime(
        self, date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get current regime state.

        Args:
            date: Date string 'YYYY-MM-DD'. If None, returns latest.

        Returns:
            Dict with regime, bull_probability, vol_regime, vol_probability
        """
        if not self._is_trained:
            return {
                'etf': self.etf_ticker,
                'regime': 'UNKNOWN',
                'bull_probability': 0.5,
                'vol_regime': 'UNKNOWN',
                'vol_probability': 0.0,
            }

        if date is not None:
            if date not in self._smoothed_probs.index:
                # Find nearest date
                dates = self._smoothed_probs.index
                nearest = dates[dates <= pd.Timestamp(date)]
                if len(nearest) == 0:
                    nearest = dates[:1]
                row = self._smoothed_probs.loc[nearest[-1]]
            else:
                row = self._smoothed_probs.loc[date]
        else:
            row = self._smoothed_probs.iloc[-1]

        regime = 'BULL' if row['regime'] == 1 else 'BEAR'
        bull_prob = float(row['bull_probability'])

        # Volatility regime from GARCH
        vol_prob = self._get_vol_probability(date)
        vol_regime = 'HIGH' if vol_prob > VOL_GATE_THRESHOLD else 'LOW'

        return {
            'etf': self.etf_ticker,
            'regime': regime,
            'bull_probability': round(bull_prob, 4),
            'vol_regime': vol_regime,
            'vol_probability': round(vol_prob, 4),
        }

    def _get_vol_probability(
        self, date: Optional[str] = None
    ) -> float:
        """Get high-volatility probability from GARCH conditional variance."""
        if self.garch_result is None:
            return 0.0
        try:
            cond_var = self.garch_result.conditional_variance
            latest_var = float(cond_var.iloc[-1])
            median_var = float(cond_var.median())
            if median_var == 0:
                return 0.0
            prob = min(1.0, latest_var / (median_var * 3))
            return prob
        except Exception:
            return 0.0

    def get_regime_history(self) -> pd.DataFrame:
        """Get full regime history as DataFrame."""
        if not self._is_trained:
            return pd.DataFrame()
        return self._smoothed_probs.copy()


class SectorRegimeManager:
    """Manages Jump Models for all 11 sector ETFs."""

    def __init__(self, jump_penalty: float = DEFAULT_LAMBDA):
        self.jump_penalty = jump_penalty
        self.models: Dict[str, JumpModel] = {}
        self.last_updated: Optional[str] = None
        self._train_lock = threading.Lock()

    def ensure_trained(self) -> bool:
        """Lazily train all Jump Models on first use (just-in-time).

        The Jump Models live only in memory and are empty after a server
        restart, which made Command Center's "Today's Regime" report UNKNOWN
        until a manual retrain ran. This trains all 11 sector ETFs on demand
        so the card resolves to BULL/BEAR without manual action. No-op once
        models are trained (per-process).

        Returns:
            True if training was triggered (or models were already trained).
        """
        if self.models and all(m.is_trained for m in self.models.values()):
            return True
        with self._train_lock:
            # Double-checked under the lock: another request may have trained
            # while this one was waiting to acquire it.
            if self.models and all(m.is_trained for m in self.models.values()):
                return True
            end = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            start = (datetime.now() - timedelta(days=int(365.25 * 3 + 35))).strftime('%Y-%m-%d')
            self.train_all(start, end)
        return True

    def train_all(
        self, start_date: str, end_date: str
    ) -> Dict[str, bool]:
        """Train Jump Models for all sector ETFs.

        Returns: dict of {etf_ticker: success_bool}
        """
        results = {}
        for etf_info in SECTOR_ETFS:
            ticker = etf_info['ticker']
            features = compute_etf_features(ticker, start_date, end_date)
            model = JumpModel(ticker, self.jump_penalty)
            success = model.train(features)
            self.models[ticker] = model
            results[ticker] = success
            logger.info(
                f"Sector {etf_info['name']} ({ticker}): "
                f"{'trained' if success else 'FAILED'}"
            )

        self.last_updated = end_date
        return results

    def get_regime(
        self, etf_ticker: str, date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get regime for a specific ETF."""
        model = self.models.get(etf_ticker)
        if model is None:
            return {
                'etf': etf_ticker,
                'regime': 'UNKNOWN',
                'bull_probability': 0.5,
                'vol_regime': 'UNKNOWN',
                'vol_probability': 0.0,
            }
        return model.get_regime(date)

    def get_all_regimes(
        self, date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get regimes for all ETFs."""
        return [
            self.get_regime(etf['ticker'], date)
            for etf in SECTOR_ETFS
        ]

    def get_ticker_regime(
        self,
        ticker: str,
        sector: str,
        date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get regime for a ticker based on its sector.

        Maps ticker sector to the corresponding ETF. SECTOR_ETFS uses
        non-GICS names (e.g. "Financial Services", "Consumer Cyclical") while
        stock_metadata.sector stores GICS names (e.g. "Financials",
        "Consumer Discretionary", "Information Technology"). Callers pass the
        raw metadata sector, so we normalize via a GICS->ETF alias table before
        falling back to the direct name match. This prevents a GICS sector from
        resolving to UNKNOWN (which would silently drop stocks from the regime
        filter).
        """
        sector_to_etf = {
            etf['name'].lower(): etf['ticker'] for etf in SECTOR_ETFS
        }
        gics_aliases = {
            'financials': 'XLF', 'financial services': 'XLF',
            'health care': 'XLV', 'healthcare': 'XLV',
            'consumer discretionary': 'XLY', 'consumer cyclical': 'XLY',
            'consumer staples': 'XLP', 'consumer defensive': 'XLP',
            'materials': 'XLB', 'basic materials': 'XLB',
            'information technology': 'XLK', 'technology': 'XLK',
            'communication services': 'XLC', 'industrials': 'XLI',
            'energy': 'XLE', 'real estate': 'XLRE', 'utilities': 'XLU',
        }
        key = sector.lower()
        etf_ticker = sector_to_etf.get(key) or gics_aliases.get(key)
        if etf_ticker is None:
            etf_ticker = sector.upper()
        return self.get_regime(etf_ticker, date)


# Lazily-initialized process-wide manager so the screener's regime filter and
# the markov router evaluate against the SAME trained regime state. `train_all`
# (called by the router on retrain) populates this instance's `models`.
_shared_regime_manager: Optional["SectorRegimeManager"] = None
_shared_regime_manager_lock = threading.Lock()


def get_shared_regime_manager() -> "SectorRegimeManager":
    """Return the process-wide trained SectorRegimeManager (lazy singleton)."""
    global _shared_regime_manager
    if _shared_regime_manager is None:
        with _shared_regime_manager_lock:
            if _shared_regime_manager is None:
                _shared_regime_manager = SectorRegimeManager()
    return _shared_regime_manager
