"""
Service Killer Script for Testing Self-Healing Dashboard.
Simulates service failure by killing the target process.
"""
import os
import signal
import sys
import psutil


TARGET_SCRIPTS = ["mock_service.py", "mock_service"]


def main():
    port = 9000

    # Find process by port
    pid = None
    for conn in psutil.net_connections(kind='inet'):
        if conn.laddr and conn.laddr.port == port and conn.status == 'LISTEN':
            if conn.pid and conn.pid != 0:
                pid = conn.pid
                break

    # Fallback: find by script name
    if not pid:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline') or []
                cmdline_str = ' '.join(cmdline)
                if any(t.lower() in cmdline_str.lower() for t in TARGET_SCRIPTS):
                    pid = proc.info['pid']
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    if not pid:
        print(f"[!] No process found on port {port} or running mock_service.py")
        print("Make sure mock_service.py is running first!")
        sys.exit(1)

    print(f"[KILL] Found process PID: {pid}")

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"[OK] Process {pid} terminated")
        print("[TEST] Dashboard should detect failure in ~2 seconds and attempt recovery")
    except OSError as e:
        print(f"[!] Failed to kill process: {e}")


if __name__ == "__main__":
    main()