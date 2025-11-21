import json
from datetime import datetime
import pandas as pd
import pytz
import os
from typing import Dict, Any, List, Tuple

from core.strategy import TradingStrategy
from core.risk_manager import RiskManager
from core.mt5_connector import MT5Connector
from utils.market_regime import MarketRegimeDetector
from utils.settings_manager import SettingsManager

class Backtester:
    
    def __init__(self, mt5_connector: MT5Connector, sm: SettingsManager):
        print("Initializing Enhanced Backtester...")
        self.mt5 = mt5_connector
        self.base_sm = sm
        self.base_settings = self.base_sm.load_settings()
        
        self.bt_config = self.base_settings['backtesting']
        self.trading_config = self.base_settings['trading']
        self.symbol = self.trading_config['symbol']
        self.timeframe = self.trading_config['timeframe']
        self.min_bars_needed = 200
        
        self.regime_detector = MarketRegimeDetector(self.base_sm, symbol=self.symbol)
        
        self.strategy: TradingStrategy = None
        self.risk_manager: RiskManager = None
        self.settings: dict = None
        
        self.balance = 0.0
        self.equity = 0.0
        self.open_positions = []
        self.closed_trades = []
        self.ticket_counter = 1
        self.symbol_info = None
        self.trade_log_buffer = []
        
        self.equity_curve = []
        self.daily_pnl = {}
        self.regime_stats = {}
        
        self.start_date = None
        self.end_date = None

    def _apply_custom_settings(self, custom_settings: Dict = None):
        run_sm = SettingsManager(self.base_sm.settings_path)
        
        run_settings = json.loads(json.dumps(self.base_settings))
        
        if custom_settings:
            if 'risk_management' in custom_settings:
                run_settings['risk_management'].update(custom_settings['risk_management'])
            if 'signal_requirements' in custom_settings:
                run_settings['signal_requirements'].update(custom_settings['signal_requirements'])
            if 'trading' in custom_settings:
                run_settings['trading'].update(custom_settings['trading'])

        run_sm.settings = run_settings 
        
        self.risk_manager = RiskManager(run_sm)
        self.strategy = TradingStrategy(run_sm)
        
        self.settings = run_settings
        
        self.bt_config = self.settings['backtesting']
        self.trading_config = self.settings['trading']

    def _reset_stats(self):
        self.initial_balance = float(self.bt_config['initial_balance'])
        self.balance = self.initial_balance
        self.equity = self.initial_balance
        self.open_positions = []
        self.closed_trades = []
        self.ticket_counter = 1
        self.symbol_info = None
        self.trade_log_buffer = []
        
        self.equity_curve = [(None, self.initial_balance)]
        self.daily_pnl = {}
        self.regime_stats = {
            'TRENDING': {'trades': 0, 'wins': 0, 'pnl': 0.0},
            'RANGING': {'trades': 0, 'wins': 0, 'pnl': 0.0},
            'VOLATILE': {'trades': 0, 'wins': 0, 'pnl': 0.0},
            'BREAKOUT': {'trades': 0, 'wins': 0, 'pnl': 0.0},
            'UNKNOWN': {'trades': 0, 'wins': 0, 'pnl': 0.0}
        }
        self.current_regime = 'UNKNOWN'

    def _get_mock_symbol_info(self, current_bar):
        spread_points = self.settings.get('filters', {}).get('spread_settings', {}).get('default_max', 30)
        
        if self.symbol_info is None:
             self.symbol_info = self.mt5.get_symbol_info(self.symbol)
             if self.symbol_info is None:
                 raise ValueError(f"Tidak bisa get_symbol_info untuk {self.symbol}")
        
        self.symbol_info['bid'] = current_bar['close']
        self.symbol_info['ask'] = current_bar['close'] + (self.symbol_info['point'] * spread_points)
        self.symbol_info['spread'] = spread_points
        return self.symbol_info

    def _open_position(self, signal_type, lot_size, price, sl, tp, risk_amount, bar):
        pos = {
            'ticket': self.ticket_counter,
            'symbol': self.symbol,
            'type': signal_type,
            'volume': lot_size,      
            'price_open': price,      
            'sl': sl,
            'tp': tp,
            'risk': risk_amount,
            'open_time': bar.name,
            'open_bar_index': bar.name,
            'profit': 0.0,
            'regime': self.current_regime
        }
        self.open_positions.append(pos)
        self.ticket_counter += 1
        
        emoji = "🟢" if signal_type == "BUY" else "🔴"
        action = f"{emoji} OPEN {signal_type:<4}"
        log_entry = f"   {bar.name} | {action} | @ {price:<9.5f} | SL {sl:<9.5f} | TP {tp:<9.5f} | Regime: {self.current_regime}"
        self.trade_log_buffer.append(log_entry)

    def _close_position(self, pos, close_price, reason, bar):
        profit = 0
        point = self.symbol_info['point']
        contract_size = self.symbol_info['trade_contract_size']
        
        entry_price = pos['price_open'] 
        lot_size = pos['volume']

        if pos['type'] == 'BUY':
            price_diff = close_price - entry_price
        else:
            price_diff = entry_price - close_price
            
        profit = price_diff * contract_size * lot_size
            
        self.balance += profit
        
        regime = pos.get('regime', 'UNKNOWN')
        if regime in self.regime_stats:
            self.regime_stats[regime]['trades'] += 1
            if profit > 0:
                self.regime_stats[regime]['wins'] += 1
            self.regime_stats[regime]['pnl'] += profit
        
        close_date = bar.name.date() if hasattr(bar.name, 'date') else bar.name
        if close_date not in self.daily_pnl:
            self.daily_pnl[close_date] = 0.0
        self.daily_pnl[close_date] += profit
        
        trade_log = {
            'ticket': pos['ticket'],
            'type': pos['type'],
            'entry_price': entry_price,
            'close_price': close_price,
            'sl': pos['sl'],
            'tp': pos['tp'],
            'profit': profit,
            'reason': reason,
            'open_time': pos['open_time'],
            'close_time': bar.name,
            'regime': regime
        }
        self.closed_trades.append(trade_log)
        self.open_positions = [p for p in self.open_positions if p['ticket'] != pos['ticket']]
        
        emoji = "💰" if profit > 0 else "⛔"
        action = f"{emoji} CLOSE {pos['type']:<4}"
        profit_str = f"Profit: ${profit:8.2f}"
        reason_str = f"Reason: {reason:<10}"
        log_entry = f"   {bar.name} | {action} | @ {close_price:<9.5f} | {profit_str} | {reason_str}"
        self.trade_log_buffer.append(log_entry)
        
        self.equity_curve.append((bar.name, self.balance))

    def _tick(self, df_history_main, df_history_htf, current_bar):
        mock_symbol_info = self._get_mock_symbol_info(current_bar)
        
        regime, details = self.regime_detector.detect_regime(df_history_main, use_cache=False)
        self.current_regime = regime
        
        self.strategy.update_dynamic_confidence(regime, details)

        signal_type, confidence, details = self.strategy.analyze(
            df_main=df_history_main, 
            df_htf=df_history_htf, 
            session="london",
            is_backtest=True
        )

        for pos in reversed(self.open_positions):
            if pos['open_bar_index'] == current_bar.name:
                continue

            if pos['type'] == 'BUY':
                if current_bar['low'] <= pos['sl']:
                    self._close_position(pos, pos['sl'], "SL Hit", current_bar)
                elif current_bar['high'] >= pos['tp']:
                    self._close_position(pos, pos['tp'], "TP Hit", current_bar)
            
            elif pos['type'] == 'SELL':
                if current_bar['high'] >= pos['sl']:
                    self._close_position(pos, pos['sl'], "SL Hit", current_bar)
                elif current_bar['low'] <= pos['tp']:
                    self._close_position(pos, pos['tp'], "TP Hit", current_bar)

        for pos in reversed(self.open_positions):
            if not any(p['ticket'] == pos['ticket'] for p in self.open_positions):
                continue
            
            should_close, reason = self.strategy.should_close_position(pos, details)
            if should_close:
                self._close_position(pos, current_bar['close'], reason, current_bar)
        
        if not signal_type:
            return 

        is_valid, reason = self.strategy.validate_signal(signal_type, df_history_main, mock_symbol_info)
        if not is_valid:
            return
            
        atr_value = self.strategy.atr.calculate(df_history_main)
        if atr_value is None:
            return 

        entry_price = mock_symbol_info['ask'] if signal_type == "BUY" else mock_symbol_info['bid']

        sl_price, tp_price = self.risk_manager.calculate_sl_tp(
            entry_price, signal_type, atr_value, self.symbol_info
        )
        
        lot_size = self.risk_manager.calculate_optimal_lot_size(
            self.balance, entry_price, sl_price, self.symbol_info
        )
        
        position_risk = self.risk_manager.calculate_position_risk(
            entry_price, sl_price, lot_size, self.symbol_info
        )
        
        can_open, reason = self.risk_manager.can_open_new_position(
            self.balance, self.open_positions, position_risk, signal_type, self.symbol_info
        )
        
        if can_open:
            self._open_position(
                signal_type, lot_size, entry_price, 
                sl_price, tp_price, position_risk, current_bar
            )

    def _calculate_drawdown(self) -> Tuple[float, float, int]:
        if not self.equity_curve:
            return 0.0, 0.0, 0
        
        peak = self.initial_balance
        max_dd = 0.0
        max_dd_pct = 0.0
        dd_duration = 0
        current_dd_duration = 0
        
        for timestamp, equity in self.equity_curve:
            if equity > peak:
                peak = equity
                current_dd_duration = 0
            else:
                dd = peak - equity
                dd_pct = (dd / peak * 100) if peak > 0 else 0
                current_dd_duration += 1
                
                if dd > max_dd:
                    max_dd = dd
                    max_dd_pct = dd_pct
                    dd_duration = current_dd_duration
        
        return max_dd, max_dd_pct, dd_duration

    def _generate_report(self) -> Dict[str, Any]:
        total_trades = len(self.closed_trades)
        
        start_date_iso = self.start_date.date().isoformat() if self.start_date else "N/A"
        end_date_iso = self.end_date.date().isoformat() if self.end_date else "N/A"
        
        if total_trades == 0:
            return {
                "start_date": start_date_iso,
                "end_date": end_date_iso,
                "initial_balance": self.initial_balance,
                "final_balance": self.balance,
                "total_pnl": 0, "total_pnl_pct": 0, "total_trades": 0, "win_rate": 0,
                "profit_factor": 0, "winners": 0, "losers": 0, "avg_win": 0, "avg_loss": 0,
                "best_trade": 0, "worst_trade": 0,
                "max_drawdown": 0, "max_dd_pct": 0, "dd_duration": 0,
                "green_days": 0, "red_days": 0, "total_days": 0, "avg_daily_pnl": 0,
                "best_day": 0, "worst_day": 0, "risk_reward": 0,
                "regime_breakdown": {}
            }

        profits = [t['profit'] for t in self.closed_trades]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]
        
        total_pnl = sum(profits)
        win_rate = (len(wins) / total_trades) * 100 if total_trades > 0 else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        sum_wins = sum(wins)
        sum_losses = abs(sum(losses))
        profit_factor = sum_wins / sum_losses if sum_losses > 0 else (999.0 if sum_wins > 0 else 0.0)
        
        best_trade = max(profits) if profits else 0
        worst_trade = min(profits) if profits else 0
        risk_reward = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        max_dd, max_dd_pct, dd_duration = self._calculate_drawdown()
        
        daily_values = list(self.daily_pnl.values())
        green_days = len([d for d in daily_values if d > 0])
        red_days = len([d for d in daily_values if d < 0])
        total_days = len(daily_values)
        avg_daily_pnl = sum(daily_values) / total_days if total_days > 0 else 0
        best_day = max(daily_values) if daily_values else 0
        worst_day = min(daily_values) if daily_values else 0
        
        regime_breakdown = {}
        for regime, stats in self.regime_stats.items():
            if stats['trades'] > 0:
                regime_breakdown[regime] = {
                    'trades': stats['trades'],
                    'win_rate': (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0,
                    'pnl': stats['pnl']
                }

        return {
            "start_date": start_date_iso,
            "end_date": end_date_iso,
            "initial_balance": self.initial_balance,
            "final_balance": round(self.balance, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round((total_pnl / self.initial_balance * 100), 2),
            "total_trades": total_trades,
            "winners": len(wins),
            "losers": len(losses),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "best_trade": round(best_trade, 2),
            "worst_trade": round(worst_trade, 2),
            "risk_reward": round(risk_reward, 2),
            "max_drawdown": round(max_dd, 2),
            "max_dd_pct": round(max_dd_pct, 2),
            "dd_duration": dd_duration,
            "green_days": green_days,
            "red_days": red_days,
            "total_days": total_days,
            "avg_daily_pnl": round(avg_daily_pnl, 2),
            "best_day": round(best_day, 2),
            "worst_day": round(worst_day, 2),
            "regime_breakdown": regime_breakdown
        }

    def _format_report_text(self, report: Dict) -> str:
        lines = []
        
        lines.append("=" * 60)
        lines.append("              BACKTEST RESULTS SUMMARY".center(60))
        lines.append("=" * 60)
        
        lines.append(f" Symbol: {self.symbol}")
        lines.append(f" Timeframe: {self.timeframe}")
        lines.append(f" Period: {report['start_date']} to {report['end_date']}")
        lines.append(f" Strategy: AUTO")
        lines.append("")
        
        lines.append(" PERFORMANCE METRICS:")
        lines.append("-" * 60)
        lines.append(f" Initial Balance:    ${report['initial_balance']:,.2f}")
        lines.append(f" Final Balance:      ${report['final_balance']:,.2f}")
        pnl_sign = "+" if report['total_pnl'] >= 0 else ""
        lines.append(f" Total P/L:          {pnl_sign}${report['total_pnl']:,.2f} ({pnl_sign}{report['total_pnl_pct']:.2f}%)")
        lines.append("")
        
        lines.append(" TRADE STATISTICS:")
        lines.append("-" * 60)
        lines.append(f" Total Trades:       {report['total_trades']}")
        lines.append(f" Winners:            {report['winners']} ({report['win_rate']:.1f}%)")
        lines.append(f" Losers:             {report['losers']} ({100-report['win_rate']:.1f}%)")
        lines.append("")
        lines.append(f" Win Rate:           {report['win_rate']:.1f}%")
        lines.append(f" Profit Factor:      {report['profit_factor']:.2f}")
        lines.append("")
        lines.append(f" Average Win:        +${report['avg_win']:.2f}")
        lines.append(f" Average Loss:       ${report['avg_loss']:.2f}")
        lines.append(f" Risk/Reward Ratio:  {report['risk_reward']:.2f}")
        lines.append("")
        lines.append(f" Best Trade:         +${report['best_trade']:.2f}")
        lines.append(f" Worst Trade:        ${report['worst_trade']:.2f}")
        lines.append("")
        
        lines.append(" DRAWDOWN ANALYSIS:")
        lines.append("-" * 60)
        lines.append(f" Max Drawdown:       -${report['max_drawdown']:.2f} (-{report['max_dd_pct']:.1f}%)")
        lines.append(f" Max DD Duration:    {report['dd_duration']} bars")
        lines.append("")
        
        lines.append(" CONSISTENCY:")
        lines.append("-" * 60)
        lines.append(f" Best Day:           +${report['best_day']:.2f}")
        lines.append(f" Worst Day:          ${report['worst_day']:.2f}")
        lines.append(f" Avg Daily P/L:      ${report['avg_daily_pnl']:+.2f}")
        lines.append("")
        
        total_days = report['total_days']
        green_pct = (report['green_days'] / total_days * 100) if total_days > 0 else 0
        red_pct = (report['red_days'] / total_days * 100) if total_days > 0 else 0
        lines.append(f" Green Days:         {report['green_days']} / {total_days} ({green_pct:.1f}%)")
        lines.append(f" Red Days:           {report['red_days']} / {total_days} ({red_pct:.1f}%)")
        lines.append("")
        
        if report['regime_breakdown']:
            lines.append(" REGIME BREAKDOWN:")
            lines.append("-" * 60)
            
            for regime, stats in sorted(report['regime_breakdown'].items(), key=lambda x: x[1]['pnl'], reverse=True):
                pnl_sign = "+" if stats['pnl'] >= 0 else ""
                lines.append(f" {regime:<12} {stats['trades']:>3} trades | Win: {stats['win_rate']:>5.1f}% | {pnl_sign}${stats['pnl']:>8,.2f}")
            lines.append("")
        
        lines.append("=" * 60)
        lines.append("               END OF REPORT".center(60))
        lines.append("=" * 60)
        
        return "\n".join(lines)

    def _export_results(self, report: Dict, silent: bool = False):
        try:
            os.makedirs('logs', exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
            filename = f"logs/backtest_{timestamp}.txt"
            
            report_text = self._format_report_text(report)
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(report_text)
                f.write("\n\n")
                f.write("=" * 60 + "\n")
                f.write("TRADE LOGS:\n")
                f.write("=" * 60 + "\n")
                
                if self.trade_log_buffer:
                    for log_entry in self.trade_log_buffer:
                        f.write(log_entry + "\n")
                else:
                    f.write("No trades executed.\n")
            
            if not silent:
                print(f"\n✅ Results exported to: {filename}")
            
            return filename
            
        except Exception as e:
            if not silent:
                print(f"⚠️  Failed to export results: {e}")
            return None

    def _print_results(self, report: Dict):
        
        print("\n" + "="*60)
        print("📈 TRADE LOGS 📈")
        print("="*60)
        if not self.trade_log_buffer:
            print("No trades executed.")
        else:
            display_logs = self.trade_log_buffer[-20:] if len(self.trade_log_buffer) > 20 else self.trade_log_buffer
            if len(self.trade_log_buffer) > 20:
                print(f"... (showing last 20 of {len(self.trade_log_buffer)} trades)")
            for log_entry in display_logs:
                print(log_entry)

        print("\n" + self._format_report_text(report))

    def run(self, custom_settings: Dict = None, silent: bool = True) -> Dict[str, Any]:
        if not silent:
            print(f"Running backtest for {self.symbol} ({self.timeframe})...")
        
        self._apply_custom_settings(custom_settings)
        self._reset_stats()
        
        try:
            self.start_date = datetime.fromisoformat(self.bt_config['start_date'])
            self.end_date = datetime.fromisoformat(self.bt_config['end_date'])
        except KeyError as e:
            if not silent: print(f"Error: Backtesting config missing: {e}")
            return {}
        except ValueError as e:
            if not silent: print(f"Error: Invalid date format in settings: {e}")
            return {}

        if not silent:
            print(f"Period: {self.start_date} to {self.end_date}")
        
        if not self.mt5.connect():
            if not silent: print("Failed to connect to MT5. Aborting backtest.")
            return {}

        self.symbol_info = self.mt5.get_symbol_info(self.symbol)
        if not self.symbol_info:
            if not silent: print(f"Failed to get symbol info for {self.symbol}. Aborting.")
            self.mt5.disconnect()
            return {}

        htf_timeframe = self.settings['signal_requirements'].get('higher_timeframe', 'H4')
        all_data_htf = self.mt5.get_rates_range(
            self.symbol, htf_timeframe, self.start_date, self.end_date
        )
        if all_data_htf is None or len(all_data_htf) < 50:
            if not silent: print(f"Not enough HTF ({htf_timeframe}) data found. Aborting.")
            self.mt5.disconnect()
            return {}

        all_data_main = self.mt5.get_rates_range(
            self.symbol, self.timeframe, self.start_date, self.end_date
        )
        
        if all_data_main is None or len(all_data_main) < self.min_bars_needed:
            if not silent: 
                print(f"Not enough data found (Need {self.min_bars_needed}, got {len(all_data_main) if all_data_main is not None else 0}).")
            self.mt5.disconnect()
            return {}
            
        if not silent:
            print("Calibrating regime detector...")
        cal_bars = min(500, len(all_data_main))
        self.regime_detector.calibrate_thresholds(all_data_main.iloc[:cal_bars])

        if not silent:
            print(f"Starting simulation over {len(all_data_main)} bars...")
        
        all_data_htf = all_data_htf.reindex(all_data_main.index, method='ffill')
        
        total_bars = len(all_data_main)
        for i in range(self.min_bars_needed, total_bars):
            
            if not silent and i % 100 == 0:
                progress_pct = (i / total_bars) * 100
                print(f"   Progress: {i} / {total_bars} bars ({progress_pct:.1f}%)", end="\r")
            
            current_df_history_main = all_data_main.iloc[0:i] 
            current_df_history_htf = all_data_htf.iloc[0:i]
            current_bar = all_data_main.iloc[i] 
            
            self._tick(current_df_history_main, current_df_history_htf, current_bar)

        if not silent:
            print(f"\nBacktest loop finished. Closing all open positions...")
        
        last_bar = all_data_main.iloc[-1]
        for pos in reversed(self.open_positions):
            self._close_position(pos, last_bar['close'], "End of Backtest", last_bar)

        report = self._generate_report()
        
        if not silent:
            self._print_results(report)
            self._export_results(report, silent=False)
        else:
            self._export_results(report, silent=True)
        
        self.mt5.disconnect()
        
        return report