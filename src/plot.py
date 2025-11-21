# import csv
# import glob
# import re
# import statistics
# from collections import defaultdict
# import matplotlib.pyplot as plt

# FILENAME_REGEX = re.compile(
#     r"^([A-Za-z0-9]+)_([A-Za-z0-9]+)_([0-9]+)_([0-9]+)_([0-9]+)_([0-9]+)\.csv$"
# )

# # FILENAME_REGEX = re.compile(
# #     r"^([A-Za-z0-9]+)_([A-Za-z0-9]+)_([0-9]+)_([0-9]+)_([0-9]+)_([0-9]+)\.(csv|txt)$"
# # )

# def read_txt_metrics(filename):
#     """Đọc file .txt với header: Throughput_Mbps,Avg_Latency_ns,PPS"""
#     throughputs, pps_list, latencies = [], [], []

#     with open(filename, 'r') as f:
#         lines = f.readlines()

#     # Tìm header
#     header_line = 0
#     for i, line in enumerate(lines):
#         if "Throughput_Mbps" in line:
#             header_line = i
#             break

#     for line in lines[header_line+1:]:
#         parts = line.strip().split(',')
#         if len(parts) != 3:
#             continue
#         thr_mbps, lat_ns, pps = parts
#         try:
#             throughputs.append(float(thr_mbps) * 1_000_000 / 8)  # Chuyển Mbps -> B/s
#             latencies.append(float(lat_ns))
#             pps_list.append(float(pps))
#         except ValueError:
#             continue

#     if not throughputs:
#         return 0, 0, 0

#     return (
#         statistics.mean(throughputs),
#         statistics.mean(pps_list),
#         statistics.mean(latencies)
#     )


# # def read_csv_metrics(filename):
# #     throughputs, pps_list, latencies = [], [], []

# #     with open(filename, newline='') as f:
# #         reader = csv.DictReader(f)
# #         for row in reader:
# #             throughputs.append(float(row["throughput_Bps"]))
# #             pps_list.append(float(row["pps"]))
# #             latencies.append(float(row["latency_ns"]))

# #     return (
# #         statistics.mean(throughputs),
# #         statistics.mean(pps_list),
# #         statistics.mean(latencies),
# #     )
# # def read_csv_metrics(filename):
# #     throughputs, pps_list, latencies = [], [], []

# #     with open(filename, newline='') as f:
# #         reader = csv.DictReader(f)
# #         for row in reader:
# #             # Kiểm tra tên cột khác nhau
# #             if "throughput_Bps" in row:
# #                 thr = float(row["throughput_Bps"])
# #             elif "Throughput_Mbps" in row:
# #                 thr = float(row["Throughput_Mbps"]) * 1_000_000 / 8
# #             else:
# #                 continue

# #             if "pps" in row:
# #                 pps = float(row["pps"])
# #             elif "PPS" in row:
# #                 pps = float(row["PPS"])
# #             else:
# #                 continue

# #             if "latency_ns" in row:
# #                 lat = float(row["latency_ns"])
# #             elif "Avg_Latency_ns" in row:
# #                 lat = float(row["Avg_Latency_ns"])
# #             else:
# #                 continue

# #             throughputs.append(thr)
# #             pps_list.append(pps)
# #             latencies.append(lat)

# #     if not throughputs:
# #         return 0,0,0

# #     return statistics.mean(throughputs), statistics.mean(pps_list), statistics.mean(latencies)

# def read_csv_metrics(filename):
#     throughputs, pps_list, latencies = [], [], []

#     with open(filename, newline='') as f:
#         reader = csv.DictReader(f)
#         for row in reader:
#             if "throughput_Bps" in row:
#                 thr = float(row["throughput_Bps"])
#             elif "Throughput_Mbps" in row:
#                 thr = float(row["Throughput_Mbps"]) * 1_000_000 / 8
#             else:
#                 continue

#             if "pps" in row:
#                 pps = float(row["pps"])
#             elif "PPS" in row:
#                 pps = float(row["PPS"])
#             else:
#                 continue

#             if "latency_ns" in row:
#                 lat = float(row["latency_ns"])
#             elif "Avg_Latency_ns" in row:
#                 lat = float(row["Avg_Latency_ns"])
#             else:
#                 continue

#             throughputs.append(thr)
#             pps_list.append(pps)
#             latencies.append(lat)

#     return throughputs, pps_list, latencies

# def read_all_csv(csv_dir):
#     """Đọc tất cả CSV"""
#     files = glob.glob(f"{csv_dir}/*.csv")
#     summary_rows = []

#     for f in files:
#         fname = f.split("/")[-1]
#         m = FILENAME_REGEX.match(fname)
#         if not m:
#             continue
#         branch, param, pps, solan, max_tree, max_leaves = m.groups()
#         # avg_thr, avg_pps, avg_lat = read_csv_metrics(f)
#         # summary_rows.append({
#         #     "branch": branch,
#         #     "param": param,
#         #     "pps": int(pps),
#         #     "solan": int(solan),
#         #     "max_tree": int(max_tree),
#         #     "max_leaves": int(max_leaves),
#         #     "throughput_avg": avg_thr,
#         #     "pps_avg": avg_pps,
#         #     "latency_avg": avg_lat
#         # })
#         thr_list, pps_list, lat_list = read_csv_metrics(f)
#         summary_rows.append({
#             "branch": branch,
#             "param": param,
#             "thr_list": thr_list,
#             "pps_list_full": pps_list,
#             "lat_list": lat_list,
#             "throughput_avg": statistics.mean(thr_list),
#             "throughput_std": statistics.stdev(thr_list) if len(thr_list) > 1 else 0,
#             "pps_avg": statistics.mean(pps_list),
#             "pps_std": statistics.stdev(pps_list) if len(pps_list) > 1 else 0,
#             "latency_avg": statistics.mean(lat_list),
#             "latency_std": statistics.stdev(lat_list) if len(lat_list) > 1 else 0,
#         })

#     return summary_rows

# # def read_all_files(data_dir):
# #     files = glob.glob(f"{data_dir}/*.*")
# #     summary_rows = []

# #     for f in files:
# #         fname = f.split("/")[-1]
# #         m = FILENAME_REGEX.match(fname)
# #         if not m:
# #             continue
# #         branch, param, pps, solan, max_tree, max_leaves, ext = m.groups()

# #         if ext == "csv":
# #             avg_thr, avg_pps, avg_lat = read_csv_metrics(f)
# #         elif ext == "txt" and branch == "nn":
# #             avg_thr, avg_pps, avg_lat = read_txt_metrics(f)
# #         else:
# #             continue

# #         summary_rows.append({
# #             "branch": branch,
# #             "param": param,
# #             "pps": int(pps),
# #             "solan": int(solan),
# #             "max_tree": int(max_tree),
# #             "max_leaves": int(max_leaves),
# #             "throughput_avg": avg_thr,
# #             "pps_avg": avg_pps,
# #             "latency_avg": avg_lat
# #         })
# #     return summary_rows

# def pretty_label(branch, param, max_tree, max_leaves):
#     if branch == "base":
#         return "BASE"
#     if branch == "quickscore":
#         return f"QuickXDP[{max_tree}][{max_leaves}]"
#     if branch == "randforest":
#         return f"RF[{max_tree}][{max_leaves}]"
#     if branch == "svm":
#         return "SVM"
#     if branch == "nn":
#         return f"NN[16][16]"
#     return f"{branch}_{param}_{max_tree}_{max_leaves}"

# def plot_multiple_keys(summary_rows, keys,
#                        out_thr="throughput_plot.png",
#                        out_pps="pps_plot.png",
#                        out_lat="latency_plot.png"):

#     # Mapping branch -> marker
#     branch_markers = {
#         "base": "o",
#         "quickscore": "x",
#         "randforest": "s",
#         "svm": "^",
#         "nn": "*"
#     }

#     def get_marker(branch):
#         return branch_markers.get(branch, '.')  # default marker

#     all_thr = []
#     all_pps = []
#     all_lat = []

#     for key_dict in keys:
#         branch = key_dict["branch"]
#         param = key_dict["param"]
#         max_tree = key_dict["max_tree"]
#         max_leaves = key_dict["max_leaves"]

#         filtered = [r for r in summary_rows if
#                     r["branch"] == branch and
#                     r["param"] == param and
#                     r["max_tree"] == max_tree and
#                     r["max_leaves"] == max_leaves]

#         if not filtered:
#             print(f"❌ Không tìm thấy dữ liệu cho key {key_dict}")
#             continue

#         # Loại pps trùng
#         pps_dict = {}
#         for r in filtered:
#             pps_val = r["pps"]
#             if pps_val not in pps_dict:
#                 pps_dict[pps_val] = r
#             else:
#                 existing = pps_dict[pps_val]
#                 pps_dict[pps_val] = {
#                     **r,
#                     "throughput_avg": (existing["throughput_avg"] + r["throughput_avg"]) / 2,
#                     "pps_avg": (existing["pps_avg"] + r["pps_avg"]) / 2,
#                     "latency_avg": (existing["latency_avg"] + r["latency_avg"]) / 2,
#                 }

#         filtered_unique = sorted(pps_dict.values(), key=lambda x: x["pps"])

#         pps_vals = [r["pps"] for r in filtered_unique]
#         thr_vals = [r["throughput_avg"] for r in filtered_unique]
#         pps_avg_vals = [r["pps_avg"] for r in filtered_unique]
#         lat_vals = [r["latency_avg"] for r in filtered_unique]

#         label = pretty_label(branch, param, max_tree, max_leaves)
#         marker = get_marker(branch)

#         all_thr.append((pps_vals, thr_vals, label, marker))
#         all_pps.append((pps_vals, pps_avg_vals, label, marker))
#         all_lat.append((pps_vals, lat_vals, label, marker))

#     # ------------ FIGURE 1 ------------
#     fig1, ax1 = plt.subplots(figsize=(12, 5))
#     for pps_vals, thr_vals, label, marker in all_thr:
#         # ax1.plot(pps_vals, thr_vals, marker=marker, label=label)
#         ax1.plot(pps_vals, thr_vals, marker=marker, label=label)
#     ax1.set_xlabel("pps")
#     ax1.set_ylabel("Throughput_avg (B/s)")
#     ax1.grid(True)
#     ax1.legend(fontsize=9)
#     fig1.tight_layout()
#     fig1.savefig(out_thr, dpi=300)
#     plt.close(fig1)

#     # ------------ FIGURE 2 ------------
#     fig2, ax2 = plt.subplots(figsize=(12, 5))
#     for pps_vals, pps_avg_vals, label, marker in all_pps:
#         # ax2.plot(pps_vals, pps_avg_vals, marker=marker, label=label)
#         ax2.plot(pps_vals, pps_avg_vals, marker=marker, linestyle="--", label=label)
#     ax2.set_xlabel("Packet sending rate(TX)")
#     ax2.set_ylabel("Packet receiving rate(RX)")
#     ax2.grid(True)
#     ax2.legend(fontsize=9)
#     fig2.tight_layout()
#     fig2.savefig(out_pps, dpi=300)
#     plt.close(fig2)

#     # ------------ FIGURE 3 ------------
#     fig3, ax3 = plt.subplots(figsize=(12, 5))
#     for pps_vals, lat_vals, label, marker in all_lat:
#         # ax3.plot(pps_vals, lat_vals, marker=marker, label=label)
#         ax3.plot(pps_vals, lat_vals, marker=marker, linestyle="--", label=label)
#     ax3.set_xlabel("Packet sending rate(TX)")
#     ax3.set_ylabel("Processing time avg")
#     ax3.grid(True)
#     ax3.legend(fontsize=9)
#     fig3.tight_layout()
#     fig3.savefig(out_lat, dpi=300)
#     plt.close(fig3)

#     print(f"✔️ Saved: {out_thr}, {out_pps}, {out_lat}")

# if __name__ == "__main__":
#     summary_rows = read_all_csv("/home/security/dtuan/autorun_estimate/all_results/results_throughput")

#     # Các key muốn vẽ so sánh
#     keys_to_plot = [
#         {"branch":"base", "param":"2", "max_tree":1, "max_leaves":1},
#         # {"branch":"quickscore", "param":"1", "max_tree":10, "max_leaves":32},
#         {"branch":"quickscore", "param":"1", "max_tree":20, "max_leaves":32},
#         # {"branch":"quickscore", "param":"1", "max_tree":30, "max_leaves":32},
#         # {"branch":"quickscore", "param":"1", "max_tree":50, "max_leaves":32},
#         # {"branch":"quickscore", "param":"1", "max_tree":70, "max_leaves":32},
#         # {"branch":"quickscore", "param":"1", "max_tree":90, "max_leaves":32},
#         {"branch":"quickscore", "param":"1", "max_tree":100, "max_leaves":32},
#         {"branch":"randforest", "param":"2", "max_tree":20, "max_leaves":32},
#         # {"branch":"randforest", "param":"2", "max_tree":10, "max_leaves":32},
#         {"branch":"svm", "param":"2", "max_tree":1, "max_leaves":1},
#         {"branch":"nn", "param":"2", "max_tree":16, "max_leaves":16}
#     ]

#     plot_multiple_keys(summary_rows, keys_to_plot)


import csv
import glob
import re
import statistics
from collections import defaultdict
import matplotlib.pyplot as plt

FILENAME_REGEX = re.compile(
    r"^([A-Za-z0-9]+)_([A-Za-z0-9]+)_([0-9]+)_([0-9]+)_([0-9]+)_([0-9]+)\.csv$"
)


# -------------------------------------------------------
#  READ CSV
# -------------------------------------------------------

def read_csv_metrics(filename):
    """
    Trả về LIST dữ liệu thô theo từng dòng
    """
    throughputs, pps_list, latencies = [], [], []

    with open(filename, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:

            # Throughput
            if "throughput_Bps" in row:
                thr = float(row["throughput_Bps"])
            elif "Throughput_Mbps" in row:
                thr = float(row["Throughput_Mbps"]) * 1_000_000 / 8
            else:
                continue

            # PPS
            if "pps" in row:
                pps = float(row["pps"])
            elif "PPS" in row:
                pps = float(row["PPS"])
            else:
                continue

            # Latency
            if "latency_ns" in row:
                lat = float(row["latency_ns"])
            elif "Avg_Latency_ns" in row:
                lat = float(row["Avg_Latency_ns"])
            else:
                continue

            throughputs.append(thr)
            pps_list.append(pps)
            latencies.append(lat)

    return throughputs, pps_list, latencies


# -------------------------------------------------------
#  READ ALL CSV
# -------------------------------------------------------

def read_all_csv(csv_dir):
    files = glob.glob(f"{csv_dir}/*.csv")
    summary_rows = []

    for f in files:
        fname = f.split("/")[-1]
        m = FILENAME_REGEX.match(fname)
        if not m:
            continue

        branch, param, pps, solan, max_tree, max_leaves = m.groups()

        thr_list, pps_list_full, lat_list = read_csv_metrics(f)
        if len(thr_list) == 0:
            continue

        summary_rows.append({
            "branch": branch,
            "param": param,
            "pps": int(pps),
            "solan": int(solan),
            "max_tree": int(max_tree),
            "max_leaves": int(max_leaves),

            # Raw lists
            "thr_list": thr_list,
            "pps_list_full": pps_list_full,
            "lat_list": lat_list,

            # Mean
            "throughput_avg": statistics.mean(thr_list),
            "pps_avg": statistics.mean(pps_list_full),
            "latency_avg": statistics.mean(lat_list),

            # Std
            "throughput_std": statistics.stdev(thr_list) if len(thr_list) > 1 else 0,
            "pps_std": statistics.stdev(pps_list_full) if len(pps_list_full) > 1 else 0,
            "latency_std": statistics.stdev(lat_list) if len(lat_list) > 1 else 0,
        })

    return summary_rows


# -------------------------------------------------------
#  LABELS
# -------------------------------------------------------

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


# -------------------------------------------------------
#  PLOT WITH CONFIDENCE BOUND
# -------------------------------------------------------

def plot_multiple_keys(summary_rows, keys,
                       out_thr="throughput_plot.png",
                       out_pps="pps_plot.png",
                       out_lat="latency_plot.png"):

    branch_markers = {
        "base": "o",
        "quickscore": "x",
        "randforest": "s",
        "svm": "^",
        "nn": "*"
    }

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
            print(f"❌ Không tìm thấy dữ liệu cho key {key_dict}")
            continue

        # Loại pps trùng
        pps_dict = {}
        for r in filtered:
            pps_val = r["pps"]
            if pps_val not in pps_dict:
                pps_dict[pps_val] = r
            else:
                # Merge mean
                e = pps_dict[pps_val]
                pps_dict[pps_val] = {
                    **r,
                    "throughput_avg": (e["throughput_avg"] + r["throughput_avg"]) / 2,
                    "pps_avg": (e["pps_avg"] + r["pps_avg"]) / 2,
                    "latency_avg": (e["latency_avg"] + r["latency_avg"]) / 2,
                }

        filtered_unique = sorted(pps_dict.values(), key=lambda x: x["pps"])

        pps_vals = [r["pps"] for r in filtered_unique]
        thr_vals = [r["throughput_avg"] for r in filtered_unique]
        pps_avg_vals = [r["pps_avg"] for r in filtered_unique]
        lat_vals = [r["latency_avg"] for r in filtered_unique]

        label = pretty_label(branch, param, max_tree, max_leaves)
        marker = get_marker(branch)

        all_thr.append((pps_vals, thr_vals, label, marker, filtered_unique))
        all_pps.append((pps_vals, pps_avg_vals, label, marker, filtered_unique))
        all_lat.append((pps_vals, lat_vals, label, marker, filtered_unique))

    # -------------------------------------------------------
    # FIGURE 1: Throughput
    # -------------------------------------------------------
    fig1, ax1 = plt.subplots(figsize=(12, 5))
    for pps_vals, thr_vals, label, marker, rows in all_thr:

        ax1.plot(pps_vals, thr_vals, marker=marker, label=label)

        # CI 95%
        stds = [r["throughput_std"] for r in rows]
        ns = [len(r["thr_list"]) for r in rows]
        ci = [1.96 * s / (n ** 0.5) if n > 1 else 0 for s, n in zip(stds, ns)]

        upper = [m + c for m, c in zip(thr_vals, ci)]
        lower = [m - c for m, c in zip(thr_vals, ci)]

        ax1.fill_between(pps_vals, lower, upper, alpha=0.2)

    ax1.set_xlabel("pps")
    ax1.set_ylabel("Throughput_avg (B/s)")
    ax1.grid(True)
    ax1.legend(fontsize=9)
    fig1.tight_layout()
    fig1.savefig(out_thr, dpi=300)
    plt.close(fig1)

    # -------------------------------------------------------
    # FIGURE 2: PPS
    # -------------------------------------------------------
    fig2, ax2 = plt.subplots(figsize=(12, 5))
    for pps_vals, pps_avg_vals, label, marker, rows in all_pps:

        ax2.plot(pps_vals, pps_avg_vals, marker=marker, linestyle="--", label=label)

        stds = [r["pps_std"] for r in rows]
        ns = [len(r["pps_list_full"]) for r in rows]
        ci = [1.96 * s / (n ** 0.5) if n > 1 else 0 for s, n in zip(stds, ns)]

        upper = [m + c for m, c in zip(pps_avg_vals, ci)]
        lower = [m - c for m, c in zip(pps_avg_vals, ci)]

        ax2.fill_between(pps_vals, lower, upper, alpha=0.2)

    ax2.set_xlabel("Packet sending rate(TX)")
    ax2.set_ylabel("Packet receiving rate(RX)")
    ax2.grid(True)
    ax2.legend(fontsize=9)
    fig2.tight_layout()
    fig2.savefig(out_pps, dpi=300)
    plt.close(fig2)

    # -------------------------------------------------------
    # FIGURE 3: Latency
    # -------------------------------------------------------
    fig3, ax3 = plt.subplots(figsize=(12, 5))
    for pps_vals, lat_vals, label, marker, rows in all_lat:

        ax3.plot(pps_vals, lat_vals, marker=marker, linestyle="--", label=label)

        stds = [r["latency_std"] for r in rows]
        ns = [len(r["lat_list"]) for r in rows]
        ci = [1.96 * s / (n ** 0.5) if n > 1 else 0 for s, n in zip(stds, ns)]

        upper = [m + c for m, c in zip(lat_vals, ci)]
        lower = [m - c for m, c in zip(lat_vals, ci)]

        ax3.fill_between(pps_vals, lower, upper, alpha=0.2)

    ax3.set_xlabel("Packet sending rate(TX)")
    ax3.set_ylabel("Processing time avg (ns)")
    ax3.grid(True)
    ax3.legend(fontsize=9)
    fig3.tight_layout()
    fig3.savefig(out_lat, dpi=300)
    plt.close(fig3)

    print(f"✔️ Saved: {out_thr}, {out_pps}, {out_lat}")


# -------------------------------------------------------
#  MAIN
# -------------------------------------------------------

if __name__ == "__main__":
    summary_rows = read_all_csv("/home/security/dtuan/autorun_estimate/all_results/results_throughput")

    keys_to_plot = [
        {"branch": "base", "param": "3", "max_tree": 1, "max_leaves": 1},
        # {"branch": "quickscore", "param": "2", "max_tree": 20, "max_leaves": 32},
        # {"branch": "quickscore", "param": "2", "max_tree": 100, "max_leaves": 32},
        {"branch": "randforest", "param": "3", "max_tree": 20, "max_leaves": 64},
        {"branch": "svm", "param": "3", "max_tree": 1, "max_leaves": 1},
        {"branch": "nn", "param": "3", "max_tree": 1, "max_leaves": 1}
    ]

    plot_multiple_keys(summary_rows, keys_to_plot)
