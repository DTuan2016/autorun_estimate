import os
import re
import csv
from datetime import datetime

# Folder chứa các file txt
folder_path = "/home/dongtv/dtuan/autorun/results_bpf1"
output_csv = "data_all.csv"

# Regex patterns
load_pattern = re.compile(r"\[(.*?)\] \[DEBUG\] Load XDP program")
unload_pattern = re.compile(r"\[(.*?)\] \[DEBUG\] Unload all XDP programs")
run_cnt_pattern = re.compile(r"^\s*(\d+)\s+run_cnt", re.MULTILINE)
metric_pattern = re.compile(r"^\s*(\d+)\s+(\w+)\s*\(([\d.]+)%\)", re.MULTILINE)

# Lấy danh sách file txt
txt_files = [f for f in os.listdir(folder_path) if f.endswith(".txt")]

data_rows = []

for txt_file in txt_files:
    file_path = os.path.join(folder_path, txt_file)
    with open(file_path, "r") as f:
        content = f.read()

    # Lấy tất cả thời gian load/unload, chỉ giữ cuối cùng
    load_matches = load_pattern.findall(content)
    unload_matches = unload_pattern.findall(content)

    if not load_matches or not unload_matches:
        continue  # bỏ qua file không đúng format

    load_time = datetime.strptime(load_matches[-1], "%Y-%m-%d %H:%M:%S")
    unload_time = datetime.strptime(unload_matches[-1], "%Y-%m-%d %H:%M:%S")
    duration_ns = (unload_time - load_time).total_seconds() * 1e9  # đổi ra ns

    # Lấy run_cnt cuối cùng
    run_cnt_matches = run_cnt_pattern.findall(content)
    run_cnt = int(run_cnt_matches[-1]) if run_cnt_matches else None

    # Lấy metrics cuối cùng
    metrics = {"l1d_loads": (None, None), "llc_misses": (None, None),
               "itlb_misses": (None, None), "dtlb_misses": (None, None)}

    for m in metric_pattern.finditer(content):
        value = int(m.group(1))
        name = m.group(2)
        percent = float(m.group(3))
        if name in metrics:
            metrics[name] = (value, percent)  # tự động ghi đè -> cuối cùng giữ giá trị cuối

    # Tính run_cnt / duration_ns
    time_per_run_ns = duration_ns / run_cnt if run_cnt and duration_ns else None

    row = {
        "file": txt_file,
        "load_time": load_time,
        "unload_time": unload_time,
        "run_cnt": run_cnt,
        "time_per_run_ns": time_per_run_ns,
    }

    for k in metrics:
        row[f"{k}_value"] = metrics[k][0]
        row[f"{k}_percent"] = metrics[k][1]

    data_rows.append(row)

# Ghi CSV
fieldnames = ["file", "load_time", "unload_time", "run_cnt", "time_per_run_ns",
              "l1d_loads_value", "l1d_loads_percent",
              "llc_misses_value", "llc_misses_percent",
              "itlb_misses_value", "itlb_misses_percent",
              "dtlb_misses_value", "dtlb_misses_percent"]

with open(output_csv, "w", newline="") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    for row in data_rows:
        writer.writerow(row)

print(f"Done! CSV saved to {output_csv}")
