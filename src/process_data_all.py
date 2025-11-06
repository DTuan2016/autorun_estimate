import pandas as pd
import re

# Đọc CSV chi tiết
df = pd.read_csv("data_all.csv")

# Regex để trích thông số từ tên file: log_<branch>_<param>_<pps>_<lần>.txt
pattern = r"log_(\w+)_(\d+)_(\d+)_(\d+)\.txt"

def parse_filename(fname):
    m = re.match(pattern, fname)
    if m:
        return pd.Series({
            "branch": m.group(1),
            "param": int(m.group(2)),
            "pps": int(m.group(3)),
            "run_cnt_file": int(m.group(4))  # số lần, sẽ bỏ khi gộp
        })
    else:
        return pd.Series({
            "branch": None,
            "param": None,
            "pps": None,
            "run_cnt_file": None
        })

# Thêm cột tham số tách từ tên file
df = df.join(df["file"].apply(parse_filename))

# Đổi tên cột nếu cần (ví dụ: time_per_run_ns → run_time_ns)
if "time_per_run_ns" in df.columns:
    df = df.rename(columns={"time_per_run_ns": "run_time_ns"})
    
# Xác định các cột số (loại trừ file, branch, param, pps, run_cnt_file)
num_cols = df.select_dtypes(include=["number"]).columns.tolist()
exclude_cols = ["param", "pps", "run_cnt_file"]  # loại bỏ cột nhóm
num_cols = [c for c in num_cols if c not in exclude_cols]

# Gộp trung bình theo branch, param, pps
df_avg = df.groupby(["branch", "param", "pps"])[num_cols].mean().reset_index()

# Gộp trung bình theo branch, param, pps
df_avg = df.groupby(["branch", "param", "pps"])[num_cols].mean().reset_index()

# Làm tròn và ép kiểu int cho các cột integer (nếu có)
int_cols = [c for c in num_cols if c.endswith("_value") or c == "run_cnt"]
for col in int_cols:
    if col in df_avg.columns:
        df_avg[col] = df_avg[col].round().astype(int)

# Tạo tên file mới, bỏ số lần
df_avg["file"] = df_avg.apply(
    lambda x: f"log_{x.branch}_{int(x.param)}_{int(x.pps)}.txt",
    axis=1
)

# Sắp xếp lại cột cho đẹp
order_cols = ["file", "branch", "param", "pps"] + [c for c in num_cols if c in df_avg.columns]
df_avg = df_avg[order_cols]

# Xuất CSV
df_avg.to_csv("data_avg_grouped_branch.csv", index=False)

print("✅ Done! Đã gộp trung bình theo branch, param, pps và lưu vào data_avg_grouped_branch.csv")
