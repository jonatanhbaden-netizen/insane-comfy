"""Wait for new pod boot -> run refetch script -> verify Animate stack."""
import json, os, ssl, sys, time, urllib.request

sys.path.insert(0, "/Users/jonatanbaden/Desktop/AIOFM SYSTEM/telegram-bot")
import runpod_ctl
import websocket

POD = __import__("os").environ.get("POD_ID", "aixyeznme5subj")
TOK = (runpod_ctl._req("GET", f"/pods/{POD}").get("env") or {}).get("JUPYTER_PASSWORD", "")
J = f"https://{POD}-8888.proxy.runpod.net"
C = f"https://{POD}-8188.proxy.runpod.net"
UA = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}


def up(url):
    try:
        r = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        urllib.request.urlopen(r, timeout=15)
        return True
    except Exception:
        return False


t0 = time.time()
while time.time() - t0 < 40 * 60:
    if up(f"{J}/api/status?token={TOK}") or up(f"{J}/api/terminals?token={TOK}"):
        break
    el = int(time.time() - t0)
    if el and el % 300 < 20:
        print(f"still booting… {el//60} min", flush=True)
    time.sleep(20)
else:
    print("TIMEOUT: jupyter never came up in 40 min"); sys.exit(1)

print(f"jupyter up after {int(time.time()-t0)//60} min — launching refetch", flush=True)
req = urllib.request.Request(f"{J}/api/terminals?token={TOK}", data=b"{}", headers=UA, method="POST")
term = json.loads(urllib.request.urlopen(req, timeout=30).read())["name"]
ws = websocket.create_connection(
    f"wss://{POD}-8888.proxy.runpod.net/terminals/websocket/{term}?token={TOK}",
    header={"User-Agent": "Mozilla/5.0"}, sslopt={"cert_reqs": ssl.CERT_REQUIRED}, timeout=20)
ws.send(json.dumps(["stdin", "nohup bash /workspace/refetch_local_models.sh > /workspace/refetch.log 2>&1 & echo GO\n"]))
time.sleep(5)
ws.close()

# poll the log until DONE
def log():
    try:
        r = urllib.request.Request(f"{J}/api/contents/refetch.log?token={TOK}",
                                   headers={"User-Agent": "Mozilla/5.0"})
        return json.loads(urllib.request.urlopen(r, timeout=30).read()).get("content") or ""
    except Exception:
        return ""

t1 = time.time()
while time.time() - t1 < 30 * 60:
    s = log()
    if "DONE" in s:
        oks = s.count("OK "); fails = s.count("FAIL ")
        print(f"refetch finished: {oks} OK, {fails} FAIL", flush=True)
        if fails:
            print(s[-800:])
        break
    time.sleep(30)
else:
    print("refetch timed out; log tail:"); print(log()[-500:]); sys.exit(1)

# verify via ComfyUI
for _ in range(40):
    if up(f"{C}/system_stats"):
        break
    time.sleep(15)
try:
    r = urllib.request.Request(f"{C}/object_info", headers={"User-Agent": "Mozilla/5.0"})
    oi = json.loads(urllib.request.urlopen(r, timeout=120).read())
    checks = {
        "pose pack": "OnnxDetectionModelLoader" in oi,
        "detection models": bool(oi.get("OnnxDetectionModelLoader", {}).get("input", {}).get("required", {}).get("vitpose_model", [[]])[0]),
        "Animate model": any("Animate" in m for m in oi.get("WanVideoModelLoader", {}).get("input", {}).get("required", {}).get("model", [[]])[0]),
        "relight LoRA": any("relight" in l for l in oi.get("LoraLoaderModelOnly", {}).get("input", {}).get("required", {}).get("lora_name", [[]])[0]),
        "clip_vision_h": "clip_vision_h.safetensors" in oi.get("CLIPVisionLoader", {}).get("input", {}).get("required", {}).get("clip_name", [[]])[0],
    }
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print("NEW POD READY — refresh browser and run" if all(checks.values())
          else "some checks failed — may need a ComfyUI refresh, or tell me")
except Exception as e:
    print("comfy verify failed (may just need more boot time):", e)
