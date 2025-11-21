import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
from utils.settings_manager import SettingsManager

class MarketRegimeDetector:
    
    def __init__(self, sm: SettingsManager, symbol: str = "XAUUSD"):
        self.sm = sm
        self.settings = self.sm.load_settings()
        self.symbol = symbol
        
        self.regime_history = []
        self.max_history = 100
        
        self.cached_indicators = {}
        self.last_update_time = None
        self.last_calibration_time = None
        
        # Load initial settings
        regime_settings = self.settings.get('market_regime', {})
        self.adx_trending_threshold = float(regime_settings.get('adx_trending', 25.0))
        self.adx_ranging_threshold = float(regime_settings.get('adx_ranging', 20.0))
        
        # Dynamic Thresholds (akan di-update via kalibrasi)
        self.atr_volatile_threshold = float(regime_settings.get('atr_volatile_ratio', 1.5))
        self.bb_width_ranging_threshold = float(regime_settings.get('bbw_ranging_pct', 0.05))
        
        breakout_config = regime_settings.get('breakout_momentum_pct', {})
        self.breakout_momentum_pct = float(breakout_config.get(self.symbol, breakout_config.get('default', 0.005)))
        
        self.is_calibrated = False
        
    def calibrate_thresholds(self, historical_data: pd.DataFrame):
        """
        Menganalisa data historis untuk menentukan ambang batas 'Volatile' dan 'Ranging' 
        secara adaptif berdasarkan kondisi pasar terkini.
        """
        if historical_data is None or len(historical_data) < 200:
            # print(f"[Regime] Warning: Need 200+ bars for calibration. Got {len(historical_data) if historical_data is not None else 0}")
            return
        
        try:
            atr = self._calculate_atr(historical_data, period=14)
            if atr is None or atr.isnull().all(): return
                
            atr_median = atr.quantile(0.5)
            atr_75th = atr.quantile(0.75)
            
            # Menentukan batas volatilitas tinggi (ATR Spike)
            # Jika ATR sekarang > X kali rata-rata ATR historis -> Volatile
            volatility_ratio = atr_75th / atr_median if atr_median > 0 else 1.5
            self.atr_volatile_threshold = max(1.3, min(volatility_ratio, 2.5))
            
            bb_width = self._calculate_bb_width(historical_data, period=20)
            if bb_width is None or bb_width.isnull().all(): return
            
            # Menentukan batas ranging (sideways)
            # Menggunakan kuartil bawah (25%) dari lebar BB historis sebagai definisi "Sideways Ketat"
            bb_width_pct_values = (bb_width / historical_data['close'].replace(0, 1e-9))
            bb_width_pct = bb_width_pct_values.quantile(0.25)
            self.bb_width_ranging_threshold = max(0.01, bb_width_pct)
            
            self.is_calibrated = True
            self.last_calibration_time = pd.Timestamp.now()
            
            # print(f"✅ [Regime] Calibrated for {self.symbol}: Volatile > {self.atr_volatile_threshold:.2f}x | Ranging < {self.bb_width_ranging_threshold*100:.2f}%")
            
        except Exception as e:
            print(f"❌ [Regime] Calibration error: {e}. Using defaults.")
            self.is_calibrated = False
        
    def detect_regime(self, data: pd.DataFrame, use_cache: bool = True) -> Tuple[str, Dict]:
        required_bars = 60
        if data is None or len(data) < required_bars:
            return "UNKNOWN", {"reason": "Insufficient data"}
        
        # Auto Re-Calibration setiap 4 jam
        now = pd.Timestamp.now()
        if not self.is_calibrated or (self.last_calibration_time and (now - self.last_calibration_time).total_seconds() > 14400):
            self.calibrate_thresholds(data)
        
        if use_cache and self._cache_is_valid(data):
            indicators = self.cached_indicators
        else:
            indicators = self._calculate_all_indicators(data)
            self.cached_indicators = indicators
            self.last_update_time = pd.Timestamp.now()
        
        if any(ind.isnull().all() for ind in indicators.values()):
            return "UNKNOWN", {"reason": "Indicator calculation failed (NaN)"}

        # Extract Current Values
        current_adx = indicators['adx'].iloc[-1]
        current_atr = indicators['atr'].iloc[-1]
        avg_atr = indicators['atr'].rolling(20).mean().iloc[-1]
        current_bb_width = indicators['bb_width'].iloc[-1]
        
        atr_ratio = current_atr / avg_atr if avg_atr > 0 else 1.0
        
        current_close = data['close'].iloc[-1]
        if current_close == 0: current_close = 1e-9
        bb_width_pct = current_bb_width / current_close
        
        scores = {
            'TRENDING': 0,
            'RANGING': 0,
            'VOLATILE': 0,
            'BREAKOUT': 0,
            'NEUTRAL': 0
        }
        
        # --- Scoring Logic (V3 Revised) ---
        
        # 1. TRENDING SCORE
        if current_adx > self.adx_trending_threshold:
            scores['TRENDING'] += max(0, (current_adx - 20) * 2.5)
            if 0.8 < atr_ratio < 1.5: # Trend sehat biasanya volatilitasnya stabil
                scores['TRENDING'] += 20
        
        # 2. RANGING SCORE
        if current_adx < self.adx_ranging_threshold:
            scores['RANGING'] += max(0, (25 - current_adx) * 3)
            if bb_width_pct < self.bb_width_ranging_threshold:
                scores['RANGING'] += 40
        
        # 3. VOLATILE SCORE
        if atr_ratio > self.atr_volatile_threshold:
            volatile_score = (atr_ratio - 1.0) * 100 
            scores['VOLATILE'] += min(volatile_score, 100)
        
        # 4. BREAKOUT SCORE (Logic Baru)
        if self._detect_breakout(data, indicators['adx'], indicators['bb_width']):
            scores['BREAKOUT'] += 150 # Prioritas SANGAT TINGGI jika terdeteksi (Override logic lain)
        
        scores['NEUTRAL'] = 30 # Baseline score
        
        # Determine Winner
        regime = max(scores, key=scores.get)
        max_score = scores[regime]
        confidence = min(max_score / 100.0, 1.0)
        
        # Cek High Volatility Warning
        is_high_volatility = (scores['VOLATILE'] > 50) or (atr_ratio > self.atr_volatile_threshold)
        
        # Jika Breakout terdeteksi, paksa regime jadi BREAKOUT meskipun skor lain tinggi
        # Karena breakout sifatnya fleeting (cepat hilang)
        if scores['BREAKOUT'] >= 100:
            regime = "BREAKOUT"
            confidence = 1.0

        details = self._generate_regime_details(
            regime, data, indicators, 
            current_adx, atr_ratio, bb_width_pct
        )
        
        details['is_high_volatility'] = is_high_volatility
        if is_high_volatility:
            details['warning'] = "High Volatility Detected!"
        
        # Logging History
        self.regime_history.append({
            'regime': regime,
            'confidence': confidence,
            'timestamp': pd.Timestamp.now(),
            'scores': scores
        })
        if len(self.regime_history) > self.max_history:
            self.regime_history.pop(0)
        
        return regime, {
            'confidence': round(confidence, 2),
            **details
        }
    
    def _generate_regime_details(self, regime: str, data: pd.DataFrame, 
                                 indicators: Dict, adx: float, 
                                 atr_ratio: float, bb_width_pct: float) -> Dict:
        
        base_details = {
            "adx": round(adx, 2),
            "atr_ratio": round(atr_ratio, 2),
            "bb_width_pct": f"{bb_width_pct*100:.2f}%"
        }

        if regime == "TRENDING":
            direction = "BULLISH" if data['close'].iloc[-1] > data['close'].iloc[-20] else "BEARISH"
            base_details.update({
                "direction": direction,
                "strength": "STRONG" if adx > 40 else "MODERATE",
                "trend_consistency": self._calculate_trend_consistency(data)
            })
        
        elif regime == "RANGING":
            high_20 = data['high'].rolling(20).max().iloc[-1]
            low_20 = data['low'].rolling(20).min().iloc[-1]
            range_pct = ((high_20 - low_20) / data['close'].iloc[-1]) * 100 if data['close'].iloc[-1] > 0 else 0
            base_details.update({
                "range_size": f"{range_pct:.2f}%",
                "support": round(low_20, 2),
                "resistance": round(high_20, 2),
                "price_position": self._get_range_position(data, low_20, high_20)
            })
        
        elif regime == "VOLATILE":
            base_details.update({
                "current_atr": round(indicators['atr'].iloc[-1], 2),
                "recommended_stop_multiplier": round(atr_ratio * 1.5, 1)
            })

        elif regime == "BREAKOUT":
            direction = "BULLISH" if data['close'].iloc[-1] > data['close'].iloc[-5] else "BEARISH"
            base_details.update({
                "direction": direction,
                "note": "MOMENTUM SURGE - DO NOT FADE",
                "adx_momentum": float(indicators['adx'].iloc[-1]) # Cast to float just in case
            })
        
        else: # NEUTRAL
             base_details.update({
                "note": "Mixed signals",
                "stability": round(self.get_regime_stability(), 2)
             })
        
        return base_details
    
    def _calculate_trend_consistency(self, data: pd.DataFrame, period: int = 20) -> str:
        closes = data['close'].iloc[-period:]
        if len(closes) < period: return "UNKNOWN"
        
        diffs = closes.diff().dropna()
        positive = (diffs > 0).sum()
        negative = (diffs < 0).sum()
        
        total = len(diffs)
        if total == 0: return "LOW"
        
        ratio = max(positive, negative) / total
        return "HIGH" if ratio > 0.7 else "LOW"
    
    def _get_range_position(self, data: pd.DataFrame, support: float, resistance: float) -> str:
        current_price = data['close'].iloc[-1]
        range_size = resistance - support
        if range_size <= 0: return "NEUTRAL"
        
        position_pct = (current_price - support) / range_size * 100
        
        if position_pct > 75: return "NEAR_RESISTANCE"
        elif position_pct < 25: return "NEAR_SUPPORT"
        else: return "MID_RANGE"
    
    def get_strategy_recommendation(self, regime: str, details: Dict) -> Dict:
        is_high_vol = details.get('is_high_volatility', False)
        
        rec = {
            "TRENDING": {
                "suggested_mode": "TREND_ONLY",
                "lot_multiplier": 1.0,
                "note": "Follow the trend."
            },
            "RANGING": {
                "suggested_mode": "SNIPER_ONLY",
                "lot_multiplier": 1.0,
                "note": "Buy Support, Sell Resistance."
            },
            "VOLATILE": {
                "suggested_mode": "BREAKOUT_ONLY", 
                "lot_multiplier": 0.7, # [FIX] Naik dari 0.5 ke 0.7 biar ga kena min-lot-trap
                "note": "High risk. Wide stops needed."
            },
            "BREAKOUT": {
                "suggested_mode": "TREND_ONLY", 
                "lot_multiplier": 1.2, 
                "note": "Aggressive entry allowed."
            },
            "NEUTRAL": {
                "suggested_mode": "SNIPER_ONLY",
                "lot_multiplier": 0.8,
                "note": "Scalp carefully."
            }
        }
        
        selected = rec.get(regime, rec["NEUTRAL"])
        
        # [LOGIC OVERRIDE]
        if is_high_vol and regime not in ["VOLATILE", "BREAKOUT"]:
            selected["lot_multiplier"] *= 0.7 # Safety reduction
            selected["note"] += " [WARNING: High Volatility]"
            
            # Ranging but Volatile = Whipsaw Risk -> Switch to Breakout
            if regime == "RANGING":
                selected["suggested_mode"] = "BREAKOUT_ONLY"
                selected["note"] = "Ranging but Volatile -> Expect Breakout."

        return selected
    
    def get_regime_summary(self) -> str:
        if not self.regime_history:
            return "No regime data"
        
        latest = self.regime_history[-1]
        regime = latest['regime']
        confidence = latest['confidence']
        
        emoji_map = {
            "TRENDING": "📈", "RANGING": "↔️", "VOLATILE": "⚡",
            "BREAKOUT": "🚀", "NEUTRAL": "⚪", "UNKNOWN": "❓"
        }
        emoji = emoji_map.get(regime, "❓")
        
        conf_bars = int(confidence * 5)
        conf_visual = "█" * conf_bars + "░" * (5 - conf_bars)
        
        stability = self.get_regime_stability()
        stability_emoji = "🔒" if stability > 0.7 else "🔄" if stability > 0.4 else "⚠️"
        
        return f"{emoji} {regime} [{conf_visual}] {confidence*100:.0f}% {stability_emoji}"

    def get_regime_stability(self) -> float:
        if len(self.regime_history) < 5: return 0.5
        recent_regimes = [h['regime'] for h in self.regime_history[-10:]]
        transitions = sum(1 for i in range(1, len(recent_regimes)) if recent_regimes[i] != recent_regimes[i-1])
        if len(recent_regimes) <= 1: return 1.0
        return 1.0 - (transitions / (len(recent_regimes) - 1))

    def _cache_is_valid(self, data: pd.DataFrame) -> bool:
        if not self.cached_indicators or self.last_update_time is None:
            return False
        age_seconds = (pd.Timestamp.now() - self.last_update_time).total_seconds()
        return age_seconds < 60
    
    def _calculate_all_indicators(self, data: pd.DataFrame) -> Dict:
        return {
            'adx': self._calculate_adx(data),
            'atr': self._calculate_atr(data),
            'bb_width': self._calculate_bb_width(data)
        }
    
    def _calculate_adx(self, data: pd.DataFrame, period: int = 14) -> pd.Series:
        high, low, close = data['high'], data['low'], data['close']
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        up_move = high - high.shift()
        down_move = low.shift() - low
        
        plus_dm = pd.Series(0.0, index=data.index)
        minus_dm = pd.Series(0.0, index=data.index)
        
        plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
        minus_dm[(down_move > up_move) & (down_move > 0)] = down_move
        
        atr = tr.ewm(span=period, adjust=False).mean()
        plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, 1)
        return dx.ewm(span=period, adjust=False).mean().fillna(0)
    
    def _calculate_atr(self, data: pd.DataFrame, period: int = 14) -> pd.Series:
        high, low, close = data['high'], data['low'], data['close']
        tr = pd.concat([high - low, abs(high - close.shift()), abs(low - close.shift())], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean().fillna(0)
    
    def _calculate_bb_width(self, data: pd.DataFrame, period: int = 20) -> pd.Series:
        close = data['close']
        std = close.rolling(period).std()
        return (4 * std).fillna(0)
    
    def _detect_breakout(self, data: pd.DataFrame, adx: pd.Series, bb_width: pd.Series) -> bool:
        if len(data) < 20: return False
        
        # [REVISI V3] Breakout Detection Instant (Price Action First)
        # Tidak lagi bergantung pada ADX (lagging), tapi pada penetrasi harga & ekspansi BB
        
        # 1. Price Breakout (Close tembus BB Upper/Lower 2.0 SD)
        period = 20
        std = data['close'].rolling(period).std().iloc[-1]
        ma = data['close'].rolling(period).mean().iloc[-1]
        upper = ma + (2.0 * std)
        lower = ma - (2.0 * std)
        
        close_now = data['close'].iloc[-1]
        is_price_breakout = close_now > upper or close_now < lower
        
        # 2. Candle Impulse (Body candle gede banget)
        open_now = data['open'].iloc[-1]
        current_body = abs(close_now - open_now)
        avg_body = abs(data['close'] - data['open']).rolling(10).mean().iloc[-1]
        
        # Jika body candle sekarang 2x lipat rata-rata -> IMPULSE
        is_impulse_candle = current_body > (avg_body * 2.0)
        
        # 3. BB Expansion (Syarat sekunder)
        avg_bbw = bb_width.rolling(10).mean().iloc[-1]
        current_bbw = bb_width.iloc[-1]
        is_bb_expanding = current_bbw > avg_bbw
        
        # Kesimpulan Breakout: Harga tembus BB DAN (Candle Gede ATAU BB Melebar)
        return is_price_breakout and (is_impulse_candle or is_bb_expanding)

if __name__ == "__main__":
    print("MarketRegimeDetector class definition loaded.")
    print("This file is intended to be imported, not run directly.")