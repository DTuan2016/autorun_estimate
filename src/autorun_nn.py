#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import re
import requests
import os
import time
import signal
from multiprocessing import Process
import argparse
from logger import init_logger, log
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

FLAMEGRAPH_SCRIPT = cfg["flamegraph_script"]
RESULTS_DIR = cfg["all_results_dir"]
LOG_FILE = os.path.join(BASEDIR, cfg["logging"]["main_log"])
BPF_DIR = os.path.join(RESULTS_DIR, cfg["results"]["bpf"])
PERF_DIR = os.path.join(RESULTS_DIR, cfg["results"]["perf"])
THROUGHPUT_DIR = os.path.join(RESULTS_DIR, cfg["results"]["throughput"])
LANFORGE_DIR = cfg["results"]["lanforge"]
NN_SCRIPTS = cfg["nn_scripts_path"]
OUT_FOLDER_NN = cfg["folder_out_nn"]

# --- Init logger ---
init_logger(LOG_FILE)

# --- Prepare folders ---
for d in [BPF_DIR, PERF_DIR, THROUGHPUT_DIR, OUT_FOLDER_NN]:
    os.makedirs(d, exist_ok=True)

# --- Helper: run shell command ---
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
        if check:
            raise
        return None

# --- Unload all XDP programs ---
def unload_xdp():
    run_cmd(["sudo", "xdp-loader", "unload", iface, "--all"], "Unload all XDP programs", check=False)
    time.sleep(1)

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

# --- Run PERF profiling ---
def run_perf_profiling(svg_file, log_file_path, duration):
    log('DEBUG', f"Starting perf ({duration}s)...")
    with open(log_file_path, "a", buffering=1) as f:
        proc = subprocess.Popen(
            ["bash", FLAMEGRAPH_SCRIPT, svg_file, str(duration), str(1)],
            stdout=f, stderr=subprocess.STDOUT, preexec_fn=os.setsid
        )
        log('INFO', f"[PERF] Started (PID={proc.pid})")
        proc.wait()
        log('INFO', "[PERF] Completed.")

# --- Load XDP and keep running ---
def load_xdp_program(iface, NN_SCRIPTS, OUT_FILE_NN, MAX_TIME):
    cmd = ["sudo", "python3", NN_SCRIPTS, iface, OUT_FILE_NN, "-S"]
    log('DEBUG', f"Start load_xdp_program: {' '.join(cmd)}")

    log_dir = os.path.dirname(OUT_FILE_NN)
    os.makedirs(log_dir, exist_ok=True)

    with open(OUT_FILE_NN, "w", buffering=1) as f:
        proc = subprocess.Popen(
            cmd,
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid
        )

        start_time = time.time()
        while True:
            if proc.poll() is not None:
                log('INFO', f"XDP exited (code={proc.returncode})")
                break
            if time.time() - start_time > MAX_TIME:
                log('ERROR', f"XDP load exceeded {MAX_TIME}s, killing...")
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    log('WARN', "XDP already exited before kill.")
                break
            time.sleep(1)

# --- Initial Cleanup ---
unload_xdp()
run_cmd(["sudo", "rm", "-rf", f"/sys/fs/bpf/{iface}"], "Remove old BPF maps", check=False)
run_cmd(["sudo", "pkill", "-9", "bpftool"], "Kill stray bpftool", check=False)
run_cmd(["sudo", "pkill", "-9", "perf"], "Kill stray perf", check=False)
run_cmd(["sudo", "pkill", "-f", "/home/security/dtuan/ebpf-classifier/nn-filter/nn_filter_xdp.py"], "Kill stray nn_filter_xdp", check=False)
# --- Main loop ---
for pps in range(10000, 150001, 10000):
    for run_idx in range(1, NUM_RUNS + 1):
        log_file_bpf = os.path.join(BPF_DIR, f"log_{branch}_{param}_{pps}_{run_idx}_1_1.txt")
        log_file_perf = os.path.join(PERF_DIR, f"log_{branch}_{param}_{pps}_{run_idx}_1_1.txt")
        log_throughput = os.path.join(THROUGHPUT_DIR, f"{branch}_{param}_{pps}_{run_idx}_1_1.csv")
        svg_file = f"{branch}_{param}_{pps}_{run_idx}_1_1.svg"
        log_file_lanforge = os.path.join(LANFORGE_DIR, f"log_{branch}_{param}_{pps}_{run_idx}_1_1.txt")

        log('HEADER', f"=== PPS={pps}, Run {run_idx}/{NUM_RUNS} ===")

        # --- Start processes ---
        log('DEBUG', "Starting all profiling processes...")
        p_xdp = Process(target=load_xdp_program, args=(iface, NN_SCRIPTS, log_throughput, MAX_TIME))
        p_perf = Process(target=run_perf_profiling, args=(svg_file, log_file_perf, MAX_TIME))
        p_tcpreplay = Process(target=call_tcpreplay_api, args=(api_url, log_file_lanforge, pps, MAX_TIME))

        p_xdp.start()
        time.sleep(8)  # cho XDP load ổn định
        p_perf.start()
        p_tcpreplay.start()
        log('INFO', f"All profiling processes started, waiting {MAX_TIME}s...")

        time.sleep(MAX_TIME)

        # --- Stop everything safely ---
        log('DEBUG', f"Stopping XDP + profiling after {MAX_TIME}s...")
        try:
            if p_xdp.is_alive():
                os.killpg(os.getpgid(p_xdp.pid), signal.SIGKILL)
                log('DEBUG', "Killed XDP process group.")
        except ProcessLookupError:
            log('WARN', "XDP process already gone before killpg().")
        except Exception as e:
            log('ERROR', f"Error stopping XDP: {e}")

        unload_xdp()

        p_perf.join(timeout=5)
        p_tcpreplay.join(timeout=5)
        p_xdp.join(timeout=5)

        run_cmd(["sudo", "rm", "-rf", f"/sys/fs/bpf/{iface}"], "Remove old BPF maps", check=False)
        log('INFO', f"Completed PPS={pps}, Run={run_idx}")
        time.sleep(3)

log('HEADER', "=== All tests completed ===")
