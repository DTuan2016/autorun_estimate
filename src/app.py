from flask import Flask, request, jsonify
import subprocess
import threading
import yaml
import os

app = Flask(__name__)

config = "config.yaml"

with open(config, "r") as f:
    cfg = yaml.safe_load(f)

LOG_LANFORGE = cfg["results"]["lanforge"]
os.mkdir(LOG_LANFORGE)
PCAP_FILE = cfg["results"]["pcap_file"]
SCRIPTS_REPLAY = cfg["scripts_tcpreplay"]
IFACE = cfg["iface_lanforge"]

def run_async(cmd):
    """Run tcpreplay in background"""
    try:
        print(f"[INFO] Running async command: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
        print("[INFO] tcpreplay finished successfully.")
    except Exception as e:
        print(f"[ERROR] tcpreplay failed: {e}")

@app.route("/run", methods=["POST"])
def run_tcpreplay():
    """API: receive request to run tcpreplay with pps"""
    data = request.json or {}
    log_file = data.get("log", "default.log")
    speed = int(data.get("speed", 100000))

    # Validate input
    if not (10000 <= speed <= 100000):
        return jsonify({"status": "error", "message": "speed must be between 10000 and 100000"}), 400

    cmd = [
        SCRIPTS_REPLAY,
        IFACE,
        PCAP_FILE,
        str(speed),
        "125",
        log_file
    ]

    threading.Thread(target=run_async, args=(cmd,), daemon=True).start()

    print(f"[INFO] Started tcpreplay at {speed} PPS (log={log_file})")
    return jsonify({
        "status": "ok",
        "message": f"Started tcpreplay at {speed} PPS (log={log_file})"
    })

@app.route("/run_acc", methods=["POST"])
def run_acc():
    """Blocking version — chỉ trả về khi tcpreplay kết thúc"""
    cmd = ["sudo", "tcpreplay", "-i", IFACE, "--limit=10000", PCAP_FILE]
    result = subprocess.run(cmd, capture_output=True, text=True)

    return jsonify({
        "status": "ok" if result.returncode == 0 else "error",
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.returncode
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=20168)
