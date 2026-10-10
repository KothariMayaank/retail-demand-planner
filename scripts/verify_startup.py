"""Start a temporary local server, verify HTTP readiness, then stop that server."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen


def verify(port: int, entrypoint: str = "app.py") -> None:
    root = Path(__file__).resolve().parents[1]
    if entrypoint not in ("app.py", "cloud_app.py"):
        raise ValueError("Use app.py or cloud_app.py as the entry point.")
    command = [sys.executable, "-m", "streamlit", "run", entrypoint,
               "--server.port", str(port), "--server.address", "127.0.0.1",
               "--server.headless", "true"]
    with tempfile.TemporaryFile(mode="w+b") as log:
        process = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
        try:
            last_error = None
            for _ in range(40):
                if process.poll() is not None:
                    raise RuntimeError("Streamlit exited before becoming ready.")
                try:
                    with urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
                        if response.status == 200 and response.read().strip() == b"ok":
                            # A short grace period catches an occupied-port process exiting.
                            time.sleep(0.5)
                            if process.poll() is not None:
                                raise RuntimeError("The temporary server exited after the health check.")
                            with urlopen(f"http://127.0.0.1:{port}/", timeout=2) as page:
                                if page.status != 200 or b"<html" not in page.read().lower():
                                    raise RuntimeError("The dashboard HTML was not served.")
                            print(f"PASS: Streamlit health and dashboard HTTP responses on port {port}.")
                            return
                except (URLError, TimeoutError, OSError) as exc:
                    last_error = exc
                time.sleep(0.25)
            raise RuntimeError(f"Streamlit did not become ready: {last_error}")
        except Exception:
            log.seek(0)
            print(log.read().decode("utf-8", errors="replace"), file=sys.stderr)
            raise
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--entrypoint", choices=["app.py", "cloud_app.py"], default="app.py")
    args = parser.parse_args()
    verify(args.port, args.entrypoint)
