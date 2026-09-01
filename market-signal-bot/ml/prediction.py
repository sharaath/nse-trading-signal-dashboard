import os
import pickle
import logging
import pandas as pd
import numpy as np
import ta
from typing import Dict, Any, Tuple, Optional
from sklearn.ensemble import RandomForestClassifier

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.dirname(os.path.abspath(__file__))

class MLPredictionEngine:
    def __init__(self, symbol: str):
        self.symbol = symbol.upper().replace("^", "")
        self.model_path = os.path.join(MODEL_DIR, f"model_{self.symbol}.pkl")
        self.model: Optional[RandomForestClassifier] = None
        self.load_model()

    def load_model(self):
        """Loads model pickle if it exists."""
        if os.path.exists(self.model_path):
            try:
                with open(self.model_path, "rb") as f:
                    self.model = pickle.load(f)
                logger.info(f"ML Model for {self.symbol} loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load ML model for {self.symbol}: {e}")

    def save_model(self):
        """Saves model to pickle file."""
        if self.model is not None:
            try:
                with open(self.model_path, "wb") as f:
                    pickle.dump(self.model, f)
                logger.info(f"ML Model for {self.symbol} saved successfully.")
            except Exception as e:
                logger.error(f"Failed to save ML model for {self.symbol}: {e}")

    def extract_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Extracts technical and structural features for model training/inference.
        All features must only use information available before the prediction timestamp.
        Specifically: NO look-ahead bias, future candle leakage, or using future high/low.
        """
        feats = pd.DataFrame(index=df.index)
        
        # 1. Technical Indicators (using strictly historical columns)
        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        
        # RSI
        feats["rsi"] = ta.momentum.RSIIndicator(close, window=14).rsi().fillna(50.0)
        
        # MACD
        macd_obj = ta.trend.MACD(close)
        feats["macd_diff"] = macd_obj.macd_diff().fillna(0.0)
        
        # EMAs and distances
        ema9 = ta.trend.EMAIndicator(close, window=9).ema_indicator()
        ema21 = ta.trend.EMAIndicator(close, window=21).ema_indicator()
        ema50 = ta.trend.EMAIndicator(close, window=50).ema_indicator()
        
        feats["close_to_ema9"] = (close - ema9) / ema9
        feats["ema9_to_ema21"] = (ema9 - ema21) / ema21
        feats["ema21_to_ema50"] = (ema21 - ema50) / ema50
        
        # ATR / Volatility
        feats["atr"] = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range().fillna(0.0)
        feats["atr_pct"] = feats["atr"] / close
        
        # Rate of Change (ROC)
        feats["roc_5"] = ta.momentum.ROCIndicator(close, window=5).roc().fillna(0.0)
        feats["roc_15"] = ta.momentum.ROCIndicator(close, window=15).roc().fillna(0.0)
        
        # 2. SMC Patterns (using strictly shifted rolling ranges to avoid target leakage)
        # Shift ranges by 1 to represent what was known BEFORE this candle close
        feats["dist_to_highest_5"] = ((high.shift(1).rolling(5).max() - close) / close).fillna(0.0)
        feats["dist_to_lowest_5"] = ((close - low.shift(1).rolling(5).min()) / close).fillna(0.0)
        
        # FVG detection proxy (using candles i-2, i-3 etc. which are fully finalized before current candle close i)
        fvg_bullish = (low.shift(1) - high.shift(3) > 0).astype(float)
        fvg_bearish = (low.shift(3) - high.shift(1) > 0).astype(float)
        feats["fvg_bullish"] = fvg_bullish.rolling(5).max().fillna(0.0)
        feats["fvg_bearish"] = fvg_bearish.rolling(5).max().fillna(0.0)
        
        # Volume expansion
        if "Volume" in df.columns:
            vol = df["Volume"]
            vol_sma20 = vol.rolling(20).mean()
            feats["vol_ratio"] = (vol / vol_sma20).fillna(1.0)
        else:
            feats["vol_ratio"] = 1.0

        return feats.fillna(0.0)

    def prepare_multiclass_labels(
        self,
        df: pd.DataFrame,
        lookforward_candles: int = 15,
        target_pct: float = 0.0025,
        stop_pct: float = 0.0015
    ) -> Tuple[pd.Series, pd.DataFrame]:
        """
        Models target vs stop loss outcomes chronologically.
        Outcome classes:
        - 1: TP_FIRST (Target reached before Stop Loss)
        - 0: SL_FIRST (Stop Loss reached before Target)
        - 2: NEITHER (Neither reached within lookforward_candles window)

        Also calculates MFE (Max Favorable Excursion) and MAE (Max Adverse Excursion) metrics.
        """
        closes = df["Close"].values
        highs = df["High"].values
        lows = df["Low"].values
        
        n = len(df)
        labels = np.zeros(n)
        
        metrics_list = []
        
        for i in range(n):
            if i >= n - lookforward_candles:
                labels[i] = 2  # default to NEITHER at end of series
                metrics_list.append({
                    "mfe": 0.0, "mae": 0.0, "time_to_t1": -1, "time_to_sl": -1,
                    "t1_first": False, "sl_first": False, "outcome": "NEITHER"
                })
                continue
                
            entry = closes[i]
            target_1 = entry * (1 + target_pct)
            stop_loss = entry * (1 - stop_pct)
            
            t1_hit = False
            sl_hit = False
            t1_time = -1
            sl_time = -1
            
            max_fav = 0.0
            max_adv = 0.0
            
            # Simulate forward chronologically
            for offset in range(1, lookforward_candles + 1):
                j = i + offset
                curr_high = highs[j]
                curr_low = lows[j]
                
                # Excursion checks
                fav_move = max(0.0, curr_high - entry)
                adv_move = max(0.0, entry - curr_low)
                
                max_fav = max(max_fav, fav_move)
                max_adv = max(max_adv, adv_move)
                
                if not sl_hit and curr_low <= stop_loss:
                    sl_hit = True
                    sl_time = offset
                    
                if not t1_hit and curr_high >= target_1:
                    t1_hit = True
                    t1_time = offset
            
            # Calculate final outcome
            t1_first = False
            sl_first = False
            outcome_str = "NEITHER"
            lbl = 2
            
            if t1_hit and (not sl_hit or t1_time < sl_time):
                t1_first = True
                outcome_str = "TP_FIRST"
                lbl = 1
            elif sl_hit and (not t1_hit or sl_time < t1_time):
                sl_first = True
                outcome_str = "SL_FIRST"
                lbl = 0
                
            labels[i] = lbl
            
            metrics_list.append({
                "mfe": max_fav / entry,
                "mae": max_adv / entry,
                "time_to_t1": t1_time,
                "time_to_sl": sl_time,
                "t1_first": t1_first,
                "sl_first": sl_first,
                "outcome": outcome_str
            })
            
        metrics_df = pd.DataFrame(metrics_list, index=df.index)
        return pd.Series(labels, index=df.index), metrics_df

    def train_model(
        self,
        df: pd.DataFrame,
        lookforward_candles: int = 15,
        target_pct: float = 0.0025,
        stop_pct: float = 0.0015
    ) -> str:
        """
        Trains the multi-class RandomForest model using strict chronological splitting:
        - Train period: first 70% of history
        - Validation period: next 15%
        - Out-of-sample test period: final 15%
        """
        if len(df) < 150:
            return "Insufficient candles to execute chronological ML split validation (min 150 required)."
            
        features = self.extract_features(df)
        labels, metrics = self.prepare_multiclass_labels(df, lookforward_candles, target_pct, stop_pct)
        
        # Align features and targets (drop final window due to lookforward constraints)
        X = features.iloc[:-lookforward_candles]
        y = labels.iloc[:-lookforward_candles]
        
        n_samples = len(X)
        train_end = int(n_samples * 0.70)
        val_end = int(n_samples * 0.85)
        
        X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
        X_val, y_val = X.iloc[train_end:val_end], y.iloc[train_end:val_end]
        X_test, y_test = X.iloc[val_end:], y.iloc[val_end:]
        
        # Train Multi-Class Classifier
        self.model = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42)
        self.model.fit(X_train, y_train)
        
        # Score across periods
        train_acc = self.model.score(X_train, y_train)
        val_acc = self.model.score(X_val, y_val)
        test_acc = self.model.score(X_test, y_test)
        
        # Fit on 100% data and cache
        self.model.fit(X, y)
        self.save_model()
        
        msg = (
            f"Chronological split training completed. "
            f"Train Acc: {train_acc:.1%}, Val Acc: {val_acc:.1%}, Out-of-Sample Test Acc: {test_acc:.1%}"
        )
        logger.info(msg)
        return msg

    def predict_probability(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Predicts target outcome probabilities for the latest completed candle (iloc[-2]).
        outcome indices:
        - Class 0: SL_FIRST
        - Class 1: TP_FIRST
        - Class 2: NEITHER
        """
        res = {"tp_before_sl": 0.33, "sl_before_tp": 0.33, "neither": 0.34}
        if self.model is None:
            return res
            
        try:
            features = self.extract_features(df)
            last_row = features.iloc[[-2]]
            
            probs = self.model.predict_proba(last_row)[0]
            
            # Match predicted class probabilities
            classes = self.model.classes_
            for idx, c in enumerate(classes):
                if c == 0:
                    res["sl_before_tp"] = float(probs[idx])
                elif c == 1:
                    res["tp_before_sl"] = float(probs[idx])
                elif c == 2:
                    res["neither"] = float(probs[idx])
        except Exception as e:
            logger.error(f"Error executing ML multi-class prediction: {e}")
            
        return res
