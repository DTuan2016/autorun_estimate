import subprocess
import re
import requests
import os
import time
import signal
from colorama import Fore, Style, init
from multiprocessing import Process
import argparse

# --- Initialize colorama ---
init(autoreset=True)

# --- Color definitions ---
COLOR_INFO = Fore.GREEN
COLOR_WARN = Fore.YELLOW
COLOR_ERROR = Fore.RED
COLOR_DEBUG = Fore.CYAN
COLOR_HEADER = Fore.MAGENTA + Style.BRIGHT
COLOR_RESET = Style.RESET_ALL

# --- Paths ---
BASE_DIR = "/home/dongtv/dtuan/autorun/all_results"
LOG_SYSTEM_PATH = os.path.join(BASE_DIR, "cpu_estimate_base.log")
BPF_DIR = os.path.join(BASE_DIR, "cpu_bpf_base")
LANFORCE_DIR = os.path.join("/home/lanforge/Desktop/app", "cpu_base")
PERF_DIR = os.path.join(BASE_DIR, "cpu_perf_base")
THROUGHPUT_DIR = os.path.join(BASE_DIR, "throughput_latency_base")
THROUGHPUT_SCRIPT = "/home/dongtv/dtuan/autorun/src/estimate_throughput_latency.py"

# --- Parse CLI arguments ---
parser = argparse.ArgumentParser(description="Automated XDP profiling runner")
parser.add_argument("--branch", required=True, help="Tên branch (ví dụ: knn_threshold)")
parser.add_argument("--param", required=True, help="Thông số thuật toán (ví dụ: 200)")
parser.add_argument("--max-time", type=int, default=120, help="Thời gian chạy mỗi lần (mặc định: 120s)")
parser.add_argument("--num-runs", type=int, default=5, help="Số lần lặp lại mỗi mức PPS (mặc định: 5)")
args = parser.parse_args()

branch = args.branch
param = args.param
MAX_TIME = args.max_time
NUM_RUNS = args.num_runs

# --- Input params ---
api_url = "http://192.168.101.238:20168/run"
iface = "eno3"

# --- Prepare folders ---
os.makedirs(BPF_DIR, exist_ok=True)
os.makedirs(PERF_DIR, exist_ok=True)
os.makedirs(THROUGHPUT_DIR, exist_ok=True)

# --- System-wide log file ---
g_system_log = open(LOG_SYSTEM_PATH, "a", buffering=1)
g_log_file = None  # profiling log (per-run)

# --- Logging function ---
def log(level, message, to_file=True):
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
    # Always log to system log
    if g_system_log:
        g_system_log.write(f"{timestamp} {msg}\n")
        g_system_log.flush()
    # Also log to per-profiling log if active
    if to_file and g_log_file:
        g_log_file.write(f"{timestamp} {msg}\n")
        g_log_file.flush()

def call_tcpreplay_api(api_url, log_file, speed):
    """Gọi tcpreplay API, chờ đúng MAX_TIME giây để đảm bảo chạy đủ."""
    payload = {"log": log_file, "speed": speed, "duration": MAX_TIME}
    log('INFO', f"Gửi tcpreplay request: speed={speed}, duration={MAX_TIME}s")
    start_time = time.time()
    try:
        resp = requests.post(api_url, json=payload, timeout=10)
        if resp.status_code == 200:
            log('INFO', f"API trả về OK: {resp.json()}")
        else:
            log('WARN', f"API lỗi: {resp.status_code} {resp.text}")
    except Exception as e:
        log('ERROR', f"Gọi API thất bại: {e}")
    log('INFO', f"Chờ tcpreplay chạy đủ {MAX_TIME}s ...")
    time.sleep(MAX_TIME)
    elapsed = time.time() - start_time
    log('INFO', f"tcpreplay hoàn tất ({elapsed:.1f}s)")

def run_throughput_latency(branch, param, pps, run_idx, max_time):
    """Chạy đo throughput/latency song song (background)."""
    output_csv = os.path.join(THROUGHPUT_DIR, f"{branch}_{param}_{pps}_{run_idx}.csv")
    cmd = [
        "sudo", "python3", THROUGHPUT_SCRIPT,
        f"/sys/fs/bpf/{iface}/accounting_map",
        output_csv,
        str(max_time)
    ]
    log('INFO', f"Khởi động đo throughput/latency → {output_csv}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc

# --- Main loop ---
for pps in range(10000, 150001, 10000):
    for run_idx in range(1, NUM_RUNS + 1):
        log_file_bpf = os.path.join(BPF_DIR, f"log_{branch}_{param}_{pps}_{run_idx}.txt")
        log_file_lanforge = os.path.join(LANFORCE_DIR, f"log_{branch}_{param}_{pps}_{run_idx}.txt")
        
        g_log_file = open(log_file_bpf, "a")
        log('HEADER', f"=== PPS={pps}, Run {run_idx}/{NUM_RUNS} ===")
        g_log_file.write(f"=== PPS={pps}, RUN={run_idx}, BRANCH={branch}, PARAM={param}, TIME={time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        
        # --- Step 1: start throughput measurement in background ---
        # measure_proc = run_throughput_latency(branch, param, pps, run_idx, MAX_TIME + 5)
        # time.sleep(2) 
        
        # --- Step 2: start traffic replay ---
        log('INFO', f"Gửi tcpreplay API (PPS={pps}) và chờ {MAX_TIME}s ...")
        call_tcpreplay_api(api_url, log_file_lanforge, pps)
        time.sleep(MAX_TIME)

        # # --- Step 3: stop measurement ---
        # if measure_proc.poll() is None:
        #     log('INFO', "Dừng tiến trình đo throughput/latency ...")
        #     measure_proc.send_signal(signal.SIGINT)
        #     try:
        #         stdout, stderr = measure_proc.communicate(timeout=5)
        #         if stdout.strip():
        #             log('INFO', f"Kết quả đo:\n{stdout.strip()}")
        #         if stderr.strip():
        #             log('WARN', f"Lỗi đo:\n{stderr.strip()}")
        #     except subprocess.TimeoutExpired:
        #         measure_proc.kill()
        #         log('ERROR', "Tiến trình đo không phản hồi, bị kill()")
        
        log('INFO', f"Completed PPS={pps}, Run={run_idx}")
        g_log_file.write(f"=== DONE PPS={pps}, RUN={run_idx}, TIME={time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
        # g_log_file.close()
        time.sleep(3)

log('HEADER', "=== All tests completed ===")
g_system_log.close()
