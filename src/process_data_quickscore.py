import pandas as pd
import re

# Đọc CSV chi tiết
df = pd.read_csv("quickscore_latency.csv")

# Regex để trích thông số từ tên file
pattern = r"log_quickscore_(\d+)_(\d+)_(\d+)_(\d+)_(\d+)\.txt"

def parse_filename(fname):
    m = re.match(pattern, fname)
    if m:
        return pd.Series({
            "param": int(m.group(1)),
            "pps": int(m.group(2)),
            "run_cnt_file": int(m.group(3)),  # số lần, sẽ dùng để tính trung bình
            "num_tree": int(m.group(4)),
            "num_leaves": int(m.group(5))
        })
    else:
        return pd.Series({
            "param": None,
            "pps": None,
            "run_cnt_file": None,
            "num_tree": None,
            "num_leaves": None
        })

# Thêm cột tham số
df = df.join(df["file"].apply(parse_filename))

# Các cột cần tính trung bình
avg_cols = ["run_time_ns", "l1d_loads_value", "l1d_loads_percent",
            "llc_misses_value", "llc_misses_percent",
            "itlb_misses_value", "itlb_misses_percent",
            "dtlb_misses_value", "dtlb_misses_percent",
            "run_cnt"]  # thêm run_cnt vào tính trung bình

# Đổi tên time_per_run_ns → run_time_ns trước khi gộp
df = df.rename(columns={"time_per_run_ns": "run_time_ns", "run_cnt": "run_cnt"})

# Gộp theo param, pps, num_tree, num_leaves (bỏ run_cnt_file)
df_avg = df.groupby(["param", "pps", "num_tree", "num_leaves"])[avg_cols].mean().reset_index()

# Tạo cột file mới
df_avg["file"] = df_avg.apply(
    lambda x: f"log_quickscore_{int(x.param)}_{int(x.pps)}_{int(x.num_tree)}_{int(x.num_leaves)}.txt",
    axis=1
)
# Sắp xếp cột cho đẹp
cols = ["file", "param", "pps", "num_tree", "num_leaves"] + avg_cols
df_avg = df_avg[cols]

# Xuất CSV
df_avg.to_csv("quickscore.csv", index=False)

print("Done! CSV trung bình theo nhóm saved to quickscore.csv")
