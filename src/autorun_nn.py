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
parser.add_argument("--config", default="../config_pc.yml", help="Đường dẫn file config YAML")
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
POWER_DIR = os.path.join(RESULTS_DIR, cfg["results"]["power"])
THROUGHPUT_DIR = os.path.join(RESULTS_DIR, cfg["results"]["throughput"])
LANFORGE_DIR = cfg["results"]["lanforge"]
NN_SCRIPTS = cfg["nn_scripts_path"]
OUT_FOLDER_NN = cfg["folder_out_nn"]
SERVER_SCRIPT = cfg["xdp_program"]["server_scripts"]

# --- Init logger ---
init_logger(LOG_FILE)

# --- Prepare folders ---
for d in [BPF_DIR, PERF_DIR, THROUGHPUT_DIR, OUT_FOLDER_NN, POWER_DIR]:
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

def read_proc_stat():
    stats = {}
    
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu"):
                parts = line.split()
                cpu = parts[0]
                values = list(map(int, parts[1:]))
                total = sum(values)
                idle = values[3] + values[4]
                stats[cpu] = (total, idle)
    return stats

def read_energy_uj():
    path = "/sys/class/powercap/intel-rapl:0/energy_uj"
    try:
        with open(path) as f:
            return int(f.read().strip())
    except:
        return None
    
def monitor_cpu_power(csv_path, duration, interval=1.0):
    with open(csv_path, "w", buffering=1) as f:
        f.write("timestamp,cpu,cpu0,cpu1,cpu2,cpu3,power_w\n")
        
        t_start = time.time()
        prev_stat = read_proc_stat()
        prev_energy = read_energy_uj()
        prev_time = time.time()
        
        while time.time() - t_start < duration:
            time.sleep(interval)
            
            now_stat = read_proc_stat()
            now_energy = read_energy_uj()
            now_time = time.time()
            
            row = [f"{now_time:.3f}"]
            
            for cpu in ["cpu", "cpu0", "cpu1", "cpu2", "cpu3"]:
                if cpu in prev_stat and cpu in now_stat:
                    t1, i1 = prev_stat[cpu]
                    t2, i2 = now_stat[cpu]
                    dt = t2 - t1
                    di = i2 - i1
                    usage = 100 * (1 - di / dt) if dt > 0 else 0.0
                    
                else:
                    usage = 0.0
                    
                row.append(f"{usage:.2f}")
            
            if prev_energy is not None and now_energy is not None:
                power = (now_energy - prev_energy) / 1e6 / (now_time - prev_time)
            else:
                power = 0.0

            row.append(f"{power:.3f}")
            f.write(",".join(row) + "\n")

            prev_stat = now_stat
            prev_energy = now_energy
            prev_time = now_time

# --- Run PERF profiling ---
def run_perf_profiling(svg_file, log_file_path, duration, core_id):
    log('DEBUG', f"Starting perf ({duration}s)...", to_file=False)
    with open(log_file_path, "a", buffering=1) as f:
        proc = subprocess.Popen(
            ["sudo", FLAMEGRAPH_SCRIPT, svg_file, str(duration), str(core_id)],
            stdout=f, stderr=subprocess.STDOUT, preexec_fn=os.setsid
        )
        log('INFO', f"[PERF] Started (PID={proc.pid})", to_file=False)
        proc.wait()
        log('INFO', "[PERF] Completed.", to_file=False)

# --- Run POWER server (FIXED: Added sudo and check return code) ---
def run_power_server(csv_path, log_file_path, duration):
    log('DEBUG', f"Starting server for {duration}s...", to_file=False)
    with open(log_file_path, "a", buffering=1) as f:
        proc = subprocess.Popen(
            # FIX: Thêm "sudo" để đảm bảo quyền truy cập cảm biến
            ["sudo", "python3", SERVER_SCRIPT, "--csv", csv_path],
            stdout=f, stderr=subprocess.STDOUT, preexec_fn=os.setsid
        )
        log('INFO', f"[POWER] Started (PID={proc.pid})", to_file=False)
        try:
            proc.wait(timeout=duration)  # đợi đúng duration
        except subprocess.TimeoutExpired:
            log('DEBUG', "[POWER] Timeout reached, sending SIGINT...", to_file=False)
            os.killpg(proc.pid, signal.SIGINT)  # gửi SIGINT cho process group
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log('WARN', "[POWER] Forcing SIGKILL...", to_file=False)
                os.killpg(proc.pid, signal.SIGKILL)
        
        # FIX: Kiểm tra mã thoát
        if proc.returncode is not None and proc.returncode != 0:
             log('ERROR', f"[POWER] Completed with non-zero exit code: {proc.returncode}. Check {log_file_path} for errors.", to_file=False)
        else:
            log('INFO', "[POWER] Completed.", to_file=False)
            
def stop_remote_traffic(api_url):
    stop_url = api_url.replace("/run", "/stop")
    log('DEBUG', f"Stopping remote traffic via {stop_url}")
    try:
        resp = requests.post(stop_url, timeout=5)

        if resp.status_code != 200:
            log('WARN', f"Stop traffic HTTP {resp.status_code}: {resp.text}")
            return

        # Try JSON, fallback to text
        try:
            data = resp.json()
            log('INFO', f"Stop traffic OK: {data}")
        except ValueError:
            log('INFO', f"Stop traffic OK (non-JSON response): {resp.text.strip()}")

    except Exception as e:
        log('WARN', f"Failed to stop remote traffic: {e}")
        
        
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
run_cmd(["sudo", "pkill", "-f", "../ebpf-classifier/nn-filter/nn_filter_xdp.py"], "Kill stray nn_filter_xdp", check=False)
run_cmd(["sudo", "pkill", "-f", "../../server.py"], "Kill stray nn_filter_xdp", check=False)
# --- Main loop ---
for pps in range(10000, 200001, 10000):
    for run_idx in range(1, NUM_RUNS + 1):
        log_file_bpf = os.path.join(BPF_DIR, f"log_{branch}_{param}_{pps}_{run_idx}_1_1.txt")
        log_file_perf = os.path.join(PERF_DIR, f"log_{branch}_{param}_{pps}_{run_idx}_1_1.txt")
        log_throughput = os.path.join(THROUGHPUT_DIR, f"{branch}_{param}_{pps}_{run_idx}_1_1.csv")
        log_power = os.path.join(POWER_DIR, f"{branch}_{param}_{pps}_{run_idx}_1_1.txt")
        csv_file_power = os.path.join(POWER_DIR, f"{branch}_{param}_{pps}_{run_idx}_1_1.csv")
        power_cpu_csv = os.path.join(POWER_DIR, f"cpu_power_{branch}_{param}_{pps}_{run_idx}.csv")
        log_file_lanforge = os.path.join(LANFORGE_DIR, f"log_{branch}_{param}_{pps}_{run_idx}_1_1.txt")

        log('HEADER', f"=== PPS={pps}, Run {run_idx}/{NUM_RUNS} ===")

        # --- Start processes ---
        log('DEBUG', "Starting all profiling processes...")
        log('INFO', "Load XDP program into interface")
        p_xdp = Process(target=load_xdp_program, args=(iface, NN_SCRIPTS, log_throughput, MAX_TIME))
        #p_xdp.start()
        log('INFO', "Call API to STOP all tcpreplay running in APP")
        stop_remote_traffic(api_url)
        log('INFO', "WAITING 30s......")
        time.sleep(60)
        processes = []
        p_tcpreplay = Process(target=call_tcpreplay_api, args=(api_url, log_file_lanforge, pps, MAX_TIME))
        p_power = Process(target=run_power_server, args=(csv_file_power, log_power, MAX_TIME))
        p_cpu_power = Process(target=monitor_cpu_power, args=(power_cpu_csv, MAX_TIME))
        # p_through = Process(target=run_throughput_latency, args=(branch, param, pps, run_idx, m, sz, MAX_TIME))
        processes.append(p_power)
        processes.append(p_cpu_power)
        # processes.append(p_through)
        for core_id in range(4):
            svg_file_cores = f"{branch}_{param}_{pps}_{run_idx}_{core_id}"
            p_perf = Process(
                target=run_perf_profiling,
                args=(svg_file_cores, log_file_perf, MAX_TIME, core_id)
            )
            processes.append(p_perf)
        p_xdp.start()
        time.sleep(5)
        p_tcpreplay.start()
        log('INFO', f"All profiling processes started, waiting {MAX_TIME}s...")          
        for p in processes:
            p.start()

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

        # p_perf0.join(); p_perf1.join(); p_perf2.join(); p_perf3.join(); p_power.join()
        for p in processes:
            p.join()     
        p_tcpreplay.join(timeout=5)
        p_xdp.join(timeout=5)

        run_cmd(["sudo", "rm", "-rf", f"/sys/fs/bpf/{iface}"], "Remove old BPF maps", check=False)
        log('INFO', f"Completed PPS={pps}, Run={run_idx}")
        time.sleep(3)

log('HEADER', "=== All tests completed ===")
