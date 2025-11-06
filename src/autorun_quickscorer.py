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
BASE_DIR = "/home/dongtv/dtuan/autorun"
LOG_SYSTEM_PATH = os.path.join(BASE_DIR, "autorun1.log")
BPF_DIR = os.path.join(BASE_DIR, "results_bpf2")
LANFORCE_DIR = os.path.join("/home/lanforge/Desktop/app", "results")
PERF_DIR = os.path.join(BASE_DIR, "results_perf2")
STATS_DIR = os.path.join(BASE_DIR, "results_stats2")
FLAMEGRAPH_SCRIPT = "/home/dongtv/FlameGraph/run_perf.sh"
XDP_PROG_DIR = os.path.expanduser("/home/dongtv/dtuan/xdp-program")

XDP_PROG_DIR1 = os.path.expanduser("/home/dongtv/dtuan/xdp-program/xdp_prog")
RF2QS_PATH = os.path.join(XDP_PROG_DIR1, "rf2qs.py")

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
os.makedirs(STATS_DIR, exist_ok=True)

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

# --- Get loaded XDP program ID ---
def get_prog_id():
    log('DEBUG', "Getting XDP program ID for 'xdp_anomaly_detector'...")
    try:
        bpftool_out = subprocess.check_output(["sudo", "bpftool", "prog", "show"], text=True)
    except subprocess.CalledProcessError as e:
        log('ERROR', f"Failed to run bpftool: {e}")
        raise RuntimeError("bpftool failed.")
    match = re.search(r'^(\d+):\s+(ext)\s+name\s+xdp_anomaly_detector', bpftool_out, re.MULTILINE)
    if not match:
        log('ERROR', "No XDP program named 'xdp_anomaly_detector' found!")
        raise RuntimeError("No XDP program found!")
    prog_id = match.group(1)
    log('INFO', f"Found xdp_anomaly_detector ID: {prog_id}")
    return prog_id

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

# --- Run BPF profiling ---
def run_bpftool_profiling(prog_id, log_file_path, duration):
    log('DEBUG', f"Starting bpftool profiling ({duration}s)...", to_file=False)
    with open(log_file_path, "a", buffering=1) as f:
        proc = subprocess.Popen(
            ["sudo", "bpftool", "prog", "profile", "id", prog_id,
             "l1d_loads", "llc_misses", "itlb_misses", "dtlb_misses"],
            stdout=f, stderr=subprocess.STDOUT, preexec_fn=os.setsid
        )
        log('INFO', f"[BPF] Profiling started (PID={proc.pid})", to_file=False)
        time.sleep(duration)
        if proc.poll() is None:
            log('DEBUG', f"[BPF] Sending SIGINT to stop profiling...", to_file=False)
            os.killpg(proc.pid, signal.SIGINT)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log('WARN', "[BPF] Forcing SIGKILL...", to_file=False)
                os.killpg(proc.pid, signal.SIGKILL)
        log('INFO', "[BPF] Profiling completed.", to_file=False)

# --- Run PERF profiling ---
def run_perf_profiling(svg_file, log_file_path, duration):
    log('DEBUG', f"Starting perf ({duration}s)...", to_file=False)
    with open(log_file_path, "a", buffering=1) as f:
        proc = subprocess.Popen(
            ["sudo", FLAMEGRAPH_SCRIPT, svg_file, str(duration)],
            stdout=f, stderr=subprocess.STDOUT, preexec_fn=os.setsid
        )
        log('INFO', f"[PERF] Started (PID={proc.pid})", to_file=False)
        proc.wait()
        log('INFO', "[PERF] Completed.", to_file=False)

# --- Initial Cleanup ---
unload_xdp()
run_cmd(["sudo", "rm", "-rf", f"/sys/fs/bpf/{iface}"], "Remove old BPF maps", check=False)
run_cmd(["sudo", "pkill", "-9", "bpftool"], "Kill stray bpftool", check=False)
run_cmd(["sudo", "pkill", "-9", "perf"], "Kill stray perf", check=False)

# --- Main loop ---
# model_params = list(range(10, 101, 20)) + [100]
model_params = [10]
model_sizes = [32]

for pps in range(10000, 150001, 10000):
    for run_idx in range(1, NUM_RUNS + 1):
        for m in model_params:
            for sz in model_sizes:
                model_file = os.path.join(os.path.expanduser("/home/dongtv/security_paper/rf"), f"rf_{m}_{sz}_model.pkl")

                log_file_bpf = os.path.join(BPF_DIR, f"log_{branch}_{param}_{pps}_{run_idx}_{m}_{sz}.txt")
                log_file_perf = os.path.join(PERF_DIR, f"log_{branch}_{param}_{pps}_{run_idx}_{m}_{sz}.txt")
                svg_file = f"{branch}_{param}_{pps}_{run_idx}_{m}_{sz}.svg"
                log_file_lanforge = os.path.join(LANFORCE_DIR, f"log_{branch}_{param}_{pps}_{run_idx}_{m}_{sz}.txt")
                log_run_xdp_stats = os.path.join(STATS_DIR, f"log_{branch}_{param}_{pps}_{run_idx}_{m}_{sz}.txt")

                g_log_file = open(log_file_bpf, "a")
                log('HEADER', f"=== PPS={pps}, Run {run_idx}/{NUM_RUNS}, Model rf_{m}_{sz} ===")
                g_log_file.write(f"=== PPS={pps}, RUN={run_idx}, BRANCH={branch}, PARAM={param}, MODEL=rf_{m}_{sz}, TIME={time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")

                #--- Step 1: Run rf2qs.py ---
                os.chdir(XDP_PROG_DIR1)
                log('INFO', f"Đã cd vào {XDP_PROG_DIR1}")
                log('INFO', f"Running python3 {RF2QS_PATH} --model {model_file}")
                run_cmd(["python3", RF2QS_PATH, "--model", model_file], "Run rf2qs.py", check=True)
                
                # --- Step 2: Build XDP program ---
                log('INFO', f"Building XDP program in {XDP_PROG_DIR}")
                run_cmd(["make", "-C", XDP_PROG_DIR], "Build XDP program")
                os.chdir(XDP_PROG_DIR1)
                
                # os.chdir(EBPF_CLASSIFIER)
                # log('INFO', f"Running python3 {EBPF_CLASSIFIER} {iface} {output_folder}")
                # run_cmd(["python3", "nn_filter_xdp.py","{iface}", "{output_folder}", "-S"], "Run scripts", check=True)
                # --- Step 3: Load XDP program ---
                run_cmd([
                    "sudo", "xdp-loader", "load", iface,
                    "-m", "skb",
                    "-n", "xdp_anomaly_detector",
                    "-p", f"/sys/fs/bpf/{iface}",
                    os.path.join(XDP_PROG_DIR1, "xdp_prog_kern.o")
                ], "Load XDP program")

                # --- Step 4: Get prog ID ---
                try:
                    prog_id = get_prog_id()
                except RuntimeError:
                    unload_xdp()
                    g_log_file.close()
                    continue

                # --- Step 5: Trigger tcpreplay API ---
                call_tcpreplay_api(api_url, log_file_lanforge, pps, MAX_TIME+5)

                # --- Step 6: Run profiling in parallel ---
                p_bpf = Process(target=run_bpftool_profiling, args=(prog_id, log_file_bpf, MAX_TIME))
                p_perf = Process(target=run_perf_profiling, args=(svg_file, log_file_perf, MAX_TIME))
                p_bpf.start(); p_perf.start()
                p_bpf.join(); p_perf.join()

                # --- Step 7: Cleanup ---
                unload_xdp()
                run_cmd(["sudo", "rm", "-rf", f"/sys/fs/bpf/{iface}"], "Remove old BPF maps", check=False)
                log('INFO', f"Completed PPS={pps}, Run={run_idx}, Model rf_{m}_{sz}")
                g_log_file.write(f"=== DONE PPS={pps}, RUN={run_idx}, MODEL=rf_{m}_{sz}, TIME={time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
                # g_log_file.close()
                time.sleep(3)

log('HEADER', "=== All tests completed ===")
g_system_log.close()
