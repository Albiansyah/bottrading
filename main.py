import time
import json
import re
import traceback
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import sys
import MetaTrader5 as mt5
from typing import Dict, List, Any, Optional
import schedule
import threading
import pandas as pd
from colorama import init, Fore, Style

# Initialize Colorama
init(autoreset=True)

# Core Imports
from core.mt5_connector import MT5Connector
from core.risk_manager import RiskManager
from core.strategy import TradingStrategy
from core.trade_executor import TradeExecutor

# Filters
from filters.news_filter import NewsFilter
from filters.session_filter import SessionFilter
from filters.spread_filter import SpreadFilter

# Utils
from notifications.telegram_bot import TelegramBot
from utils.logger import Logger
from utils.backtester import Backtester
from utils.settings_manager import SettingsManager
from utils.profit_target import ProfitTargetManager
from utils.market_regime import MarketRegimeDetector

load_dotenv()
import warnings
from pandas.errors import SettingWithCopyWarning
warnings.simplefilter(action="ignore", category=SettingWithCopyWarning)

# --- UI CONSTANTS ---
BOX = {'H': '═', 'V': '║', 'TL': '╔', 'TR': '╗', 'BL': '╚', 'BR': '╝', 'ML': '╠', 'MR': '╣', 'MT': '╦', 'MB': '╩', 'C': '╬'}
WIDTH = 80
C_TITLE = Fore.YELLOW + Style.BRIGHT
C_HEADER = Fore.CYAN + Style.BRIGHT
C_BORDER = Fore.MAGENTA
C_TEXT = Fore.WHITE
C_LABEL = Fore.CYAN
C_VALUE = Fore.WHITE + Style.BRIGHT
C_GREEN = Fore.GREEN
C_RED = Fore.RED
C_YELLOW = Fore.YELLOW
C_CYAN = Fore.CYAN
C_DIM = Style.DIM + Fore.WHITE
C_RESET = Style.RESET_ALL

# --- HELPER FUNCTIONS ---
def clear_screen(): os.system('cls' if os.name == 'nt' else 'clear')
def strip_ansi(text: str) -> str: return re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])').sub('', text)

def print_box_line(text_left: str = "", text_right: str = "", width: int = WIDTH, color: str = C_TEXT):
    content_width = width - 4
    left_clean = strip_ansi(text_left)
    right_clean = strip_ansi(text_right)
    
    total_len = len(left_clean) + len(right_clean)
    if total_len > content_width:
        avail = content_width - len(right_clean) - 3
        if avail > 0:
            text_left = text_left[:avail] + "..."
            left_clean = strip_ansi(text_left)

    if text_right:
        padding = max(1, content_width - len(left_clean) - len(right_clean))
        content = f"{text_left}{' ' * padding}{text_right}"
    else:
        padding = content_width - len(left_clean)
        content = f"{color}{text_left}{' ' * padding}{C_RESET}"
    
    print(f"{C_BORDER}{BOX['V']}{C_RESET} {content} {C_BORDER}{BOX['V']}{C_RESET}")

def print_box_separator(width: int = WIDTH, type: str = 'middle'):
    if type == 'top': print(f"{C_BORDER}{BOX['TL']}{BOX['H'] * (width - 2)}{BOX['TR']}{C_RESET}")
    elif type == 'bottom': print(f"{C_BORDER}{BOX['BL']}{BOX['H'] * (width - 2)}{BOX['BR']}{C_RESET}")
    elif type == 'middle': print(f"{C_BORDER}{BOX['ML']}{BOX['H'] * (width - 2)}{BOX['MR']}{C_RESET}")
    elif type == 'sub': print(f"{C_BORDER}{BOX['V']}{C_DIM}{'─' * (width - 2)}{C_BORDER}{BOX['V']}{C_RESET}")

def get_progress_bar(percent: float, width: int = 20) -> str:
    percent = max(0, min(100, percent))
    filled = int(width * percent / 100)
    return f"[{C_GREEN}{'█' * filled}{C_DIM}{'░' * (width - filled)}{C_RESET}]"

# ==========================================
# UTILITY & MENU FUNCTIONS
# ==========================================

def job_weekly_report():
    pass 

def job_news_preload():
    try:
        sm = SettingsManager()
        NewsFilter(sm).update_news_cache()
    except: pass

def run_scheduler_thread():
    schedule.every().saturday.at("09:00").do(job_weekly_report)
    schedule.every().sunday.at("20:00").do(job_news_preload)
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except: time.sleep(60)

# --- MENU UI ---

def quick_settings_menu(sm: SettingsManager):
    while True:
        clear_screen()
        print_box_separator(WIDTH, 'top')
        print_box_line(f"{C_HEADER}QUICK SETTINGS EDITOR", width=WIDTH)
        print_box_separator(WIDTH, 'middle')
        
        status_news = f"{C_GREEN}ON" if sm.get_news_filter_enabled() else f"{C_RED}OFF"
        status_session = f"{C_GREEN}ON" if sm.get_session_filter_enabled() else f"{C_RED}OFF"
        margin_status = f"{C_GREEN}ON" if sm.get_margin_filter_enabled() else f"{C_RED}OFF"
        lot_display = "AUTO" if sm.get_lot_size() == 0.0 else f"{sm.get_lot_size():.2f}"
        
        print_box_line(f"{C_LABEL}TRADING", f"{C_LABEL}RISK", width=WIDTH)
        print_box_separator(WIDTH, 'sub')
        print_box_line(f"Symbol: {C_VALUE}{sm.get_symbol()}", f"Risk: {C_VALUE}{sm.get_risk_per_trade()}%", width=WIDTH)
        print_box_line(f"TF: {C_VALUE}{sm.get_timeframe()}", f"Max Total: {C_VALUE}{sm.get_max_total_risk()}%", width=WIDTH)
        print_box_line(f"Lot: {C_VALUE}{lot_display}", f"Margin: {margin_status}", width=WIDTH)
        
        print_box_separator(WIDTH, 'middle')
        print_box_line(f"{C_LABEL}FILTERS", width=WIDTH)
        print_box_separator(WIDTH, 'sub')
        print_box_line(f"News: {status_news}", f"Session: {status_session}", width=WIDTH)
        print_box_line(f"Spread: {C_VALUE}{sm.get_max_spread()}", f"Sessions: {','.join(sm.get_allowed_sessions())}", width=WIDTH)
        
        print_box_separator(WIDTH, 'middle')
        print_box_line(f"{C_HEADER}ACTIONS", width=WIDTH)
        print_box_line(f" [1] Edit Trading", f" [2] Edit Risk", width=WIDTH)
        print_box_line(f" [3] Edit Filters", f" [4] Change Mode", width=WIDTH)
        print_box_line(f" [0] Back", width=WIDTH)
        print_box_separator(WIDTH, 'bottom')
        
        ch = input(C_YELLOW + "\nChoice: ").strip()
        if ch == '0': break
        elif ch == '1': edit_trading_settings_submenu(sm)
        elif ch == '2': edit_risk_settings_submenu(sm)
        elif ch == '3': edit_filters_submenu(sm)
        elif ch == '4': edit_strategy_submenu(sm)

def edit_trading_settings_submenu(sm: SettingsManager):
    while True:
        clear_screen()
        print_box_separator(WIDTH, 'top')
        print_box_line(f"{C_HEADER}EDIT TRADING", width=WIDTH)
        print_box_separator(WIDTH, 'middle')
        print_box_line(f" [1] Symbol ({sm.get_symbol()})", width=WIDTH)
        print_box_line(f" [2] Timeframe ({sm.get_timeframe()})", width=WIDTH)
        print_box_line(f" [3] Lot Size ({sm.get_lot_size()})", width=WIDTH)
        print_box_line(f" [4] Max Pos ({sm.get_max_positions()})", width=WIDTH)
        print_box_line(f" [0] Back", width=WIDTH)
        print_box_separator(WIDTH, 'bottom')
        
        ch = input(C_YELLOW + "\nChoice: ").strip()
        if ch == '0': break
        elif ch == '1':
            v = input("New Symbol: ").strip()
            if v: sm.set_symbol(v)
        elif ch == '2':
            v = input("New TF (M1/M5/H1): ").strip()
            if v: sm.set_timeframe(v)
        elif ch == '3':
            v = input("New Lot (0 for Auto): ").strip()
            if v: sm.set_lot_size(v)
        elif ch == '4':
            v = input("New Max Pos: ").strip()
            if v: sm.set_max_positions(v)

def edit_risk_settings_submenu(sm: SettingsManager):
    while True:
        clear_screen()
        print_box_separator(WIDTH, 'top')
        print_box_line(f"{C_HEADER}EDIT RISK", width=WIDTH)
        print_box_separator(WIDTH, 'middle')
        print_box_line(f" [1] Risk Per Trade ({sm.get_risk_per_trade()}%)", width=WIDTH)
        print_box_line(f" [2] Max Total Risk ({sm.get_max_total_risk()}%)", width=WIDTH)
        print_box_line(f" [3] Min Margin Lvl ({sm.get_min_margin_level()}%)", width=WIDTH)
        print_box_line(f" [4] Toggle Margin Filter", width=WIDTH)
        print_box_line(f" [0] Back", width=WIDTH)
        print_box_separator(WIDTH, 'bottom')
        
        ch = input(C_YELLOW + "\nChoice: ").strip()
        if ch == '0': break
        elif ch == '1':
            v = input("New Risk %: ").strip()
            if v: sm.set_risk_per_trade(v)
        elif ch == '2':
            v = input("New Max Total %: ").strip()
            if v: sm.set_max_total_risk(v)
        elif ch == '3':
            v = input("New Margin Lvl: ").strip()
            if v: sm.set_min_margin_level(v)
        elif ch == '4':
            sm.toggle_margin_filter()

def edit_filters_submenu(sm: SettingsManager):
    while True:
        clear_screen()
        print_box_separator(WIDTH, 'top')
        print_box_line(f"{C_HEADER}EDIT FILTERS", width=WIDTH)
        print_box_separator(WIDTH, 'middle')
        
        # [FIX] Accessing Safe Method for Asia Mode
        asia_mode = sm.get_asia_session_mode()
        asia_col = C_RED if asia_mode == 'AGGRESSIVE' else C_GREEN

        print_box_line(f" [1] Toggle News ({'ON' if sm.get_news_filter_enabled() else 'OFF'})", width=WIDTH)
        print_box_line(f" [2] Toggle Session ({'ON' if sm.get_session_filter_enabled() else 'OFF'})", width=WIDTH)
        print_box_line(f" [3] Max Spread ({sm.get_max_spread()})", width=WIDTH)
        print_box_line(f" [4] Asia Mode ({asia_col}{asia_mode}{C_RESET})", width=WIDTH)
        print_box_line(f" [0] Back", width=WIDTH)
        print_box_separator(WIDTH, 'bottom')
        
        ch = input(C_YELLOW + "\nChoice: ").strip()
        if ch == '0': break
        elif ch == '1': sm.toggle_news_filter()
        elif ch == '2': sm.toggle_session_filter()
        elif ch == '3':
            v = input("Max Spread: ").strip()
            if v: sm.set_max_spread(v)
        elif ch == '4':
            curr = sm.get_asia_session_mode()
            new = 'AGGRESSIVE' if curr == 'DEFENSIVE' else 'DEFENSIVE'
            sm.set_asia_session_mode(new)
            print(f"Set to {new}")
            time.sleep(1)

def edit_strategy_submenu(sm: SettingsManager):
    clear_screen()
    print_box_separator(WIDTH, 'top')
    print_box_line(f"{C_HEADER}CHANGE MODE", width=WIDTH)
    print_box_line(f"Current: {sm.get_trading_mode()}", width=WIDTH)
    print_box_separator(WIDTH, 'middle')
    print_box_line(" [1] AUTO (Smart)", width=WIDTH)
    print_box_line(" [2] SNIPER_ONLY", width=WIDTH)
    print_box_line(" [3] TREND_ONLY", width=WIDTH)
    print_box_line(" [4] BREAKOUT_ONLY", width=WIDTH)
    print_box_separator(WIDTH, 'bottom')
    
    ch = input(C_YELLOW + "\nChoice: ").strip()
    if ch == '1': sm.set_trading_mode('AUTO')
    elif ch == '2': sm.set_trading_mode('SNIPER_ONLY')
    elif ch == '3': sm.set_trading_mode('TREND_ONLY')
    elif ch == '4': sm.set_trading_mode('BREAKOUT_ONLY')

def profit_target_menu(sm: SettingsManager):
    ptm = ProfitTargetManager(sm)
    while True:
        clear_screen()
        ptm.load_settings()
        ptm.load_daily_stats()
        print_box_separator(WIDTH, 'top')
        print_box_line(f"{C_HEADER}PROFIT TARGET", width=WIDTH)
        print_box_separator(WIDTH, 'middle')
        print_box_line(f"Status: {'ON' if ptm.enabled else 'OFF'}", width=WIDTH)
        print_box_line(f"Target: ${ptm.daily_target_usd}", f"Current: ${ptm.today_profit:.2f}", width=WIDTH)
        print_box_separator(WIDTH, 'middle')
        print_box_line("[1] Toggle ON/OFF", width=WIDTH)
        print_box_line("[2] Set Target", width=WIDTH)
        print_box_line("[3] Reset Stats", width=WIDTH)
        print_box_line("[0] Back", width=WIDTH)
        print_box_separator(WIDTH, 'bottom')
        
        ch = input(C_YELLOW + "\nChoice: ").strip()
        if ch == '0': break
        elif ch == '1': ptm.toggle_enabled()
        elif ch == '2': 
            t = input("New Target ($): ").strip()
            ptm.update_target(t)
        elif ch == '3': ptm.manual_reset()

def auto_detect_symbols_menu(sm: SettingsManager, mt5c: MT5Connector):
    clear_screen()
    print("Scanning for XAU/USD pairs...")
    if not mt5c.connect(): return
    
    symbols = mt5.symbols_get()
    found = []
    if symbols:
        for s in symbols:
            if "XAU" in s.name.upper() or "GOLD" in s.name.upper():
                found.append(s.name)
            
    if not found:
        print("No Gold pairs found.")
    else:
        print(f"Found: {', '.join(found)}")
        sel = input("Enter symbol name to select: ").strip()
        if sel in found:
            sm.set_symbol(sel)
            print("Saved.")
    
    mt5c.disconnect()
    time.sleep(2)

def quick_backtest_menu(sm: SettingsManager, mt5c: MT5Connector):
    clear_screen()
    print_box_line("QUICK BACKTEST", width=WIDTH)
    print_box_line("[1] Last 7 Days", width=WIDTH)
    print_box_line("[2] Last 30 Days", width=WIDTH)
    
    ch = input("Choice: ").strip()
    today = datetime.now()
    if ch == '1':
        start = (today - timedelta(days=7)).strftime('%Y-%m-%d')
        sm.set_backtest_period(start, today.strftime('%Y-%m-%d'))
        run_backtest_mode(sm, mt5c, silent=False)
    elif ch == '2':
        start = (today - timedelta(days=30)).strftime('%Y-%m-%d')
        sm.set_backtest_period(start, today.strftime('%Y-%m-%d'))
        run_backtest_mode(sm, mt5c, silent=False)

def position_management_menu(sm: SettingsManager, mt5c: MT5Connector):
    clear_screen()
    print_box_line("CONNECTING...", width=WIDTH, color=C_YELLOW)
    if not mt5c.connect(): return
    positions = mt5c.get_positions(sm.get_symbol())
    
    print_box_separator(WIDTH, 'top')
    print_box_line(f"OPEN POSITIONS: {len(positions)}", width=WIDTH)
    print_box_separator(WIDTH, 'middle')
    
    for p in positions:
        pl_col = C_GREEN if p['profit'] >= 0 else C_RED
        print_box_line(f"#{p['ticket']} {p['type']} {p['volume']}lot", f"{pl_col}${p['profit']:.2f}", width=WIDTH)
    
    print_box_separator(WIDTH, 'bottom')
    ch = input("\n[C] Close All | [Enter] Back: ").upper()
    if ch == 'C':
        for p in positions: mt5c.close_position(p['ticket'])
        print("Done.")
        time.sleep(1)

def run_backtest_mode(sm: SettingsManager, mt5c: MT5Connector, silent=True):
    if not silent:
        clear_screen()
        print("\nInitializing Backtest Mode...")
    if not sm.settings.get('mt5_credentials', {}).get('login'):
        print(C_RED + "Error: MT5_LOGIN missing.")
        input("\nEnter to return.")
        return
    try:
        backtester = Backtester(mt5c, sm)
        backtester.run(silent=False)
    except Exception as e:
        print(C_RED + f"\nBacktest failed: {e}")
    if not silent: input("\nBacktest finished. Enter to return.")

def show_hotkeys():
    clear_screen()
    print_box_line("HOTKEYS", width=WIDTH)
    print_box_line("[Ctrl+C] Stop Bot", width=WIDTH)
    input("\nEnter to return...")

# ==========================================
# MAIN BOT CLASS (V4.6 FORTRESS)
# ==========================================

class GoldScalperBot:
    def __init__(self, sm: SettingsManager, mt5_connector: MT5Connector):
        print(Style.BRIGHT + "=" * 50)
        print(Style.BRIGHT + "BIFROST V4.6 (FORTRESS) - Initializing...")
        print(Style.BRIGHT + "=" * 50)
        
        self.sm = sm
        self.mt5 = mt5_connector
        self._lock = threading.RLock() # Thread Safety
        
        self.risk_manager = RiskManager(self.sm)
        self.strategy = TradingStrategy(self.sm)
        self.news_filter = NewsFilter(self.sm)
        self.session_filter = SessionFilter(self.sm)
        self.spread_filter = SpreadFilter(self.sm)
        # Pass self to TelegramBot for remote control
        self.telegram = TelegramBot(self.sm, main_bot_instance=self) 
        self.logger = Logger()
        self.ptm = ProfitTargetManager(self.sm)
        
        self.symbol = self.sm.get_symbol()
        self.timeframe = self.sm.get_timeframe()
        
        self.executor = TradeExecutor(self.mt5, self.risk_manager, self.strategy, self.sm, self.ptm)
        self.regime_detector = MarketRegimeDetector(self.sm, symbol=self.symbol)
        
        self.current_regime = "UNKNOWN"
        self.regime_details: Dict[str, Any] = {}
        self.is_running = False
        self.bot_state = "STARTING" 
        self.error_msg = ""
        
        self._base_default_lot = self.sm.get_lot_size()
        self.last_signal_details = {'signal_type': 'NEUTRAL', 'confidence': 0, 'details': {}}
        self.loop_count = 0
        self.active_session_label = "UNKNOWN"
        self.last_regime_check = 0
        self.last_news_check = 0
        
        print(C_GREEN + Style.BRIGHT + f"✓ System Initialized (Symbol: {self.symbol})")

    def start(self):
        if not self.mt5.connect():
            self.bot_state = "ERROR"
            self.error_msg = "MT5 Connection Failed"
            return False
        
        # [FIXED] Auto-Detect Symbol Logic (Strict)
        print(f"Checking configured symbol '{self.symbol}'...")
        info = self.mt5.get_symbol_info(self.symbol)
        symbol_valid = False
        if info and info.get('trade_mode') != mt5.SYMBOL_TRADE_MODE_DISABLED:
            symbol_valid = True
            print(C_GREEN + f"✓ Configured symbol '{self.symbol}' is valid.")
        
        if not symbol_valid:
            print(C_YELLOW + f"⚠️ Symbol '{self.symbol}' invalid. Scanning for XAUUSD variants...")
            all_syms = mt5.symbols_get()
            found_alt = None
            
            for s in all_syms:
                name = s.name.upper()
                if (name.startswith("XAUUSD") or name.startswith("GOLD")) and "BTC" not in name and "ETH" not in name:
                     if s.trade_mode != mt5.SYMBOL_TRADE_MODE_DISABLED:
                         found_alt = s.name
                         break
            
            if found_alt:
                print(C_GREEN + f"✅ Switched to '{found_alt}'")
                self.symbol = found_alt
                self.sm.set_symbol(found_alt)
                self.executor.symbol = found_alt
                self.regime_detector.symbol = found_alt
            else:
                print(C_RED + "❌ FATAL: No tradable XAUUSD/GOLD pair found!")
                self.bot_state = "ERROR"
                return False
        
        print(C_HEADER + "\nCalibrating market intelligence...")
        data = self.mt5.get_price_data(self.symbol, self.timeframe, bars=500)
        if data is not None and len(data) >= 200:
            self.regime_detector.calibrate_thresholds(data)
        else:
            print(C_YELLOW + "⚠️ Calibration skipped (insufficient data).")

        acc = self.mt5.get_account_info()
        if acc:
            self.telegram.notify_bot_status('STARTED', f"V4.6 Online\nSymbol: {self.symbol}\nBal: ${acc['balance']:.2f}")
        
        self.telegram.start_listening()
            
        self.is_running = True
        self.bot_state = "RUNNING"
        return True

    def stop(self):
        self.is_running = False
        self.telegram.notify_bot_status('STOPPED', 'User Shutdown')
        self.mt5.disconnect()
        print(Style.BRIGHT + C_YELLOW + "\nBot stopped gracefully.")

    def _apply_session_rules(self):
        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()

        if weekday == 4 and hour >= 23:
            self.active_session_label = "FRIDAY HARD EXIT"
            return "FRIDAY_STOP"

        current_mode = self.sm.get_trading_mode()
        target_mode = current_mode 
        session_label = "UNKNOWN"

        if 4 <= hour < 13: # Asia
            asia_pref = self.sm.get_asia_session_mode()
            if asia_pref == 'AGGRESSIVE':
                 session_label = "ASIA (Aggressive Override)"
                 target_mode = 'AUTO'
            else:
                 session_label = "ASIA (Defensive)"
                 target_mode = 'SNIPER_ONLY'
                 
        elif 13 <= hour or hour < 3: # London/US
            session_label = "LONDON/US (Aggressive)"
            target_mode = 'AUTO'
        else:
            session_label = "SWAP GAP (Paused)"
            return "PAUSED_SWAP"

        self.active_session_label = session_label

        if current_mode != target_mode:
            print(f"🔄 Auto-Switch Mode: {current_mode} -> {target_mode}")
            self.sm.set_trading_mode(target_mode)
            
        return "NORMAL"

    def update_dashboard(self):
        clear_screen()
        summary = self.executor.get_trading_summary()
        regime_summary = self.regime_detector.get_regime_summary()
        ptm_stats = self.ptm.get_progress()
        
        print_box_separator(WIDTH, 'top')
        state_col = C_GREEN if self.bot_state == "RUNNING" else C_RED
        print_box_line(f"{C_TITLE}BIFROST V4.6 (FORTRESS)", f"{datetime.now().strftime('%H:%M:%S')}", width=WIDTH)
        print_box_line(f"State: {state_col}{self.bot_state}", f"Loop: {self.loop_count}", width=WIDTH)
        
        if self.error_msg:
             print_box_line(f"{C_RED}LAST ERROR: {self.error_msg[:70]}", width=WIDTH)

        print_box_separator(WIDTH, 'middle')
        
        if summary:
            acc = summary['account']
            risk = summary['risk_stats']
            col_bal = C_GREEN if acc['balance'] > 0 else C_RED
            col_pl = C_GREEN if acc['profit'] >= 0 else C_RED
            print_box_line(f"{C_LABEL}Account: {C_VALUE}{acc['login']}", f"{C_LABEL}Margin: {C_VALUE}{acc['margin_level']:.0f}%", width=WIDTH)
            print_box_line(f"{C_LABEL}Balance: {col_bal}${acc['balance']:,.2f}", f"{C_LABEL}Equity: {col_bal}${acc['equity']:,.2f}", width=WIDTH)
            print_box_line(f"{C_LABEL}Floating: {col_pl}${acc['profit']:+,.2f}", f"{C_LABEL}Risk: {C_YELLOW}{risk['risk_pct']:.2f}%", width=WIDTH)
        else:
            print_box_line(f"{C_RED}Connection Lost / No Data", width=WIDTH)

        print_box_separator(WIDTH, 'middle')
        print_box_line(f"{C_HEADER}MARKET INTELLIGENCE ({self.symbol})", width=WIDTH)
        print_box_line(f"{C_LABEL}Regime: {C_VALUE}{regime_summary}", width=WIDTH)
        
        if self.regime_details:
            sugg_mode = self.regime_detector.get_strategy_recommendation(self.current_regime, self.regime_details)
            print_box_line(f"{C_LABEL}Advice: {C_YELLOW}{sugg_mode.get('suggested_mode')} {C_DIM}(x{sugg_mode.get('lot_multiplier')})", width=WIDTH)
            
            if 'pattern' in self.last_signal_details.get('details', {}).get('signals', {}):
                pat_data = self.last_signal_details['details']['signals']['pattern']
                pats = ",".join(pat_data.get('patterns', []))
                if pats: print_box_line(f"{C_LABEL}Pattern: {C_VALUE}{pats}", width=WIDTH)

        print_box_separator(WIDTH, 'middle')
        print_box_line(f"{C_LABEL}Session: {C_VALUE}{self.active_session_label}", width=WIDTH)
        print_box_line(f"{C_LABEL}Mode: {C_YELLOW}{self.sm.get_trading_mode()}", width=WIDTH)
        
        if ptm_stats['enabled']:
            pnl_col = C_GREEN if ptm_stats['current'] >= 0 else C_RED
            bar = get_progress_bar(ptm_stats['progress_pct'], 20)
            print_box_line(f"{C_LABEL}Daily: {pnl_col}${ptm_stats['current']:+.2f} {C_TEXT}/ ${ptm_stats['target']}", f"{bar}", width=WIDTH)
            
        print_box_separator(WIDTH, 'bottom')

    def trading_cycle(self):
        try:
            if not self.mt5.ensure_connected():
                self.bot_state = "ERROR"
                self.error_msg = "MT5 Disconnected"
                return

            status = self._apply_session_rules()
            
            if status == "FRIDAY_STOP":
                self.bot_state = "FRIDAY_STOP"
                if self.mt5.get_positions(self.symbol):
                    print(C_RED + "\n⛔ FRIDAY EXIT: Closing all positions...")
                    self.executor.close_all_positions(reason="Friday Hard Exit")
                return 

            if status == "PAUSED_SWAP":
                self.bot_state = "PAUSED_SWAP"
                return

            self.bot_state = "RUNNING"
            self.error_msg = ""

            now = time.time()
            if (now - self.last_regime_check) > 60: 
                with self._lock:
                    self.detect_and_update_regime()
                self.last_regime_check = now

            ok_pt, reason_pt = self.ptm.can_trade()
            if not ok_pt:
                self.bot_state = "PAUSED_PTM"
                return

            rec = self.regime_detector.get_strategy_recommendation(self.current_regime, self.regime_details)
            mult = rec.get('lot_multiplier', 1.0)
            
            if self._base_default_lot > 0:
                final_lot = round(self._base_default_lot * mult, 2)
                if final_lot < 0.01: final_lot = 0.01
                self.executor.trading_config['default_lot'] = final_lot

            filters = {
                'news_filter': self.news_filter, 
                'session_filter': self.session_filter, 
                'spread_filter': self.spread_filter
            }
            can_trade, session_name = self.executor.can_trade(filters)
            
            if can_trade:
                closed_list = self.executor.reconcile_closed_by_broker()
                if closed_list:
                    for closed in closed_list:
                        self.telegram.notify_exit(closed)
                        self.ptm.add_trade_result(closed.get('profit', 0.0))
                
                self.executor.manage_positions()
                self.executor.check_exit_signals(session_name)
                self.check_entries(session_name)

        except Exception as e:
            tb = traceback.format_exc()
            self.logger.log_error(f"Cycle Error: {e}\n{tb}")
            self.error_msg = str(e)

    def detect_and_update_regime(self):
        data = self.mt5.get_price_data(self.symbol, self.timeframe, bars=100)
        if data is None or len(data) < 60: return
        
        regime, details = self.regime_detector.detect_regime(data)
        if regime != self.current_regime:
            self.current_regime = regime
            self.regime_details = details
            self.strategy.update_dynamic_confidence(regime, details)
        else:
            self.regime_details = details

    def check_entries(self, session):
        res = self.executor.check_for_new_entry(session)
        if not res: return
        
        self.last_signal_details = {
            'signal_type': res.get('signal_type'), 
            'confidence': res.get('confidence'), 
            'details': res.get('details')
        }
        
        if res.get('action_taken') == 'EXECUTED':
            self.telegram.notify_entry(res['order_info'], {})
            self.logger.log_trade_entry(res['order_info'])

    def run(self):
        if not self.start(): 
            print("Bot failed to start.")
            return
        
        schedule.every().saturday.at("09:00").do(self._weekly_report)
        
        try:
            while self.is_running:
                self.loop_count += 1
                
                if self.bot_state != "FRIDAY_STOP":
                    self.update_dashboard()
                else:
                    print(f"\r[FRIDAY SLEEP] System Sleeping until Monday... {datetime.now()}", end="")
                
                if time.time() - self.last_news_check > 3600:
                    try: self.news_filter.update_news_cache()
                    except: pass
                    self.last_news_check = time.time()
                
                self.trading_cycle()
                schedule.run_pending()
                
                sleep_time = 60 if self.bot_state == "FRIDAY_STOP" else 1
                time.sleep(sleep_time)
                    
        except KeyboardInterrupt:
            self.stop()
        except Exception as e:
            print(f"Critical Main Loop Error: {e}")
            traceback.print_exc()
            self.stop()

    def _weekly_report(self):
        pass

# --- ENTRY POINT ---
def run_live(sm, mt5c): 
    bot = GoldScalperBot(sm, mt5c)
    bot.run()

def run_health(sm, mt5c):
    clear_screen()
    print(C_HEADER + "DIAGNOSIS...")
    mt5c.connect()
    status, tag, warns = sm.get_health_status()
    print(f"Health: {tag} {status}")
    for w in warns: print(f"- {w}")
    input("\nEnter to back...")

def main():
    sm = SettingsManager()
    mt5c = MT5Connector(sm)
    
    while True:
        clear_screen()
        print(C_TITLE + "="*WIDTH)
        print(C_TITLE + f"{'BIFROST V4.6 ENTERPRISE':^{WIDTH}}")
        print(C_TITLE + "="*WIDTH + C_RESET)
        
        print_box_line(f"Symbol: {sm.get_symbol()}", f"Mode: {sm.get_trading_mode()}")
        print_box_separator()
        print_box_line(f" [1] Start LIVE Bot", "Run V4.6 Logic")
        print_box_line(f" [2] Position Manager", "Close Trades")
        print_box_line(f" [3] Settings Editor", "Edit Config")
        print_box_line(f" [4] Health Check", "Audit Config")
        print_box_line(f" [5] Load Preset", "Reset Config")
        print_box_line(f" [6] Symbol Detect", "Scan Pairs")
        print_box_line(f" [7] Profit Target", "Manage Goals")
        print_box_separator()
        print_box_line(f" [0] Exit", "")
        
        ch = input(C_YELLOW + "\nChoice: ").strip()
        
        if ch == '1': run_live(sm, mt5c)
        elif ch == '2': position_management_menu(sm, mt5c)
        elif ch == '3': quick_settings_menu(sm)
        elif ch == '4': run_health(sm, mt5c)
        elif ch == '5':
             presets = sm.get_setting_presets()
             keys = list(presets.keys())
             clear_screen()
             print_box_line(f"{C_HEADER}LOAD PRESET CONFIGURATION", width=WIDTH)
             for i, key in enumerate(keys, 1):
                 p_name = presets[key].get('name', 'Unknown')
                 print_box_line(f" {C_VALUE}[{i}]{C_TEXT} {key:<15}", f"{C_DIM}{p_name}", width=WIDTH)
             print_box_line(f" {C_VALUE}[0]{C_TEXT} Cancel", width=WIDTH)
             
             sel = input(C_YELLOW + "\nSelect Preset Number [0-3]: ").strip()
             if sel.isdigit():
                 idx = int(sel) - 1
                 if 0 <= idx < len(keys):
                     target_preset = keys[idx] 
                     ok, msg = sm.load_preset(target_preset)
                     print(f"\n{msg}")
                 elif int(sel) == 0: print("\nCancelled.")
                 else: print(f"\n{C_RED}❌ Invalid number.")
             else: print(f"\n{C_RED}❌ Invalid input.")
             time.sleep(2)
        elif ch == '6': auto_detect_symbols_menu(sm, mt5c)
        elif ch == '7': profit_target_menu(sm)
        elif ch == '0': sys.exit()

if __name__ == "__main__":
    main()