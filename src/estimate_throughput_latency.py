#!/usr/bin/env python3
import ctypes
import time
import csv
import sys
from datetime import datetime
from bcc import libbcc

# ==== KHAI BÁO HÀM GỐC TỪ LIBBCC ====
libbcc.lib.bpf_obj_get.argtypes = [ctypes.c_char_p]
libbcc.lib.bpf_obj_get.restype = ctypes.c_int

libbcc.lib.bpf_map_lookup_elem.argtypes = [
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p
]
libbcc.lib.bpf_map_lookup_elem.restype = ctypes.c_int


# ==== STRUCT PHẢI KHỚP VỚI CODE C ====
class Accounting(ctypes.Structure):
    _fields_ = [
        ("time_in", ctypes.c_uint64),
        ("proc_time", ctypes.c_uint64),
        ("total_pkts", ctypes.c_uint32),
        ("total_bytes", ctypes.c_uint32),
    ]


def read_accounting(map_path: str):
    """Đọc entry duy nhất trong accounting_map"""
    map_fd = libbcc.lib.bpf_obj_get(map_path.encode("utf-8"))
    if map_fd < 0:
        raise OSError(f"Cannot open pinned map at {map_path}")

    key = ctypes.c_uint32(0)
    val = Accounting()
    ret = libbcc.lib.bpf_map_lookup_elem(map_fd, ctypes.byref(key), ctypes.byref(val))
    if ret != 0:
        raise OSError("Failed to read map element")
    return val


def compute_metrics(ac1: Accounting, ac2: Accounting, interval: float):
    """Tính throughput (B/s), latency (ns/pkt), PPS trong khoảng interval (giây)"""
    delta_bytes = ac2.total_bytes - ac1.total_bytes
    delta_pkts = ac2.total_pkts - ac1.total_pkts
    delta_proc = ac2.proc_time - ac1.proc_time  # ns

    throughput_bps = delta_bytes / interval if interval > 0 else 0
    avg_latency_ns = (delta_proc / delta_pkts) if delta_pkts > 0 else 0
    pps = delta_pkts / interval if interval > 0 else 0

    return throughput_bps, avg_latency_ns, pps


def main(map_path: str,
         csv_file: str = "throughput_latency.csv",
         interval: float = 1.0,
         duration: float = None):
    """
    map_path: đường dẫn pinned map
    csv_file: file CSV đầu ra
    interval: khoảng thời gian đo (giây)
    duration: tổng thời gian chạy (giây), None = chạy vô hạn
    """
    print(f"Đang đọc map {map_path}, ghi ra {csv_file} mỗi {interval:.1f}s...")
    if duration:
        print(f"Thời gian chạy tối đa: {duration:.1f}s\n")

    start_time = time.time()
    with open(csv_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "throughput_Bps", "pps", "latency_ns"])

        ac_prev = read_accounting(map_path)
        time_prev = start_time

        while True:
            time.sleep(interval)
            ac_now = read_accounting(map_path)
            time_now = time.time()

            throughput, latency, pps = compute_metrics(ac_prev, ac_now, time_now - time_prev)

            # Định dạng timestamp sang ngày giờ
            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            writer.writerow([
                timestamp_str,
                round(throughput, 6),  # MB/s
                round(pps, 3),
                round(latency, 3)      # µs
            ])
            f.flush()

            print(f"{timestamp_str} | "
                  f"Throughput = {throughput:.3f} B/s | "
                  f"PPS = {pps:.1f} | "
                  f"Latency = {latency:.2f} ns")

            ac_prev, time_prev = ac_now, time_now

            if duration and (time_now - start_time) >= duration:
                print(f"\nHoàn thành sau {duration:.1f}s, dữ liệu đã lưu tại {csv_file}")
                break


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: sudo {sys.argv[0]} /sys/fs/bpf/<iface>/accounting_map [output.csv] [duration_s]")
        sys.exit(1)

    map_path = sys.argv[1]
    csv_file = sys.argv[2] if len(sys.argv) > 2 else "throughput_latency.csv"
    duration = float(sys.argv[3]) if len(sys.argv) > 3 else None
    main(map_path, csv_file, duration=duration)
