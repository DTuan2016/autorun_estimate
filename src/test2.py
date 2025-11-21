import os
import glob

dir_path = "/home/security/dtuan/autorun_estimate/all_results/results_throughput"

for f in glob.glob(os.path.join(dir_path, "log_nn_*.txt")):
    base = os.path.basename(f)
    # "log_nn_2_70000_3.txt" -> "nn_2_70000_3_16_16.csv"
    new_name = base.replace("log_", "")       # nn_2_70000_3.txt
    new_name = new_name.replace(".txt", "_16_16.csv")  # nn_2_70000_3_16_16.csv
    old_path = os.path.join(dir_path, base)
    new_path = os.path.join(dir_path, new_name)
    os.rename(old_path, new_path)
    print(f"{old_path} -> {new_path}")
