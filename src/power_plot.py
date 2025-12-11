import argparse
import csv
import glob
import math
import os
import re
import statistics
from collections import defaultdict
from typing import Dict, List, Tuple
from scipy.stats import gaussian_kde
import numpy as np  

import matplotlib.pyplot as plt

# -------------------------
# Regex (phù hợp định dạng bạn xác nhận)
# branch_param_pps_solan_max_tree_max_leaves.csv
# ví dụ: main_voltage_1000pps_1_10_32.csv
FILENAME_REGEX = re.compile(
    r"^([A-Za-z0-9_]+)_([A-Za-z0-9_]+)_([0-9]+)_([0-9]+)_([0-9]+)_([0-9]+)\.csv$"
)

# Marker map
BRANCH_MARKERS = {
    "base": "o",
    "quickscore": "x",
    "randforest": "s",
    "svm": "^",
    "nn": "*",
}


def pretty_label(branch: str, param: str, max_tree: int, max_leaves: int) -> str:
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


def read_csv_metrics(filename: str) -> Tuple[List[float], List[float]]:
    """
    Đọc file CSV, trả về (power_list, energy_list).
    Tự động tìm dòng header có chứa 'power_W' và 'energy_kWh'.
    Bỏ qua các dòng trước header.
    """
    power_list: List[float] = []
    energy_list: List[float] = []

    with open(filename, newline="") as f:
        all_lines = f.readlines()

    header_index = None
    for i, line in enumerate(all_lines):
        if "power_W" in line and "energy_kWh" in line:
            header_index = i
            break

    if header_index is None:
        # File không hợp lệ
        return [], []

    start_idx = header_index + 1
    if start_idx >= len(all_lines):
        print(f"File không đủ dữ liệu sau khi skip 15 dòng: {filename}")
        return [], []
    
    # Tạo DictReader từ vị trí header tìm được
    csv_text = "".join([all_lines[header_index]] + all_lines[start_idx:])
    reader = csv.DictReader(csv_text.splitlines())
    if not reader.fieldnames:
        return [], []

    for row in reader:
        p_raw = row.get("power_W", "").strip()
        e_raw = row.get("energy_kWh", "").strip()

        if not p_raw or not e_raw:
            continue

        p = safe_float(p_raw)
        e = safe_float(e_raw)

        if p is None or e is None:
            continue

        power_list.append(p)
        energy_list.append(e)

    return power_list, energy_list


def aggregate_directory(csv_dir: str):
    """
    Đọc toàn bộ csv trong thư mục csv_dir, trả về dict có key:
    (branch,param,max_tree,max_leaves,pps) -> {"power_list": [...], "energy_list": [...], ...}
    """
    files = glob.glob(os.path.join(csv_dir, "*.csv"))
    if not files:
        raise FileNotFoundError(f"No CSV files found in directory: {csv_dir}")

    aggregated: Dict[Tuple[str, str, int, int, int], Dict] = {}

    for path in files:
        fname = os.path.basename(path)
        m = FILENAME_REGEX.match(fname)
        if not m:
            # skip files not matching pattern
            # optionally you can log them
            # print(f"Skipping (name mismatch): {fname}")
            continue

        branch, param, pps_s, solan_s, max_tree_s, max_leaves_s = m.groups()
        pps = int(pps_s)
        solan = int(solan_s)
        max_tree = int(max_tree_s)
        max_leaves = int(max_leaves_s)

        power_list, energy_list = read_csv_metrics(path)
        if not power_list:
            # skip empty / invalid files
            continue

        key = (branch, param, max_tree, max_leaves, pps)
        if key not in aggregated:
            aggregated[key] = {
                "branch": branch,
                "param": param,
                "max_tree": max_tree,
                "max_leaves": max_leaves,
                "pps": pps,
                "solan_total": solan,
                "power_list": list(power_list),
                "energy_list": list(energy_list),
            }
        else:
            # append lists (gộp tất cả samples)
            aggregated[key]["power_list"].extend(power_list)
            aggregated[key]["energy_list"].extend(energy_list)
            aggregated[key]["solan_total"] += solan

    # compute stats
    summary_rows = []
    for key, v in aggregated.items():
        p_list = v["power_list"]
        e_list = v["energy_list"]
        n_p = len(p_list)
        n_e = len(e_list)

        power_avg = statistics.mean(p_list) if n_p else 0.0
        energy_avg = statistics.mean(e_list) if n_e else 0.0
        power_std = statistics.stdev(p_list) if n_p > 1 else 0.0
        energy_std = statistics.stdev(e_list) if n_e > 1 else 0.0

        summary_rows.append(
            {
                "branch": v["branch"],
                "param": v["param"],
                "pps": v["pps"],
                "solan_total": v["solan_total"],
                "max_tree": v["max_tree"],
                "max_leaves": v["max_leaves"],
                "power_list": p_list,
                "energy_list": e_list,
                "power_avg": power_avg,
                "energy_avg": energy_avg,
                "power_std": power_std,
                "energy_std": energy_std,
                "n_power": n_p,
                "n_energy": n_e,
            }
        )

    return summary_rows


def plot_multiple_keys(
    summary_rows,
    keys_to_plot,
    out_power="power_plot.png",
    out_energy="energy_plot.png",
    plot_all=False,
):
    # Build index by (branch,param,max_tree,max_leaves)
    by_key = defaultdict(list)
    for r in summary_rows:
        k = (r["branch"], r["param"], r["max_tree"], r["max_leaves"])
        by_key[k].append(r)

    # If plot_all, generate keys from by_key
    if plot_all:
        keys_to_plot = []
        for k in sorted(by_key.keys()):
            branch, param, max_tree, max_leaves = k
            keys_to_plot.append(
                {"branch": branch, "param": param, "max_tree": max_tree, "max_leaves": max_leaves}
            )

    # Prepare series
    all_power_series = []
    all_energy_series = []

    for key in keys_to_plot:
        branch = key["branch"]
        param = key["param"]
        max_tree = key["max_tree"]
        max_leaves = key["max_leaves"]

        group = by_key.get((branch, param, max_tree, max_leaves), [])
        if not group:
            print(f"Không tìm thấy dữ liệu cho key {key}")
            continue

        # group may contain multiple pps values (each entry has its pps)
        group_sorted = sorted(group, key=lambda r: r["pps"])
        pps_vals = [r["pps"] for r in group_sorted]
        power_vals = [r["power_avg"] for r in group_sorted]
        energy_vals = [r["energy_avg"] for r in group_sorted]

        all_power_series.append((pps_vals, power_vals, pretty_label(branch, param, max_tree, max_leaves), BRANCH_MARKERS.get(branch, "."), group_sorted))
        all_energy_series.append((pps_vals, energy_vals, pretty_label(branch, param, max_tree, max_leaves), BRANCH_MARKERS.get(branch, "."), group_sorted))

    # Plot POWER
    fig1, ax1 = plt.subplots(figsize=(12, 5))
    for pps_vals, power_vals, label, marker, rows in all_power_series:
        ax1.plot(pps_vals, power_vals, marker=marker, linestyle="--", label=label)
        # compute CI
        stds = [r["power_std"] for r in rows]
        ns = [r["n_power"] for r in rows]
        ci = [1.96 * s / math.sqrt(n) if n > 1 else 0.0 for s, n in zip(stds, ns)]
        upper = [m + c for m, c in zip(power_vals, ci)]
        lower = [m - c for m, c in zip(power_vals, ci)]
        # only fill if there's some non-zero CI
        if any(ci):
            ax1.fill_between(pps_vals, lower, upper, alpha=0.2)

    ax1.set_xlabel("PPS")
    ax1.set_ylabel("Power (W)")
    ax1.grid(True)
    ax1.legend(fontsize=9)
    fig1.tight_layout()
    fig1.savefig(out_power, dpi=300)
    plt.close(fig1)

    # Plot ENERGY
    fig2, ax2 = plt.subplots(figsize=(12, 5))
    for pps_vals, energy_vals, label, marker, rows in all_energy_series:
        ax2.plot(pps_vals, energy_vals, marker=marker, linestyle="--", label=label)
        stds = [r["energy_std"] for r in rows]
        ns = [r["n_energy"] for r in rows]
        ci = [1.96 * s / math.sqrt(n) if n > 1 else 0.0 for s, n in zip(stds, ns)]
        upper = [m + c for m, c in zip(energy_vals, ci)]
        lower = [m - c for m, c in zip(energy_vals, ci)]
        if any(ci):
            ax2.fill_between(pps_vals, lower, upper, alpha=0.2)

    ax2.set_xlabel("Packet sending rate (PPS)")
    ax2.set_ylabel("Energy (kWh)")
    ax2.grid(True)
    ax2.legend(fontsize=9)
    fig2.tight_layout()
    fig2.savefig(out_energy, dpi=300)
    plt.close(fig2)

    print(f"Saved: {out_power}, {out_energy}")


def parse_args():
    p = argparse.ArgumentParser(description="Plot power & energy from many CSV files")
    p.add_argument("--csv-dir", required=True, help="Directory containing CSV files")
    p.add_argument("--out-power", default="power_plot.png", help="Output PNG for power")
    p.add_argument("--out-energy", default="energy_plot.png", help="Output PNG for energy")
    p.add_argument("--plot-all", action="store_true", help="Plot all available (branch,param,tree,leaves) keys")
    p.add_argument(
        "--keys",
        nargs="+",
        help=(
            "Specific keys to plot. Each key as branch:param:max_tree:max_leaves "
            "Example: base:1:1:1 svm:1:1:1"
        ),
    )
    return p.parse_args()


def plot_power_pdf(summary_rows: List[Dict], pps_target: int, out_file: str = "power_pdf.png"):
    """
    Vẽ PDF của Power tại PPS cố định từ dữ liệu summary_rows.
    
    summary_rows: output từ aggregate_directory()
    pps_target: PPS muốn vẽ PDF
    out_file: tên file PNG lưu kết quả
    """
    # Lấy tất cả mẫu power cho PPS mong muốn
    power_samples = []
    for r in summary_rows:
        if r["pps"] == pps_target:
            power_samples.extend(r["power_list"])
    
    if not power_samples:
        print(f"No data found for PPS={pps_target}")
        return

    # KDE để ước lượng PDF
    density = gaussian_kde(power_samples)
    xs = np.linspace(min(power_samples), max(power_samples), 200)

    # Vẽ
    plt.figure(figsize=(10,5))
    plt.plot(xs, density(xs), label=f'Power PDF @ {pps_target} PPS', color='blue')
    plt.xlabel("Power (W)")
    plt.ylabel("Density")
    plt.title(f"PDF of Power @ {pps_target} PPS")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_file, dpi=300)
    plt.close()

    print(f"Saved Power PDF: {out_file}")

def main():
    args = parse_args()
    summary_rows = aggregate_directory(args.csv_dir)

    # build keys_to_plot
    keys_to_plot = []
    if args.plot_all:
        # will be handled inside plot_multiple_keys by fetching all keys
        keys_to_plot = []
    elif args.keys:
        for k in args.keys:
            parts = k.split(":")
            if len(parts) != 4:
                print(f"Invalid key format (expect branch:param:max_tree:max_leaves): {k}")
                continue
            branch, param, max_tree_s, max_leaves_s = parts
            try:
                max_tree = int(max_tree_s)
                max_leaves = int(max_leaves_s)
            except ValueError:
                print(f"Invalid numeric in key: {k}")
                continue
            keys_to_plot.append({"branch": branch, "param": param, "max_tree": max_tree, "max_leaves": max_leaves})
    else:
        # default example keys: try some common ones; user can edit these in script
        keys_to_plot = [
            {"branch": "base", "param": "2", "max_tree": 1, "max_leaves": 1},
            {"branch": "svm", "param": "1", "max_tree": 1, "max_leaves": 1},
            {"branch": "nn", "param": "1", "max_tree": 1, "max_leaves": 1},
            {"branch": "randforest", "param": "2", "max_tree": 20, "max_leaves": 64},
            {"branch": "quickscore", "param": "1", "max_tree": 20, "max_leaves": 64},
            {"branch": "quickscore", "param": "1", "max_tree": 100, "max_leaves": 32},
            # {"branch": "randforest", "param": "2", "max_tree": 20, "max_leaves": 8},
            {"branch": "randforest", "param": "2", "max_tree": 10, "max_leaves": 64},
            # {"branch": "randforest", "param": "2", "max_tree": 10, "max_leaves": 32},
            # {"branch": "randforest", "param": "2", "max_tree": 10, "max_leaves": 16},
            # {"branch": "randforest", "param": "2", "max_tree": 10, "max_leaves": 8},
        ]

    plot_multiple_keys(summary_rows, keys_to_plot, out_power=args.out_power, out_energy=args.out_energy, plot_all=args.plot_all)
    pps_target = 140000
    plot_power_pdf(summary_rows, pps_target)
    
if __name__ == "__main__":
    main()