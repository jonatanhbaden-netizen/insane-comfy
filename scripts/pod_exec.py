#!/usr/bin/env python3
"""Run commands on a RunPod pod through JupyterLab.

RunPod's proxy SSH never works with this image: start.sh execs ComfyUI directly
and no sshd is ever launched, so the proxy connects and then hangs at the
banner. Jupyter is the working remote shell — set JUPYTER_PASSWORD on the pod
(it becomes the token) and this drives a kernel over the same HTTPS proxy.

    python3 pod_exec.py --pod xhdpa8jf73tgqr --token <tok> "ls -la /workspace"
    python3 pod_exec.py --pod xhdpa8jf73tgqr --token <tok> --python script.py

Everything goes through the Cloudflare-fronted proxy, so a browser User-Agent
is mandatory — plain requests get a 403 on anything that isn't a GET.
"""
import argparse
import json
import sys
import uuid

import requests
import websocket

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/146.0 Safari/537.36")


def run(base, token, code, timeout=600):
    """Execute code in a fresh kernel; return (stdout, stderr)."""
    http = base.rstrip("/")
    ws_base = http.replace("https://", "wss://").replace("http://", "ws://")
    headers = {"User-Agent": UA, "Authorization": f"token {token}"}

    r = requests.post(f"{http}/api/kernels", headers=headers,
                      json={"name": "python3"}, timeout=60)
    r.raise_for_status()
    kid = r.json()["id"]

    out, err = [], []
    try:
        ws = websocket.create_connection(
            f"{ws_base}/api/kernels/{kid}/channels?token={token}",
            header=[f"User-Agent: {UA}"], timeout=timeout)
        msg_id = uuid.uuid4().hex
        ws.send(json.dumps({
            "header": {"msg_id": msg_id, "username": "x", "session": uuid.uuid4().hex,
                       "msg_type": "execute_request", "version": "5.3"},
            "parent_header": {}, "metadata": {},
            "content": {"code": code, "silent": False, "store_history": False,
                        "user_expressions": {}, "allow_stdin": False,
                        "stop_on_error": True},
            "channel": "shell",
        }))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            t = msg["msg_type"]
            c = msg["content"]
            if t == "stream":
                (out if c["name"] == "stdout" else err).append(c["text"])
            elif t == "error":
                err.append("\n".join(c.get("traceback", [])))
            elif t in ("execute_result", "display_data"):
                out.append(c.get("data", {}).get("text/plain", ""))
            elif t == "status" and c.get("execution_state") == "idle":
                break
        ws.close()
    finally:
        requests.delete(f"{http}/api/kernels/{kid}", headers=headers, timeout=30)

    return "".join(out), "".join(err)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", nargs="?", help="shell command to run")
    ap.add_argument("--pod", help="pod id (builds the proxy URL)")
    ap.add_argument("--url", help="full Jupyter base URL (overrides --pod)")
    ap.add_argument("--token", required=True)
    ap.add_argument("--python", help="run this local .py file on the pod instead")
    ap.add_argument("--timeout", type=int, default=1800)
    a = ap.parse_args()

    base = a.url or f"https://{a.pod}-8888.proxy.runpod.net"
    if a.python:
        code = open(a.python).read()
    elif a.command:
        # bang-escape so shell output streams back through the kernel
        code = ("import subprocess,sys\n"
                "p=subprocess.run(%r, shell=True, capture_output=True, text=True)\n"
                "sys.stdout.write(p.stdout)\n"
                "sys.stderr.write(p.stderr)\n"
                "print('[exit %%d]'%%p.returncode)" % a.command)
    else:
        ap.error("give a command or --python")

    out, err = run(base, a.token, code, a.timeout)
    if out:
        print(out, end="")
    if err:
        print(err, end="", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
