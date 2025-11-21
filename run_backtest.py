# File: run_backtest.py
# (Simpan file ini di folder root bot lo, sejajar dengan main.py)

import sys
from dotenv import load_dotenv

# Import semua komponen inti
from core.mt5_connector import MT5Connector
from core.strategy import TradingStrategy
from core.risk_manager import RiskManager
from utils.backtester import Backtester

import warnings
import pandas as pd
from pandas.errors import SettingWithCopyWarning
warnings.simplefilter(action="ignore", category=SettingWithCopyWarning)

# Load .env (PENTING! MT5Connector butuh ini)
load_dotenv()

def main():
    """
    Fungsi utama untuk menjalankan backtest.
    """
    
    # 1. Inisialisasi semua komponen
    # Bot ini akan pakai file config/settings.json yang sama
    print("Initializing components for backtest...")
    mt5 = MT5Connector()
    strategy = TradingStrategy()
    risk_manager = RiskManager()
    
    # 2. Buat instance Backtester
    # Pastikan "backtesting" di settings.json udah lo atur
    # dengan start_date, end_date, dan initial_balance
    try:
        backtester = Backtester(mt5, strategy, risk_manager)
    except Exception as e:
        print(f"Failed to initialize Backtester. Cek settings.json.")
        print(f"Error: {e}")
        return

    # 3. Jalankan
    print("Starting backtest runner...")
    backtester.run()
    print("Backtest run finished.")

if __name__ == "__main__":
    # Ini adalah entry point saat lo menjalankan: python run_backtest.py
    main()