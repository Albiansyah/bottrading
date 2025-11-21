import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import sys
from datetime import datetime
from collections import deque
import math
import re

from colorama import init as colorama_init

# ==== Core (punya kamu) ====
from core.mt5_connector import MT5Connector
from utils.settings_manager import SettingsManager
from main import GoldScalperBot

colorama_init()


# ==================== UTIL ====================
def strip_ansi(text: str) -> str:
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


# ==================== TOAST ====================
class ToastNotification(tk.Toplevel):
    def __init__(self, parent, message, toast_type="info", duration=3000):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes('-topmost', True)

        colors = {
            'success': ('#10b981', '#ffffff'),
            'error': ('#ef4444', '#ffffff'),
            'warning': ('#f59e0b', '#ffffff'),
            'info': ('#3b82f6', '#ffffff')
        }
        bg_color, fg_color = colors.get(toast_type, colors['info'])
        self.configure(bg=bg_color)

        icons = {'success': '✓', 'error': '✗', 'warning': '⚠', 'info': 'ℹ'}
        icon = icons.get(toast_type, 'ℹ')

        frame = tk.Frame(self, bg=bg_color)
        frame.pack(padx=20, pady=15)

        tk.Label(frame, text=icon, font=("Segoe UI", 16, "bold"),
                 fg=fg_color, bg=bg_color).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(frame, text=message, font=("Segoe UI", 10),
                 fg=fg_color, bg=bg_color, wraplength=320, justify="left").pack(side=tk.LEFT)

        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        tw, th = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{sw - tw - 24}+{sh - th - 90}")

        self.attributes('-alpha', 0.0)
        self._fade_in()
        self.after(duration, self._fade_out)

    def _fade_in(self, alpha=0.0):
        alpha += 0.12
        if alpha <= 1.0:
            self.attributes('-alpha', alpha)
            self.after(24, lambda: self._fade_in(alpha))

    def _fade_out(self, alpha=1.0):
        alpha -= 0.12
        if alpha >= 0:
            self.attributes('-alpha', alpha)
            self.after(24, lambda: self._fade_out(alpha))
        else:
            self.destroy()


def show_toast(root, msg, t="info"):
    ToastNotification(root, msg, t)


# ==================== TOOLTIP ====================
class EnhancedTooltip:
    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tooltip = None
        self.id = None
        self.widget.bind('<Enter>', self._on_enter)
        self.widget.bind('<Leave>', self._on_leave)

    def _on_enter(self, _=None):
        self._schedule()

    def _on_leave(self, _=None):
        self._unschedule()
        self._hide()

    def _schedule(self):
        self._unschedule()
        self.id = self.widget.after(self.delay, self._show)

    def _unschedule(self):
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None

    def _show(self):
        if self.tooltip:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tooltip = tk.Toplevel(self.widget)
        self.tooltip.overrideredirect(True)
        self.tooltip.attributes('-topmost', True)
        tk.Label(self.tooltip, text=self.text, font=("Segoe UI", 9),
                 bg="#1a1a2e", fg="#ffffff",
                 padx=10, pady=6, relief='solid', borderwidth=1).pack()
        self.tooltip.geometry(f"+{x}+{y}")
        self.tooltip.attributes('-alpha', 0.0)
        self._fade_in()

    def _fade_in(self, alpha=0.0):
        if not self.tooltip:
            return
        alpha += 0.2
        if alpha <= 0.95:
            self.tooltip.attributes('-alpha', alpha)
            self.tooltip.after(18, lambda: self._fade_in(alpha))
        else:
            self.tooltip.attributes('-alpha', 0.95)

    def _hide(self):
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None


# ==================== MICRO CHARTS ====================
class SparklineChart(tk.Canvas):
    def __init__(self, parent, width=150, height=40, color="#3b82f6", **kwargs):
        super().__init__(parent, width=width, height=height, bg='white',
                         highlightthickness=0, **kwargs)
        self.width = width
        self.height = height
        self.color = color
        self.data = deque(maxlen=30)
        self.bind('<Configure>', self._on_resize)

    def _on_resize(self, event):
        self.width = event.width
        self.height = event.height
        self.redraw()

    def add_point(self, value):
        self.data.append(value)
        self.redraw()

    def redraw(self):
        self.delete('all')
        if len(self.data) < 2:
            return
        values = list(self.data)
        vmin, vmax = min(values), max(values)
        if vmax == vmin:
            vmax = vmin + 1
        pts = []
        for i, v in enumerate(values):
            x = (i / (len(values) - 1)) * self.width
            y = self.height - ((v - vmin) / (vmax - vmin)) * (self.height - 6) - 3
            pts.append((x, y))
        for i in range(len(pts) - 1):
            self.create_line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1],
                             fill=self.color, width=2, smooth=True)
        if pts:
            area = pts + [(self.width, self.height), (0, self.height)]
            flat = [c for p in area for c in p]
            self.create_polygon(flat, fill=self.color, stipple='gray25', outline='')


class GaugeMeter(tk.Canvas):
    def __init__(self, parent, size=100, max_value=100, label="", **kwargs):
        super().__init__(parent, width=size, height=size, bg='white',
                         highlightthickness=0, **kwargs)
        self.size = size
        self.max_value = max_value
        self.label = label
        self.value = 0.0
        self.cx = size // 2
        self.cy = size // 2
        self.r = (size // 2) - 14
        self.draw()

    def set_value(self, value):
        self.value = float(value)
        self.draw()

    def draw(self):
        self.delete('all')
        self.create_arc(self.cx - self.r, self.cy - self.r,
                        self.cx + self.r, self.cy + self.r,
                        start=135, extent=270, outline='#e5e7eb', width=10, style='arc')
        pct = max(0.0, min(self.value / self.max_value, 1.0))
        angle = 270 * pct
        color = '#10b981' if pct < 0.5 else ('#f59e0b' if pct < 0.8 else '#ef4444')
        self.create_arc(self.cx - self.r, self.cy - self.r,
                        self.cx + self.r, self.cy + self.r,
                        start=135, extent=angle, outline=color, width=10, style='arc')
        self.create_text(self.cx, self.cy - 5, text=f"{self.value:.1f}%",
                         font=("Segoe UI", 13, "bold"), fill='#2c3e50')
        self.create_text(self.cx, self.cy + 14, text=self.label,
                         font=("Segoe UI", 8), fill='#7f8c8d')


class SkeletonLoader(tk.Canvas):
    def __init__(self, parent, width=200, height=20, **kwargs):
        super().__init__(parent, width=width, height=height, bg='white',
                         highlightthickness=0, **kwargs)
        self.width = width
        self.height = height
        self.offset = 0
        self._animate()

    def _animate(self):
        self.delete('all')
        for i in range(0, self.width, 10):
            intensity = (math.sin((i + self.offset) * 0.05) + 1) / 2
            gray = int(220 + (intensity * 25))
            color = f'#{gray:02x}{gray:02x}{gray:02x}'
            self.create_rectangle(i, 0, i + 10, self.height, fill=color, outline='')
        self.offset = (self.offset + 5) % 120
        self.after(45, self._animate)


class StatusTimeline(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg='white', **kwargs)
        self.timeline_items = []
        self.max_items = 14
        tk.Label(self, text="Activity Timeline", font=("Segoe UI", 10, "bold"),
                 fg="#2c3e50", bg='white').pack(anchor='w', padx=12, pady=(6, 4))
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8)
        self.canvas = tk.Canvas(self, bg='white', highlightthickness=0, height=220)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollframe = tk.Frame(self.canvas, bg='white')
        self.scrollframe.bind("<Configure>",
                              lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scrollframe, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

    def add_event(self, event_type, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        icons = {
            'start': ('▶', '#10b981'),
            'stop': ('⏹', '#ef4444'),
            'trade': ('💰', '#3b82f6'),
            'signal': ('📊', '#8b5cf6'),
            'warning': ('⚠', '#f59e0b'),
            'error': ('✖', '#ef4444'),
            'info': ('ℹ', '#6b7280')
        }
        icon, color = icons.get(event_type, ('•', '#6b7280'))

        row = tk.Frame(self.scrollframe, bg='white')
        row.pack(fill=tk.X, padx=10, pady=3)
        dot = tk.Label(row, text=icon, font=("Segoe UI", 12), fg=color, bg='white', width=2)
        dot.pack(side=tk.LEFT)
        content = tk.Frame(row, bg='white')
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Label(content, text=timestamp, font=("Segoe UI", 8),
                 fg='#9ca3af', bg='white').pack(anchor='w')
        tk.Label(content, text=message, font=("Segoe UI", 9),
                 fg='#2c3e50', bg='white', wraplength=260, justify="left").pack(anchor='w')

        self.timeline_items.append(row)
        if len(self.timeline_items) > self.max_items:
            old = self.timeline_items.pop(0)
            old.destroy()
        self.canvas.yview_moveto(1.0)


class StdoutRedirector:
    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.text_widget.configure(state='disabled')

    def write(self, text_to_write):
        clean_text = strip_ansi(text_to_write)
        if not clean_text.strip():
            return
        self.text_widget.configure(state='normal')
        self.text_widget.insert(tk.END, clean_text)
        self.text_widget.see(tk.END)
        self.text_widget.configure(state='disabled')

    def flush(self):
        pass


class ModernCard(ttk.Frame):
    def __init__(self, parent, title="", collapsible=False, **kwargs):
        super().__init__(parent, relief='flat', borderwidth=0, style='Card.TFrame')
        self.collapsible = collapsible
        self.is_collapsed = False
        header = ttk.Frame(self, style='Card.TFrame')
        header.pack(fill=tk.X, padx=16, pady=(12, 6))
        ttk.Label(header, text=title, font=("Segoe UI", 10, "bold"),
                  foreground="#2c3e50", background='white').pack(side=tk.LEFT)
        if collapsible:
            self.collapse_btn = tk.Label(header, text="▼", font=("Segoe UI", 10),
                                         fg="#7f8c8d", bg='white', cursor="hand2")
            self.collapse_btn.pack(side=tk.RIGHT)
            self.collapse_btn.bind('<Button-1>', self.toggle_collapse)
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=12)
        self.content = ttk.Frame(self, style='Card.TFrame')
        self.content.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

    def toggle_collapse(self, _=None):
        if self.is_collapsed:
            self.content.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
            self.collapse_btn.config(text="▼")
        else:
            self.content.pack_forget()
            self.collapse_btn.config(text="▶")
        self.is_collapsed = not self.is_collapsed


class MetricLabel(ttk.Frame):
    def __init__(self, parent, label_text, value_var, color="#2c3e50",
                 show_sparkline=False, tooltip_text=None, **kwargs):
        super().__init__(parent, style='Card.TFrame', **kwargs)
        ttk.Label(self, text=label_text, font=("Segoe UI", 9),
                  foreground="#7f8c8d", background='white').pack(anchor='w')
        row = tk.Frame(self, bg='white')
        row.pack(anchor='w', fill=tk.X)
        self.value_label = ttk.Label(row, textvariable=value_var,
                                     font=("Segoe UI", 11, "bold"),
                                     foreground=color, background='white')
        self.value_label.pack(side=tk.LEFT)
        self.sparkline = SparklineChart(row, width=90, height=26, color=color) if show_sparkline else None
        if self.sparkline:
            self.sparkline.pack(side=tk.LEFT, padx=(10, 0))
        if tooltip_text:
            EnhancedTooltip(self.value_label, tooltip_text)

    def set_color(self, color):
        self.value_label.configure(foreground=color)
        if self.sparkline:
            self.sparkline.color = color
            self.sparkline.redraw()

    def add_sparkline_point(self, value):
        if self.sparkline:
            self.sparkline.add_point(value)


# ==================== SETTINGS DIALOG ====================
class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, settings_reader, settings_writer, initial_values: dict):
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.configure(bg="#ffffff")
        self.attributes("-topmost", True)

        self._read = settings_reader
        self._write = settings_writer

        # ---- State vars
        self.var_mode = tk.StringVar(value=initial_values.get("trading_mode", "AUTO"))
        self.var_risk = tk.DoubleVar(value=float(initial_values.get("risk_pct", 0.5)))
        self.var_lot_mult = tk.DoubleVar(value=float(initial_values.get("lot_multiplier", 1.0)))
        self.var_daily_enable = tk.BooleanVar(value=bool(initial_values.get("daily_target_enabled", False)))
        self.var_daily_target = tk.DoubleVar(value=float(initial_values.get("daily_target", 10.0)))
        self.var_symbol = tk.StringVar(value=initial_values.get("symbol", "XAUUSD"))
        self.var_max_spread = tk.IntVar(value=int(initial_values.get("max_spread", 40)))
        self.var_news = tk.BooleanVar(value=bool(initial_values.get("enable_news_filter", True)))
        self.var_session = tk.BooleanVar(value=bool(initial_values.get("enable_session_filter", True)))
        self.var_spread = tk.BooleanVar(value=bool(initial_values.get("enable_spread_filter", True)))
        self.var_dark_default = tk.BooleanVar(value=bool(initial_values.get("dark_mode_default", False)))

        container = tk.Frame(self, bg="white", padx=16, pady=16)
        container.pack(fill=tk.BOTH, expand=True)

        # --- Grid (2 kolom)
        row = 0
        def add_row(lbl, widget):
            nonlocal row
            tk.Label(container, text=lbl, bg="white", fg="#374151",
                     font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w", pady=6, padx=(0, 12))
            widget.grid(row=row, column=1, sticky="we", pady=6)
            row += 1

        # Inputs
        mode_cb = ttk.Combobox(container, textvariable=self.var_mode, state="readonly",
                               values=["AUTO", "MANUAL-BUY", "MANUAL-SELL"], width=24)
        add_row("Trading Mode", mode_cb)

        risk_sp = ttk.Spinbox(container, textvariable=self.var_risk, from_=0.01, to=10.0,
                              increment=0.01, width=10)
        add_row("Risk % per trade", risk_sp)

        lot_sp = ttk.Spinbox(container, textvariable=self.var_lot_mult, from_=0.1, to=10.0,
                             increment=0.1, width=10)
        add_row("Lot Multiplier (x)", lot_sp)

        sym_entry = ttk.Entry(container, textvariable=self.var_symbol, width=20)
        add_row("Symbol", sym_entry)

        spread_sp = ttk.Spinbox(container, textvariable=self.var_max_spread, from_=1, to=500,
                                increment=1, width=10)
        add_row("Max Spread (pts)", spread_sp)

        # Filters
        filt_frame = tk.Frame(container, bg="white")
        ttk.Checkbutton(filt_frame, text="News", variable=self.var_news).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(filt_frame, text="Session", variable=self.var_session).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(filt_frame, text="Spread", variable=self.var_spread).pack(side=tk.LEFT, padx=6)
        add_row("Filters", filt_frame)

        # Daily target
        daily_frame = tk.Frame(container, bg="white")
        ttk.Checkbutton(daily_frame, text="Enable", variable=self.var_daily_enable).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Spinbox(daily_frame, textvariable=self.var_daily_target, from_=1, to=100000,
                    increment=1, width=10).pack(side=tk.LEFT)
        add_row("Daily Target ($)", daily_frame)

        # Theme
        theme_cb = ttk.Checkbutton(container, text="Start with Dark Mode", variable=self.var_dark_default)
        add_row("Theme", theme_cb)

        container.grid_columnconfigure(1, weight=1)

        # Buttons
        btns = tk.Frame(self, bg="white")
        btns.pack(fill=tk.X, padx=16, pady=(0, 16))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btns, text="Save & Apply", command=self._save).pack(side=tk.RIGHT)

    def _save(self):
        payload = {
            "trading_mode": self.var_mode.get(),
            "risk_pct": float(self.var_risk.get()),
            "lot_multiplier": float(self.var_lot_mult.get()),
            "symbol": self.var_symbol.get().strip(),
            "max_spread": int(self.var_max_spread.get()),
            "enable_news_filter": bool(self.var_news.get()),
            "enable_session_filter": bool(self.var_session.get()),
            "enable_spread_filter": bool(self.var_spread.get()),
            "daily_target_enabled": bool(self.var_daily_enable.get()),
            "daily_target": float(self.var_daily_target.get()),
            "dark_mode_default": bool(self.var_dark_default.get()),
        }
        self._write(payload)
        self.destroy()


# ==================== MAIN GUI ====================
class BotGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bifrost Gold Bot - Pro Edition")
        self.geometry("1280x860")
        self.minsize(1120, 760)

        self.is_dark_mode = False
        self.configure(bg="#ecf0f1")
        self.bot_instance: GoldScalperBot | None = None
        self.bot_thread: threading.Thread | None = None
        self.is_loading = True

        # ---- Vars
        self.account_name_var = tk.StringVar(value="N/A")
        self.leverage_var = tk.StringVar(value="N/A")
        self.balance_var = tk.StringVar(value="$0.00")
        self.equity_var = tk.StringVar(value="$0.00")
        self.open_pl_var = tk.StringVar(value="$0.00")
        self.open_risk_var = tk.StringVar(value="$0.00")
        self.risk_pct_var = tk.StringVar(value="0.00%")
        self.positions_var = tk.StringVar(value="0")
        self.buy_pos_var = tk.StringVar(value="0")
        self.sell_pos_var = tk.StringVar(value="0")
        self.margin_lvl_var = tk.StringVar(value="0.00%")

        self.regime_var = tk.StringVar(value="UNKNOWN")
        self.regime_icon_var = tk.StringVar(value="❓")
        self.regime_strength_var = tk.StringVar(value="0%")
        self.regime_detail_var = tk.StringVar(value="N/A")
        self.regime_suggest_var = tk.StringVar(value="N/A")

        self.bid_var = tk.StringVar(value="0.00000")
        self.ask_var = tk.StringVar(value="0.00000")
        self.spread_var = tk.StringVar(value="0 pts")

        self.status_var = tk.StringVar(value="IDLE")
        self.status_icon_var = tk.StringVar(value="⚪")
        self.mode_var = tk.StringVar(value="N/A")
        self.last_signal_var = tk.StringVar(value="NEUTRAL")
        self.last_conf_var = tk.StringVar(value="0.0%")

        self.ptm_bar_var = tk.DoubleVar(value=0.0)
        self.daily_pnl_var = tk.StringVar(value="$0.00")
        self.daily_target_var = tk.StringVar(value="$0.00")
        self.daily_pct_var = tk.StringVar(value="0.0%")

        self.last_update_var = tk.StringVar(value="Never")
        self.heartbeat_indicator = None
        self._log_visible = True

        # cache settings (fallback) when SettingsManager tidak punya setter
        self._settings_cache = {}

        self._setup_styles()
        self._create_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.after(250, self._finish_loading)

    # ----- Theme
    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        self.light_theme = {
            'bg': '#ecf0f1', 'card_bg': 'white', 'text': '#2c3e50',
            'text_secondary': '#7f8c8d', 'border': '#e5e7eb'
        }
        self.dark_theme = {
            'bg': '#0f172a', 'card_bg': '#111827', 'text': '#f9fafb',
            'text_secondary': '#9ca3af', 'border': '#374151'
        }
        self._apply_theme()
        style.configure('Modern.Horizontal.TProgressbar',
                        background="#3498db", troughcolor="#ecf0f1",
                        borderwidth=0, thickness=18)
        style.configure('Loss.Modern.Horizontal.TProgressbar', background="#e74c3c")
        style.configure('Win.Modern.Horizontal.TProgressbar', background="#10b981")

    def _apply_theme(self):
        theme = self.dark_theme if self.is_dark_mode else self.light_theme
        style = ttk.Style()
        style.configure('.', background=theme['bg'], foreground=theme['text'])
        style.configure('Card.TFrame', background=theme['card_bg'])
        style.configure('TLabel', background=theme['card_bg'], font=("Segoe UI", 10))
        style.configure('Title.TLabel', font=("Segoe UI", 12, "bold"),
                        foreground=theme['text'], background=theme['card_bg'])
        self.configure(bg=theme['bg'])

    def toggle_dark_mode(self):
        self.is_dark_mode = not self.is_dark_mode
        self._apply_theme()
        self._cascade_bg(self)
        show_toast(self, "Dark Mode aktif" if self.is_dark_mode else "Light Mode aktif", "info")

    def _cascade_bg(self, widget):
        theme = self.dark_theme if self.is_dark_mode else self.light_theme
        try:
            if isinstance(widget, (tk.Frame, tk.Label, tk.Canvas, scrolledtext.ScrolledText)):
                bg = theme['card_bg'] if isinstance(widget, (tk.Label, tk.Canvas, scrolledtext.ScrolledText)) else theme['bg']
                widget.configure(bg=bg)
            for child in widget.winfo_children():
                self._cascade_bg(child)
        except Exception:
            pass

    def _finish_loading(self):
        self.is_loading = False
        if hasattr(self, 'balance_skeleton'):
            self.balance_skeleton.destroy()
        if hasattr(self, 'equity_skeleton'):
            self.equity_skeleton.destroy()

    # ----- Settings Manager helpers (aman)
    def _sm_get(self, key, default=None):
        try:
            # coba SettingsManager
            if hasattr(self, "sm") and hasattr(self.sm, "get"):
                v = self.sm.get(key)
                return default if v is None else v
            # fallback
            return self._settings_cache.get(key, default)
        except Exception:
            return self._settings_cache.get(key, default)

    def _sm_set(self, key, value):
        try:
            if hasattr(self, "sm") and hasattr(self.sm, "set"):
                self.sm.set(key, value)
            else:
                self._settings_cache[key] = value
        except Exception:
            self._settings_cache[key] = value

    def _open_settings(self):
        # ambil nilai awal
        initial = {
            "trading_mode": self._sm_get("trading_mode", "AUTO"),
            "risk_pct": float(self._sm_get("risk_pct", 0.5)),
            "lot_multiplier": float(self._sm_get("lot_multiplier", 1.0)),
            "symbol": self._sm_get("symbol", "XAUUSD"),
            "max_spread": int(self._sm_get("max_spread", 40)),
            "enable_news_filter": bool(self._sm_get("enable_news_filter", True)),
            "enable_session_filter": bool(self._sm_get("enable_session_filter", True)),
            "enable_spread_filter": bool(self._sm_get("enable_spread_filter", True)),
            "daily_target_enabled": bool(self._sm_get("daily_target_enabled", False)),
            "daily_target": float(self._sm_get("daily_target", 10.0)),
            "dark_mode_default": bool(self._sm_get("dark_mode_default", False)),
        }

        def writer(payload: dict):
            # simpan ke SettingsManager / cache
            for k, v in payload.items():
                self._sm_set(k, v)
            # terapkan ke UI/Bot
            self._apply_settings_to_runtime(payload)
            show_toast(self, "Settings saved & applied", "success")

        SettingsDialog(self, self._sm_get, writer, initial)

    def _apply_settings_to_runtime(self, s: dict):
        # Theme default (kalau user mau start dalam dark)
        if s.get("dark_mode_default", False) and not self.is_dark_mode:
            self.toggle_dark_mode()
        if not s.get("dark_mode_default", False) and self.is_dark_mode:
            self.toggle_dark_mode()

        # Update label Risk % di UI
        self.risk_pct_var.set(f"{float(s.get('risk_pct', 0.0)):.2f}%")

        # Terapkan ke bot bila sedang jalan
        if self.bot_instance and getattr(self.bot_instance, "is_running", False):
            # Trading mode
            try:
                mode = s.get("trading_mode", "AUTO")
                if hasattr(self.bot_instance.sm, "set_trading_mode"):
                    self.bot_instance.sm.set_trading_mode(mode)
                else:
                    self._sm_set("trading_mode", mode)
            except Exception:
                pass

            # Risk & lot multiplier
            try:
                if hasattr(self.bot_instance, "risk_manager"):
                    rm = self.bot_instance.risk_manager
                    if hasattr(rm, "set_risk_pct"):
                        rm.set_risk_pct(float(s.get("risk_pct", 0.5)))
                    if hasattr(rm, "set_lot_multiplier"):
                        rm.set_lot_multiplier(float(s.get("lot_multiplier", 1.0)))
            except Exception:
                pass

            # Filters
            try:
                if hasattr(self.bot_instance, "news_filter") and hasattr(self.bot_instance.news_filter, "set_enabled"):
                    self.bot_instance.news_filter.set_enabled(bool(s.get("enable_news_filter", True)))
                if hasattr(self.bot_instance, "session_filter") and hasattr(self.bot_instance.session_filter, "set_enabled"):
                    self.bot_instance.session_filter.set_enabled(bool(s.get("enable_session_filter", True)))
                if hasattr(self.bot_instance, "spread_filter"):
                    sf = self.bot_instance.spread_filter
                    if hasattr(sf, "set_enabled"):
                        sf.set_enabled(bool(s.get("enable_spread_filter", True)))
                    if hasattr(sf, "set_max_spread"):
                        sf.set_max_spread(int(s.get("max_spread", 40)))
            except Exception:
                pass

            # Daily target / PTM
            try:
                if hasattr(self.bot_instance, "ptm"):
                    ptm = self.bot_instance.ptm
                    if hasattr(ptm, "set_enabled"):
                        ptm.set_enabled(bool(s.get("daily_target_enabled", False)))
                    if hasattr(ptm, "set_target"):
                        ptm.set_target(float(s.get("daily_target", 10.0)))
            except Exception:
                pass

            # Symbol (jika bot mendukung runtime switch)
            try:
                new_symbol = s.get("symbol", "XAUUSD").strip()
                if new_symbol and hasattr(self.bot_instance, "set_symbol"):
                    self.bot_instance.set_symbol(new_symbol)
            except Exception:
                pass

    # ----- UI
    def _create_ui(self):
        header = tk.Frame(self, bg="#1f2937", height=84)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)

        left = tk.Frame(header, bg="#1f2937")
        left.pack(side=tk.LEFT, padx=20, pady=14)

        tk.Label(left, text="🏆 BIFROST GOLD BOT",
                 font=("Segoe UI", 20, "bold"), fg="white", bg="#1f2937").pack(anchor='w')
        tk.Label(left, text="Professional Trading System v4.0",
                 font=("Segoe UI", 10), fg="#9ca3af", bg="#1f2937").pack(anchor='w')

        self.heartbeat_indicator = tk.Label(header, text="●",
                                            font=("Segoe UI", 16),
                                            fg="#6b7280", bg="#1f2937")
        self.heartbeat_indicator.pack(side=tk.LEFT, padx=10)

        hmetrics = tk.Frame(header, bg="#1f2937")
        hmetrics.pack(side=tk.LEFT, padx=12, fill=tk.Y)
        tk.Label(hmetrics, textvariable=self.equity_var,
                 font=("Segoe UI", 16, "bold"), fg="#10b981", bg="#1f2937").pack(anchor='w')
        tk.Label(hmetrics, textvariable=self.open_pl_var,
                 font=("Segoe UI", 12), fg="#3b82f6", bg="#1f2937").pack(anchor='w')

        controls = tk.Frame(header, bg="#1f2937")
        controls.pack(side=tk.RIGHT, padx=20, pady=14)

        btn_settings = tk.Button(controls, text="⚙️", command=self._open_settings,
                                 bg="#374151", fg="white", font=("Segoe UI", 13),
                                 relief='flat', padx=10, pady=6, cursor="hand2", width=3)
        btn_settings.pack(side=tk.LEFT, padx=6)
        EnhancedTooltip(btn_settings, "Open Settings")

        self.dark_mode_btn = tk.Button(controls, text="🌙", command=self.toggle_dark_mode,
                                       bg="#374151", fg="white", font=("Segoe UI", 13),
                                       relief='flat', padx=10, pady=6, cursor="hand2", width=3)
        self.dark_mode_btn.pack(side=tk.LEFT, padx=6)
        EnhancedTooltip(self.dark_mode_btn, "Toggle Dark/Light")

        self.start_button = tk.Button(controls, text="▶ START",
                                      command=self.start_bot_thread,
                                      bg="#059669", fg="white", font=("Segoe UI", 11, "bold"),
                                      relief='flat', padx=18, pady=10, cursor="hand2",
                                      activebackground="#047857", activeforeground="white")
        self.start_button.pack(side=tk.LEFT, padx=6)

        self.stop_button = tk.Button(controls, text="⏹ STOP",
                                     command=self.stop_bot_thread,
                                     bg="#6b7280", fg="white", font=("Segoe UI", 11, "bold"),
                                     relief='flat', padx=18, pady=10, cursor="hand2",
                                     state='disabled', activebackground="#991b1b",
                                     activeforeground="white")
        self.stop_button.pack(side=tk.LEFT, padx=6)

        self.toggle_log_btn = tk.Button(controls, text="🗒 Hide Log",
                                        command=self._toggle_log,
                                        bg="#374151", fg="white", font=("Segoe UI", 10),
                                        relief='flat', padx=12, pady=8, cursor="hand2")
        self.toggle_log_btn.pack(side=tk.LEFT, padx=6)

        main = tk.Frame(self, bg="#ecf0f1")
        main.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        left_panel = tk.Frame(main, bg="#ecf0f1")
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        right_panel = tk.Frame(main, bg="#ecf0f1", width=380)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(6, 0))
        right_panel.pack_propagate(False)

        # --- Account & Risk
        account_card = ModernCard(left_panel, title="💼 Account & Risk", collapsible=True)
        account_card.pack(fill=tk.X, pady=(0, 10))
        acc_grid = ttk.Frame(account_card.content, style='Card.TFrame')
        acc_grid.pack(fill=tk.BOTH, expand=True)

        self.balance_skeleton = SkeletonLoader(acc_grid, width=120, height=20)
        self.balance_skeleton.grid(row=1, column=0, sticky='w', padx=(0, 20), pady=5)
        self.equity_skeleton = SkeletonLoader(acc_grid, width=120, height=20)
        self.equity_skeleton.grid(row=1, column=1, sticky='w', padx=(0, 20), pady=5)

        self.ml_balance = MetricLabel(acc_grid, "Balance", self.balance_var,
                                      color="#059669", show_sparkline=True,
                                      tooltip_text="Current account balance")
        self.ml_balance.grid(row=1, column=0, sticky='w', padx=(0, 20), pady=5)

        self.ml_equity = MetricLabel(acc_grid, "Equity", self.equity_var,
                                     color="#059669", show_sparkline=True,
                                     tooltip_text="Real-time equity value")
        self.ml_equity.grid(row=1, column=1, sticky='w', padx=(0, 20), pady=5)

        self.ml_open_pl = MetricLabel(acc_grid, "Open P/L", self.open_pl_var,
                                      color="#ef4444", tooltip_text="Unrealized profit/loss")
        self.ml_open_pl.grid(row=2, column=0, sticky='w', padx=(0, 20), pady=5)

        self.ml_open_risk = MetricLabel(acc_grid, "Open Risk", self.open_risk_var,
                                        color="#f59e0b", tooltip_text="Total risk exposure")
        self.ml_open_risk.grid(row=2, column=1, sticky='w', padx=(0, 20), pady=5)

        MetricLabel(acc_grid, "Account", self.account_name_var).grid(
            row=0, column=0, sticky='w', padx=(0, 20), pady=5)
        MetricLabel(acc_grid, "Leverage", self.leverage_var).grid(
            row=0, column=1, sticky='w', padx=(0, 20), pady=5)
        MetricLabel(acc_grid, "Risk %", self.risk_pct_var, color="#f59e0b",
                    tooltip_text="Risk as % of balance").grid(
            row=2, column=2, sticky='w', pady=5)

        # --- Positions
        pos_card = ModernCard(left_panel, title="📊 Positions", collapsible=True)
        pos_card.pack(fill=tk.X, pady=(0, 10))
        pos_grid = ttk.Frame(pos_card.content, style='Card.TFrame')
        pos_grid.pack(fill=tk.BOTH, expand=True)
        MetricLabel(pos_grid, "Total Positions", self.positions_var,
                    color="#3b82f6").grid(row=0, column=0, sticky='w', padx=(0, 20), pady=5)
        MetricLabel(pos_grid, "Buy Positions", self.buy_pos_var,
                    color="#059669").grid(row=0, column=1, sticky='w', padx=(0, 20), pady=5)
        MetricLabel(pos_grid, "Sell Positions", self.sell_pos_var,
                    color="#ef4444").grid(row=0, column=2, sticky='w', pady=5)
        MetricLabel(pos_grid, "Margin Level", self.margin_lvl_var,
                    color="#9b59b6").grid(row=1, column=0, sticky='w', pady=5)

        # --- Regime
        regime_card = ModernCard(left_panel, title="🌊 Market Regime", collapsible=True)
        regime_card.pack(fill=tk.X, pady=(0, 10))
        regime_header = ttk.Frame(regime_card.content, style='Card.TFrame')
        regime_header.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(regime_header, textvariable=self.regime_icon_var,
                  font=("Segoe UI", 32), background='white').pack(side=tk.LEFT, padx=(0, 14))
        regime_info = ttk.Frame(regime_header, style='Card.TFrame')
        regime_info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(regime_info, textvariable=self.regime_var,
                  font=("Segoe UI", 16, "bold")).pack(anchor='w')
        ttk.Label(regime_info, textvariable=self.regime_strength_var,
                  font=("Segoe UI", 12), foreground="#7f8c8d").pack(anchor='w')

        regime_details = ttk.Frame(regime_card.content, style='Card.TFrame')
        regime_details.pack(fill=tk.X)
        MetricLabel(regime_details, "Details", self.regime_detail_var).pack(anchor='w', pady=2)
        MetricLabel(regime_details, "Suggested Strategy", self.regime_suggest_var,
                    color="#f59e0b").pack(anchor='w', pady=2)

        # --- Price
        price_card = ModernCard(left_panel, title="💰 Market Price", collapsible=True)
        price_card.pack(fill=tk.X, pady=(0, 10))
        price_grid = ttk.Frame(price_card.content, style='Card.TFrame')
        price_grid.pack(fill=tk.BOTH, expand=True)
        self.ml_bid = MetricLabel(price_grid, "BID", self.bid_var, color="#ef4444", show_sparkline=True)
        self.ml_bid.grid(row=0, column=0, sticky='w', padx=(0, 20), pady=5)
        self.ml_ask = MetricLabel(price_grid, "ASK", self.ask_var, color="#059669", show_sparkline=True)
        self.ml_ask.grid(row=0, column=1, sticky='w', padx=(0, 20), pady=5)
        self.ml_spread = MetricLabel(price_grid, "SPREAD", self.spread_var,
                                     color="#f39c12", tooltip_text="Current spread in points")
        self.ml_spread.grid(row=0, column=2, sticky='w', pady=5)

        # --- Log
        log_card = ModernCard(left_panel, title="📝 Activity Log", collapsible=True)
        log_card.pack(fill=tk.BOTH, expand=True)
        self.log_container = log_card
        self.log_widget = scrolledtext.ScrolledText(
            log_card.content, wrap=tk.WORD, height=12,
            background="#111827", foreground="#e5e7eb",
            font=("Cascadia Mono", 10), insertbackground="white",
            relief='flat', borderwidth=0)
        self.log_widget.pack(fill=tk.BOTH, expand=True)
        self.stdout_redirector = StdoutRedirector(self.log_widget)
        sys.stdout = self.stdout_redirector
        sys.stderr = self.stdout_redirector

        # --- Right: status
        status_card = ModernCard(right_panel, title="⚡ Bot Status")
        status_card.pack(fill=tk.X, pady=(0, 10))
        status_display = ttk.Frame(status_card.content, style='Card.TFrame')
        status_display.pack(fill=tk.X, pady=6)
        ttk.Label(status_display, textvariable=self.status_icon_var,
                  font=("Segoe UI", 24)).pack(side=tk.LEFT, padx=(0, 10))
        status_text = ttk.Frame(status_display, style='Card.TFrame')
        status_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.status_text_label = ttk.Label(status_text, textvariable=self.status_var,
                                           font=("Segoe UI", 14, "bold"))
        self.status_text_label.pack(anchor='w')
        ttk.Label(status_text, textvariable=self.last_update_var,
                  font=("Segoe UI", 8), foreground="#9ca3af").pack(anchor='w')
        MetricLabel(status_card.content, "Mode", self.mode_var,
                    color="#3b82f6").pack(anchor='w', pady=4)

        # --- Gauges
        gauges_card = ModernCard(right_panel, title="📊 Risk Gauges")
        gauges_card.pack(fill=tk.X, pady=(0, 10))
        gbox = ttk.Frame(gauges_card.content, style='Card.TFrame')
        gbox.pack(fill=tk.X, pady=6)
        self.risk_gauge = GaugeMeter(gbox, size=100, max_value=5.0, label="Risk %")
        self.risk_gauge.pack(side=tk.LEFT, padx=8)
        self.margin_gauge = GaugeMeter(gbox, size=100, max_value=1000, label="Margin %")
        self.margin_gauge.pack(side=tk.LEFT, padx=8)

        # --- Last Signal
        signal_card = ModernCard(right_panel, title="🎯 Last Signal")
        signal_card.pack(fill=tk.X, pady=(0, 10))
        sdisp = ttk.Frame(signal_card.content, style='Card.TFrame')
        sdisp.pack(fill=tk.X)
        self.last_signal_label = ttk.Label(sdisp, textvariable=self.last_signal_var,
                                           font=("Segoe UI", 18, "bold"))
        self.last_signal_label.pack(anchor='w')
        ttk.Label(sdisp, textvariable=self.last_conf_var,
                  font=("Segoe UI", 12), foreground="#7f8c8d").pack(anchor='w')

        # --- Daily Target
        target_card = ModernCard(right_panel, title="🎯 Daily Target")
        target_card.pack(fill=tk.X, pady=(0, 10))
        tstats = ttk.Frame(target_card.content, style='Card.TFrame')
        tstats.pack(fill=tk.X, pady=(0, 6))
        self.ml_daily_pnl = MetricLabel(tstats, "Current P/L", self.daily_pnl_var,
                                        color="#059669", show_sparkline=True)
        self.ml_daily_pnl.pack(anchor='w', pady=2)
        MetricLabel(tstats, "Target", self.daily_target_var,
                    color="#3b82f6").pack(anchor='w', pady=2)
        MetricLabel(tstats, "Progress", self.daily_pct_var,
                    color="#f59e0b").pack(anchor='w', pady=2)
        self.ptm_progress_bar = ttk.Progressbar(
            target_card.content, variable=self.ptm_bar_var,
            style='Modern.Horizontal.TProgressbar', mode='determinate')
        self.ptm_progress_bar.pack(fill=tk.X, pady=8)

        # --- Timeline
        self.timeline = StatusTimeline(right_panel)
        self.timeline.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.timeline.add_event('info', 'System initialized')
        self.timeline.add_event('info', 'Waiting for bot start...')

        self._animate_heartbeat()
        self.after(1000, self.update_gui_dashboard)

    # ----- Controls
    def _toggle_log(self):
        if self._log_visible:
            self.log_container.pack_forget()
            self.toggle_log_btn.configure(text="🗒 Show Log")
        else:
            self.log_container.pack(fill=tk.BOTH, expand=True)
            self.toggle_log_btn.configure(text="🗒 Hide Log")
        self._log_visible = not self._log_visible

    def _animate_heartbeat(self):
        if self.bot_instance and getattr(self.bot_instance, "is_running", False):
            self.heartbeat_indicator.configure(fg=("#10b981"
                                                   if self.heartbeat_indicator.cget('fg') != "#10b981"
                                                   else "#6ee7b7"))
            self.after(450, self._animate_heartbeat)
        else:
            self.heartbeat_indicator.configure(fg="#6b7280")
            self.after(900, self._animate_heartbeat)

    def start_bot_thread(self):
        self.start_button.configure(state='disabled', bg="#6b7280")
        self.stop_button.configure(state='normal', bg="#ef4444")
        self.timeline.add_event('start', 'Bot started')
        show_toast(self, "Bot is starting...", "info")
        self.bot_thread = threading.Thread(target=self._run_bot_logic, daemon=True)
        self.bot_thread.start()

    def _run_bot_logic(self):
        try:
            self.sm = SettingsManager()
            mt5c = MT5Connector(self.sm)
            self.bot_instance = GoldScalperBot(self.sm, mt5c)
            # apply default theme setting on start
            if bool(self._sm_get("dark_mode_default", False)):
                if not self.is_dark_mode:
                    self.toggle_dark_mode()
            self.bot_instance.run()
            self.timeline.add_event('stop', 'Bot stopped normally')
            show_toast(self, "Bot stopped", "warning")
        except Exception:
            self.timeline.add_event('error', 'Critical error occurred')
            show_toast(self, "Error occurred", "error")
        finally:
            self.start_button.configure(state='normal', bg="#059669")
            self.stop_button.configure(state='disabled', bg="#6b7280")

    def stop_bot_thread(self):
        self.stop_button.configure(state='disabled', bg="#6b7280")
        self.timeline.add_event('warning', 'Stop signal sent')
        show_toast(self, "Stopping bot...", "warning")
        if self.bot_instance:
            threading.Thread(target=self.bot_instance.stop, daemon=True).start()
        self.start_button.configure(state='normal', bg="#059669")

    def on_closing(self):
        if self.bot_instance and getattr(self.bot_instance, "is_running", False):
            if messagebox.askyesno("Keluar?", "Bot masih jalan. Yakin mau keluar (bot akan stop)?"):
                self.stop_bot_thread()
                self.destroy()
        else:
            self.destroy()

    # ----- Dashboard updater
    def update_gui_dashboard(self):
        self.after(1000, self.update_gui_dashboard)
        if not self.bot_instance or not getattr(self.bot_instance, "is_running", False):
            return
        try:
            self.last_update_var.set(f"Updated: {datetime.now().strftime('%H:%M:%S')}")
            summary = self.bot_instance.executor.get_trading_summary()
            ptm_progress = self.bot_instance.ptm.get_progress() if hasattr(self.bot_instance, "ptm") else None

            if summary:
                account = summary.get('account', {})
                risk = summary.get('risk_stats', {})
                info = summary.get('symbol_info', {})

                login = account.get('login', 'N/A')
                server = account.get('server', 'N/A')
                self.account_name_var.set(f"{login} ({server})")
                self.leverage_var.set(f"1:{account.get('leverage', 'N/A')}")

                balance_val = float(account.get('balance', 0) or 0)
                equity_val = float(account.get('equity', 0) or 0)
                self.balance_var.set(f"${balance_val:,.2f}")
                self.equity_var.set(f"${equity_val:,.2f}")
                self.ml_balance.add_sparkline_point(balance_val)
                self.ml_equity.add_sparkline_point(equity_val)

                profit = float(account.get('profit', 0) or 0)
                self.open_pl_var.set(f"${profit:+,.2f}")
                self.ml_open_pl.set_color("#059669" if profit >= 0 else "#ef4444")

                risk_pct_val = float(risk.get('risk_pct', 0) or 0)
                self.open_risk_var.set(f"${float(risk.get('total_risk', 0) or 0):.2f}")
                self.risk_pct_var.set(f"{risk_pct_val:.2f}%")
                self.ml_open_risk.set_color("#f59e0b" if risk_pct_val > 1.0 else "#2c3e50")

                self.risk_gauge.set_value(risk_pct_val)
                margin_level = float(account.get('margin_level', 0) or 0)
                self.margin_gauge.set_value(min(margin_level / 10, 100))
                self.margin_lvl_var.set(f"{margin_level:.2f}%")

                self.positions_var.set(str(risk.get('total_positions', 0)))
                self.buy_pos_var.set(str(risk.get('buy_positions', 0)))
                self.sell_pos_var.set(str(risk.get('sell_positions', 0)))

                bid_val = float(info.get('bid', 0.0) or 0.0)
                ask_val = float(info.get('ask', 0.0) or 0.0)
                self.bid_var.set(f"{bid_val:.5f}")
                self.ask_var.set(f"{ask_val:.5f}")
                self.ml_bid.add_sparkline_point(bid_val)
                self.ml_ask.add_sparkline_point(ask_val)

                spread_val = int(info.get('spread', 0) or 0)
                self.spread_var.set(f"{spread_val} pts")
                self.ml_spread.set_color("#f39c12" if spread_val > int(self._sm_get("max_spread", 40)) else "#2c3e50")

            regime = getattr(self.bot_instance, "current_regime", "UNKNOWN")
            regime_icons = {"TRENDING": "📈", "RANGING": "↔️", "BREAKOUT": "🚀",
                            "VOLATILE": "⚡", "NEUTRAL": "➖", "UNKNOWN": "❓"}
            self.regime_icon_var.set(regime_icons.get(regime, "❓"))
            self.regime_var.set(regime)

            details = getattr(self.bot_instance, "regime_details", None)
            if details:
                strength = details.get('strength', 'N/A')
                if regime == "TRENDING":
                    strength_pct = {"WEAK": "30%", "MODERATE": "60%", "STRONG": "90%"}.get(strength, "0%")
                    self.regime_strength_var.set(f"Strength: {strength_pct}")
                    self.regime_detail_var.set(f"{details.get('direction', 'N/A')} {strength}")
                elif regime == "RANGING":
                    self.regime_strength_var.set("Range Detected")
                    self.regime_detail_var.set(f"{details.get('support', 'N/A')} - {details.get('resistance', 'N/A')}")
                else:
                    self.regime_strength_var.set("")
                    self.regime_detail_var.set(details.get('direction', 'N/A'))

                if hasattr(self.bot_instance, "regime_detector"):
                    reco = self.bot_instance.regime_detector.get_strategy_recommendation(regime, details)
                    self.regime_suggest_var.set(f"{reco.get('suggested_mode', 'N/A')} (Lot: {reco.get('lot_multiplier', 1.0)}x)")

            # Status
            sm = self.bot_instance.sm
            current_mode = sm.get_trading_mode() if hasattr(sm, "get_trading_mode") else self._sm_get("trading_mode", "AUTO")
            filters = {'news_filter': getattr(self.bot_instance, "news_filter", None),
                       'session_filter': getattr(self.bot_instance, "session_filter", None),
                       'spread_filter': getattr(self.bot_instance, "spread_filter", None)}
            can_trade, reason_or_session = self.bot_instance.executor.can_trade(filters)

            if not can_trade:
                self.status_var.set("PAUSED")
                self.status_icon_var.set("⏸️")
                self.mode_var.set(reason_or_session[:44] if reason_or_session else "Paused")
                self.status_text_label.configure(foreground="#f59e0b")
            else:
                self.status_var.set("ACTIVE")
                self.status_icon_var.set("✅")
                self.mode_var.set(f"{'AUTO' if current_mode == 'AUTO' else f'MANUAL ({current_mode})'} ({regime})")
                self.status_text_label.configure(foreground="#059669")

            # Signal
            last_signal = self.bot_instance.last_signal_details.get('signal_type', 'NEUTRAL')
            last_conf = float(self.bot_instance.last_signal_details.get('confidence', 0.0))
            self.last_signal_var.set(last_signal)
            self.last_signal_label.configure(
                foreground=("#059669" if last_signal == "BUY" else "#ef4444" if last_signal == "SELL" else "#2c3e50"))
            self.last_conf_var.set(f"Confidence: {last_conf:.1f}%")

            # PTM
            if ptm_progress and ptm_progress.get('enabled'):
                pnl = float(ptm_progress.get('current', 0))
                target = float(ptm_progress.get('target', 0))
                pct = float(ptm_progress.get('progress_pct', 0))
                self.daily_pnl_var.set(f"${pnl:+.2f}")
                self.ml_daily_pnl.set_color("#059669" if pnl >= 0 else "#ef4444")
                self.ml_daily_pnl.add_sparkline_point(pnl)
                self.daily_target_var.set(f"${target:.2f}")
                self.daily_pct_var.set(f"{pct:.1f}%")
                self.ptm_bar_var.set(min(pct, 100))
                if pct >= 100 and not getattr(self, '_target_reached', False):
                    self._target_reached = True
                    self.timeline.add_event('success', 'Daily target achieved! 🎉')
                    show_toast(self, 'Daily Target Achieved! 🎉', 'success')
                if pnl < 0:
                    self.ptm_progress_bar.configure(style="Loss.Modern.Horizontal.TProgressbar")
                elif pct >= 100:
                    self.ptm_progress_bar.configure(style="Win.Modern.Horizontal.TProgressbar")
                else:
                    self.ptm_progress_bar.configure(style="Modern.Horizontal.TProgressbar")
            else:
                self.daily_pnl_var.set("DISABLED")
                self.daily_target_var.set("N/A")
                self.daily_pct_var.set("0%")
                self.ptm_bar_var.set(0)

        except Exception:
            pass  # jangan tampilkan debug

    # ----- App loop
    def mainloop(self, n=0):
        super().mainloop(n)


if __name__ == "__main__":
    app = BotGUI()
    app.mainloop()
