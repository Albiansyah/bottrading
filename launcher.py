import subprocess
import time
import sys
from datetime import datetime

# Konfigurasi
SCRIPT_NAME = "main.py"
RESTART_DELAY = 5  
MAX_RESTARTS = 100 

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [WATCHDOG] {msg}")

def run_bot():
    restart_count = 0
    
    while True:
        try:
            log(f"🚀 Starting {SCRIPT_NAME}...")
            process = subprocess.Popen([sys.executable, SCRIPT_NAME])
            process.wait()
            
            exit_code = process.returncode
            
            log(f"⚠️ Bot died with exit code: {exit_code}")
            
            restart_count += 1
            if restart_count > MAX_RESTARTS:
                log("❌ Too many restarts. Stopping Watchdog.")
                break
            
            log(f"🔄 Restarting in {RESTART_DELAY} seconds...")
            time.sleep(RESTART_DELAY)
            
        except KeyboardInterrupt:
            log("🛑 Watchdog stopped by user.")
            break
        except Exception as e:
            log(f"❌ Critical Watchdog Error: {e}")
            break

if __name__ == "__main__":
    print("========================================")
    print("   BIFROST GUARDIAN (AUTO-RESTART)      ")
    print("========================================")
    run_bot()