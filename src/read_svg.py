import os
import glob
import csv
import re
import xml.etree.ElementTree as ET
import matplotlib.pyplot as plt

# =======================================================
#  CONFIG
# =======================================================

input_folder = r'/home/security/dtuan/autorun_estimate/all_results/results_perf'
output_csv_file = r'/home/security/dtuan/autorun_estimate/all_results/test.csv'

# Các pattern cần track trong flamegraph
patterns_to_track = {
    "do_xdp_generic": r"do_xdp_generic",
    # "__htab_map_lookup_elem": r"__htab_map_lookup_elem",
    # "bpf_for_each_hash_elem": r"bpf_for_each_hash_elem",
}

# =======================================================
#  HELPERS
# =======================================================

def parse_filename(filename):
    """Parse filename theo dạng: branch_param_pps_solan_maxtree_maxleaf.svg"""
    name = filename.replace(".svg", "")
    parts = name.split("_")
    if len(parts) != 6:
        return [""] * 6
    return parts


def parse_title(title_string):
    """Parse title SVG: func (samples, percent)."""
    match = re.search(r'^(.*?)\s*\(([\d,]+)\s*samples,\s*([\d\.]+)%\)', title_string)
    if match:
        name = match.group(1).strip()
        samples = int(match.group(2).replace(',', ''))
        percent = float(match.group(3))
        return name, samples, percent

    match = re.search(r'^(.*?)\s*\(([\d,]+)\s*samples', title_string)
    if match:
        name = match.group(1).strip()
        samples = int(match.group(2).replace(',', ''))
        return name, samples, 0.0

    return None, 0, 0.0


def is_child_of(child, parent):
    """Kiểm tra nested flamegraph block."""
    fudge = 0.0001
    return (
        child['y'] < parent['y']
        and child['x'] >= parent['x'] - fudge
        and (child['x'] + child['width']) <= (parent['x'] + parent['width'] + fudge)
    )

# =======================================================
#  BASIC STATS
# =======================================================

def analyze_basic_stats(file_path):
    tag_samples = {name: 0 for name in patterns_to_track}
    total_all_samples = 0

    try:
        with open(file_path, encoding='utf-8') as f:
            for line in f:

                if "<title>all (" in line:
                    m = re.search(r'([\d,]+) samples', line)
                    if m:
                        total_all_samples = int(m.group(1).replace(',', ''))

                for name, pattern in patterns_to_track.items():
                    if re.search(rf"<title>{pattern}", line):
                        m = re.search(r'([\d,]+) samples', line)
                        if m:
                            tag_samples[name] += int(m.group(1).replace(',', ''))

    except Exception as e:
        print(f"[ERROR] Lỗi khi đọc file {os.path.basename(file_path)}: {e}")

    return total_all_samples, tag_samples

# =======================================================
#  CUSTOM STATS
# =======================================================

def extract_svg_frames(root):
    ns = '{http://www.w3.org/2000/svg}'
    return ns, root.find(f".//{ns}g[@id='frames']")


def get_max_anomaly_detector_percentage(root):
    ns, frames = extract_svg_frames(root)
    if frames is None:
        return 0.0

    do_xdp_list = []
    detectors = []

    for g in frames.findall(f'{ns}g'):
        title = g.find(f'{ns}title')
        rect = g.find(f'{ns}rect')
        if title is None or rect is None:
            continue

        name, samples, percent = parse_title(title.text)
        if not name:
            continue

        func = {
            'name': name,
            'percentage': percent,
            'x': float(rect.attrib['x']),
            'y': float(rect.attrib['y']),
            'width': float(rect.attrib['width'])
        }

        if "do_xdp_generic" in name:
            do_xdp_list.append(func)
        elif re.search(r'bpf_prog_.*_xdp_anomaly_detector', name):
            detectors.append(func)

    total = 0.0
    for parent in do_xdp_list:
        maxp = 0.0
        for child in detectors:
            if is_child_of(child, parent):
                maxp = max(maxp, child['percentage'])
        total += maxp

    return total


def get_valid_callback_knn_percentage(root):
    ns, frames = extract_svg_frames(root)
    if frames is None:
        return 0.0

    do_xdp_list = []
    hash_list = []
    cb_list = []

    for g in frames.findall(f'{ns}g'):
        title = g.find(f'{ns}title')
        rect = g.find(f'{ns}rect')
        if title is None:
            continue

        name, samples, percent = parse_title(title.text)
        func = {
            'name': name,
            'percentage': percent,
            'x': float(rect.attrib['x']),
            'y': float(rect.attrib['y']),
            'width': float(rect.attrib['width'])
        }

        if "do_xdp_generic" in name:
            do_xdp_list.append(func)
        elif "bpf_for_each_hash_elem" in name:
            hash_list.append(func)
        elif "knn_scan_cb" in name:
            cb_list.append(func)

    total = 0.0
    for gp in do_xdp_list:
        for parent in hash_list:
            if is_child_of(parent, gp):
                for child in cb_list:
                    if is_child_of(child, parent):
                        total += child['percentage']
    return total

# =======================================================
#  CSV WRITER
# =======================================================

def main():
    file_paths = glob.glob(os.path.join(input_folder, "/home/security/dtuan/autorun_estimate/all_results/results_mul/*.svg"))
    if not file_paths:
        print("[ERROR] Không có file SVG.")
        return

    with open(output_csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        header = [
            "File", "branch", "param", "pps", "solan", "max_tree", "max_leaves",
            "Total Samples"
        ]
        header += [f"Samples {p}" for p in patterns_to_track]
        header += [f"Percent {p}" for p in patterns_to_track]
        header += ["Max Anomaly %", "Valid Callback KNN %"]

        writer.writerow(header)

        for path in sorted(file_paths):
            fn = os.path.basename(path)
            print("→ Processing:", fn)

            branch, param, pps, solan, max_tree, max_leaves = parse_filename(fn)
            total_samples, sample_dict = analyze_basic_stats(path)

            try:
                root = ET.parse(path).getroot()
                max_anomaly = get_max_anomaly_detector_percentage(root)
                knn_percent = get_valid_callback_knn_percentage(root)
            except Exception:
                max_anomaly = 0.0
                knn_percent = 0.0

            row = [fn, branch, param, pps, solan, max_tree, max_leaves, total_samples]

            # Samples theo pattern
            for p in patterns_to_track:
                row.append(sample_dict[p])

            # Percent theo pattern
            if total_samples > 0:
                for p in patterns_to_track:
                    row.append(f"{sample_dict[p] * 100 / total_samples:.4f}")
            else:
                row += ["0.0000"] * len(patterns_to_track)

            row.append(f"{max_anomaly:.4f}")
            row.append(f"{knn_percent:.4f}")

            writer.writerow(row)

    print("✔ CSV saved:", output_csv_file)

# =======================================================
#  CSV LOADER + PLOT TOOL
# =======================================================
def load_csv_to_dict(csv_path):
    rows = []
    with open(csv_path, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows

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

def plot_patterns_multiple(summary_rows, pattern_list, keys_to_plot, out_file="patterns_plot.png"):
    fig, ax = plt.subplots(figsize=(12, 6))

    for pattern in pattern_list:
        col = f"Percent {pattern}"
        if col not in summary_rows[0]:
            print(f"⚠ Không có cột {col}")
            continue

        for key in keys_to_plot:
            br   = key["branch"]
            pm   = key["param"]
            mt   = str(key["max_tree"])
            ml   = str(key["max_leaves"])

            for pattern in pattern_list:
                col = f"Percent {pattern}"
                if col not in summary_rows[0]:
                    print(f"⚠ Không có cột {col}")
                    continue

                # --- Lọc đúng cấu hình ---
                rows = []
                for row in summary_rows:
                    if (row["branch"] == br and
                        row["param"] == pm and
                        row["max_tree"] == mt and
                        row["max_leaves"] == ml):

                        try:
                            pps = int(row["pps"])
                            pct = float(row[col])
                        except:
                            continue

                        rows.append((pps, pct))

                if not rows:
                    print(f"Không có dữ liệu cho config {key} pattern={pattern}")
                    continue

                # ---------------------------------------
                #  GỘP PPS TRÙNG → LẤY TRUNG BÌNH
                # ---------------------------------------
                merged = {}
                for pps, pct in rows:
                    merged.setdefault(pps, []).append(pct)

                # Lấy trung bình
                merged_rows = [(pps, sum(vals) / len(vals)) for pps, vals in merged.items()]
                merged_rows.sort(key=lambda x: x[0])

                pps_vals = [x[0] for x in merged_rows]
                pct_vals = [x[1] for x in merged_rows]

                # Label đẹp
                label = pretty_label(br, pm, mt, ml)

                ax.plot(pps_vals, pct_vals, marker="o", linestyle="--", label=label)
                
    ax.set_xlabel("PPS")
    ax.set_ylabel(f"{pattern} (%)")
    ax.grid(True)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_file, dpi=300)
    plt.close(fig)

    print(f"✔ Saved plot: {out_file}")


# =======================================================
if __name__ == "__main__":
    # main()
    # keys_to_plot = [
    #     {"branch": "base", "param": "3", "max_tree": 1, "max_leaves": 1},
    #     {"branch": "quickscore", "param": "3", "max_tree": 20, "max_leaves": 64},
    #     # {"branch": "quickscore", "param": "3", "max_tree": 60, "max_leaves": 64},
    #     # {"branch": "quickscore", "param": "3", "max_tree": 70, "max_leaves": 32},
    #     # {"branch": "quickscore", "param": "3", "max_tree": 80, "max_leaves": 32},
    #     # {"branch": "quickscore", "param": "3", "max_tree": 90, "max_leaves": 32},
    #     {"branch": "quickscore", "param": "3", "max_tree": 100, "max_leaves": 32},
    #     {"branch": "randforest", "param": "3", "max_tree": 20, "max_leaves": 64},
    #     {"branch": "svm", "param": "3", "max_tree": 1, "max_leaves": 1},
    #     {"branch": "nn", "param": "3", "max_tree": 1, "max_leaves": 1}
    # ]
    
    keys_to_plot = [
        {"branch": "base", "param": "mul", "max_tree": 1, "max_leaves": 1},
        # {"branch": "quickscore", "param": "3", "max_tree": 20, "max_leaves": 64},
        # {"branch": "quickscore", "param": "3", "max_tree": 60, "max_leaves": 64},
        # {"branch": "quickscore", "param": "3", "max_tree": 70, "max_leaves": 32},
        # {"branch": "quickscore", "param": "3", "max_tree": 80, "max_leaves": 32},
        # {"branch": "quickscore", "param": "3", "max_tree": 90, "max_leaves": 32},
        # {"branch": "quickscore", "param": "3", "max_tree": 100, "max_leaves": 32},
        {"branch": "randforest", "param": "mul", "max_tree": 20, "max_leaves": 64},
        {"branch": "svm", "param": "mul", "max_tree": 1, "max_leaves": 1},
        {"branch": "nn", "param": "mul", "max_tree": 1, "max_leaves": 1}
    ]
    
    summary_rows = load_csv_to_dict(output_csv_file)
    pattern_list = list(patterns_to_track.keys())

    plot_patterns_multiple(summary_rows, pattern_list, keys_to_plot,
                           out_file="patterns_plot.png")