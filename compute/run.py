"""Entry point: python run.py"""
import socket
import uvicorn

def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == "__main__":
    ip = _lan_ip()
    print(f"\n  Compute worker → http://{ip}:8001\n", flush=True)
    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=True)
