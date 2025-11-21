import json
import os
from datetime import datetime
import time
import MetaTrader5 as mt5
import pandas as pd
from typing import Tuple, Dict, Any

from utils.settings_manager import SettingsManager
from utils.profit_target import ProfitTargetManager
from core.strategy import TradingStrategy
from core.risk_manager import RiskManager
from core.mt5_connector import MT5Connector

class TradeExecutor:
    def __init__(self, mt5_connector: MT5Connector, risk_manager: RiskManager, strategy: TradingStrategy, sm: SettingsManager, ptm: ProfitTargetManager):
        self.mt5 = mt5_connector
        self.risk_manager = risk_manager
        self.strategy = strategy
        self.sm = sm
        self.ptm = ptm
        self.settings = self.sm.load_settings()

        self.trading_config = self.settings.get('trading', {})
        self.signal_config = self.settings.get('signal_requirements', {})
        self.risk_config = self.settings.get('risk_management', {})
        
        self.symbol = self.trading_config.get('symbol', 'XAUUSD')
        self.timeframe = self.trading_config.get('timeframe', 'M1')

        self.managed_positions = {}
        self.scaled_out_tickets = {}
        self.at_breakeven_tickets = {}
        
        self.last_trade_close_time = 0 
        self.last_order_open_time = 0
        self.last_order_bar_time = None
        
        self.timeframe_seconds = self._timeframe_to_seconds(self.timeframe)
        
        self.use_bar_close_only = self.signal_config.get('bar_close_only', True)
        self.use_one_order_per_bar = self.signal_config.get('one_order_per_bar', True)

    def _timeframe_to_seconds(self, timeframe_str: str) -> int:
        if timeframe_str == 'M1': return 60
        if timeframe_str == 'M5': return 300
        if timeframe_str == 'M15': return 900
        if timeframe_str == 'M30': return 1800
        if timeframe_str == 'H1': return 3600
        if timeframe_str == 'H4': return 14400
        return 300

    def _is_bar_complete(self) -> bool:
        """
        Cek apakah candle saat ini sudah mendekati penutupan.
        """
        if not self.use_bar_close_only:
            return True 
        
        try:
            tick = mt5.symbol_info_tick(self.symbol)
            
            if tick is None:
                return False 
            
            server_time = datetime.fromtimestamp(tick.time)
            seconds_into_bar = server_time.second
            minutes_into_bar = server_time.minute
            
            # [REVISI V3] Lebarkan jendela waktu entry jadi 5 detik (>= 55)
            # Biar ga ketinggalan kereta kalau proses analisa makan waktu
            
            if self.timeframe == 'M1':
                return seconds_into_bar >= 55 
            
            if self.timeframe == 'M5':
                return (minutes_into_bar % 5) == 4 and seconds_into_bar >= 55
            
            if self.timeframe == 'M15':
                return (minutes_into_bar % 15) == 14 and seconds_into_bar >= 55
            
            # Default true untuk TF besar agar tidak miss signal
            return True

        except Exception as e:
            print(f"Error checking bar completion: {e}")
            return False

    def _check_cooldown_and_bar_limits(self, df_main: pd.DataFrame) -> Tuple[bool, str]:
        now = time.time()
        
        cooldown_bars = self.signal_config.get('cooldown_bars', 1) # Default dipendekin
        cooldown_seconds = cooldown_bars * self.timeframe_seconds
        
        if (now - self.last_order_open_time) < cooldown_seconds:
            return False, f'Cooldown active (waiting {cooldown_seconds}s after last open)'

        if self.use_one_order_per_bar:
            if df_main.empty:
                return False, 'No data to check bar time'
            
            current_bar_time = df_main.index[-1]
            if self.last_order_bar_time == current_bar_time:
                return False, f'One order per bar limit active (waiting for new bar)'
        
        return True, "OK"

    def _check_daily_limits(self, account_balance: float) -> Tuple[bool, str]:
        loss_limit_pct = self.risk_config.get('daily_loss_limit_pct', 0.0)
        if loss_limit_pct <= 0:
            return True, "OK" 
            
        self.ptm.load_daily_stats()
        today_pnl = self.ptm.today_profit
        
        if today_pnl < 0:
            loss_pct = (abs(today_pnl) / account_balance) * 100
            if loss_pct >= loss_limit_pct:
                return False, f"⛔ Daily Loss Limit Hit! (${today_pnl:.2f} / -{loss_limit_pct}%)"
                
        return True, "OK"

    def _get_current_price(self, symbol_info: dict, position_type: str) -> float:
        if position_type == 'BUY':
            return float(symbol_info.get('bid', 0.0))
        else:
            return float(symbol_info.get('ask', 0.0))

    def check_for_new_entry(self, session_name):
        result = {}
        symbol_info = self.mt5.get_symbol_info(self.symbol)
        if not symbol_info:
            return {'action_taken': 'FAILED', 'reason': 'Failed to get symbol info'}

        try:
            # 1. Cek Waktu Candle
            if not self._is_bar_complete():
                return None 
                
            # 2. Ambil Data Harga Utama
            df_main = self.mt5.get_price_data(self.symbol, self.timeframe, bars=200)
            if df_main is None or len(df_main) < 100:
                return None
            
            # 3. Cek Cooldown
            ok, reason = self._check_cooldown_and_bar_limits(df_main)
            if not ok:
                return { 
                    'signal_type': 'NEUTRAL', 'confidence': 0, 'details': {},
                    'action_taken': 'SKIPPED', 'reason': reason 
                }
            
            # 4. Ambil Data Higher Timeframe
            htf_timeframe = self.strategy.settings['signal_requirements'].get('higher_timeframe', 'H1')
            df_htf = self.mt5.get_price_data(self.symbol, htf_timeframe, bars=200)
            
            # [REVISI V3] Soft-fail. Jangan return SKIPPED jika HTF gagal load.
            if df_htf is None or len(df_htf) < 50:
                 # print("WARNING: HTF Data missing, proceeding with Current TF only.")
                 df_htf = None # Lanjut aja, nanti strategy yg handle (skor dikurangi)

            # 5. Analisa Strategy
            signal_type, confidence, details = self.strategy.analyze(
                df_main=df_main, 
                df_htf=df_htf, 
                session=session_name, 
                is_backtest=False
            )
            
            if signal_type is None:
                buy_score = float(details.get('buy_score', 0)) if isinstance(details, dict) else 0.0
                sell_score = float(details.get('sell_score', 0)) if isinstance(details, dict) else 0.0
                
                if buy_score > 0 or sell_score > 0:
                    return {
                        'signal_type': None, 'confidence': 0, 'details': details or {},
                        'action_taken': 'SKIPPED',
                        'reason': f"Scores too low (buy={buy_score:.1f}, sell={sell_score:.1f})"
                    }
                return None

            result = {
                'signal_type': signal_type,
                'confidence': float(confidence or 0),
                'details': details or {}
            }

            # 6. Validasi Tambahan
            is_valid, validation_msg = self.strategy.validate_signal(signal_type, df_main, symbol_info)
            if not is_valid:
                result['action_taken'] = 'REJECTED'
                result['reason'] = validation_msg
                return result

            account_info = self.mt5.get_account_info()
            if not account_info:
                result['action_taken'] = 'FAILED'
                result['reason'] = 'Failed to get account info'
                return result

            positions = self.mt5.get_positions(self.symbol) or []
            balance = float(account_info.get('balance', 0.0))
            
            ok, reason = self._check_daily_limits(balance)
            if not ok:
                result['action_taken'] = 'REJECTED'
                result['reason'] = reason
                return result

            if signal_type == "BUY":
                entry_price = float(symbol_info.get('ask', 0.0))
            else:
                entry_price = float(symbol_info.get('bid', 0.0))

            if entry_price <= 0:
                result['action_taken'] = 'FAILED'
                result['reason'] = 'Invalid entry price'
                return result

            atr_value = details.get('signals', {}).get('atr')
            if atr_value is None or atr_value <= 0:
                atr_value = self.strategy.atr.calculate(df_main)
                if atr_value is None:
                    result['action_taken'] = 'FAILED'
                    result['reason'] = 'Failed to get ATR'
                    return result

            # 7. Hitung Risk Management
            strategy_mode = details.get('strategy_mode', 'AUTO')
            
            sl_price, tp_price = self.risk_manager.calculate_sl_tp(
                entry_price, signal_type, atr_value, symbol_info, strategy_mode
            )
            if sl_price is None or tp_price is None:
                result['action_taken'] = 'FAILED'
                result['reason'] = 'Failed to calculate SL/TP'
                return result

            lot_size = self.risk_manager.calculate_optimal_lot_size(
                balance, entry_price, sl_price, symbol_info
            )

            position_risk = self.risk_manager.calculate_position_risk(
                entry_price, sl_price, lot_size, symbol_info
            )
            can_open, reason = self.risk_manager.can_open_new_position(
                balance, positions, position_risk, signal_type, symbol_info
            )
            if not can_open:
                result['action_taken'] = 'REJECTED'
                result['reason'] = reason
                return result

            # 8. Eksekusi Order
            order_comment = f"Bot-V3-{strategy_mode}"

            order_result = self.mt5.send_order(
                self.symbol, signal_type, lot_size,
                sl=sl_price, tp=tp_price,
                comment=order_comment
            )
            if not order_result or 'ticket' not in order_result:
                result['action_taken'] = 'FAILED'
                result['reason'] = 'Order execution failed (MT5 Error)'
                return result

            order_info = {
                'ticket': order_result['ticket'],
                'symbol': self.symbol,
                'type': signal_type,
                'lot': order_result['volume'],
                'entry': order_result['price'], 
                'sl': sl_price,
                'tp': tp_price,
                'risk': position_risk,
                'confidence': result['confidence'],
                'time': datetime.now(),
                'details': result['details']
            }
            
            self.managed_positions[order_info['ticket']] = order_info['type']
            self.last_order_open_time = time.time()
            self.last_order_bar_time = df_main.index[-1]
            
            result['action_taken'] = 'EXECUTED'
            result['order_info'] = order_info
            return result

        except Exception as e:
            print(f"❌ Error in check_for_new_entry: {e}")
            result['action_taken'] = 'FAILED'
            result['reason'] = str(e)
            return result

    def reconcile_closed_by_broker(self):
        if not self.managed_positions:
            return []

        try:
            open_positions = self.mt5.get_positions(self.symbol) or []
            open_tickets_on_mt5 = {p.get('ticket') for p in open_positions}

            closed_tickets = [t for t in list(self.managed_positions.keys())
                                if t not in open_tickets_on_mt5]
            if not closed_tickets:
                return []

            closed_trades_info = []
            for ticket in closed_tickets:
                try:
                    deals = mt5.history_deals_get(position=ticket)
                except Exception:
                    deals = None
                
                profit = 0.0
                if deals:
                    for deal in deals:
                        if deal.entry == mt5.DEAL_ENTRY_OUT or deal.entry == mt5.DEAL_ENTRY_INOUT:
                            profit += deal.profit
                
                reason = "SL/TP Hit (or Manual)"
                pos_type = self.managed_positions.get(ticket, "UNKNOWN")

                closed_trades_info.append({
                    'ticket': ticket,
                    'profit': profit,
                    'reason': reason,
                    'type': pos_type
                })

                self.managed_positions.pop(ticket, None)
                self.scaled_out_tickets.pop(ticket, None) 
                self.at_breakeven_tickets.pop(ticket, None)
                
                self.last_trade_close_time = time.time()

            return closed_trades_info

        except Exception as e:
            print(f"Error during trade reconciliation: {e}")
            return []

    def manage_positions(self):
        actions = []
        positions = self.mt5.get_positions(self.symbol) or []
        if not positions:
            return actions

        symbol_info = self.mt5.get_symbol_info(self.symbol)
        if not symbol_info:
            return actions
            
        # Di sini kita panggil get_price_data lagi, tapi ini krusial buat trailing stop
        # Tidak apa-apa ada overhead sedikit demi keamanan posisi yg udah kebuka
        df_main = self.mt5.get_price_data(self.symbol, self.timeframe, bars=100)
        if df_main is None or len(df_main) < 20:
             atr_value = 0.0
        else:
             atr_value = self.strategy.atr.calculate(df_main) or 0.0

        open_tickets = [p.get('ticket') for p in positions if p.get('ticket') in self.managed_positions]
        if not open_tickets:
            return actions

        for ticket in open_tickets:
            try:
                pos_list = self.mt5.get_positions(ticket=ticket)
                if not pos_list:
                    continue 
                position = pos_list[0]
                
                current_price = self._get_current_price(symbol_info, position.get('type'))
                        
                has_scaled_out = self.scaled_out_tickets.get(ticket, False)
                is_at_breakeven = self.at_breakeven_tickets.get(ticket, False)

                # 1. Scale Out (Partial Close)
                if not has_scaled_out: 
                    should_scale, lot_to_close, rr = self.risk_manager.check_scale_out(position, current_price)
                    
                    if should_scale and lot_to_close > 0:
                        if self.mt5.partial_close_position(ticket, lot_to_close, comment=f"Scale Out {rr}R"):
                            actions.append({'action': 'SCALE_OUT', 'ticket': ticket, 'volume': lot_to_close})
                            # print(f"INFO: Posisi {ticket} sukses partial close {lot_to_close} lot.")
                            self.scaled_out_tickets[ticket] = True
                        else:
                            pass # print(f"WARNING: Gagal eksekusi Partial Close untuk ticket {ticket}.")
                
                # 2. Move to Breakeven
                if not is_at_breakeven:
                    should_be, new_sl = self.risk_manager.should_move_to_breakeven(
                        position, current_price, symbol_info
                    )
                    if should_be and new_sl:
                        if self.mt5.modify_position(ticket, sl=new_sl):
                            actions.append({'action': 'BREAKEVEN', 'ticket': ticket, 'new_sl': new_sl})
                            position['sl'] = new_sl 
                            self.at_breakeven_tickets[ticket] = True 
                            # print(f"INFO: Posisi {ticket} mencapai R:R. Breakeven diaktifkan.")
                
                # 3. Trailing Stop
                if is_at_breakeven:
                    new_trailing_sl = self.risk_manager.calculate_trailing_stop(
                        position, current_price, atr_value, symbol_info
                    )
                    if new_trailing_sl:
                        if position.get('sl') != new_trailing_sl:
                            if self.mt5.modify_position(ticket, sl=new_trailing_sl):
                                actions.append({'action': 'TRAILING_STOP', 'ticket': ticket, 'new_sl': new_trailing_sl})
            except Exception as e:
                # print(f"Error managing position {ticket}: {e}")
                continue

        return actions

    def check_exit_signals(self, session_name):
        closed_positions = []
        positions = self.mt5.get_positions(self.symbol) or []
        if not positions:
            return closed_positions

        df_main = self.mt5.get_price_data(self.symbol, self.timeframe, bars=200)
        if df_main is None or len(df_main) < 100:
            return closed_positions
        
        # Data HTF opsional untuk exit signal
        htf_timeframe = self.strategy.settings['signal_requirements'].get('higher_timeframe', 'H1')
        df_htf = self.mt5.get_price_data(self.symbol, htf_timeframe, bars=200)
        
        symbol_info = self.mt5.get_symbol_info(self.symbol)
        if not symbol_info:
            return closed_positions

        signal_type, confidence, details = self.strategy.analyze(
            df_main=df_main, 
            df_htf=df_htf, 
            session=session_name, 
            is_backtest=False
        )

        for position in positions:
            ticket = position.get('ticket')
            if ticket not in self.managed_positions:
                continue

            should_close, reason = self.strategy.should_close_position(position, details or {})
            if should_close:
                profit_before_close = float(position.get('profit', 0.0))
                success = self.mt5.close_position(ticket)
                if success:
                    closed_positions.append({
                        'ticket': ticket,
                        'reason': reason,
                        'profit': profit_before_close,
                        'type': position.get('type', 'UNKNOWN')
                    })
                    self.managed_positions.pop(ticket, None)
                    self.scaled_out_tickets.pop(ticket, None)
                    self.at_breakeven_tickets.pop(ticket, None)
                    
                    self.last_trade_close_time = time.time()

        return closed_positions

    def close_all_positions(self, reason="Manual close"):
        positions = self.mt5.get_positions(self.symbol) or []
        closed_count = 0
        for position in positions:
            ticket = position.get('ticket')
            if ticket in self.managed_positions:
                if self.mt5.close_position(ticket):
                    closed_count += 1
                    self.managed_positions.pop(ticket, None)
                    self.scaled_out_tickets.pop(ticket, None)
                    self.at_breakeven_tickets.pop(ticket, None)
        
        if closed_count > 0:
            self.last_trade_close_time = time.time()
            
        return closed_count

    def get_trading_summary(self):
        account_info = self.mt5.get_account_info()
        if not account_info:
            return None

        positions = self.mt5.get_positions(self.symbol) or []
        symbol_info = self.mt5.get_symbol_info(self.symbol)
        if not symbol_info:
            return None

        risk_stats = self.risk_manager.get_position_stats(
            float(account_info.get('balance', 0.0)),
            positions,
            symbol_info
        )

        return {
            'account': account_info,
            'positions': positions,
            'risk_stats': risk_stats,
            'symbol_info': symbol_info,
            'timestamp': datetime.now()
        }

    def can_trade(self, filters):
        reasons = []
        session_name = "us"

        fset = self.settings.get('filters', {})
        news_enabled = bool(fset.get('news_filter_enabled', False))
        session_enabled = bool(fset.get('session_filter_enabled', True))
        
        rset = self.settings.get('risk_management', {})
        margin_filter_enabled = bool(rset.get('enable_margin_filter', True))
        min_margin_level = float(rset.get('min_margin_level_pct', 500.0))

        session_filter = filters.get('session_filter')
        if session_enabled and session_filter:
            try:
                is_allowed, session_result = session_filter.is_trading_allowed()
                if not is_allowed:
                    reasons.append(session_result)
                else:
                    session_name = session_result
            except Exception as e:
                reasons.append(f"Session filter error: {e}")
        else:
            session_name = "london" 

        if news_enabled:
            news_filter = filters.get('news_filter')
            if news_filter:
                try:
                    is_news, msg, _event = news_filter.is_news_time(self.symbol)
                    if is_news:
                        reasons.append(f"News filter: {msg}")
                except Exception as e:
                    reasons.append(f"News filter error: {e}")

        account_info = self.mt5.get_account_info()
        if margin_filter_enabled and account_info:
            margin_level = float(account_info.get('margin_level', 99999.0))
            if margin_level < min_margin_level and float(account_info.get('margin', 0.0)) > 0:
                reasons.append(f"Margin Level too low: {margin_level:.1f}% (min: {min_margin_level}%)")

        spread_filter = filters.get('spread_filter')
        symbol_info = self.mt5.get_symbol_info(self.symbol)
        if spread_filter and symbol_info:
            try:
                # [CHECK] Logic Spread Check akan dipanggil, 
                # Pastikan spread_settings di JSON sudah diupdate (Misal max 50 untuk Gold)
                ok, msg = spread_filter.is_spread_acceptable(symbol_info, session_name) 
                if not ok:
                    reasons.append(f"Spread filter: {msg}")
            except Exception as e:
                reasons.append(f"Spread filter error: {e}")
        
        if account_info:
            ok, reason = self._check_daily_limits(account_info.get('balance', 0.0))
            if not ok:
                reasons.append(reason)

        can = len(reasons) == 0
        return (True, session_name) if can else (False, ", ".join(reasons))