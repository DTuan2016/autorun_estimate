import argparse
import csv
import glob
import math
import os
import re
import statistics
from collections import defaultdict
from typing import Dict, List, Tuple

import numpy as np
from scipy.stats import gaussian_kde
import matplotlib.pyplot as plt


FILENAME_REGEX = re.compile(
    r"^([A-Za-z0-9]+)_([A-Za-z0-9]+)_([0-9]+)_([0-9]+)_([0-9]+)_([0-9]+)\.csv$"
)

BRANCH_MARKERS = {
    "base": "o",
    "quickscore": "x",
    "randforest": "s",
    "svm": "^",
    "nn": "*",
}

def pretty_label(branch, param, max_tree, max_leaves):
    if branch == "base":
        return "BASE"
    if branch == "quickscore":
        return f"QuickXDP[{max_tree}][{max_leaves}]"
    if branch == "randforest":
        return f"RF[{max_tree}][{max_leaves}]"
    if branch == "svm":
        return "SVM"
    if branch == "nn":
        return f"NN[16][16]"
    return f"{branch}_{param}_{max_tree}_{max_leaves}"

def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None

# ================================================================
#             PIPELINE 1 — THROUGHPUT / PPS / LATENCY
# ================================================================
def read_csv_metrics_throughput(filename):
    """
    Đọc throughput / pps / latency
    Bỏ 15 dòng sau header.
    """
    throughputs, pps_list, latencies = [], [], []

    with open(filename, newline='') as f:
        reader = csv.DictReader(f)

        # Skip 15 rows
        for _ in range(15):
            next(reader, None)

        for row in reader:

            # Throughput
            if "throughput_Bps" in row:
                thr = safe_float(row["throughput_Bps"])
            elif "Throughput_Mbps" in row:
                thr = safe_float(row["Throughput_Mbps"])
                thr = thr * 1_000_000 / 8 if thr is not None else None
            else:
                continue

            # PPS
            pps = safe_float(row.get("pps") or row.get("PPS"))
            if pps is None:
                continue

            # Latency
            lat = safe_float(row.get("latency_ns") or row.get("Avg_Latency_ns"))
            if lat is None:
                continue

            throughputs.append(thr)
            pps_list.append(pps)
            latencies.append(lat)

    return throughputs, pps_list, latencies

def aggregate_throughput(csv_dir):
    """
    Đọc tất cả file → summary_rows cho throughput/pps/latency.
    """
    files = glob.glob(os.path.join(csv_dir, "*.csv"))
    summary_rows = []

    for path in files:
        fname = os.path.basename(path)
        m = FILENAME_REGEX.match(fname)
        if not m:
            continue

        branch, param, pps, solan, max_tree, max_leaves = m.groups()
        thr_list, pps_list_full, lat_list = read_csv_metrics_throughput(path)

        if not thr_list:
            continue

        summary_rows.append({
            "branch": branch,
            "param": param,
            "pps": int(pps),
            "solan": int(solan),
            "max_tree": int(max_tree),
            "max_leaves": int(max_leaves),

            "thr_list": thr_list,
            "pps_list_full": pps_list_full,
            "lat_list": lat_list,

            "throughput_avg": statistics.mean(thr_list),
            "pps_avg": statistics.mean(pps_list_full),
            "latency_avg": statistics.mean(lat_list),

            "throughput_std": statistics.stdev(thr_list) if len(thr_list) > 1 else 0,
            "pps_std": statistics.stdev(pps_list_full) if len(pps_list_full) > 1 else 0,
            "latency_std": statistics.stdev(lat_list) if len(lat_list) > 1 else 0,
        })

    return summary_rows

def plot_throughput(summary_rows, keys, out_thr, out_pps, out_lat):
    branch_markers = BRANCH_MARKERS

    def get_marker(branch):
        return branch_markers.get(branch, '.')

    all_thr = []
    all_pps = []
    all_lat = []

    for key_dict in keys:
        branch = key_dict["branch"]
        param = key_dict["param"]
        max_tree = key_dict["max_tree"]
        max_leaves = key_dict["max_leaves"]

        filtered = [r for r in summary_rows if
                    r["branch"] == branch and
                    r["param"] == param and
                    r["max_tree"] == max_tree and
                    r["max_leaves"] == max_leaves]

        if not filtered:
            print(f"[THROUGHPUT] Missing key {key_dict}")
            continue

        # deduplicate pps
        pps_dict = {}
        for r in filtered:
            if r["pps"] not in pps_dict:
                pps_dict[r["pps"]] = r
            else:
                e = pps_dict[r["pps"]]
                pps_dict[r["pps"]] = {
                    **r,
                    "throughput_avg": (e["throughput_avg"] + r["throughput_avg"]) / 2,
                    "pps_avg": (e["pps_avg"] + r["pps_avg"]) / 2,
                    "latency_avg": (e["latency_avg"] + r["latency_avg"]) / 2,
                }

        rows = sorted(pps_dict.values(), key=lambda x: x["pps"])

        pps_vals = [r["pps"] for r in rows]
        thr_vals = [r["throughput_avg"] for r in rows]
        pps_avg_vals = [r["pps_avg"] for r in rows]
        lat_vals = [r["latency_avg"] for r in rows]

        label = pretty_label(branch, param, max_tree, max_leaves)
        marker = get_marker(branch)

        all_thr.append((pps_vals, thr_vals, label, marker, rows))
        all_pps.append((pps_vals, pps_avg_vals, label, marker, rows))
        all_lat.append((pps_vals, lat_vals, label, marker, rows))

    # ---- Plot Throughput ----
    fig, ax = plt.subplots(figsize=(12, 5))
    for pps_vals, thr_vals, label, marker, rows in all_thr:

        ax.plot(pps_vals, thr_vals, marker=marker, linestyle="--", label=label)

        # CI
        stds = [r["throughput_std"] for r in rows]
        ns = [len(r["thr_list"]) for r in rows]
        ci = [1.96 * s / math.sqrt(n) if n > 1 else 0 for s, n in zip(stds, ns)]
        upper = [m + c for m, c in zip(thr_vals, ci)]
        lower = [m - c for m, c in zip(thr_vals, ci)]

        ax.fill_between(pps_vals, lower, upper, alpha=0.2)

    ax.set_xlabel("pps")
    ax.set_ylabel("Throughput_avg (B/s)")
    ax.grid(True)
    ax.legend()
    plt.tight_layout()
    plt.savefig(out_thr, dpi=300)
    plt.close()

    # ---- Plot PPS ----
    fig, ax = plt.subplots(figsize=(12, 5))
    for pps_vals, pps_avg_vals, label, marker, rows in all_pps:

        ax.plot(pps_vals, pps_avg_vals, marker=marker, linestyle="--", label=label)

        stds = [r["pps_std"] for r in rows]
        ns = [len(r["pps_list_full"]) for r in rows]
        ci = [1.96 * s / math.sqrt(n) if n > 1 else 0 for s, n in zip(stds, ns)]
        upper = [m + c for m, c in zip(pps_avg_vals, ci)]
        lower = [m - c for m, c in zip(pps_avg_vals, ci)]

        ax.fill_between(pps_vals, lower, upper, alpha=0.2)

    ax.set_xlabel("TX pps")
    ax.set_ylabel("RX pps")
    ax.grid(True)
    ax.legend()
    plt.tight_layout()
    plt.savefig(out_pps, dpi=300)
    plt.close()

    # ---- Plot Latency ----
    fig, ax = plt.subplots(figsize=(12, 5))
    for pps_vals, lat_vals, label, marker, rows in all_lat:

        ax.plot(pps_vals, lat_vals, marker=marker, linestyle="--", label=label)

        stds = [r["latency_std"] for r in rows]
        ns = [len(r["lat_list"]) for r in rows]
        ci = [1.96 * s / math.sqrt(n) if n > 1 else 0 for s, n in zip(stds, ns)]
        upper = [m + c for m, c in zip(lat_vals, ci)]
        lower = [m - c for m, c in zip(lat_vals, ci)]

        ax.fill_between(pps_vals, lower, upper, alpha=0.2)

    ax.set_xlabel("TX pps")
    ax.set_ylabel("Latency (ns)")
    ax.grid(True)
    ax.legend()
    plt.tight_layout()
    plt.savefig(out_lat, dpi=300)
    plt.close()

    print(f"[DONE] Saved throughput plots → {out_thr}, {out_pps}, {out_lat}")
    
# ================================================================
#                  PIPELINE 2 — POWER / ENERGY
# ================================================================
def read_csv_metrics_power(filename) -> Tuple[List[float], List[float]]:
    """
    Tự tìm header chứa power_W + energy_kWh
    """
    power_list, energy_list = [], []

    with open(filename, newline="") as f:
        all_lines = f.readlines()

    header_index = None
    for i, line in enumerate(all_lines):
        if "power_W" in line and "energy_kWh" in line:
            header_index = i
            break

    if header_index is None:
        return [], []

    csv_text = "".join([all_lines[header_index]] + all_lines[header_index+1:])
    reader = csv.DictReader(csv_text.splitlines())

    for row in reader:
        p = safe_float(row.get("power_W", "").strip())
        e = safe_float(row.get("energy_kWh", "").strip())

        if p is None or e is None:
            continue

        power_list.append(p)
        energy_list.append(e)

    return power_list, energy_list


def aggregate_power(csv_dir):
    """
    Trả về summary_rows dạng power.
    """
    files = glob.glob(os.path.join(csv_dir, "*.csv"))
    aggregated: Dict[Tuple[str, str, int, int, int], Dict] = {}

    for path in files:
        fname = os.path.basename(path)
        m = FILENAME_REGEX.match(fname)
        if not m:
            continue

        branch, param, pps_s, solan_s, max_tree_s, max_leaves_s = m.groups()
        pps = int(pps_s)
        solan = int(solan_s)
        max_tree = int(max_tree_s)
        max_leaves = int(max_leaves_s)

        p_list, e_list = read_csv_metrics_power(path)
        if not p_list:
            continue

        key = (branch, param, max_tree, max_leaves, pps)
        if key not in aggregated:
            aggregated[key] = {
                "branch": branch,
                "param": param,
                "pps": pps,
                "solan_total": solan,
                "max_tree": max_tree,
                "max_leaves": max_leaves,
                "power_list": p_list.copy(),
                "energy_list": e_list.copy(),
            }
        else:
            aggregated[key]["solan_total"] += solan
            aggregated[key]["power_list"].extend(p_list)
            aggregated[key]["energy_list"].extend(e_list)

    summary_rows = []
    for key, v in aggregated.items():
        p_list = v["power_list"]
        e_list = v["energy_list"]

        summary_rows.append({
            **v,
            "power_avg": statistics.mean(p_list),
            "energy_avg": statistics.mean(e_list),
            "power_std": statistics.stdev(p_list) if len(p_list) > 1 else 0,
            "energy_std": statistics.stdev(e_list) if len(e_list) > 1 else 0,
            "n_power": len(p_list),
            "n_energy": len(e_list),
        })

    return summary_rows


def plot_power(summary_rows, keys, out_power, out_energy):
    by_key = defaultdict(list)
    for r in summary_rows:
        k = (r["branch"], r["param"], r["max_tree"], r["max_leaves"])
        by_key[k].append(r)

    # prepare
    all_power = []
    all_energy_series = []

    for key in keys:
        branch = key["branch"]
        param = key["param"]
        max_tree = key["max_tree"]
        max_leaves = key["max_leaves"]

        group = by_key.get((branch, param, max_tree, max_leaves), [])
        if not group:
            print(f"[POWER] Missing key {key}")
            continue

        group = sorted(group, key=lambda r: r["pps"])
        pps_vals = [r["pps"] for r in group]
        power_vals = [r["power_avg"] for r in group]
        energy_vals = [r["energy_avg"] for r in group]

        label = pretty_label(branch, param, max_tree, max_leaves)
        marker = BRANCH_MARKERS.get(branch, ".")

        all_power.append((pps_vals, power_vals, label, marker, group))
        all_energy_series.append((pps_vals, energy_vals, label, marker, group))

    # ---- POWER ----
    fig, ax = plt.subplots(figsize=(12, 5))
    for pps_vals, power_vals, label, marker, rows in all_power:

        ax.plot(pps_vals, power_vals, marker=marker, linestyle="--", label=label)

        stds = [r["power_std"] for r in rows]
        ns = [r["n_power"] for r in rows]
        ci = [1.96 * s / math.sqrt(n) if n > 1 else 0 for s, n in zip(stds, ns)]

        upper = [m + c for m, c in zip(power_vals, ci)]
        lower = [m - c for m, c in zip(power_vals, ci)]

        ax.fill_between(pps_vals, lower, upper, alpha=0.2)

    ax.set_xlabel("PPS")
    ax.set_ylabel("Power (W)")
    ax.grid(True)
    ax.legend()
    plt.tight_layout()
    plt.savefig(out_power, dpi=300)
    plt.close()

    # ---- ENERGY ----
    fig, ax = plt.subplots(figsize=(12, 5))
    for pps_vals, e_vals, label, marker, rows in all_energy_series:

        ax.plot(pps_vals, e_vals, marker=marker, linestyle="--", label=label)

        stds = [r["energy_std"] for r in rows]
        ns = [r["n_energy"] for r in rows]
        ci = [1.96 * s / math.sqrt(n) if n > 1 else 0 for s, n in zip(stds, ns)]
        upper = [m + c for m, c in zip(e_vals, ci)]
        lower = [m - c for m, c in zip(e_vals, ci)]

        ax.fill_between(pps_vals, lower, upper, alpha=0.2)

    ax.set_xlabel("PPS")
    ax.set_ylabel("Energy (kWh)")
    ax.grid(True)
    ax.legend()
    plt.tight_layout()
    plt.savefig(out_energy, dpi=300)
    plt.close()

    print(f"[DONE] Saved power plots → {out_power}, {out_energy}")

def plot_power_box(summary_rows, keys, pps_target, out_power="power_box.png"):
    """
    Vẽ box plot Power tại PPS cố định.
    summary_rows: từ aggregate_power()
    keys: list các key giống plot_power()
    pps_target: PPS cố định
    out_power: file PNG lưu kết quả
    """
    data_to_plot = []
    labels = []

    for key in keys:
        branch = key["branch"]
        param = key["param"]
        max_tree = key["max_tree"]
        max_leaves = key["max_leaves"]

        # Lọc các row đúng key và PPS
        rows = [r for r in summary_rows 
                if r["branch"] == branch and r["param"] == param 
                and r["max_tree"] == max_tree and r["max_leaves"] == max_leaves
                and r["pps"] == pps_target]
        
        if not rows:
            print(f"[BOX] No data for key {key} at PPS={pps_target}")
            continue

        # gộp tất cả samples
        samples = []
        for r in rows:
            samples.extend(r["power_list"])
        
        data_to_plot.append(samples)
        labels.append(pretty_label(branch, param, max_tree, max_leaves))

    if not data_to_plot:
        print(f"No data to plot boxplot at PPS={pps_target}")
        return

    plt.figure(figsize=(12,6))
    plt.boxplot(data_to_plot, labels=labels, patch_artist=True)
    plt.ylabel("Power (W)")
    plt.xlabel(f"PPS = {pps_target}")
    plt.title(f"Box plot of Power @ PPS {pps_target}")
    plt.grid(True, axis='y', linestyle='--', alpha=0.7)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(out_power, dpi=300)
    plt.close()
    print(f"[DONE] Saved Power Box Plot: {out_power}")
    
# ================================================================
#                          MAIN PROGRAM
# ================================================================
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["throughput", "power"], required=True)
    p.add_argument("--csv-dir", required=True)
    p.add_argument("--keys", nargs="+", help="branch:param:max_tree:max_leaves")
    p.add_argument("--plot-type", choices=["line", "box"], default="line",
               help="Chọn kiểu plot: line (mặc định) hoặc box")
    p.add_argument("--pps-box", type=int, help="Chỉ định PPS khi vẽ box plot")

    # output names
    p.add_argument("--out-thr", default="../img/thr.png")
    p.add_argument("--out-pps", default="../img/pps.png")
    p.add_argument("--out-lat", default="../img/latency.png")
    p.add_argument("--out-power", default="../img/power.png")
    p.add_argument("--out-energy", default="../img/energy.png")

    args = p.parse_args()

    # parse keys
    keys = []
    if args.keys:
        for k in args.keys:
            parts = k.split(":")
            if len(parts) != 4:
                print(f"Bad key format: {k}")
                continue
            branch, param, t, l = parts
            keys.append({
                "branch": branch,
                "param": param,
                "max_tree": int(t),
                "max_leaves": int(l),
            })

    # -------------------------------------------------------------
    #                      DISPATCH MODE
    # -------------------------------------------------------------
    if args.mode == "throughput":
        summary_rows = aggregate_throughput(args.csv_dir)
        plot_throughput(summary_rows, keys,
                        args.out_thr, args.out_pps, args.out_lat)

    elif args.mode == "power":
        summary_rows = aggregate_power(args.csv_dir)
        
        if args.plot_type == "line":
            plot_power(summary_rows, keys, args.out_power, args.out_energy)
        elif args.plot_type == "box":
            if args.pps_box is None:
                print("Bạn cần chỉ định --pps-box khi vẽ box plot")
                return
            plot_power_box(summary_rows, keys, args.pps_box, out_power=args.out_power)

if __name__ == "__main__":
    main()