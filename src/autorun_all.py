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
parser.add_argument("--config", default="/home/security/dtuan/autorun_estimate/config_pi.yml", help="Đường dẫn file config YAML")
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
RESULTS_DIR = cfg["all_results_dir"]
BPF_DIR = os.path.join(RESULTS_DIR, cfg["results"]["bpf"])
PERF_DIR = os.path.join(RESULTS_DIR, cfg["results"]["perf"])
LANFORGE_DIR = cfg["results"]["lanforge"]
XDP_PROG_DIR = cfg["xdp_prog_dir"]
XDP_PROG_DIR1 = cfg["xdp_prog_dir1"]
THROUGHPUT_SCRIPT = cfg["xdp_program"]["throughput_script"]
THROUGHPUT_DIR = os.path.join(RESULTS_DIR, cfg["results"]["throughput"])
if branch == "randforest" or "svm":
    PYTHON_SCRIPS = cfg["xdp_program"]["python_RF"]
else:
    PYTHON_SCRIPS = cfg["xdp_program"]["python_quickXDP"]

# --- Init logger ---
init_logger(LOG_FILE)

# --- Prepare folders ---z
os.makedirs(BPF_DIR, exist_ok=True)
os.makedirs(PERF_DIR, exist_ok=True)
os.makedirs(THROUGHPUT_DIR, exist_ok=True)

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

# --- Get loaded XDP program ID ---
def get_prog_id():
    log('DEBUG', "Getting XDP program ID for 'xdp_anomaly_detector'...")
    try:
        bpftool_out = subprocess.check_output(["sudo", "bpftool", "prog", "show"], text=True)
    except subprocess.CalledProcessError as e:
        log('ERROR', f"Failed to run bpftool: {e}")
        raise RuntimeError("bpftool failed.")
    match = re.search(r'^(\d+):\s+(xdp)\s+name\s+xdp_anomaly_detector', bpftool_out, re.MULTILINE)
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
            ["sudo", FLAMEGRAPH_SCRIPT, svg_file, str(duration), "all"],
            stdout=f, stderr=subprocess.STDOUT, preexec_fn=os.setsid
        )
        log('INFO', f"[PERF] Started (PID={proc.pid})", to_file=False)
        proc.wait()
        log('INFO', "[PERF] Completed.", to_file=False)

def run_throughput_latency(branch, param, pps, run_idx, m, sz, duration):
    """
    Đo throughput/latency song song trong thời gian chỉ định.
    Kết quả được ghi vào file CSV theo format {branch}_{param}_{pps}_{run_idx}_{m}_{sz}.csv
    """
    output_csv = os.path.join(THROUGHPUT_DIR, f"{branch}_{param}_{pps}_{run_idx}_{m}_{sz}.csv")
    log_file_path = os.path.join(THROUGHPUT_DIR, f"log_{branch}_{param}_{pps}_{run_idx}_{m}_{sz}.txt")

    cmd = [
        "sudo", "python3", THROUGHPUT_SCRIPT,
        f"/sys/fs/bpf/{iface}/accounting_map",
        output_csv,
        str(duration)
    ]

    log('DEBUG', f"Starting throughput/latency measurement ({duration}s)...", to_file=False)
    log('INFO', f"[THROUGHPUT] Command: {' '.join(cmd)}", to_file=False)
    log('INFO', f"[THROUGHPUT] Output CSV: {output_csv}", to_file=False)

    with open(log_file_path, "a", buffering=1) as f:
        proc = subprocess.Popen(
            cmd,
            stdout=f,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid
        )
        log('INFO', f"[THROUGHPUT] Started (PID={proc.pid})", to_file=False)

        try:
            proc.wait(timeout=duration + 10)
            log('INFO', "[THROUGHPUT] Completed successfully.", to_file=False)
        except subprocess.TimeoutExpired:
            log('WARN', "[THROUGHPUT] Timeout reached, sending SIGINT...", to_file=False)
            os.killpg(proc.pid, signal.SIGINT)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log('WARN', "[THROUGHPUT] Forcing SIGKILL...", to_file=False)
                os.killpg(proc.pid, signal.SIGKILL)
        except Exception as e:
            log('ERROR', f"[THROUGHPUT] Error: {e}", to_file=False)
        finally:
            log('INFO', "[THROUGHPUT] Measurement finished.", to_file=False)

# --- Initial Cleanup ---
unload_xdp()
run_cmd(["sudo", "rm", "-rf", f"/sys/fs/bpf/{iface}"], "Remove old BPF maps", check=False)
run_cmd(["sudo", "pkill", "-9", "bpftool"], "Kill stray bpftool", check=False)
run_cmd(["sudo", "pkill", "-9", "perf"], "Kill stray perf", check=False)

# --- Main loop ---
if branch == "randforest" :
    model_params = [10, 20]
    # model_params = [20]
    model_sizes = [8, 16, 32, 64]
    # model_sizes = [32, 64]
    
elif branch == "quickscore":
    # model_params = [70, 80, 90, 100]
    # model_params = [10, 20, 30, 40, 50, 60]
    # model_sizes = [8, 16, 32, 64]
    # model_sizes = [8, 16, 32]
    model_params = [20]
    model_sizes = [64]
    PYTHON_SCRIPS = cfg["xdp_program"]["python_quickXDP"]
else:
    model_params = [1]
    model_sizes = [1]
    
for pps in range(10000, 150001, 10000):
    for run_idx in range(1, NUM_RUNS + 1):
        for m in model_params:
            for sz in model_sizes:
                model_file = os.path.join(os.path.expanduser(MODEL_RF), f"rf_{m}_{sz}_model.pkl")

                log_file_bpf = os.path.join(BPF_DIR, f"log_{branch}_{param}_{pps}_{run_idx}_{m}_{sz}.txt")
                log_file_perf = os.path.join(PERF_DIR, f"log_{branch}_{param}_{pps}_{run_idx}_{m}_{sz}.txt")
                svg_file = f"{branch}_{param}_{pps}_{run_idx}_{m}_{sz}.svg"
                log_file_lanforge = os.path.join(LANFORGE_DIR, f"log_{branch}_{param}_{pps}_{run_idx}_{m}_{sz}.txt")
                # log_run_xdp_stats = os.path.join(STATS_DIR, f"log_{branch}_{param}_{pps}_{run_idx}_{m}_{sz}.txt")

                g_log_file = open(log_file_bpf, "a")
                log('HEADER', f"=== PPS={pps}, Run {run_idx}/{NUM_RUNS}, Model rf_{m}_{sz} ===")
                g_log_file.write(f"=== PPS={pps}, RUN={run_idx}, BRANCH={branch}, PARAM={param}, MODEL=rf_{m}_{sz}, TIME={time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                if branch == "base":
                    log('INFO', f"Building XDP program in {XDP_PROG_DIR}")
                    run_cmd(["make", "-C", XDP_PROG_DIR], "Build XDP program")
                    os.chdir(XDP_PROG_DIR1)
                    
                    run_cmd([
                        "sudo", XDP_LOADER, "--dev", iface,
                        "-S",
                        "--progname", "xdp_anomaly_detector"
                    ], "Load XDP program")

                    # --- Step 1: Gọi tcpreplay API ---
                    call_tcpreplay_api(api_url, log_file_lanforge, pps, MAX_TIME + 5)
                    # --- Step 2: Chạy perf profiling ---
                    p_through = Process(target=run_throughput_latency, args=(branch, param, pps, run_idx, m, sz, MAX_TIME))
                    p_perf = Process(target=run_perf_profiling, args=(svg_file, log_file_perf, MAX_TIME))
                    p_perf.start(); p_through.start()
                    p_perf.join(); p_through.join()
                    # run_perf_profiling(svg_file, log_file_perf, MAX_TIME)
                    unload_xdp()
                    run_cmd(["sudo", "rm", "-rf", f"/sys/fs/bpf/{iface}"], "Remove old BPF maps", check=False)
                    log('INFO', f"[BASE] Completed PPS={pps}, Run={run_idx}")
                    g_log_file.write(f"=== DONE BASE PPS={pps}, RUN={run_idx}, MODEL=rf_{m}_{sz}, TIME={time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
                    time.sleep(3)
                    continue 

                #--- Step 1: Run rf2qs.py ---
                os.chdir(XDP_PROG_DIR1)
                log('INFO', f"Đã cd vào {XDP_PROG_DIR1}")
                log('INFO', f"Running python3 {PYTHON_SCRIPS} --model {model_file}")
                if branch == "randforest":
                    run_cmd([
                        "python3",
                        PYTHON_SCRIPS,
                        "--max_tree", str(m),
                        "--max_leaves", str(sz),
                        "--iface", iface,
                        "--model_folder", "/home/security/dtuan/security_paper/rf",
                        "--home_folder", "/home/security"
                    ], "Run read_model_to_map.py", check=True)
                    run_cmd(["sudo", "xdp-loader", "unload", "eth0", "--all"], "Unload", check=True)
                elif branch == "quickscore":
                    run_cmd(["python3", PYTHON_SCRIPS, "--model", model_file], "Run rf2qs.py", check=True)
                else:
                    run_cmd(["python3", PYTHON_SCRIPS, "--svm_model", "/home/security/dtuan/security_paper/svm/models/SVM-Linear.pkl", \
                             "--scaler", "/home/security/dtuan/security_paper/svm/scalers/scaler_SVM-Linear.pkl"], "Run read_model_to_map.py", check=True)
                # --- Step 2: Build XDP program ---
                log('INFO', f"Building XDP program in {XDP_PROG_DIR}")
                run_cmd(["make", "-C", XDP_PROG_DIR], "Build XDP program")
                os.chdir(XDP_PROG_DIR1)
                
                run_cmd([
                    "sudo", XDP_LOADER, "--dev", iface,
                    "-S",
                    "--progname", "xdp_anomaly_detector"
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
                p_through = Process(target=run_throughput_latency, args=(branch, param, pps, run_idx, m, sz, MAX_TIME))
                p_bpf = Process(target=run_bpftool_profiling, args=(prog_id, log_file_bpf, MAX_TIME))
                p_perf = Process(target=run_perf_profiling, args=(svg_file, log_file_perf, MAX_TIME))
                p_bpf.start(); p_perf.start(); p_through.start()
                p_bpf.join(); p_perf.join(); p_through.join()

                # --- Step 7: Cleanup ---
                unload_xdp()
                run_cmd(["sudo", "rm", "-rf", f"/sys/fs/bpf/{iface}"], "Remove old BPF maps", check=False)
                log('INFO', f"Completed PPS={pps}, Run={run_idx}, Model rf_{m}_{sz}")
                g_log_file.write(f"=== DONE PPS={pps}, RUN={run_idx}, MODEL=rf_{m}_{sz}, TIME={time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
                # g_log_file.close()
                time.sleep(3)

log('HEADER', "=== All tests completed ===")
g_system_log.close()
