"""
AgenticLiner - Easy Live Server Launcher
Usage:
    python run.py
"""
import sys
import uvicorn
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

if __name__ == "__main__":
    host = "127.0.0.1"
    port = 8000
    print("=" * 65)
    print(f"🚀 Starting AgenticLiner Platform at http://{host}:{port}")
    print("   Press CTRL+C to stop the server.")
    print("=" * 65)
    uvicorn.run("backend.api.main:app", host=host, port=port, reload=True)
