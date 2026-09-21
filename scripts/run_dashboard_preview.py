"""Autonomous Futures Bot — Integrated Dashboard Preview Runner.

Launches both FastAPI backend and Vite frontend development server concurrently,
verifies health and connectivity, and coordinates clean process termination.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
FRONTEND_HOST = "127.0.0.1"
FRONTEND_PORT = 5173


def is_port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def wait_for_http(url: str, timeout: float = 15.0, description: str = "service") -> bool:
    start_time = time.monotonic()
    while time.monotonic() - start_time < timeout:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AFBot-Preview-Probe/1.0"})
            with urllib.request.urlopen(req, timeout=1.0) as response:
                if response.status in (200, 304):
                    return True
        except urllib.error.URLError, ConnectionError, TimeoutError, OSError:
            time.sleep(0.3)
    return False


def main() -> int:
    root_dir = Path(__file__).resolve().parent.parent
    frontend_dir = root_dir / "frontend"

    print("=" * 68)
    print(" AUTONOMOUS FUTURES BOT — LIVE LOCAL PREVIEW LAUNCHER")
    print("=" * 68)

    env = os.environ.copy()
    src_dir = str(root_dir / "src")
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = src_dir

    backend_proc: subprocess.Popen[bytes] | None = None
    frontend_proc: subprocess.Popen[bytes] | None = None

    # 1. Start FastAPI Backend if not already running
    if is_port_in_use(BACKEND_HOST, BACKEND_PORT):
        print(f"[+] Backend port {BACKEND_PORT} is already active. Probing /health...")
        if not wait_for_http(
            f"http://{BACKEND_HOST}:{BACKEND_PORT}/health", timeout=3.0, description="backend"
        ):
            print(f"[!] Port {BACKEND_PORT} in use by another service. Aborting.")
            return 1
        print("[+] Existing FastAPI backend verified healthy.")
    else:
        print(f"[*] Starting FastAPI backend on http://{BACKEND_HOST}:{BACKEND_PORT}...")
        backend_cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "autonomous_futures.api.app:app",
            "--host",
            BACKEND_HOST,
            "--port",
            str(BACKEND_PORT),
            "--log-level",
            "info",
        ]
        backend_proc = subprocess.Popen(backend_cmd, cwd=root_dir, env=env)
        if not wait_for_http(
            f"http://{BACKEND_HOST}:{BACKEND_PORT}/health", timeout=12.0, description="backend"
        ):
            print("[!] Failed to verify backend health on port 8000 within timeout.")
            if backend_proc:
                backend_proc.terminate()
            return 1
        print("[+] FastAPI backend verified healthy.")

    # 2. Start Vite Frontend if not already running
    if is_port_in_use(FRONTEND_HOST, FRONTEND_PORT):
        print(f"[+] Frontend port {FRONTEND_PORT} is already active. Probing index...")
        if not wait_for_http(
            f"http://{FRONTEND_HOST}:{FRONTEND_PORT}/", timeout=3.0, description="frontend"
        ):
            print(f"[!] Port {FRONTEND_PORT} in use by another service.")
            return 1
        print("[+] Existing Vite frontend server verified active.")
    else:
        print(
            f"[*] Starting Vite frontend development server on http://{FRONTEND_HOST}:{FRONTEND_PORT}..."
        )
        is_windows = sys.platform.startswith("win")
        npm_cmd = "npm.cmd" if is_windows else "npm"
        frontend_cmd = [
            npm_cmd,
            "run",
            "dev",
            "--",
            "--host",
            FRONTEND_HOST,
            "--port",
            str(FRONTEND_PORT),
        ]
        frontend_proc = subprocess.Popen(frontend_cmd, cwd=frontend_dir, shell=is_windows)
        if not wait_for_http(
            f"http://{FRONTEND_HOST}:{FRONTEND_PORT}/", timeout=15.0, description="frontend"
        ):
            print("[!] Failed to connect to Vite development server within timeout.")
            if frontend_proc:
                frontend_proc.terminate()
            if backend_proc:
                backend_proc.terminate()
            return 1
        print("[+] Vite frontend server verified ready.")

    print("\n" + "=" * 68)
    print(" LIVE PREVIEW READY — OPEN IN YOUR BROWSER:")
    print(f"  --> Web App Dashboard: http://localhost:{FRONTEND_PORT}/")
    print(f"  --> Backend API Health: http://localhost:{BACKEND_PORT}/health")
    print(f"  --> Telemetry Summary:  http://localhost:{BACKEND_PORT}/api/v1/canary/summary")
    print(f"  --> Hawkes Snapshot:   http://localhost:{BACKEND_PORT}/api/v1/canary/hawkes")
    print(f"  --> Risk Controls:     http://localhost:{BACKEND_PORT}/api/v1/canary/risk")
    print(f"  --> Double-Entry Ledger: http://localhost:{BACKEND_PORT}/api/v1/canary/accounting")
    print("=" * 68)
    print(" Press Ctrl+C to stop both servers cleanly.\n")

    def cleanup(signum: int, frame: object) -> None:
        print("\n[*] Shutting down preview servers cleanly...")
        if frontend_proc and frontend_proc.poll() is None:
            frontend_proc.terminate()
            try:
                frontend_proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                frontend_proc.kill()
        if backend_proc and backend_proc.poll() is None:
            backend_proc.terminate()
            try:
                backend_proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                backend_proc.kill()
        print("[+] Shutdown complete.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        while True:
            if backend_proc and backend_proc.poll() is not None:
                print("[!] Backend server exited unexpectedly.")
                break
            if frontend_proc and frontend_proc.poll() is not None:
                print("[!] Frontend server exited unexpectedly.")
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        cleanup(signal.SIGINT, None)

    return 0


if __name__ == "__main__":
    sys.exit(main())
