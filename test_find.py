import psutil

print("=== Processes with 'python' in cmdline ===")
for p in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmdline = p.info.get('cmdline')
        if cmdline:
            cmdline_str = ' '.join(cmdline)
            if 'mock' in cmdline_str.lower():
                print(f"PID: {p.info['pid']}, CMD: {cmdline_str}")
    except:
        pass

print("\n=== Connections on port 9000 ===")
for conn in psutil.net_connections(kind='inet'):
    if conn.laddr:
        if conn.laddr.port == 9000:
            print(f"PID: {conn.pid}, Status: {conn.status}")