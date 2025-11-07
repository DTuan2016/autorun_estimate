#!/usr/bin/env python3
import time
import os
from colorama import Fore, Style, init

init(autoreset=True)

# --- Color definitions ---
COLOR_INFO = Fore.GREEN
COLOR_WARN = Fore.YELLOW
COLOR_ERROR = Fore.RED
COLOR_DEBUG = Fore.CYAN
COLOR_HEADER = Fore.MAGENTA + Style.BRIGHT
COLOR_RESET = Style.RESET_ALL

# --- Global variables ---
g_system_log = None
g_log_file = None

def init_logger(system_log_path):
    """Khởi tạo file log hệ thống."""
    global g_system_log
    os.makedirs(os.path.dirname(system_log_path), exist_ok=True)
    g_system_log = open(system_log_path, "a", buffering=1)
    return g_system_log

def set_run_log(path):
    """Ghi log cho một lần chạy cụ thể (run)."""
    global g_log_file
    g_log_file = open(path, "a", buffering=1)
    return g_log_file

def close_run_log():
    """Đóng file log của run hiện tại."""
    global g_log_file
    if g_log_file:
        g_log_file.close()
        g_log_file = None

def log(level, message, to_file=True):
    """Hàm ghi log ra console + file."""
    global g_system_log, g_log_file
    if level == 'INFO': color, prefix = COLOR_INFO, '[INFO]'
    elif level == 'WARN': color, prefix = COLOR_WARN, '[WARN]'
    elif level == 'ERROR': color, prefix = COLOR_ERROR, '[ERROR]'
    elif level == 'DEBUG': color, prefix = COLOR_DEBUG, '[DEBUG]'
    elif level == 'HEADER': color, prefix = COLOR_HEADER, '==='
    else: color, prefix = COLOR_RESET, ''
    msg = f"{prefix} {message}"
    print(f"{color}{msg}{COLOR_RESET}")
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    if g_system_log:
        g_system_log.write(f"{timestamp} {msg}\n")
        g_system_log.flush()
    if to_file and g_log_file:
        g_log_file.write(f"{timestamp} {msg}\n")
        g_log_file.flush()
