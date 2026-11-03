"""
AgenticLiner - Easy Live Server Launcher
Usage:
    python run.py
"""
import os
import sys
import uvicorn
from dotenv import load_dotenv, find_dotenv

# Safe utf-8 handling on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv(find_dotenv(usecwd=True))
os.environ.setdefault("ALLOW_DEMO_LOGIN", "1")

if __name__ == "__main__":
    host = "127.0.0.1"
    port = 8000
    print("=" * 65)
    print(f"[*] Starting AgenticLiner Platform at http://{host}:{port}")
    print("    Press CTRL+C to stop the server.")
    print("=" * 65)
    uvicorn.run("backend.api.main:app", host=host, port=port, reload=True)
