import pandas as pd
import numpy as np

from indicators.moving_average import MovingAverage
from indicators.rsi import RSI
from indicators.macd import MACD
from indicators.bollinger_bands import BollingerBands
from indicators.atr import ATR
from indicators.stochastic import Stochastic
from indicators.fibonacci import FibonacciRetracement
from core.candle_patterns import CandlePattern

from utils.settings_manager import SettingsManager 

try:
    from core.ai_analyzer import AIAnalyzer
except Exception:
    AIAnalyzer = None


class TradingStrategy:

    def __init__(self, sm: SettingsManager):
        self.sm = sm
        self.settings = sm.load_settings()

        ind = self.settings['indicators']
        sig = self.settings['signal_requirements']
        
        # Trading Style: SCALPING / SWING / AUTO
        # Ini mengontrol cara engine memilih mode & threshold,
        # tapi di dalamnya tetap AUTO (bisa SNIPER/TREND/BREAKOUT)
        try:
            self.trading_style = self.sm.get_trading_style().upper()
        except Exception:
            self.trading_style = 'SCALPING'

        self.settings.setdefault('debug', {})
        self.debug_config = self.settings['debug']
        self.log_mtf = self.debug_config.get('log_mtf_filter', False)
        self.log_regime = self.debug_config.get('log_regime_changes', False)

        self.ma = MovingAverage(period=ind['ma_period'], shift=ind['ma_shift'])
        self.ma_long = MovingAverage(period=ind['ma_long_period'], shift=ind['ma_shift']) 
        # EMA 200 untuk Trend Filter Global
        self.ema_trend = MovingAverage(period=200)

        self.rsi = RSI(period=ind['rsi_period'],
                            overbought=ind['rsi_overbought'], oversold=ind['rsi_oversold'])
        self.macd = MACD(fast_period=ind['macd_fast'],
                            slow_period=ind['macd_slow'], signal_period=ind['macd_signal'])
        self.bb = BollingerBands(period=ind['bb_period'], deviation=ind['bb_deviation'])
        self.atr = ATR(period=ind['atr_period'])
        self.stoch = Stochastic(
            k_period=ind['stoch_k_period'],
            d_period=ind['stoch_d_period'],
            slowing=ind['stoch_slowing'],
            overbought=ind['stoch_overbought'],
            oversold=ind['stoch_oversold'],
        )
        
        # Configurable Lookback for Fibonacci
        fib_lookback = int(sig.get('fib_lookback', 100))
        self.fib = FibonacciRetracement(lookback=fib_lookback)
        
        self.cp = CandlePattern() 
        
        # Default MTF config akan disesuaikan lagi oleh style profile
        self.htf_timeframe = sig.get('higher_timeframe', 'H1') 
        self.enable_mtf = sig.get('enable_mtf', True)
        self.ma_htf = MovingAverage(period=50) 

        self.signal_config = sig
        self.scoring_config = sig.get('scoring', {})
        self.strategy_mode_override = sig.get('strategy_mode_override', 'AUTO').upper()

        self._base_min_conf_sniper = float(sig.get('min_conf_sniper', 0.5))
        self._base_min_conf_trend  = float(sig.get('min_conf_trend', 0.5))
        self._base_min_conf_pullback = float(sig.get('min_conf_pullback', 0.5)) 
        self._base_min_conf_breakout = float(sig.get('min_conf_breakout', 0.5))
        
        self.min_exit_score = float(sig.get('min_exit_score', 2.0))

        # Nilai ini akan di-tune ulang oleh style profile (SCALPING / SWING)
        self.min_conf_sniper = self._base_min_conf_sniper
        self.min_conf_trend  = self._base_min_conf_trend
        self.min_conf_pullback = self._base_min_conf_pullback
        self.min_conf_breakout = self._base_min_conf_breakout

        self.current_regime = "UNKNOWN"
        self.regime_details = {} 

        # Terapkan profil awal berdasarkan trading_style
        self._apply_style_profile(self.trading_style) 

        self.ai_analyzer = None
        if sig.get('use_ai', False) and AIAnalyzer is not None:
            try:
                self.ai_analyzer = AIAnalyzer(self.settings)
            except Exception:
                self.ai_analyzer = None

    def _apply_style_profile(self, style: str):
        """
        Sesuaikan parameter strategi berdasarkan trading_style:
        - SCALPING : fokus M5, entry cepat, gunakan HTF H1 sebagai kompas
        - SWING    : fokus H1/H4, lebih strict, gunakan HTF H4 sebagai kompas
        - AUTO     : gunakan setting bawaan dari file config
        """
        style = (style or 'SCALPING').upper()
        self.trading_style = style

        # Default: gunakan nilai base dari config
        self.min_conf_sniper = self._base_min_conf_sniper
        self.min_conf_trend = self._base_min_conf_trend
        self.min_conf_pullback = self._base_min_conf_pullback
        self.min_conf_breakout = self._base_min_conf_breakout

        if style == 'SCALPING':
            # Entry di TF cepat (umumnya M5), gunakan HTF = H1 sebagai kompas trend
            self.htf_timeframe = 'H1'
            self.enable_mtf = True

            # Buat sedikit lebih mudah untuk tembak signal sniper,
            # tapi tetap menjaga trend/breakout tidak terlalu liar
            self.min_conf_sniper = max(0.5, self._base_min_conf_sniper - 0.5)
            self.min_conf_trend = self._base_min_conf_trend
            self.min_conf_pullback = self._base_min_conf_pullback
            self.min_conf_breakout = max(0.5, self._base_min_conf_breakout - 0.2)

        elif style == 'SWING':
            # Entry di TF besar (H1/H4), gunakan HTF lebih besar lagi (H4)
            self.htf_timeframe = 'H4'
            self.enable_mtf = True

            # Untuk swing, kita ingin konfirmasi lebih kuat
            self.min_conf_sniper = self._base_min_conf_sniper + 0.5
            self.min_conf_trend = max(1.0, self._base_min_conf_trend)
            self.min_conf_pullback = self._base_min_conf_pullback + 0.5
            self.min_conf_breakout = self._base_min_conf_breakout + 0.5

        else:
            # AUTO: gunakan setting file seadanya
            self.htf_timeframe = self.signal_config.get('higher_timeframe', 'H1')
            self.enable_mtf = self.signal_config.get('enable_mtf', True)

    def analyze(self, df_main: pd.DataFrame, session: str, df_htf: pd.DataFrame = None, is_backtest: bool = False):
        if df_main is None or len(df_main) < 205:
            return "NEUTRAL", 0.0, {}
        
        manual_mode = self.sm.get_trading_mode().upper() 
        
        # --- 1. MODE SELECTION ---
        if manual_mode != "AUTO":
            mode = manual_mode
        else:
            regime = self.current_regime
            # Mapping regime -> mode disesuaikan dengan trading_style,
            # tapi tetap fleksibel (engine bisa SNIPER/TREND/BREAKOUT)
            if self.trading_style == 'SCALPING':
                if regime in ["RANGING", "VOLATILE"]:
                    mode = "SNIPER_ONLY"
                elif regime in ["TRENDING", "BREAKOUT"]:
                    mode = "TREND_ONLY"
                else:
                    mode = "SNIPER_ONLY"
            elif self.trading_style == "SWING":
                # Swing: fokus tren besar, gunakan TREND/PULLBACK sebagai default
                if regime in ["TRENDING", "BREAKOUT"]:
                    mode = "TREND_ONLY"
                elif regime == "RANGING":
                    mode = "SNIPER_ONLY"
                else:
                    mode = "TREND_ONLY"
            else:
                # Default AUTO behaviour lama
                if regime == "TRENDING":
                    mode = "TREND_ONLY"
                elif regime == "RANGING":
                    mode = "SNIPER_ONLY"
                elif regime == "BREAKOUT":
                    mode = "TREND_ONLY"
                elif regime == "VOLATILE":
                    mode = "SNIPER_ONLY"
                else:
                    mode = "SNIPER_ONLY"

        sigs = {}
        sc = self.signal_config
        s = self.scoring_config
        total_score = 2.0

        # --- 2. INDICATOR CALCULATION ---
        if sc.get('use_atr', True):
            sigs['atr'] = self.atr.calculate(df_main)
            sigs['volatility'] = self.atr.get_volatility_state(df_main)
        
        # EMA Trend Filter
        ema200_val = self.ema_trend.get_ema(df_main)
        current_price = df_main['close'].iloc[-1]
        
        ma_trend = "NEUTRAL"
        if ema200_val:
            if current_price > ema200_val:
                ma_trend = "BULLISH"
            elif current_price < ema200_val:
                ma_trend = "BEARISH"
        
        sigs['main_trend'] = ma_trend 

        # Pattern Analysis
        atr_val = sigs.get('atr', 0.0)
        pattern_result = self.cp.analyze(df_main, atr=atr_val, current_trend=ma_trend)
        sigs['pattern'] = pattern_result

        # Fibonacci Calculation
        fib_levels = self.fib.calculate_levels(df_main)
        fib_zone = self.fib.get_current_zone(current_price, fib_levels)
        sigs['fib_levels'] = fib_levels
        sigs['fib_zone'] = fib_zone

        # HTF Check
        if self.enable_mtf and df_htf is not None and len(df_htf) > 50:
            htf_ma_val = self.ma_htf.calculate(df_htf)
            htf_trend = "NEUTRAL"
            if htf_ma_val:
                htf_price = df_htf['close'].iloc[-1]
                if htf_price > htf_ma_val:
                    htf_trend = "BULLISH"
                elif htf_price < htf_ma_val:
                    htf_trend = "BEARISH"
            
            htf_atr = self.atr.calculate(df_htf) or 0.0
            htf_pattern_result = self.cp.analyze(df_htf, atr=htf_atr, current_trend=htf_trend)
            sigs['htf_pattern'] = htf_pattern_result

        # Standard Indicators
        if mode in ["SNIPER_ONLY", "SNIPER"]:
            if sc.get('use_rsi', True):
                sigs['rsi'] = self.rsi.get_signal(df_main)
                sigs['rsi_value'] = self.rsi.calculate(df_main)
            if sc.get('use_bb', True):
                sigs['bb'] = self.bb.get_price_position_state(df_main)
            if sc.get('use_stoch', True):
                sigs['stoch'] = self.stoch.get_signal(df_main)
            min_conf_needed = self.min_conf_sniper
            total_score = s.get('sniper_setup_score', 1.5) + s.get('sniper_confirm_score', 1.0)

        elif mode in ["TREND_ONLY", "TREND"]:
            if sc.get('use_ma', True):
                sigs['ma'] = self.ma.get_signal(df_main)
            if sc.get('use_macd', True):
                sigs['macd'] = self.macd.get_state(df_main)
            min_conf_needed = self.min_conf_trend
            total_score = s.get('trend_ma_score', 1.5) + s.get('trend_macd_score', 1.0)

        elif mode == "PULLBACK_ONLY":
            if sc.get('use_ma', True):
                sigs['ma_long'] = self.ma_long.get_signal(df_main) 
            if sc.get('use_rsi', True):
                sigs['rsi'] = self.rsi.get_signal(df_main)
            if sc.get('use_stoch', True):
                sigs['stoch'] = self.stoch.get_signal(df_main)
            min_conf_needed = self.min_conf_pullback
            total_score = s.get('pullback_trend_score', 1.5) + s.get('pullback_rsi_score', 1.0)
        
        elif mode == "BREAKOUT_ONLY":
            sigs['regime'] = self.current_regime
            sigs['details'] = self.regime_details
            min_conf_needed = self.min_conf_breakout
            total_score = s.get('breakout_signal_score', 1.5) + s.get('breakout_confirm_score', 1.0)
        
        else: 
            return "NEUTRAL", 0.0, {}

        # --- 3. SCORING ---
        buy_score, sell_score = self._calculate_signal_scores(df_main, sigs, mode, df_htf)

        if total_score <= 0:
            total_score = 1

        signal_type = None
        confidence = 0.0
        
        if mode in ["SNIPER_ONLY", "SNIPER"]:
            min_conf_needed = self.min_conf_sniper
        elif mode in ["TREND_ONLY", "TREND"]:
            min_conf_needed = self.min_conf_trend
        elif mode == "PULLBACK_ONLY":
            min_conf_needed = self.min_conf_pullback
        elif mode == "BREAKOUT_ONLY":
            min_conf_needed = self.min_conf_breakout

        if buy_score >= min_conf_needed and buy_score > sell_score:
            signal_type = "BUY"
            confidence = (buy_score / total_score) * 100.0
        elif sell_score >= min_conf_needed and sell_score > buy_score:
            signal_type = "SELL"
            confidence = (sell_score / total_score) * 100.0

        confidence = min(confidence, 99.9)

        details = {
            'signals': sigs,
            'buy_score': buy_score,
            'sell_score': sell_score,
            'confidence': confidence,
            'signal_type': signal_type,
            'strategy_mode': mode,
            'min_conf_used': min_conf_needed,
            'main_trend': ma_trend
        }
        return signal_type, confidence, details

    def _get_htf_trend(self, df_htf: pd.DataFrame) -> str:
        """Get trend dari Higher Time Frame"""
        if df_htf is None or len(df_htf) < 50:
            return "NEUTRAL"
        try:
            htf_ma_value = self.ma_htf.calculate(df_htf)
            if htf_ma_value is None:
                return "NEUTRAL"
            current_price = df_htf['close'].iloc[-1]
            if current_price > htf_ma_value:
                return "BULLISH"
            elif current_price < htf_ma_value:
                return "BEARISH"
            return "NEUTRAL"
        except Exception:
            return "NEUTRAL"

    def _calculate_signal_scores(self, df_main: pd.DataFrame, signals: dict, strategy_mode: str, df_htf: pd.DataFrame):
        """Calculate BUY/SELL scores berdasarkan indicators"""
        buy, sell = 0.0, 0.0
        s = self.scoring_config

        pattern_data = signals.get('pattern', {})
        pat_score = pattern_data.get('score', 0)
        pat_strength = pattern_data.get('strength', 'LOW') 
        is_doji = pattern_data.get('is_doji', False)
        patterns_list = pattern_data.get('patterns', [])

        strength_mult = 1.5 if pat_strength == 'HIGH' else 1.0
        pattern_bonus = pat_score * 0.5 * strength_mult

        if pattern_bonus > 0:
            buy += pattern_bonus
        elif pattern_bonus < 0:
            sell += abs(pattern_bonus)

        htf_pat = signals.get('htf_pattern', {})
        htf_score = htf_pat.get('score', 0)
        if htf_score > 0:
            buy += 2.0 
        elif htf_score < 0:
            sell += 2.0

        if (pat_score > 0 and htf_score < 0) or (pat_score < 0 and htf_score > 0):
            buy *= 0.5
            sell *= 0.5
        
        if is_doji:
            buy *= 0.8
            sell *= 0.8

        # --- FIBONACCI BONUSES ---
        fib_zone = signals.get('fib_zone', 'UNKNOWN')
        fib_levels = signals.get('fib_levels', {})
        fib_trend = fib_levels.get('trend', 'UNKNOWN')

        if fib_zone == "IN_GOLDEN_ZONE":
            confluence = False
            if pat_score != 0:
                confluence = True
            elif signals.get('stoch') in ['BUY', 'SELL']:
                confluence = True
            elif signals.get('rsi') in ['BUY', 'SELL', 'OVERSOLD', 'OVERBOUGHT']:
                confluence = True
            
            if confluence:
                if fib_trend == "UP":
                    buy += 2.0
                    print(f"🔥 FIBONACCI BUY (Zone+Conf): {fib_zone}")
                elif fib_trend == "DOWN":
                    sell += 2.0
                    print(f"🔥 FIBONACCI SELL (Zone+Conf): {fib_zone}")
        
        # FIB INVALIDATION PENALTY
        if fib_trend == "UP" and fib_zone == "BELOW_ZONE":
            buy -= 5.0 
        elif fib_trend == "DOWN" and fib_zone == "ABOVE_ZONE":
            sell -= 5.0 

        # --- INDICATOR SCORING ---
        if strategy_mode in ["SNIPER_ONLY", "SNIPER"]:
            # Panic Candle Logic (Re-Added)
            last_candle = df_main.iloc[-1]
            recent_bodies = (df_main['close'].iloc[-11:-1] - df_main['open'].iloc[-11:-1]).abs().mean()
            current_body = abs(last_candle['close'] - last_candle['open'])
            is_panic_candle = current_body > (recent_bodies * 2.5)
            
            is_bullish_reversal = "BULLISH_PINBAR" in patterns_list or "MORNING_STAR" in patterns_list or "BULLISH_ENGULFING" in patterns_list
            is_bearish_reversal = "BEARISH_PINBAR" in patterns_list or "EVENING_STAR" in patterns_list or "BEARISH_ENGULFING" in patterns_list
            
            rsi_sig = signals.get('rsi')
            bb_sig = signals.get('bb')
            stoch_sig = signals.get('stoch')
            
            oversold_count = 0
            if rsi_sig in ['OVERSOLD', 'BUY']:
                oversold_count += 1
            if bb_sig == 'OVERSOLD':
                oversold_count += 1
            if stoch_sig in ['OVERSOLD', 'BUY']:
                oversold_count += 1
            
            overbought_count = 0
            if rsi_sig in ['OVERBOUGHT', 'SELL']:
                overbought_count += 1
            if bb_sig == 'OVERBOUGHT':
                overbought_count += 1
            if stoch_sig in ['OVERBOUGHT', 'SELL']:
                overbought_count += 1

            if oversold_count >= 1:
                # Filter Panic Candle without Reversal
                if is_panic_candle and not is_bullish_reversal:
                    pass  # Skip (Falling Knife)
                else:
                    buy += s.get('sniper_setup_score', 1.5) * (oversold_count / 2.0)
                    buy += s.get('sniper_confirm_score', 1.0)

            if overbought_count >= 1:
                if is_panic_candle and not is_bearish_reversal:
                    pass  # Skip (Rocket Launch)
                else:
                    sell += s.get('sniper_setup_score', 1.5) * (overbought_count / 2.0)
                    sell += s.get('sniper_confirm_score', 1.0)
        
        elif strategy_mode in ["TREND_ONLY", "TREND"]:
            if signals.get('ma') in ['BUY', 'BULLISH', 'BULLISH_CROSS']:
                buy += s.get('trend_ma_score', 1.5)
            if signals.get('ma') in ['SELL', 'BEARISH', 'BEARISH_CROSS']:
                sell += s.get('trend_ma_score', 1.5)

            if signals.get('macd') in ['BUY', 'BULLISH', 'BULLISH_CROSS']:
                buy += s.get('trend_macd_score', 1.0)
            if signals.get('macd') in ['SELL', 'BEARISH', 'BEARISH_CROSS']:
                sell += s.get('trend_macd_score', 1.0)

            direction = self.regime_details.get('direction', 'NEUTRAL')
            if direction == 'BULLISH':
                buy += 1.0 
            elif direction == 'BEARISH':
                sell += 1.0

        elif strategy_mode == "PULLBACK_ONLY":
            main_trend = signals.get('ma_long')
            rsi_sig = signals.get('rsi')
            if main_trend in ['BUY', 'BULLISH']:
                buy += s.get('pullback_trend_score', 1.5)
                if rsi_sig in ['BUY', 'OVERSOLD']:
                    buy += s.get('pullback_rsi_score', 1.0)
            elif main_trend in ['SELL', 'BEARISH']:
                sell += s.get('pullback_trend_score', 1.5)
                if rsi_sig in ['SELL', 'OVERBOUGHT']:
                    sell += s.get('pullback_rsi_score', 1.0)
        
        elif strategy_mode == "BREAKOUT_ONLY":
            direction = signals.get('details', {}).get('direction', 'NEUTRAL')
            if direction == "BULLISH":
                buy += s.get('breakout_signal_score', 1.5)
            elif direction == "BEARISH":
                sell += s.get('breakout_signal_score', 1.5)

        # --- MTF VETO (SAFETY FIRST) ---
        if self.enable_mtf and df_htf is not None:
            htf_trend = self._get_htf_trend(df_htf)
            bonus = s.get('mtf_bonus_score', 2.0)
            
            # Bonus jika searah
            if htf_trend == "BULLISH":
                buy += bonus
            elif htf_trend == "BEARISH":
                sell += bonus
            
            # VETO: Jangan lawan tren besar di mode Trend/Breakout
            if strategy_mode in ["TREND_ONLY", "BREAKOUT_ONLY"]:
                if buy > 0 and htf_trend == "BEARISH":
                    buy = 0  # Kill Signal
                if sell > 0 and htf_trend == "BULLISH":
                    sell = 0  # Kill Signal

        return buy, sell

    def update_dynamic_confidence(self, regime: str, details: dict):
        """Update confidence thresholds berdasarkan market regime"""
        self.current_regime = regime
        self.regime_details = details 
        if regime == "VOLATILE":
            self.min_conf_sniper += 2.0 
            self.min_conf_breakout = max(1.0, self._base_min_conf_breakout - 0.2)
        elif regime == "TRENDING":
            strength = details.get('strength', 'N/A')
            if strength == 'STRONG':
                self.min_conf_trend = max(1.0, self._base_min_conf_trend - 0.5) 
                self.min_conf_pullback = max(1.0, self._base_min_conf_pullback - 0.5)
                self.min_conf_sniper += 2.0 
        elif regime == "RANGING":
            self.min_conf_sniper = max(1.5, self._base_min_conf_sniper - 0.5)

    def should_close_position(self, position: dict, details: dict):
        """
        Emergency Exit Conditions
        Hanya close jika kondisi berbahaya (Trend Reversal / Fib Invalidation)
        """
        pos_type = position.get('type')
        main_trend = details.get('main_trend', 'NEUTRAL')
        
        # 1. TREND REVERSAL EXIT (EMA 200 Cross)
        if pos_type == 'BUY' and main_trend == 'BEARISH':
            return True, "Emergency Exit: Trend Reversal (Price < EMA200)"
        if pos_type == 'SELL' and main_trend == 'BULLISH':
            return True, "Emergency Exit: Trend Reversal (Price > EMA200)"

        # 2. FIB INVALIDATION EXIT
        # Pastikan level fib valid sebelum dicek
        fib_levels = details.get('signals', {}).get('fib_levels')
        if fib_levels:
            fib_zone = details.get('signals', {}).get('fib_zone')
            if pos_type == 'BUY' and fib_zone == 'BELOW_ZONE':
                return True, "Exit: Fib Setup Invalidated (Price < Swing Low)"
            if pos_type == 'SELL' and fib_zone == 'ABOVE_ZONE':
                return True, "Exit: Fib Setup Invalidated (Price > Swing High)"

        return False, "Hold"

    def get_signal_summary(self, details: dict) -> str:
        """Get summary text dari signal details"""
        sigs = details.get('signals', {})
        parts = []
        
        fib_zone = sigs.get('fib_zone', 'UNKNOWN')
        if fib_zone != 'UNKNOWN':
            parts.append(f"FIB: {fib_zone}")

        if 'pattern' in sigs and sigs['pattern'].get('patterns'):
            pats = ",".join(sigs['pattern']['patterns'])
            parts.append(f"PAT: {pats}")
        
        parts.append(f"MODE: {details.get('strategy_mode', 'N/A')}")
        parts.append(f"TREND: {details.get('main_trend', 'N/A')}")
        return " | ".join(parts) if parts else "No clear signals"

    def validate_signal(self, signal_type: str, df, symbol_info: dict):
        """Validate signal sebelum execute"""
        if len(df) < 200:
            return False, "Insufficient data for EMA200"
        
        current_price = df['close'].iloc[-1]
        ema200 = self.ema_trend.get_ema(df)
        
        if not ema200:
            return True, "EMA not ready" 
        
        # EMA 200 Filter (Strict for Trend Mode)
        mode = self.sm.get_trading_mode()
        if mode != "SNIPER_ONLY":
            if signal_type == "BUY" and current_price < ema200:
                return False, "Filtered: BUY below EMA 200"
            if signal_type == "SELL" and current_price > ema200:
                return False, "Filtered: SELL above EMA 200"
            
        return True, "Signal valid"