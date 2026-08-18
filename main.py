import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from config import Config
from core.assistant import Assistant


def backend_is_up() -> bool:
    try:
        return requests.get(f"{Config.BACKEND_URL}/health", timeout=1).status_code == 200
    except requests.RequestException:
        return False


def _print_backend_log(log_path) -> None:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in lines[-15:]:
        print(f"    {line}")


def ensure_backend():
    """Start the local brain service automatically if it is not already running."""
    if Config.ASSISTANT_MODE == "offline" or backend_is_up():
        return None
    address = urlparse(Config.BACKEND_URL)
    print("[Status] Starting the local brain service...")
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "backend.log"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    log_file = open(log_path, "w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            address.hostname or "127.0.0.1",
            "--port",
            str(address.port or 8000),
        ],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )
    for _ in range(30):
        if backend_is_up():
            print("[Status] Brain service is ready.")
            return process
        if process.poll() is not None:
            print(f"[Status] Brain service failed to start. Last lines of {log_path}:")
            log_file.flush()
            _print_backend_log(log_path)
            print("[Status] Continuing with local commands only.")
            return None
        time.sleep(0.5)
    print("[Status] Brain service is taking a while; continuing while it finishes starting.")
    return process


def main():
    process = ensure_backend()
    try:
        Assistant().run()
    finally:
        if process is not None and process.poll() is None:
            process.terminate()


if __name__ == "__main__":
    main()
