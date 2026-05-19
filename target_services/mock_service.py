"""
Mock HTTP Service for Testing.
A simple HTTP server that provides health check endpoint and can be "killed" for testing.
"""
import json
import socket
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import signal
import os


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP request handler with health endpoint."""

    def log_message(self, format, *args):
        """Override to customize logging output."""
        sys.stdout.write(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}\n")
        sys.stdout.flush()

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/health" or self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {
                "status": "healthy",
                "service": "mock_api",
                "timestamp": datetime.now().isoformat(),
                "pid": os.getpid()
            }
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_HEAD(self):
        """Handle HEAD requests."""
        self.send_response(200)
        self.end_headers()


def find_free_port(start_port: int = 9000, max_attempts: int = 100) -> int:
    """Find a free port to bind to."""
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("localhost", port))
                return port
        except OSError:
            continue
    raise RuntimeError("Could not find free port")


def run_server(port: int):
    """Run the HTTP server."""
    server_address = ("localhost", port)
    httpd = HTTPServer(server_address, HealthHandler)

    print(f"[START] Mock service started on http://localhost:{port}")
    print(f"[PID]   Process ID: {os.getpid()}")
    print(f"[HEALTH] Health check: http://localhost:{port}/health")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[STOP] Server shutdown requested")
        httpd.shutdown()


def get_running_port() -> int:
    """Get the port from command line argument or use default."""
    if len(sys.argv) > 1:
        try:
            return int(sys.argv[1])
        except ValueError:
            pass
    return 9000


if __name__ == "__main__":
    port = get_running_port()

    # Allow port override via environment variable
    if env_port := os.getenv("MOCK_SERVICE_PORT"):
        port = int(env_port)

    run_server(port)