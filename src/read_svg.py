import os
import glob
import csv
import re
import xml.etree.ElementTree as ET

input_folder = r'/home/dongtv/dtuan/autorun/results_perf' 
output_csv_file = r'/home/dongtv/dtuan/autorun/mlp.csv'
tags_to_track_patterns = {
    "do_xdp_generic": r"do_xdp_generic",
    "__htab_map_lookup_elem": r"__htab_map_lookup_elem",
    "bpf_for_each_hash_elem": r"bpf_for_each_hash_elem",
    "htab_map_update_elem": r"htab_map_update_elem",
}
def parse_title(title_string):
    """
    Trích xuất tên hàm, số lượng samples, và phần trăm từ chuỗi title.
    """
    match = re.search(r'^(.*?)\s*\((\d{1,3}(,\d{3})*)\s*samples,\s*([\d\.]+)%\)', title_string)
    if match:
        name = match.group(1).strip()
        samples_str = match.group(2).replace(',', '')
        percentage_str = match.group(4)
        return name, int(samples_str), float(percentage_str)
    
    # Fallback nếu chỉ có samples
    match_samples_only = re.search(r'^(.*?)\s*\((\d{1,3}(,\d{3})*)\s*samples', title_string)
    if match_samples_only:
        name = match_samples_only.group(1).strip()
        samples_str = match_samples_only.group(2).replace(',', '')
        return name, int(samples_str), 0.0

    return None, 0, 0.0

def is_child_of(child, parent):
    """
    Kiểm tra xem một khối 'child' có phải là con của khối 'parent' trên flame graph không.
    Trong SVG, hàm con (vẽ bên trên) có tọa độ y nhỏ hơn.
    """
    fudge = 0.0001 # Sai số cho so sánh số thực
    child_x_end = child['x'] + child['width']
    parent_x_end = parent['x'] + parent['width']
    
    # Điều kiện: y của con < y của cha VÀ con nằm trong cha theo chiều ngang
    return (child['y'] < parent['y'] and
            child['x'] >= parent['x'] - fudge and
            child_x_end <= parent_x_end + fudge)

def get_max_anomaly_detector_percentage(root):
    """
    Tính tổng max % của bpf_prog_...xdp_anomaly_detector trong mỗi do_xdp_generic.
    """
    namespace = '{http://www.w3.org/2000/svg}'
    frames_group = root.find(f".//{namespace}g[@id='frames']")
    if frames_group is None:
        return 0.0

    do_xdp_generics = []
    bpf_detectors = []

    for g_elem in frames_group.findall(f'{namespace}g'):
        title_elem = g_elem.find(f'{namespace}title')
        rect_elem = g_elem.find(f'{namespace}rect')

        if title_elem is not None and rect_elem is not None and title_elem.text:
            name, samples, percentage = parse_title(title_elem.text)
            if name:
                try:
                    func_data = {
                        'name': name,
                        'percentage': percentage,
                        'x': float(rect_elem.attrib['x']),
                        'y': float(rect_elem.attrib['y']),
                        'width': float(rect_elem.attrib['width'])
                    }
                    if 'do_xdp_generic' in name:
                        do_xdp_generics.append(func_data)
                    # Pattern đầy đủ cho detector
                    elif re.search(r'bpf_prog_.*_xdp_anomaly_detector', name): 
                        bpf_detectors.append(func_data)
                except (KeyError, ValueError):
                    pass

    total_max_bpf_percentage = 0.0
    
    for parent in do_xdp_generics:
        max_percentage_in_parent = 0.0
        
        for child in bpf_detectors:
            if is_child_of(child, parent):
                if child['percentage'] > max_percentage_in_parent:
                    max_percentage_in_parent = child['percentage']
        
        total_max_bpf_percentage += max_percentage_in_parent

    return total_max_bpf_percentage


def get_valid_callback_knn_percentage(root):
    """
    Tính tổng % của callback_knn hợp lệ (do_xdp_generic -> bpf_for_each_hash_elem -> knn_scan_cb).
    """
    namespace = '{http://www.w3.org/2000/svg}'
    frames_group = root.find(f".//{namespace}g[@id='frames']")
    if frames_group is None:
        return 0.0

    do_xdp_generics = []
    hash_elems = []
    callback_knns = []

    for g_elem in frames_group.findall(f'{namespace}g'):
        title_elem = g_elem.find(f'{namespace}title')
        rect_elem = g_elem.find(f'{namespace}rect')

        if title_elem is not None and rect_elem is not None and title_elem.text:
            name, samples, percentage = parse_title(title_elem.text)
            if name:
                try:
                    func_data = {
                        'name': name,
                        'percentage': percentage,
                        'x': float(rect_elem.attrib['x']),
                        'y': float(rect_elem.attrib['y']),
                        'width': float(rect_elem.attrib['width'])
                    }
                    if 'do_xdp_generic' in name:
                        do_xdp_generics.append(func_data)
                    elif 'bpf_for_each_hash_elem' in name:
                        hash_elems.append(func_data)
                    elif 'knn_scan_cb' in name:
                        callback_knns.append(func_data)
                except (KeyError, ValueError):
                    pass

    total_callback_percentage = 0.0
    
    # Lặp qua để tìm chuỗi 3 cấp hợp lệ
    for grandparent in do_xdp_generics:
        for parent in hash_elems:
            if is_child_of(parent, grandparent):
                for child in callback_knns:
                    if is_child_of(child, parent):
                        total_callback_percentage += child['percentage']
                        
    return total_callback_percentage

# --- Hàm phân tích cơ bản (từ loc_svg.py) ---

def analyze_basic_stats(file_path):
    """
    Đọc file SVG, tính mẫu tổng và mẫu/phần trăm cho các hàm cơ bản.
    """
    tag_samples = {name: 0 for name in tags_to_track_patterns.keys()}
    total_all_samples = 0
    
    try:
        with open(file_path, encoding='utf-8') as f:
            for line in f:
                # Tổng "all"
                if "<title>all (" in line:
                    m = re.search(r'([\d,]+) samples', line)
                    if m:
                        total_all_samples = int(m.group(1).replace(',', ''))
                
                # Tính mẫu cho từng tag
                for name, pattern in tags_to_track_patterns.items():
                    # Dùng pattern đầy đủ để tránh nhầm lẫn giữa text và pattern trong title
                    full_pattern = r"<title>" + pattern
                    if re.search(full_pattern, line):
                        m = re.search(r'([\d,]+) samples', line)
                        if m:
                            tag_samples[name] += int(m.group(1).replace(',', ''))
    except Exception as e:
        print(f"Lỗi khi đọc file {os.path.basename(file_path)}: {e}")
        return total_all_samples, tag_samples
    
    return total_all_samples, tag_samples

# --- Hàm chính ---

def main():
    """
    Hàm chính để tìm các tệp .svg, phân tích và xuất ra CSV.
    """
    # CHỈ TÌM CÁC TỆP .svg
    file_paths = glob.glob(os.path.join(input_folder, 'mlp*.svg'))

    if not file_paths:
        print(f"Không tìm thấy tệp .svg nào trong thư mục '{input_folder}'.")
        return

    print(f"Đã tìm thấy {len(file_paths)} tệp .svg để phân tích trong '{input_folder}'.")

    # Mở file CSV để ghi kết quả
    with open(output_csv_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        
        # Tạo Header của CSV
        header = ['File Name', 'Total Samples of All']
        # Thêm header cho Basic Stats
        header.extend([f'Total Samples of {name}' for name in tags_to_track_patterns.keys()])
        header.extend([f'Percentage of {name} (%)' for name in tags_to_track_patterns.keys()])
        # Thêm header cho Custom Stats
        header.append('Total Max Anomaly Detector %') # Logic từ xdp_anomaly_detector.py
        header.append('Total Valid Callback KNN %') # Logic từ callback.py
        
        writer.writerow(header)

        for file_path in sorted(file_paths):
            filename = os.path.basename(file_path)
            print(f"Đang xử lý: {filename}...")
            
            # 1. Phân tích Basic Stats (tổng samples)
            total_all_samples, tag_samples = analyze_basic_stats(file_path)
            
            # 2. Phân tích Custom Stats (dựa trên cấu trúc XML/SVG)
            total_max_bpf_percentage = 0.0
            total_callback_percentage = 0.0
            
            try:
                # Phân tích SVG dưới dạng XML
                tree = ET.parse(file_path)
                root = tree.getroot()
                
                # Lấy kết quả từ logic xdp_anomaly_detector
                total_max_bpf_percentage = get_max_anomaly_detector_percentage(root)
                
                # Lấy kết quả từ logic callback.py
                total_callback_percentage = get_valid_callback_knn_percentage(root)
                
            except ET.ParseError as e:
                print(f"  Lỗi: Không thể phân tích tệp XML/SVG để tính Custom Stats: {e}")
            except Exception as e:
                print(f"  Lỗi không xác định khi tính Custom Stats: {e}")

            row_data = [filename, total_all_samples]
     
            row_data.extend([tag_samples[name] for name in tags_to_track_patterns.keys()])
            
            if total_all_samples > 0:
                for name in tags_to_track_patterns.keys():
                    percentage = (tag_samples[name] / total_all_samples) * 100
                    row_data.append(f'{percentage:.4f}')
            else:
                row_data.extend(['0.0000'] * len(tags_to_track_patterns))

            row_data.append(f'{total_max_bpf_percentage:.4f}')
            row_data.append(f'{total_callback_percentage:.4f}')
            
            writer.writerow(row_data)
            print(f"  -> Tổng Max Anomaly Detector %: {total_max_bpf_percentage:.4f}%")
            print(f"  -> Tổng Valid Callback KNN %: {total_callback_percentage:.4f}%")

    print(f"\n✅ Hoàn thành! Kết quả đã được lưu vào tệp '{output_csv_file}'.")

if __name__ == '__main__':
    main()