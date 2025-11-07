import subprocess
import requests
import os
import time
import signal
from colorama import Fore, Style, init
import argparse
from logger import (
    init_logger, set_run_log, close_run_log, log
)
import yaml

# --- Parse CLI arguments ---
parser = argparse.ArgumentParser(description="Automated XDP profiling runner")
parser.add_argument("--branch", required=True, help="Tên branch (ví dụ: knn_threshold)")
parser.add_argument("--param", required=True, help="Thông số thuật toán (ví dụ: 200)")
parser.add_argument("--config", default="/home/dongtv/dtuan/autorun/config.yml", help="Đường dẫn file config YAML")
parser.add_argument("--max-time", type=int, default=120, help="Thời gian chạy mỗi lần (mặc định: 120s)")
parser.add_argument("--num-runs", type=int, default=5, help="Số lần lặp lại mỗi mức PPS (mặc định: 5)")
args = parser.parse_args()
branch = args.branch
param = args.param
MAX_TIME = args.max_time
NUM_RUNS = args.num_runs

with open(args.config, "r") as f:
    cfg = yaml.safe_load(f)

BASEDIR = cfg["base_dir"]
iface = cfg["iface"]
api_url = cfg["api_url_run"]

XDP_KERN_OBJ = cfg["xdp_program"]["kern_obj"]
XDP_STATS_BIN = cfg["xdp_program"]["stats_bin"]
XDP_DUMP_BIN = cfg["xdp_program"]["dump_bin"]
FLAMEGRAPH_SCRIPT = cfg["flamegraph_script"]
MODEL_RF = cfg["rf_model_dir"]
XDP_LOADER = cfg["xdp_program"]["xdp_loader"]

GROUND_TRUTH = cfg["dataset"]["ground_truth"]
LOG_FILE = os.path.join(BASEDIR, cfg["logging"]["main_log"])
BPF_DIR = os.path.join(BASEDIR, cfg["results"]["bpf"])
PERF_DIR = os.path.join(BASEDIR, cfg["results"]["perf"])
THROUGHPUT_DIR = os.path.join(BASEDIR, cfg["results"]["throughput"])
LANFORGE_DIR = cfg["results"]["lanforge"]
XDP_PROG_DIR = cfg["xdp_prog_dir"]
XDP_PROG_DIR1 = cfg["xdp_prog_dir1"]
THROUGHPUT_SCRIPT = cfg["xdp_program"]["through_scripts"]
# LANFORGE_DIR = cfg["results"]["lanforge"]

# --- Prepare folders ---
os.makedirs(BPF_DIR, exist_ok=True)
os.makedirs(PERF_DIR, exist_ok=True)
os.makedirs(THROUGHPUT_DIR, exist_ok=True)

# --- Init logger ---
LOG_FILE = os.path.join(BASEDIR, cfg["logging"]["main_log"])
init_logger(LOG_FILE)

# --- System-wide log file ---
g_system_log = open(LOG_FILE, "a", buffering=1)
g_log_file = None  # profiling log (per-run)

# --- Run shell command ---
def run_cmd(cmd, desc, check=True):
    log('DEBUG', f"{desc}: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=check, capture_output=True, text=True)
        if result.stdout.strip():
            for line in result.stdout.splitlines():
                log('INFO', f"  {line}", to_file=False)
        if result.stderr.strip():
            for line in result.stderr.splitlines():
                log('WARN', f"  {line}", to_file=False)
        return result
    except subprocess.CalledProcessError as e:
        log('ERROR', f"Command failed ({desc}): {e}")
        log('ERROR', f"STDOUT: {e.stdout.strip()}")
        log('ERROR', f"STDERR: {e.stderr.strip()}")
        if check: raise
        return None

# --- Unload all XDP programs ---
def unload_xdp():
    run_cmd(["sudo", "xdp-loader", "unload", iface, "--all"], "Unload all XDP programs", check=False)
    time.sleep(2)

# --- Call tcpreplay API ---
def call_tcpreplay_api(api_url, log_file, speed, duration):
    payload = {"log": log_file, "speed": speed, "duration": duration}
    log('DEBUG', f"Calling tcpreplay API at {api_url} (duration={duration}s)...")
    try:
        resp = requests.post(api_url, json=payload, timeout=duration + 10)
        if resp.status_code == 200:
            log('INFO', f"API OK -> {resp.json()}")
        else:
            log('WARN', f"API returned {resp.status_code}: {resp.text}")
    except Exception as e:
        log('ERROR', f"Failed to call API: {e}")

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
        if branch == "base":
            log('INFO', f"Gửi tcpreplay API (PPS={pps}) và chờ {MAX_TIME}s ...")
            call_tcpreplay_api(api_url, log_file_lanforge, pps)
            time.sleep(MAX_TIME)
        
        log_file_bpf = os.path.join(BPF_DIR, f"log_{branch}_{param}_{pps}_{run_idx}.txt")
        log_file_lanforge = os.path.join(LANFORGE_DIR, f"log_{branch}_{param}_{pps}_{run_idx}.txt")
        
        g_log_file = open(log_file_bpf, "a")
        log('HEADER', f"=== PPS={pps}, Run {run_idx}/{NUM_RUNS} ===")
        g_log_file.write(f"=== PPS={pps}, RUN={run_idx}, BRANCH={branch}, PARAM={param}, TIME={time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        
        # --- Step 1: start throughput measurement in background ---
        measure_proc = run_throughput_latency(branch, param, pps, run_idx, MAX_TIME + 5)
        time.sleep(2) 
        
        # --- Step 2: start traffic replay ---
        log('INFO', f"Gửi tcpreplay API (PPS={pps}) và chờ {MAX_TIME}s ...")
        call_tcpreplay_api(api_url, log_file_lanforge, pps)
        time.sleep(MAX_TIME)

        # --- Step 3: stop measurement ---
        if measure_proc.poll() is None:
            log('INFO', "Dừng tiến trình đo throughput/latency ...")
            measure_proc.send_signal(signal.SIGINT)
            try:
                stdout, stderr = measure_proc.communicate(timeout=5)
                if stdout.strip():
                    log('INFO', f"Kết quả đo:\n{stdout.strip()}")
                if stderr.strip():
                    log('WARN', f"Lỗi đo:\n{stderr.strip()}")
            except subprocess.TimeoutExpired:
                measure_proc.kill()
                log('ERROR', "Tiến trình đo không phản hồi, bị kill()")
        
        log('INFO', f"Completed PPS={pps}, Run={run_idx}")
        g_log_file.write(f"=== DONE PPS={pps}, RUN={run_idx}, TIME={time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
        time.sleep(3)

log('HEADER', "=== All tests completed ===")
g_system_log.close()
