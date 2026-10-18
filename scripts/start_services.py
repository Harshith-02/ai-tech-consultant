import os
import sys
import subprocess
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():
    VENV_PYTHON = Path(sys.executable)

TASK1_DIR = BASE_DIR / "task1-knowledge-brain"
TASK2_DIR = BASE_DIR / "task2-inbox-agent"
TASK3_DIR = BASE_DIR / "task3-meeting-to-scope"
DASHBOARD_DIR = BASE_DIR / "dashboard"

def start_all():
    print("=" * 65)
    print("STARTING AI TECH CONSULTANT (3 CONNECTED SERVICES + DASHBOARD)")
    print("=" * 65)

    processes = []

    # 1. Start Task 1: Knowledge Brain (FastAPI on Port 8000)
    print("\n[1/4] Launching Task 1: Knowledge Brain API on http://127.0.0.1:8000 ...")
    p1 = subprocess.Popen(
        [str(VENV_PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(TASK1_DIR)
    )
    processes.append(("Task 1: Knowledge Brain (Port 8000)", p1))
    time.sleep(2)

    # 2. Start Task 2: Inbox Agent (Node.js on Port 3001)
    print("\n[2/4] Launching Task 2: Inbox Agent API on http://127.0.0.1:3001 ...")
    p2 = subprocess.Popen(
        ["node", "dist/server.js"],
        cwd=str(TASK2_DIR),
        shell=True
    )
    processes.append(("Task 2: Inbox Agent (Port 3001)", p2))
    time.sleep(1.5)

    # 3. Start Task 3: Meeting to Scope (FastAPI on Port 8002)
    print("\n[3/4] Launching Task 3: Meeting to Scope API on http://127.0.0.1:8002 ...")
    p3 = subprocess.Popen(
        [str(VENV_PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8002"],
        cwd=str(TASK3_DIR)
    )
    processes.append(("Task 3: Meeting to Scope (Port 8002)", p3))
    time.sleep(2)

    # 4. Start Unified Dashboard (HTTP on Port 5000)
    print("\n[4/4] Launching Unified Web Dashboard on http://127.0.0.1:5000 ...")
    p4 = subprocess.Popen(
        [str(VENV_PYTHON), "server.py"],
        cwd=str(DASHBOARD_DIR)
    )
    processes.append(("Unified Dashboard (Port 5000)", p4))

    print("\n" + "=" * 65)
    print("ALL SERVICES OPERATIONAL!")
    print("Open your browser at: http://127.0.0.1:5000")
    print("Press Ctrl+C to terminate all services.")
    print("=" * 65 + "\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down all services...")
        for name, p in processes:
            print(f"Stopping {name}...")
            p.terminate()
        print("All services stopped.")

if __name__ == "__main__":
    start_all()
