import re
import os
import csv
from glob import glob

def extract_log_data(log_data):
    """
    Trích xuất dữ liệu từ một chuỗi log đơn lẻ.
    Sử dụng Regex linh hoạt để trích xuất thời gian và các chỉ số hiệu năng.
    """
    data = {
        'Start Time': 'N/A',
        'End Time': 'N/A',
        'run_cnt': 'N/A',
        'l1d_loads': 'N/A',
        'llc_misses': 'N/A',
        'itlb_misses': 'N/A',
        'dtlb_misses': 'N/A',
    }

    # 1. Trích xuất thời gian Bắt đầu và Kết thúc
    start_time_match = re.search(r"TIME=(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", log_data)
    if start_time_match:
        data['Start Time'] = start_time_match.group(1)

    end_time_match = re.search(r"=== DONE .* TIME=(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*===", log_data)
    if end_time_match:
        data['End Time'] = end_time_match.group(1)

    # 2. Trích xuất các Chỉ số Hiệu năng
    # Định vị khối dữ liệu hiệu năng
    metrics_block_match = re.search(r"(\d+)\s*run_cnt.*(\d+)\s*dtlb_misses", log_data, re.DOTALL)
    
    if metrics_block_match:
        metrics_block = metrics_block_match.group(0) 
        
        # Pattern linh hoạt, xử lý khoảng trắng bất thường (\u00A0) và %
        metric_pattern = re.compile(r"""
            ^\s* (\d+)             # NHÓM 1: Giá trị số
            [\s\u00A0]+        # Khớp 1 hoặc nhiều khoảng trắng (bao gồm non-breaking space)
            (\S+)             # NHÓM 2: Tên chỉ số
            \s* (?:\([^\)]+\))?   # Bỏ qua phần trăm (nếu có)
            \s*$              
        """, re.MULTILINE | re.VERBOSE)

        for match in metric_pattern.finditer(metrics_block):
            value = match.group(1)
            name = match.group(2).strip()
            
            if name in data:
                 data[name] = value

    return data

def process_log_folder(input_folder, output_csv_file, log_file_pattern="*.txt"):
    """
    Lặp qua tất cả các file log trong thư mục và ghi kết quả vào file CSV.
    """
    # Lấy đường dẫn tuyệt đối cho thư mục input
    input_folder_abs = os.path.abspath(input_folder)
    
    search_path = os.path.join(input_folder_abs, log_file_pattern)
    log_files = glob(search_path)
    
    if not log_files:
        print(f"❌ KHÔNG tìm thấy file log nào khớp với pattern '{log_file_pattern}' trong thư mục '{input_folder_abs}'.")
        print("Vui lòng kiểm tra lại đường dẫn INPUT_FOLDER và tên file.")
        return

    all_results = []
    fieldnames = ['File Name', 'Start Time', 'End Time', 'run_cnt', 'l1d_loads', 'llc_misses', 'itlb_misses', 'dtlb_misses']

    print(f"Đang xử lý {len(log_files)} file log...")

    for file_path in log_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f: 
                log_data = f.read()
            
            data = extract_log_data(log_data)
            data['File Name'] = os.path.basename(file_path)
            
            all_results.append(data)
        except Exception as e:
            print(f"    -> ❌ LỖI KHẨN CẤP khi xử lý file {file_path}: {e}")
            error_data = {'File Name': os.path.basename(file_path)}
            for key in fieldnames[1:]:
                error_data[key] = f"ERROR: {e}"
            all_results.append(error_data)
    with open(output_csv_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_results)

    print("\n==============================================")
    print(f"✅ Hoàn thành! Đã xử lý {len(log_files)} file. Kết quả đã được lưu vào: {output_csv_file}")
    print("==============================================")

INPUT_FOLDER = '/home/dongtv/dtuan/autorun/results_perf' 
OUTPUT_CSV = '/home/dongtv/dtuan/autorun/log_svm.csv'

if __name__ == "__main__":
    process_log_folder(INPUT_FOLDER, OUTPUT_CSV)
process_log_folder(INPUT_FOLDER, OUTPUT_CSV)