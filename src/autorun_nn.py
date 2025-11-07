import subprocess
import re
import requests
import os
import time
import signal
from multiprocessing import Process
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

FLAMEGRAPH_SCRIPT = cfg["flamegraph_script"]

LOG_FILE = os.path.join(BASEDIR, cfg["logging"]["main_log"])
BPF_DIR = os.path.join(BASEDIR, cfg["results"]["bpf"])
PERF_DIR = os.path.join(BASEDIR, cfg["results"]["perf"])
LANFORGE_DIR = cfg["results"]["lanforge"]
NN_SCRIPTS = cfg["nn_scripts_path"]
OUT_FOLDER_NN = cfg["folder_out_nn"]

# --- Init logger ---
init_logger(LOG_FILE)

# --- Prepare folders ---
os.makedirs(BPF_DIR, exist_ok=True)
os.makedirs(PERF_DIR, exist_ok=True)

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

def get_prog_id():
    log('DEBUG', "Getting XDP program ID for 'nn_xdp_drop_packet'...")
    try:
        bpftool_out = subprocess.check_output(["sudo", "bpftool", "prog", "show"], text=True)
    except subprocess.CalledProcessError as e:
        log('ERROR', f"Failed to run bpftool: {e}")
        raise RuntimeError("bpftool failed.")

    # Tìm tất cả các ID chương trình có tên nn_xdp_drop_packet
    matches = re.findall(r'^(\d+):\s+\w+\s+name\s+nn_xdp_drop_packet', bpftool_out, re.MULTILINE)

    if not matches:
        log('ERROR', "No XDP program named 'nn_xdp_drop_packet' found!")
        raise RuntimeError("No XDP program found!")

    # Lấy ID cuối cùng (chương trình mới nhất)
    prog_id = matches[-1]

    log('INFO', f"Found latest nn_xdp_drop_packet ID: {prog_id}")
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
            ["bash", FLAMEGRAPH_SCRIPT, svg_file, str(duration)],
            stdout=f, stderr=subprocess.STDOUT, preexec_fn=os.setsid
        )
        log('INFO', f"[PERF] Started (PID={proc.pid})", to_file=False)
        proc.wait()
        log('INFO', "[PERF] Completed.", to_file=False) 

def load_xdp_program(iface, NN_SCRIPTS, OUT_FOLDER_NN, MAX_TIME):
    cmd = ["sudo", "python3", NN_SCRIPTS, iface, OUT_FOLDER_NN, "-S"]
    log('DEBUG', f"Start load_xdp_program: {' '.join(cmd)}")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=os.setsid)
    start_time = time.time()

    while True:
        if proc.poll() is not None:
            log('INFO', f"XDP program loaded successfully (exit={proc.returncode})")
            return proc.returncode
        if time.time() - start_time > MAX_TIME:
            log('ERROR', f"Load XDP exceeded {MAX_TIME}s, killing...")
            os.killpg(proc.pid, signal.SIGKILL)
            return -1
        time.sleep(1)

# --- Initial Cleanup ---
unload_xdp()
run_cmd(["sudo", "rm", "-rf", f"/sys/fs/bpf/{iface}"], "Remove old BPF maps", check=False)
run_cmd(["sudo", "pkill", "-9", "bpftool"], "Kill stray bpftool", check=False)
run_cmd(["sudo", "pkill", "-9", "perf"], "Kill stray perf", check=False)

# --- Main loop ---
for pps in range(10000, 150001, 10000):
    for run_idx in range(1, NUM_RUNS + 1):
        log_file_bpf = os.path.join(BPF_DIR, f"log_{branch}_{param}_{pps}_{run_idx}.txt")
        log_file_perf = os.path.join(PERF_DIR, f"log_{branch}_{param}_{pps}_{run_idx}.txt")
        svg_file = f"{branch}_{param}_{pps}_{run_idx}.svg"
        log_file_lanforge = os.path.join(LANFORGE_DIR, f"log_{branch}_{param}_{pps}_{run_idx}.txt")
        
        g_log_file = open(log_file_bpf, "a")
        log('HEADER', f"=== PPS={pps}, Run {run_idx}/{NUM_RUNS} ===")
        g_log_file.write(f"=== PPS={pps}, RUN={run_idx}, BRANCH={branch}, PARAM={param}, TIME={time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")

        # --- Start XDP loader in background ---
        log('DEBUG', f"Starting XDP loader in background...")
        p_xdp = subprocess.Popen(
            ["sudo", "python3", NN_SCRIPTS, iface, OUT_FOLDER_NN, "-S"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=os.setsid
        )
        time.sleep(10)  # cho chương trình load ổn định (5s)

        try:
            prog_id = get_prog_id()
        except RuntimeError:
            log('ERROR', "XDP not loaded properly!")
            os.killpg(p_xdp.pid, signal.SIGKILL)
            unload_xdp()
            continue

        # --- Start tcpreplay + profiling in parallel ---
        p_bpf = Process(target=run_bpftool_profiling, args=(prog_id, log_file_bpf, MAX_TIME))
        p_perf = Process(target=run_perf_profiling, args=(svg_file, log_file_perf, MAX_TIME))
        p_tcpreplay = Process(target=call_tcpreplay_api, args=(api_url, log_file_lanforge, pps, MAX_TIME))

        p_bpf.start()
        p_perf.start()
        p_tcpreplay.start()

        log('INFO', f"All profiling processes started, waiting {MAX_TIME}s...")

        time.sleep(MAX_TIME)  # cho phép chúng chạy đồng thời

        # --- Stop everything ---
        log('DEBUG', f"Stopping XDP + profiling after {MAX_TIME}s...")
        os.killpg(p_xdp.pid, signal.SIGKILL)
        unload_xdp()

        p_bpf.join()
        p_perf.join()
        p_tcpreplay.join()

        run_cmd(["sudo", "rm", "-rf", f"/sys/fs/bpf/{iface}"], "Remove old BPF maps", check=False)
        log('INFO', f"Completed PPS={pps}, Run={run_idx}")
        g_log_file.write(f"=== DONE PPS={pps}, RUN={run_idx}, TIME={time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
        g_log_file.close()
        time.sleep(3)
log('HEADER', "=== All tests completed ===")
g_system_log.close()
