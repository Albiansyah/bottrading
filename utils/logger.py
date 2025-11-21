import csv
import os
from datetime import datetime
import shutil
import pandas as pd

class Logger:
    def __init__(self, log_dir='logs'):
        self.log_dir = log_dir
        self.trades_file = os.path.join(log_dir, 'trades.csv')
        self.exits_file = os.path.join(log_dir, 'trade_exits.csv')
        self.signals_file = os.path.join(log_dir, 'signals.csv')
        self.errors_file = os.path.join(log_dir, 'errors.log')
        
        os.makedirs(log_dir, exist_ok=True)
        
        self._init_csv(self.trades_file, [
            'timestamp', 'ticket', 'symbol', 'type', 'lot',
            'entry_price', 'sl', 'tp', 'risk', 'confidence', 'status'
        ])
        
        self._init_csv(self.exits_file, [
            'timestamp', 'ticket', 'close_price', 'profit', 'duration', 'reason'
        ])
        
        self._init_csv(self.signals_file, [
            'timestamp', 'symbol', 'signal_type', 'confidence',
            'ma_signal', 'rsi_signal', 'rsi_value', 'macd_signal',
            'bb_signal', 'stoch_signal', 'atr_value', 'volatility',
            'action_taken', 'reason'
        ])
    
    def _init_csv(self, filepath, headers):
        if not os.path.exists(filepath):
            try:
                with open(filepath, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
            except IOError as e:
                print(f"Error initializing CSV {filepath}: {e}")

    def _safe_float(self, value, default=0.0):
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def log_trade_entry(self, order_info):
        try:
            with open(self.trades_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    order_info.get('ticket', ''),
                    order_info.get('symbol', ''),
                    order_info.get('type', ''),
                    order_info.get('lot', ''),
                    order_info.get('entry', ''),
                    order_info.get('sl', ''),
                    order_info.get('tp', ''),
                    order_info.get('risk', ''),
                    order_info.get('confidence', ''),
                    'OPEN'
                ])
        except IOError as e:
            self.log_error(f"Failed to log trade entry: {e}")

    def log_trade_exit(self, ticket, close_price, profit, duration, reason):
        try:
            with open(self.exits_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    ticket,
                    close_price,
                    profit,
                    duration,
                    reason
                ])
        except IOError as e:
            self.log_error(f"Failed to log trade exit for ticket {ticket}: {e}")

    def log_signal(self, signal_type, confidence, details, action_taken, reason):
        signals = details.get('signals', {})
        
        try:
            with open(self.signals_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'XAUUSD',
                    signal_type if signal_type else 'NONE',
                    confidence,
                    signals.get('ma', ''),
                    signals.get('rsi', ''),
                    signals.get('rsi_value', ''),
                    signals.get('macd', ''),
                    signals.get('bb', ''),
                    signals.get('stoch', ''),
                    signals.get('atr', ''),
                    signals.get('volatility', ''),
                    action_taken,
                    reason
                ])
        except IOError as e:
            self.log_error(f"Failed to log signal: {e}")
    
    def log_error(self, error_message, error_type='ERROR', exc_info=False):
        try:
            with open(self.errors_file, 'a', encoding='utf-8') as f:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"[{timestamp}] [{error_type}] {error_message}\n")
        except IOError as e:
            print(f"CRITICAL: Failed to write to error log: {e}")
    
    def log_info(self, message):
        self.log_error(message, error_type='INFO', exc_info=False)
    
    def log_warning(self, message):
        self.log_error(message, error_type='WARNING', exc_info=False)
    
    def _get_combined_trades_df(self):
        try:
            trades_df = pd.read_csv(self.trades_file)
        except FileNotFoundError:
            return None
        except pd.errors.EmptyDataError:
            return None

        try:
            exits_df = pd.read_csv(self.exits_file)
        except FileNotFoundError:
            exits_df = pd.DataFrame(columns=['ticket', 'profit', 'timestamp_exit'])
        except pd.errors.EmptyDataError:
            exits_df = pd.DataFrame(columns=['ticket', 'profit', 'timestamp_exit'])

        if exits_df.empty:
            trades_df['status'] = 'OPEN'
            trades_df['profit'] = 0.0
            trades_df['timestamp_exit'] = pd.NaT
            return trades_df

        exits_df = exits_df.rename(columns={'timestamp': 'timestamp_exit'})
        exits_df['ticket'] = exits_df['ticket'].astype(str)
        trades_df['ticket'] = trades_df['ticket'].astype(str)

        combined_df = pd.merge(trades_df, exits_df, on='ticket', how='left')
        
        combined_df['status'] = combined_df['profit'].apply(lambda x: 'CLOSED' if pd.notna(x) else 'OPEN')
        combined_df['profit'] = combined_df['profit'].apply(lambda x: self._safe_float(x, 0.0))
        
        return combined_df

    def get_today_trades(self):
        today = datetime.now().strftime('%Y-%m-%d')
        stats = {
            'total_trades': 0, 'closed_trades': 0, 'open_trades': 0,
            'winning_trades': 0, 'losing_trades': 0,
            'total_profit': 0.0, 'win_rate': 0.0
        }
        
        try:
            combined_df = self._get_combined_trades_df()
            if combined_df is None:
                return stats
        except Exception as e:
            self.log_error(f"Failed to read trades file for stats: {e}")
            return stats

        trades_today = combined_df[combined_df['timestamp'].str.startswith(today)]
        if trades_today.empty:
            return stats

        closed_trades = trades_today[trades_today['status'] == 'CLOSED']
        open_trades = trades_today[trades_today['status'] == 'OPEN']
        
        stats['total_trades'] = len(trades_today)
        stats['closed_trades'] = len(closed_trades)
        stats['open_trades'] = len(open_trades)

        if closed_trades.empty:
            return stats

        profits = closed_trades['profit']
        winning_trades = profits[profits > 0]
        losing_trades = profits[profits <= 0]
        
        stats['winning_trades'] = len(winning_trades)
        stats['losing_trades'] = len(losing_trades)
        stats['total_profit'] = profits.sum()
        stats['win_rate'] = (len(winning_trades) / len(closed_trades) * 100) if not closed_trades.empty else 0
        
        return stats
    
    def get_all_time_stats(self):
        stats = {
            'total_trades': 0, 'total_profit': 0.0, 'win_rate': 0.0,
            'average_profit': 0.0, 'best_trade': 0.0, 'worst_trade': 0.0
        }
        
        try:
            combined_df = self._get_combined_trades_df()
            if combined_df is None:
                return stats
        except Exception as e:
            self.log_error(f"Failed to read trades file for stats: {e}")
            return stats

        closed_trades = combined_df[combined_df['status'] == 'CLOSED']
        if closed_trades.empty:
            stats['total_trades'] = len(combined_df)
            return stats
            
        profits = closed_trades['profit']
        winning_trades = profits[profits > 0]
        
        stats['total_trades'] = len(closed_trades)
        stats['total_profit'] = profits.sum()
        stats['win_rate'] = (len(winning_trades) / len(closed_trades) * 100) if not closed_trades.empty else 0
        stats['average_profit'] = profits.mean() if not closed_trades.empty else 0
        stats['best_trade'] = profits.max() if not profits.empty else 0.0
        stats['worst_trade'] = profits.min() if not profits.empty else 0.0
        
        return stats