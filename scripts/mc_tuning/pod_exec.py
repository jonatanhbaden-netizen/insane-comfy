"""Run a command on the pod via Jupyter terminal websocket.

Usage: pod_exec.py '<command>'
Starts the command, echoes early output, exits (command continues pod-side).
"""
import json, ssl, sys, time, urllib.request
import websocket

sys.path.insert(0, "/Users/jonatanbaden/Desktop/AIOFM SYSTEM/telegram-bot")
import runpod_ctl

POD = __import__("os").environ.get("POD_ID", "aixyeznme5subj")
TOK = (runpod_ctl._req("GET", f"/pods/{POD}").get("env") or {}).get("JUPYTER_PASSWORD", "")
BASE = f"https://{POD}-8888.proxy.runpod.net"
CMD = sys.argv[1]

req = urllib.request.Request(f"{BASE}/api/terminals?token={TOK}", data=b"{}",
    headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}, method="POST")
term = json.loads(urllib.request.urlopen(req, timeout=30).read())["name"]
print(f"terminal {term} opened", flush=True)

ws = websocket.create_connection(
    f"wss://{POD}-8888.proxy.runpod.net/terminals/websocket/{term}?token={TOK}",
    header={"User-Agent": "Mozilla/5.0"}, sslopt={"cert_reqs": ssl.CERT_REQUIRED},
    timeout=20)
ws.send(json.dumps(["stdin", CMD + "\n"]))

t0 = time.time()
buf = ""
while time.time() - t0 < 25:
    try:
        frame = json.loads(ws.recv())
        if frame[0] == "stdout":
            buf += frame[1]
    except Exception:
        break
# strip ANSI junk for readability
import re
clean = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\r", "", buf)
print("--- early output ---")
print(clean[-2000:])
ws.close()
