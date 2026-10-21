"""
ComplianceAI - one-command launcher for the whole system.

    python run.py              start scanner + admin + portfolio
    python run.py --no-web     skip the portfolio static server
    python run.py --open       open the scanner in a browser on start

Ports:
    5000  scanner API + UI        http://127.0.0.1:5000
    5001  admin console           http://127.0.0.1:5001/admin
    5500  ML portfolio            http://127.0.0.1:5500/index.html
"""
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend")

SCANNER_PORT = 5000
ADMIN_PORT = int(os.environ.get("ADMIN_PORT", 5001))
PORTFOLIO_PORT = 5500

SERVICES = []


def port_open(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((host, port)) == 0


def wait_for_port(port, name, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port):
            print(f"  [ok]   {name:<10} http://127.0.0.1:{port}")
            return True
        time.sleep(0.5)
    print(f"  [warn] {name:<10} did not answer on port {port} within {timeout}s")
    return False


def stream(prefix, proc):
    """Pipe a child's stdout to ours, tagged with the service name."""
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            print(f"[{prefix}] {line}", flush=True)
    proc.wait()


def start(name, args, cwd, env=None):
    full_env = dict(os.environ)
    # children print box-drawing / em-dash banners -> force UTF-8 on the pipe
    full_env["PYTHONIOENCODING"] = "utf-8"
    if env:
        full_env.update(env)
    proc = subprocess.Popen(
        [sys.executable] + args,
        cwd=cwd,
        env=full_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    SERVICES.append((name, proc))
    threading.Thread(target=stream, args=(name, proc), daemon=True).start()
    return proc


def stop_all():
    print("\nShutting down...")
    for name, proc in SERVICES:
        if proc.poll() is None:
            proc.terminate()
    deadline = time.time() + 6
    for name, proc in SERVICES:
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.2)
        if proc.poll() is None:
            proc.kill()
        print(f"  stopped {name}")


def main():
    args = sys.argv[1:]
    with_web = "--no-web" not in args
    open_browser = "--open" in args

    print("=" * 62)
    print(" ComplianceAI - Legal Metrology compliance platform")
    print("=" * 62)

    for port, name in ((SCANNER_PORT, "scanner"), (ADMIN_PORT, "admin"), (PORTFOLIO_PORT, "portfolio")):
        if port_open(port):
            print(f"  [busy] port {port} is already in use - {name} may already be running")
            if name in ("scanner", "admin"):
                print(f"         http://127.0.0.1:{port}")
                return 1

    if not os.path.exists(os.path.join(BACKEND, "compliance.db")):
        print("  [note] first run - database will be created on start")

    print("  starting services...")
    start("scanner", ["app.py"], BACKEND, {"PORT": str(SCANNER_PORT)})
    start("admin", ["admin_app.py"], BACKEND, {"ADMIN_PORT": str(ADMIN_PORT)})
    if with_web:
        start("portfolio", ["-m", "http.server", str(PORTFOLIO_PORT), "--directory", FRONTEND], ROOT)

    print("\n  waiting for services...")
    wait_for_port(SCANNER_PORT, "scanner")
    wait_for_port(ADMIN_PORT, "admin")
    if with_web:
        wait_for_port(PORTFOLIO_PORT, "portfolio")

    print("\n" + "-" * 62)
    print("  Scanner API    http://127.0.0.1:%d" % SCANNER_PORT)
    print("  Admin console  http://127.0.0.1:%d/admin   (admin / admin123)" % ADMIN_PORT)
    if with_web:
        print("  Portfolio      http://127.0.0.1:%d/index.html" % PORTFOLIO_PORT)
    print("-" * 62)
    print("  Press Ctrl+C to stop everything.\n")

    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{SCANNER_PORT}")

    try:
        while True:
            time.sleep(1)
            for name, proc in SERVICES:
                if proc.poll() is not None:
                    print(f"[{name}] exited with code {proc.returncode}")
                    stop_all()
                    return proc.returncode or 0
    except KeyboardInterrupt:
        stop_all()
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        stop_all()
        raise
