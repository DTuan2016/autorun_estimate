import os
import glob
import csv
import re
from collections import defaultdict
import matplotlib.pyplot as plt

# =======================================================
# CONFIG
# =======================================================

INPUT_FOLDER = "/home/gnb/dtuan/autorun_estimate/all_results/results_perf"
OUT_DIR = "/home/gnb/dtuan/autorun_estimate/out"
CSV_OUT = os.path.join(OUT_DIR, "summary_per_core.csv")
PLOT_OUT = os.path.join(OUT_DIR, "do_xdp_generic_vs_pps.png")

os.makedirs(OUT_DIR, exist_ok=True)

PATTERN = "do_xdp_generic"

# =======================================================
# FILENAME PARSER
# =======================================================

def parse_filename(fn):
    """
    branch_param_pps_solan_max_tree_max_leaves_core.svg
    """
    name = fn.replace(".svg", "")
    p = name.split("_")
    if len(p) != 7:
        raise ValueError(f"Bad filename: {fn}")

    return {
        "branch": p[0],
        "param": p[1],
        "pps": int(p[2]),
        "solan": p[3],
        "max_tree": p[4],
        "max_leaves": p[5],
        "core_id": int(p[6]),
    }

# =======================================================
# SVG BASIC STATS
# =======================================================

def extract_stats(svg_path):
    total = 0
    tag = 0

    with open(svg_path, encoding="utf-8") as f:
        for line in f:
            if "<title>all (" in line:
                m = re.search(r'([\d,]+) samples', line)
                if m:
                    total = int(m.group(1).replace(",", ""))

            if re.search(rf"<title>.*{PATTERN}", line):
                m = re.search(r'([\d,]+) samples', line)
                if m:
                    tag += int(m.group(1).replace(",", ""))

    pct = tag * 100 / total if total > 0 else 0.0
    return total, tag, pct

# =======================================================
# STEP 1: AVG theo (branch,param,max_tree,max_leaves,core_id)
# =======================================================

def build_per_core_summary():
    files = glob.glob(os.path.join(INPUT_FOLDER, "*.svg"))
    if not files:
        raise RuntimeError("No SVG found")

    buckets = defaultdict(list)

    for path in files:
        fn = os.path.basename(path)
        meta = parse_filename(fn)
        total, tag, pct = extract_stats(path)

        key = (
            meta["branch"],
            meta["param"],
            meta["max_tree"],
            meta["max_leaves"],
            meta["core_id"],
            meta["pps"],
        )

        buckets[key].append(pct)

    rows = []
    for (br, pm, mt, ml, cid, pps), vals in buckets.items():
        rows.append({
            "branch": br,
            "param": pm,
            "max_tree": mt,
            "max_leaves": ml,
            "core_id": cid,
            "pps": pps,
            "pct": sum(vals) / len(vals),
        })

    return rows

# =======================================================
# WRITE CSV (PER CORE)
# =======================================================

def write_csv(rows):
    with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "branch", "param", "max_tree", "max_leaves",
            "core_id", "pps",
            "Percent do_xdp_generic (avg)"
        ])

        for r in sorted(rows, key=lambda x: (
            x["branch"], x["param"], x["max_tree"],
            x["max_leaves"], x["core_id"], x["pps"]
        )):
            w.writerow([
                r["branch"],
                r["param"],
                r["max_tree"],
                r["max_leaves"],
                r["core_id"],
                r["pps"],
                f"{r['pct']:.4f}",
            ])

    print("✔ CSV saved:", CSV_OUT)

# =======================================================
# STEP 2: PLOT (AVG theo core_id)
# =======================================================

def plot_by_keys(rows, keys, core_mode, out_file):
    """
    rows: dữ liệu per-core (từ CSV hoặc memory)
    keys: list of dict:
        {
          "branch": "...",
          "param": "...",
          "max_tree": "...",
          "max_leaves": "..."
        }
    """

    plt.figure(figsize=(10, 6))

    for key in keys:
        br = key["branch"]
        pm = key["param"]
        mt = str(key["max_tree"])
        ml = str(key["max_leaves"])

        # ------------------------------------------------
        # 1. Lọc đúng cấu hình
        # ------------------------------------------------
        filtered = [
            r for r in rows
            if r["branch"] == br
            and r["param"] == pm
            and r["max_tree"] == mt
            and r["max_leaves"] == ml
        ]

        if not filtered:
            print(f"⚠ Không có dữ liệu cho key {key}")
            continue

        # ------------------------------------------------
        # 2. Gom theo PPS
        # ------------------------------------------------
        by_pps = defaultdict(list)
        for r in filtered:
            by_pps[r["pps"]].append(r["pct"])

        points = []

        for pps, vals in by_pps.items():
            non_zero = [v for v in vals if v > 0.0]
            if not non_zero:
                continue

            if pm != "mul":
                value = max(non_zero)
            else:
                value = sum(non_zero) / len(non_zero)

            points.append((pps, value))

        if not points:
            continue

        # ------------------------------------------------
        # 3. Sort PPS & vẽ
        # ------------------------------------------------
        points.sort(key=lambda x: x[0])

        label = f"{br.upper()}-{pm}[{mt}][{ml}]"

        plt.plot(
            [p for p, _ in points],
            [v for _, v in points],
            marker="o",
            linestyle="--",
            label=label
        )

    plt.xlabel("Packets Per Second (PPS)")
    plt.ylabel("CPU usage (%)")
    plt.title(f"CPU usage vs PPS ({core_mode})")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_file, dpi=300)
    plt.close()

    print("✔ Plot saved:", out_file)

# =======================================================
# MAIN
# =======================================================

def main():
    rows = build_per_core_summary()
    write_csv(rows)
    core_mode = "1"
    keys_to_plot = [
        {"branch": "base",        "param": core_mode, "max_tree": 1,   "max_leaves": 1},
        {"branch": "quickscore",  "param": core_mode, "max_tree": 20,  "max_leaves": 64},
        {"branch": "quickscore",  "param": core_mode, "max_tree": 100, "max_leaves": 32},
        {"branch": "randforest",  "param": core_mode, "max_tree": 20,  "max_leaves": 64},
        {"branch": "svm",         "param": core_mode, "max_tree": 1,   "max_leaves": 1},
        {"branch": "nn",          "param": core_mode, "max_tree": 1,   "max_leaves": 1},
    ]

    plot_by_keys(rows, keys_to_plot, core_mode, f"../out/cpu_usage_{core_mode}.png")
    # plot_avg_over_cores(rows)

if __name__ == "__main__":
    main()
