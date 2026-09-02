"""
ProStream Entry Point
Run directly with: python main.py
"""
import uvicorn
from app.config import PORT, HOST

if __name__ == "__main__":
    print(f"🚀 Starting ProStream Downloader on http://localhost:{PORT}")
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
