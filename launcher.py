import subprocess
import time
import sys
import os
from datetime import datetime, timedelta

# Konfigurasi
SCRIPT_NAME = "main.py"
RESTART_DELAY = 5  
MAX_RESTARTS = 100 

# ANSI Color codes untuk styling
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    UNDERLINE = '\033[4m'

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header(restart_count=0, uptime_start=None):
    clear_screen()
    width = 60
    print(f"{Colors.CYAN}{'═' * width}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'BIFROST GUARDIAN':^{width}}{Colors.ENDC}")
    print(f"{Colors.DIM}{'Auto-Restart Watchdog System':^{width}}{Colors.ENDC}")
    print(f"{Colors.CYAN}{'═' * width}{Colors.ENDC}")
    
    if uptime_start:
        uptime = datetime.now() - uptime_start
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        
        print(f"{Colors.DIM}Uptime: {Colors.GREEN}{uptime_str}{Colors.ENDC} | ", end="")
        print(f"{Colors.DIM}Restarts: {Colors.YELLOW}{restart_count}{Colors.ENDC}/{MAX_RESTARTS}")
    
    print(f"{Colors.CYAN}{'─' * width}{Colors.ENDC}\n")

def log(msg, level="INFO"):
    timestamp = datetime.now().strftime('%H:%M:%S')
    
    if level == "START":
        icon = "🚀"
        color = Colors.GREEN
    elif level == "RESTART":
        icon = "🔄"
        color = Colors.YELLOW
    elif level == "ERROR":
        icon = "❌"
        color = Colors.RED
    elif level == "WARN":
        icon = "⚠️"
        color = Colors.YELLOW
    elif level == "STOP":
        icon = "🛑"
        color = Colors.RED
    elif level == "SUCCESS":
        icon = "✅"
        color = Colors.GREEN
    else:
        icon = "ℹ️"
        color = Colors.CYAN
    
    print(f"{Colors.DIM}[{timestamp}]{Colors.ENDC} {icon}  {color}{msg}{Colors.ENDC}")

def progress_bar(seconds):
    """Animated progress bar untuk countdown"""
    bar_length = 40
    for i in range(seconds):
        progress = (i + 1) / seconds
        filled = int(bar_length * progress)
        bar = '█' * filled + '░' * (bar_length - filled)
        remaining = seconds - i - 1
        
        sys.stdout.write(f"\r{Colors.YELLOW}⏳ Restarting in {remaining}s {Colors.CYAN}[{bar}]{Colors.ENDC}")
        sys.stdout.flush()
        time.sleep(1)
    
    print()  # New line setelah progress bar

def print_status_box(status, details=""):
    """Print status dalam box"""
    box_width = 56
    print(f"\n{Colors.CYAN}┌{'─' * box_width}┐{Colors.ENDC}")
    print(f"{Colors.CYAN}│{Colors.ENDC} {status:<{box_width-2}} {Colors.CYAN}│{Colors.ENDC}")
    if details:
        print(f"{Colors.CYAN}│{Colors.ENDC} {Colors.DIM}{details:<{box_width-2}}{Colors.ENDC} {Colors.CYAN}│{Colors.ENDC}")
    print(f"{Colors.CYAN}└{'─' * box_width}┘{Colors.ENDC}\n")

def run_bot():
    restart_count = 0
    start_time = datetime.now()
    last_restart_time = None
    
    while True:
        try:
            print_header(restart_count, start_time)
            
            if restart_count > 0:
                log(f"Attempt #{restart_count + 1}", "INFO")
            
            log(f"Starting {SCRIPT_NAME}...", "START")
            print_status_box(
                f"{Colors.GREEN}● RUNNING{Colors.ENDC}",
                f"Process: {SCRIPT_NAME} | PID: Loading..."
            )
            
            process = subprocess.Popen([sys.executable, SCRIPT_NAME])
            pid = process.pid
            
            # Update status dengan PID
            print(f"\r{Colors.DIM}Process ID: {Colors.CYAN}{pid}{Colors.ENDC}")
            
            process.wait()
            
            exit_code = process.returncode
            
            # Clear dan print header lagi
            print_header(restart_count, start_time)
            
            if exit_code == 0:
                log(f"Process exited gracefully (code: {exit_code})", "SUCCESS")
            else:
                log(f"Process crashed with exit code: {exit_code}", "ERROR")
            
            restart_count += 1
            
            if restart_count > MAX_RESTARTS:
                print_status_box(
                    f"{Colors.RED}● STOPPED{Colors.ENDC}",
                    f"Maximum restart limit reached ({MAX_RESTARTS})"
                )
                log("Maximum restarts reached. Stopping Watchdog.", "STOP")
                break
            
            print_status_box(
                f"{Colors.YELLOW}● RESTARTING{Colors.ENDC}",
                f"Waiting {RESTART_DELAY} seconds before restart..."
            )
            
            progress_bar(RESTART_DELAY)
            
        except KeyboardInterrupt:
            print(f"\n\n{Colors.YELLOW}{'─' * 60}{Colors.ENDC}")
            log("Watchdog stopped by user (Ctrl+C)", "STOP")
            print_status_box(
                f"{Colors.YELLOW}● STOPPED BY USER{Colors.ENDC}",
                f"Total restarts: {restart_count}"
            )
            break
            
        except Exception as e:
            print_header(restart_count, start_time)
            log(f"Critical Watchdog Error: {str(e)}", "ERROR")
            print_status_box(
                f"{Colors.RED}● CRITICAL ERROR{Colors.ENDC}",
                str(e)
            )
            break

if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        print(f"\n{Colors.RED}Fatal Error: {e}{Colors.ENDC}")
    finally:
        print(f"\n{Colors.DIM}{'═' * 60}{Colors.ENDC}")
        print(f"{Colors.CYAN}Bifrost Guardian terminated.{Colors.ENDC}\n")