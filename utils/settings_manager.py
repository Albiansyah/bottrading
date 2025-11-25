import json
import os
import shutil
import threading
from datetime import datetime
from typing import Tuple, Dict, List, Any, Optional
from copy import deepcopy

# --- CONSTANTS ---
KEY_TRADING = 'trading'
KEY_RISK = 'risk_management'
KEY_SIGNALS = 'signal_requirements'
KEY_REGIME = 'market_regime'
KEY_FILTERS = 'filters'
KEY_DEBUG = 'debug'
KEY_BACKTEST = 'backtesting'
KEY_INDICATORS = 'indicators'
KEY_META = '_meta' 

CURRENT_CONFIG_VERSION = 1

class SettingsManager:
    _instance = None
    _lock = threading.RLock()

    def __init__(self, settings_path='config/settings.json'):
        self.settings_path = settings_path
        self.backup_dir = 'config/backups'
        self.audit_file = 'config/audit.log'
        self.temp_path = f"{settings_path}.tmp"
        
        self._settings_cache: Dict[str, Any] = {}
        
        os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)
        
        self._load_and_validate()

    def _get_defaults(self) -> Dict[str, Any]:
        """Centralized Default Schema Definition."""
        return {
            KEY_META: {'version': CURRENT_CONFIG_VERSION, 'last_updated': str(datetime.now())},
            KEY_TRADING: {
                'symbol': 'XAUUSD',
                'timeframe': 'M5',
                'default_lot': 0.01,
                'max_positions': 5,
                'max_positions_per_direction': 3,
                # Default trading style profile:
                # SCALPING -> fokus TF cepat (M5)
                # SWING    -> fokus TF besar (H1/H4)
                # AUTO     -> bot yang pilih profile berdasarkan kondisi
                'trading_style': 'SCALPING'
            },
            KEY_RISK: {
                'max_total_risk_pct': 5.0,
                'risk_per_trade_pct': 1.0,
                'max_single_position_risk_pct': 2.0,
                'min_risk_reward_ratio': 1.5,
                'atr_multiplier_sl': 1.5,
                'atr_multiplier_tp': 2.5,
                'breakeven_rr': 1.0,
                'scale_out_enabled': True,
                'scale_out_rr1': 1.5,
                'scale_out_pct1': 0.5,
                'trailing_stop_enabled': True,
                'trailing_stop_atr_multiplier': 2.0,
                'trailing_step_points': 50,
                'trailing_activation_rr': 1.0,
                'drawdown_risk_reduction': True,
                'enable_margin_filter': True,
                'min_margin_level_pct': 500.0,
                'daily_loss_limit_pct': 5.0
            },
            KEY_SIGNALS: {
                'strategy_mode_override': 'AUTO',
                'higher_timeframe': 'H1',
                'enable_mtf': True,
                'use_ai': False,
                'min_conf_sniper': 2.0,
                'min_conf_trend': 1.5,
                'min_conf_pullback': 2.0,
                'min_conf_breakout': 1.2,
                'min_exit_score': 2.0,
                'cooldown_bars': 1,
                'one_order_per_bar': True,
                'scoring': {
                    'sniper_setup_score': 1.5, 'sniper_confirm_score': 1.0,
                    'trend_ma_score': 1.5, 'trend_macd_score': 1.0,
                    'pullback_trend_score': 1.8, 'pullback_rsi_score': 1.2,
                    'breakout_signal_score': 1.8, 'breakout_confirm_score': 1.2,
                    'mtf_bonus_score': 2.0, 'mtf_penalty_pct': 0.5
                }
            },
            KEY_INDICATORS: {
                'ma_period': 50, 'ma_shift': 0, 'ma_long_period': 200,
                'rsi_period': 14, 'rsi_overbought': 70, 'rsi_oversold': 30,
                'bb_period': 20, 'bb_deviation': 2.0,
                'atr_period': 14,
                'stoch_k_period': 14, 'stoch_d_period': 3, 'stoch_slowing': 3,
                'stoch_overbought': 80, 'stoch_oversold': 20,
                'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9
            },
            KEY_REGIME: {
                'adx_trending': 25.0,
                'adx_ranging': 20.0,
                'atr_volatile_ratio': 1.5,
                'bbw_ranging_pct': 0.05,
                'breakout_momentum_pct': {'default': 0.005, 'XAUUSD': 0.003}
            },
            KEY_FILTERS: {
                'news_filter_enabled': True,
                'news_before_minutes': 30, 
                'news_after_minutes': 30,  
                'session_filter_enabled': True,
                'min_atr_value': 0.2,
                'allowed_sessions': ['asian', 'london', 'us'],
                'spread_settings': {'default_max': 35, 'overrides': {'XAUUSD': 50}},
                'asia_session_mode': 'DEFENSIVE'
            },
            KEY_BACKTEST: {
                'start_date': None,
                'end_date': None,
                'initial_balance': 1000.0
            },
            KEY_DEBUG: {
                'log_lot_calculation': False,
                'log_mtf_filter': False,
                'log_regime_changes': True
            }
        }

    # --- AUDIT LOGGING ---
    def _log_audit(self, action: str, key: str, old_val: Any, new_val: Any):
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            entry = f"[{timestamp}] {action.upper()} | Key: {key} | Old: {old_val} -> New: {new_val}\n"
            with open(self.audit_file, 'a') as f:
                f.write(entry)
        except Exception as e:
            print(f"Audit log failed: {e}")

    # --- MIGRATION & LOAD ---
    def _migrate_schema(self, data: Dict) -> Dict:
        meta = data.get(KEY_META, {})
        version = meta.get('version', 0)
        
        if version < CURRENT_CONFIG_VERSION:
            print(f"[Settings] Migrating config from v{version} to v{CURRENT_CONFIG_VERSION}...")
            if KEY_META not in data: data[KEY_META] = {}
            data[KEY_META]['version'] = CURRENT_CONFIG_VERSION
            data[KEY_META]['last_migration'] = str(datetime.now())
            
        return data

    def _load_and_validate(self):
        with self._lock:
            loaded = {}
            try:
                if os.path.exists(self.settings_path) and os.path.getsize(self.settings_path) > 0:
                    with open(self.settings_path, 'r') as f:
                        loaded = json.load(f)
                else:
                    loaded = self._get_defaults()
            except json.JSONDecodeError:
                print("[Settings] ❌ CORRUPTED JSON! Attempting restore...")
                if self._restore_last_working():
                    return self._load_and_validate()
                else:
                    loaded = self._get_defaults()
            
            loaded = self._migrate_schema(loaded)
            self._settings_cache = self._validate_schema(loaded)
            self.save_settings(log_audit=False)

    def _validate_schema(self, config: Dict) -> Dict:
        defaults = self._get_defaults()
        for key, val in defaults.items():
            if key not in config:
                config[key] = val
            elif isinstance(val, dict):
                for sub_key, sub_val in val.items():
                    if sub_key not in config[key]:
                        config[key][sub_key] = sub_val
        return config

    def load_settings(self) -> Dict[str, Any]:
        return deepcopy(self._settings_cache)

    def save_settings(self, log_audit=True) -> bool:
        with self._lock:
            try:
                self._validate_cross_fields()
                
                if KEY_META not in self._settings_cache: self._settings_cache[KEY_META] = {}
                self._settings_cache[KEY_META]['last_updated'] = str(datetime.now())

                with open(self.temp_path, 'w') as f:
                    json.dump(self._settings_cache, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(self.temp_path, self.settings_path)
                return True
            except Exception as e:
                print(f"[Settings] Save failed: {e}")
                if os.path.exists(self.temp_path): os.remove(self.temp_path)
                return False

    def _validate_cross_fields(self):
        rm = self._settings_cache.get(KEY_RISK, {})
        if rm.get('risk_per_trade_pct', 0) > rm.get('max_total_risk_pct', 100):
             rm['risk_per_trade_pct'] = rm['max_total_risk_pct']
        if rm.get('max_single_position_risk_pct', 0) > rm.get('max_total_risk_pct', 100):
             rm['max_single_position_risk_pct'] = rm['max_total_risk_pct']

    # --- PRESETS (Deep Merge) ---
    
    def get_setting_presets(self) -> Dict[str, Dict]:
        return {
            'CONSERVATIVE': {
                'name': 'Conservative (Safe)',
                'settings': {
                    KEY_RISK: {'risk_per_trade_pct': 0.5, 'max_total_risk_pct': 2.0, 'trailing_activation_rr': 1.5},
                    KEY_SIGNALS: {'enable_mtf': True, 'min_conf_sniper': 3.0},
                    KEY_FILTERS: {'news_filter_enabled': True}
                }
            },
            'BALANCED': {
                'name': 'Balanced (Standard)',
                'settings': {
                    KEY_RISK: {'risk_per_trade_pct': 1.0, 'max_total_risk_pct': 3.0, 'trailing_activation_rr': 1.0},
                    KEY_SIGNALS: {'enable_mtf': True, 'min_conf_sniper': 2.0},
                    KEY_FILTERS: {'news_filter_enabled': True}
                }
            },
            'SCALPER_GOLD': {
                'name': 'Gold Scalper (Aggressive V4)',
                'settings': {
                    KEY_RISK: {
                        'risk_per_trade_pct': 1.5, 'max_total_risk_pct': 6.0,
                        'trailing_stop_enabled': True, 'trailing_step_points': 50, 'trailing_activation_rr': 0.8
                    },
                    KEY_SIGNALS: {
                        'enable_mtf': False, 'strategy_mode_override': 'AUTO', 'cooldown_bars': 0
                    },
                    KEY_FILTERS: {
                        'news_filter_enabled': False, 'session_filter_enabled': False,
                        'spread_settings': {'default_max': 35, 'overrides': {'XAUUSD': 60}},
                        'asia_session_mode': 'DEFENSIVE'
                    }
                }
            }
        }

    def _deep_update(self, base_dict: Dict, update_dict: Dict) -> Dict:
        for key, value in update_dict.items():
            if isinstance(value, dict) and key in base_dict and isinstance(base_dict[key], dict):
                self._deep_update(base_dict[key], value)
            else:
                base_dict[key] = value
        return base_dict

    def load_preset(self, preset_name: str) -> Tuple[bool, str]:
        with self._lock:
            try:
                presets = self.get_setting_presets()
                if preset_name not in presets: return False, "Preset not found"

                self.backup_settings(auto=True)

                temp_settings = deepcopy(self._settings_cache)
                preset_data = presets[preset_name]['settings']
                
                temp_settings = self._deep_update(temp_settings, preset_data)
                temp_settings['active_preset'] = preset_name
                
                self._validate_schema(temp_settings)
                
                old_preset = self._settings_cache.get('active_preset', 'None')
                self._settings_cache = temp_settings
                
                self._log_audit("LOAD_PRESET", "Preset", old_preset, preset_name)
                
                if self.save_settings(): return True, f"Loaded {preset_name}"
                return False, "Save failed"
            except Exception as e:
                return False, str(e)

    # --- BACKUP ---

    def backup_settings(self, auto=False) -> Tuple[bool, str]:
        with self._lock:
            try:
                ts = datetime.now().strftime('%Y-%m-%d_%H%M%S')
                prefix = "auto_" if auto else ""
                fname = f"{prefix}settings_backup_{ts}.json"
                fpath = os.path.join(self.backup_dir, fname)
                
                # Atomic Copy
                temp_backup = fpath + ".tmp"
                with open(temp_backup, 'w') as f:
                    json.dump(self._settings_cache, f, indent=2)
                os.replace(temp_backup, fpath)
                
                self._cleanup_old_backups()
                return True, fpath
            except Exception as e: return False, str(e)

    def _cleanup_old_backups(self):
        try:
            files = []
            with os.scandir(self.backup_dir) as entries:
                for entry in entries:
                    if entry.is_file() and entry.name.endswith('.json'):
                        files.append((entry.path, entry.stat().st_mtime))
            files.sort(key=lambda x: x[1], reverse=True)
            for fpath, _ in files[10:]:
                try: os.remove(fpath)
                except: pass
        except: pass

    def list_backups(self) -> List[Dict[str, Any]]:
        backups = []
        try:
            with os.scandir(self.backup_dir) as entries:
                for entry in entries:
                    if entry.is_file() and entry.name.endswith('.json'):
                        try:
                            ts = datetime.fromtimestamp(entry.stat().st_mtime)
                            backups.append({'filename': entry.name, 'path': entry.path, 'timestamp': ts, 'is_auto': 'auto_' in entry.name})
                        except: continue
            backups.sort(key=lambda x: x['timestamp'], reverse=True)
        except: pass
        return backups

    def _restore_last_working(self) -> bool:
        backups = self.list_backups()
        if not backups: return False
        try:
            shutil.copy2(backups[0]['path'], self.settings_path)
            return True
        except: return False

    def restore_settings(self, backup_index: int) -> Tuple[bool, str]:
        with self._lock:
            backups = self.list_backups()
            if not (0 <= backup_index < len(backups)): return False, "Invalid index"
            try:
                with open(backups[backup_index]['path'], 'r') as f: data = json.load(f)
                self._settings_cache = self._validate_schema(data)
                self._log_audit("RESTORE", "Backup", "Current", backups[backup_index]['filename'])
                self.save_settings()
                return True, "Restored"
            except Exception as e: return False, str(e)

    def compare_backup(self, backup_index: int) -> str:
        backups = self.list_backups()
        if not (0 <= backup_index < len(backups)): return "Invalid Index"
        try:
            with open(backups[backup_index]['path'], 'r') as f: backup_data = json.load(f)
            diffs = []
            for section in [KEY_RISK, KEY_TRADING, KEY_SIGNALS]:
                curr = self._settings_cache.get(section, {})
                back = backup_data.get(section, {})
                for k, v in curr.items():
                    bv = back.get(k, "N/A")
                    if v != bv: diffs.append(f"[{section}][{k}]: Curr={v} | Back={bv}")
            return "\n".join(diffs) if diffs else "No major differences."
        except Exception as e: return f"Diff error: {e}"

    # --- SETTERS ---

    def _validate_input(self, key: str, value: Any) -> bool:
        try:
            if key == 'risk_per_trade_pct': return 0.1 <= float(value) <= 100.0
            elif key == 'max_total_risk_pct': return 1.0 <= float(value) <= 100.0
            elif key == 'default_lot': return float(value) >= 0.0
            elif key == 'timeframe': return str(value).upper() in ['M1','M5','M15','M30','H1','H4','D1']
            elif key == 'max_positions': return 1 <= int(value) <= 20
            elif key == 'max_spread': return 0 <= int(value) <= 500
            elif key == 'asia_session_mode': return str(value).upper() in ['DEFENSIVE', 'AGGRESSIVE']
            elif key == 'trading_style': return str(value).upper() in ['SCALPING', 'SWING', 'AUTO']
            return True
        except: return False

    def _set_val(self, section: str, key: str, value: Any, audit=True) -> bool:
        with self._lock:
            if not self._validate_input(key, value):
                print(f"[Settings] ❌ Invalid Input: {key}={value}")
                return False
                
            if section not in self._settings_cache: self._settings_cache[section] = {}
            
            old_val = self._settings_cache[section].get(key)
            
            if key in ['timeframe', 'strategy_mode_override', 'symbol', 'asia_session_mode']:
                value = str(value).upper()
            elif old_val is not None:
                try: value = type(old_val)(value)
                except: pass

            self._settings_cache[section][key] = value
            if audit and old_val != value:
                self._log_audit("UPDATE", f"{section}.{key}", old_val, value)

            return self.save_settings()

    # --- GETTERS ---
    def _get(self, section: str, key: str, default=None):
        return self._settings_cache.get(section, {}).get(key, default)

    def get_symbol(self): return self._get(KEY_TRADING, 'symbol', 'XAUUSD')
    def set_symbol(self, v): return self._set_val(KEY_TRADING, 'symbol', v)
    def get_timeframe(self): return self._get(KEY_TRADING, 'timeframe', 'M5')
    def set_timeframe(self, v): return self._set_val(KEY_TRADING, 'timeframe', v)
    def get_lot_size(self): return float(self._get(KEY_TRADING, 'default_lot', 0.0))
    def set_lot_size(self, v): return self._set_val(KEY_TRADING, 'default_lot', v)
    def get_max_positions(self): return int(self._get(KEY_TRADING, 'max_positions', 5))
    def set_max_positions(self, v): return self._set_val(KEY_TRADING, 'max_positions', v)

    # Trading Style Profile: SCALPING / SWING / AUTO
    def get_trading_style(self): return self._get(KEY_TRADING, 'trading_style', 'SCALPING')
    def set_trading_style(self, v): return self._set_val(KEY_TRADING, 'trading_style', v)

    def get_risk_per_trade(self): return float(self._get(KEY_RISK, 'risk_per_trade_pct', 1.0))
    def set_risk_per_trade(self, v): return self._set_val(KEY_RISK, 'risk_per_trade_pct', v)
    def get_max_total_risk(self): return float(self._get(KEY_RISK, 'max_total_risk_pct', 5.0))
    def set_max_total_risk(self, v): return self._set_val(KEY_RISK, 'max_total_risk_pct', v)
    def get_margin_filter_enabled(self): return self._get(KEY_RISK, 'enable_margin_filter', True)
    def toggle_margin_filter(self): return self._set_val(KEY_RISK, 'enable_margin_filter', not self.get_margin_filter_enabled())
    def get_min_margin_level(self): return float(self._get(KEY_RISK, 'min_margin_level_pct', 500.0))
    def set_min_margin_level(self, v): return self._set_val(KEY_RISK, 'min_margin_level_pct', v)

    def get_news_filter_enabled(self): return self._get(KEY_FILTERS, 'news_filter_enabled', True)
    def toggle_news_filter(self): return self._set_val(KEY_FILTERS, 'news_filter_enabled', not self.get_news_filter_enabled())
    def get_session_filter_enabled(self): return self._get(KEY_FILTERS, 'session_filter_enabled', True)
    def toggle_session_filter(self): return self._set_val(KEY_FILTERS, 'session_filter_enabled', not self.get_session_filter_enabled())
    def get_allowed_sessions(self): return self._get(KEY_FILTERS, 'allowed_sessions', [])
    def set_allowed_sessions(self, v): return self._set_val(KEY_FILTERS, 'allowed_sessions', v)
    
    def get_min_atr(self): return float(self._get(KEY_FILTERS, 'min_atr_value', 0.2))
    def set_min_atr(self, v): return self._set_val(KEY_FILTERS, 'min_atr_value', v)
    
    def get_max_spread(self): return int(self._get(KEY_FILTERS, 'spread_settings', {}).get('default_max', 35))
    def set_max_spread(self, v): 
        with self._lock:
            if 'spread_settings' not in self._settings_cache[KEY_FILTERS]:
                self._settings_cache[KEY_FILTERS]['spread_settings'] = {}
            self._settings_cache[KEY_FILTERS]['spread_settings']['default_max'] = int(v)
            return self.save_settings()

    def get_trading_mode(self): return self._get(KEY_SIGNALS, 'strategy_mode_override', 'AUTO')
    def set_trading_mode(self, v): return self._set_val(KEY_SIGNALS, 'strategy_mode_override', v)
    
    # [FIX: Added Missing Method for Asia Mode]
    def get_asia_session_mode(self): return self._get(KEY_FILTERS, 'asia_session_mode', 'DEFENSIVE')
    def set_asia_session_mode(self, v): return self._set_val(KEY_FILTERS, 'asia_session_mode', v.upper())

    def get_backtest_config(self): return self._get(KEY_BACKTEST, 'config', {})
    def set_backtest_period(self, s, e):
        with self._lock:
            self._settings_cache[KEY_BACKTEST]['start_date'] = s
            self._settings_cache[KEY_BACKTEST]['end_date'] = e
            return self.save_settings()

    # --- HEALTH & STATS ---
    def get_health_status(self) -> Tuple[str, str, List[str]]:
        warnings = []
        danger = 0
        
        rm = self._settings_cache.get(KEY_RISK, {})
        sig = self._settings_cache.get(KEY_SIGNALS, {})
        flt = self._settings_cache.get(KEY_FILTERS, {})
        active_preset = self._settings_cache.get('active_preset', '')

        risk_per = rm.get('risk_per_trade_pct', 1.0)
        if risk_per > 3:
            warnings.append(f"⚠️ Aggressive Risk ({risk_per}%)")
            danger += 1
            
        mtf_on = sig.get('enable_mtf', True)
        if not mtf_on:
            if 'SCALPER' not in active_preset:
                warnings.append("⚠️ MTF Filter OFF (Risky)")
                danger += 1
        
        news_on = flt.get('news_filter_enabled', True)
        if not news_on:
            if 'SCALPER' not in active_preset:
                 warnings.append("⚠️ News Filter OFF")

        if not rm.get('enable_margin_filter', True):
            warnings.append("🔴 DANGER: Margin Filter OFF")
            danger += 2

        if danger > 1: return "🔴", "CRITICAL", warnings
        if danger > 0 or warnings: return "🟡", "WARNING", warnings
        return "🟢", "HEALTHY", []

    def get_summary(self, balance: float = 10000.0) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append("              CURRENT CONFIGURATION".center(60))
        lines.append("=" * 60)

        emoji, status, warns = self.get_health_status()
        lines.append(f" {emoji} Health: {status}")
        if self._settings_cache.get('active_preset'):
             lines.append(f" 💾 Preset: {self._settings_cache['active_preset']}")
        lines.append("")

        lines.append(" 📊 TRADING:")
        lines.append(f" Symbol:        {self.get_symbol()}")
        lines.append(f" Timeframe:     {self.get_timeframe()}")
        lines.append(f" Mode:          {self.get_trading_mode()}")
        lines.append("")

        lines.append(" 💰 RISK:")
        risk_pct = self.get_risk_per_trade()
        risk_usd = balance * (risk_pct / 100.0)
        lines.append(f" Per Trade:     {risk_pct}% (~${risk_usd:.2f})")
        
        max_risk = self.get_max_total_risk()
        max_usd = balance * (max_risk / 100.0)
        lines.append(f" Max Total:     {max_risk}% (~${max_usd:.2f})")
        lines.append("")
        
        lines.append(" 🛡️ FILTERS:")
        lines.append(f" News Filter:   {'ON' if self.get_news_filter_enabled() else 'OFF'}")
        lines.append(f" MTF Filter:    {'ON' if self._get(KEY_SIGNALS, 'enable_mtf') else 'OFF'}")

        if warns:
            lines.append("")
            lines.append(" ⚠️ WARNINGS:")
            for w in warns: lines.append(f" {w}")

        lines.append("=" * 60)
        return "\n".join(lines)

    def get_quick_stats(self, balance: float = 10000.0) -> Dict[str, Any]:
        risk_pct = self.get_risk_per_trade()
        max_risk = self.get_max_total_risk()
        max_pos = self.get_max_positions()
        
        risk_usd = balance * (risk_pct / 100.0)
        max_total_usd = balance * (max_risk / 100.0)
        
        max_dd_usd = min(risk_usd * max_pos, max_total_usd)
        max_dd_pct = (max_dd_usd / balance * 100.0) if balance > 0 else 0
        
        emoji, status, warns = self.get_health_status()
        
        return {
            'health_emoji': emoji,
            'health_status': status,
            'risk_per_trade_pct': risk_pct,
            'risk_per_trade_usd': round(risk_usd, 2),
            'max_total_risk_pct': max_risk,
            'max_total_risk_usd': round(max_total_usd, 2),
            'max_drawdown_usd': round(max_dd_usd, 2),
            'max_drawdown_pct': round(max_dd_pct, 1),
            'warnings_count': len(warns),
            'warnings': warns
        }