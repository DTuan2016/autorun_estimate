#!/usr/bin/env python3
import subprocess
import requests
import os
import time
import signal
from colorama import Fore, Style, init
from multiprocessing import Process, Manager
import argparse
import yaml
from logger import (
    init_logger, set_run_log, close_run_log, log
)
# --- Parse CLI arguments ---
parser = argparse.ArgumentParser(description="Automated XDP profiling runner")
parser.add_argument("--branch", required=True, help="Tên nhánh (ví dụ: knn_threshold)")
parser.add_argument("--param", required=True, help="Tham số (ví dụ: 200)")
parser.add_argument("--config", default="/home/dongtv/dtuan/autorun/config.yaml", help="Đường dẫn file config YAML")
parser.add_argument("--num-runs", type=int, default=5, help="Số lần lặp lại (mặc định: 5)")
parser.add_argument("--iface", default="eno3", help="Tên interface (mặc định: eno3)")
parser.add_argument("--api-url", default="http://192.168.101.238:20168/run_acc", help="URL API để replay traffic")
args = parser.parse_args()

branch = args.branch
param = args.param
NUM_RUNS = args.num_runs
iface = args.iface
api_url = args.api_url

# --- Load config file ---
with open(args.config, "r") as f:
    cfg = yaml.safe_load(f)

BASEDIR = cfg["base_dir"]
iface = cfg["iface"]

XDP_KERN_OBJ = cfg["xdp_program"]["kern_obj"]
XDP_STATS_BIN = cfg["xdp_program"]["stats_bin"]
XDP_DUMP_BIN = cfg["xdp_program"]["dump_bin"]

GROUND_TRUTH = cfg["dataset"]["ground_truth"]
ACC_DIR = os.path.join(BASEDIR, cfg["dataset"]["output_dir_acc"])
LOG_FILE = os.path.join(BASEDIR, cfg["logging"]["main_log"])

# --- Init logger ---
init_logger(LOG_FILE)

# --- Logging setup ---
g_system_log = open(LOG_FILE, "a", buffering=1)
g_log_file = None

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
        if check:
            raise
        return None

# --- Unload all XDP programs ---
def unload_xdp():
    run_cmd(["sudo", "xdp-loader", "unload", iface, "--all"], "Unload all XDP programs", check=False)
    time.sleep(2)

# --- Run xdp_stats (until stop signal) ---
def run_xdp_stats(log_file_path, iface, stop_flag):
    log('DEBUG', f"Starting xdp_stats on {iface} (wait until API done)...", to_file=False)
    cmd = ["sudo", XDP_STATS_BIN, "--dev", iface, "--load-csv"]
    with open(log_file_path, "a", buffering=1) as f:
        proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        log('INFO', f"[XDP_STATS] Started (PID={proc.pid})", to_file=False)
        try:
            # Poll every 1s, stop when API done
            while not stop_flag["done"]:
                time.sleep(1)
        finally:
            if proc.poll() is None:
                log('DEBUG', "[XDP_STATS] Stopping after API completed...", to_file=False)
                os.killpg(proc.pid, signal.SIGINT)
                time.sleep(1)
                if proc.poll() is None:
                    log('WARN', "[XDP_STATS] Forcing kill...", to_file=False)
                    os.killpg(proc.pid, signal.SIGKILL)
            log('INFO', "[XDP_STATS] Finished.", to_file=False)

# --- Call tcpreplay API (blocking) ---
def call_tcpreplay_api(api_url):
    print(f"[INFO] Gọi tcpreplay API {api_url} ...")
    resp = requests.post(f"{api_url}", timeout=None)  # chờ đến khi xong
    if resp.status_code == 200:
        print("[INFO] tcpreplay hoàn tất, kết quả:")
        print(resp.json())
    else:
        print(f"[ERROR] API trả mã lỗi {resp.status_code}: {resp.text}")

    print("[INFO] Tiếp tục thực hiện phần tính toán...")

def evaluate_results(file_pred, file_true, output_csv):
    """
    So sánh flows.csv do XDP sinh ra với file ground truth,
    tính Accuracy / Precision / Recall / F1-score,
    và ghi kết quả vào CSV (append, không ghi header nếu đã tồn tại).
    """
    import pandas as pd
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    from datetime import datetime
    import os

    # --- Đọc file ---
    if not os.path.exists(file_pred):
        log("ERROR", f"File dự đoán không tồn tại: {file_pred}")
        return
    if not os.path.exists(file_true):
        log("ERROR", f"File ground truth không tồn tại: {file_true}")
        return

    predict = pd.read_csv(file_pred)
    ground = pd.read_csv(file_true)

    if "Label" not in predict.columns:
        log("ERROR", f"File {file_pred} thiếu cột Label")
        return
    if "Label" not in ground.columns:
        log("ERROR", f"File {file_true} thiếu cột Label")
        return

    # --- Chuẩn hóa label ground truth ---
    ground["Label_true"] = ground["Label"].apply(lambda x: 1 if str(x).upper() == "BENIGN" else 0)

    # --- Ghép 2 file theo khóa flow ---
    flow_keys = ["SrcIP", "SrcPort", "DstIP", "DstPort", "Proto"]
    merged = pd.merge(
        predict[flow_keys + ["Label"]],
        ground[flow_keys + ["Label_true"]],
        on=flow_keys,
        how="inner"
    )

    if merged.empty:
        log("WARN", "Không có flow nào trùng khớp giữa hai file!")
        return

    # --- Lấy nhãn ---
    y_true = merged["Label_true"]
    y_pred = merged["Label"]

    # --- Tính metric ---
    acc  = accuracy_score(y_true, y_pred)
    prec = precision_score(y_true, y_pred, zero_division=0)
    rec  = recall_score(y_true, y_pred, zero_division=0)
    f1   = f1_score(y_true, y_pred, zero_division=0)

    # --- In ra log ---
    log("INFO", f"[EVAL] Matched flows: {len(merged)}")
    log("INFO", f"[EVAL] Accuracy : {acc:.4f}")
    log("INFO", f"[EVAL] Precision: {prec:.4f}")
    log("INFO", f"[EVAL] Recall   : {rec:.4f}")
    log("INFO", f"[EVAL] F1-score : {f1:.4f}")

    # --- Chuẩn bị kết quả ---
    result = pd.DataFrame([{
        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Matched_Flows": len(merged),
        "Accuracy": acc,
        "Precision": prec,
        "Recall": rec,
        "F1_Score": f1
    }])

    # --- Ghi ra file ---
    write_header = not os.path.exists(output_csv)
    result.to_csv(output_csv, mode="a", index=False, header=write_header)

    log("INFO", f"[EVAL] Kết quả được ghi vào: {output_csv}")

# --- Main execution ---
for run_idx in range(1, NUM_RUNS + 1):
    csv_out = os.path.join(ACC_DIR, f"{branch}_{param}_{run_idx}.csv")
    log_file_bpf = os.path.join(ACC_DIR, f"{branch}_{param}_{run_idx}.log")

    # mở file log riêng cho run này
    # global g_log_file
    g_log_file = open(log_file_bpf, "a", buffering=1)
    log('HEADER', f"=== RUN {run_idx}/{NUM_RUNS} ({branch}, param={param}) ===")
    try:
        # Load XDP
        run_cmd([
            "sudo", "xdp-loader", "load", iface,
            "-m", "skb",
            "-n", "xdp_anomaly_detector",
            "-p", f"/sys/fs/bpf/{iface}",
            XDP_KERN_OBJ
        ], "Load XDP program")

        # Shared flag giữa process
        from multiprocessing import Manager
        with Manager() as manager:
            stop_flag = manager.dict()
            stop_flag["done"] = False

            # Start xdp_stats song song
            p_xdp_stats = Process(target=run_xdp_stats, args=(log_file_bpf, iface, stop_flag))
            p_xdp_stats.start()

            # Start API call (blocking bên trong)
            p_api = Process(target=call_tcpreplay_api, args=(api_url,))
            p_api.start()

            # Chờ API hoàn tất
            p_api.join()

            # Khi API kết thúc, báo xdp_stats dừng
            stop_flag["done"] = True
            p_xdp_stats.join()

        # Dump map to CSV
        log('INFO', f"Dumping map to CSV -> {csv_out}")
        run_cmd(["sudo", XDP_DUMP_BIN, iface, "nodes.csv", csv_out],
                "Dump XDP map to CSV", check=False)

        # Evaluate results
        evaluate_results(
            file_pred=csv_out,
            file_true=GROUND_TRUTH,
            output_csv=os.path.join(ACC_DIR, "evaluation_results.csv")
        )

        # Cleanup
        unload_xdp()
        run_cmd(["sudo", "rm", "-rf", f"/sys/fs/bpf/{iface}"],
                "Remove old BPF maps", check=False)

        log('INFO', f"Completed run {run_idx}/{NUM_RUNS}")
        g_log_file.write(f"=== DONE RUN={run_idx}, TIME={time.strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")

    finally:
        g_log_file.close()