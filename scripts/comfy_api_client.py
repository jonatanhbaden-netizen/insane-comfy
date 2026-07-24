#!/usr/bin/env python3
"""Minimal ComfyUI API client — queue a workflow, wait, list/download outputs.

Works with API-format workflow JSON (in ComfyUI: Workflow menu ->
"Export (API)"). The two shipped workflows are UI-format for editing;
export an API copy of your tuned setup once, then drive it headless:

    python3 comfy_api_client.py wf_api.json \
        --host http://127.0.0.1:8188 \
        --set "12.inputs.text=a cinematic portrait ..." \
        --set "28.inputs.seed=1234" \
        --out ./results

--set paths are <node_id>.inputs.<field>=<value>; values are auto-coerced
to int/float/bool when they look like one. No external dependencies.
"""

import argparse
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request
import uuid


def coerce(value: str):
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value


def apply_set(wf: dict, expr: str):
    path, _, raw = expr.partition("=")
    if not _:
        sys.exit(f"bad --set (need path=value): {expr}")
    keys = path.split(".")
    node = wf
    for key in keys[:-1]:
        if key not in node:
            sys.exit(f"--set path not found in workflow: {path} (missing '{key}')")
        node = node[key]
    node[keys[-1]] = coerce(raw)


def post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workflow", help="API-format workflow JSON file")
    ap.add_argument("--host", default="http://127.0.0.1:8188")
    ap.add_argument("--set", action="append", default=[], metavar="PATH=VALUE",
                    help="override an input, e.g. 28.inputs.seed=42 (repeatable)")
    ap.add_argument("--out", default=None,
                    help="download image/video outputs into this directory")
    ap.add_argument("--timeout", type=int, default=3600,
                    help="max seconds to wait for the job (default 3600)")
    args = ap.parse_args()

    wf = json.loads(pathlib.Path(args.workflow).read_text())
    for expr in args.set:
        apply_set(wf, expr)

    client_id = str(uuid.uuid4())
    queued = post_json(f"{args.host}/prompt", {"prompt": wf, "client_id": client_id})
    if "prompt_id" not in queued:
        sys.exit(f"queue rejected: {json.dumps(queued, indent=2)}")
    pid = queued["prompt_id"]
    print(f"queued: {pid}")

    deadline = time.time() + args.timeout
    entry = None
    while time.time() < deadline:
        history = get_json(f"{args.host}/history/{pid}")
        if pid in history:
            entry = history[pid]
            break
        time.sleep(3)
    if entry is None:
        sys.exit("timed out waiting for job")

    status = entry.get("status", {})
    if status.get("status_str") == "error":
        print(json.dumps(status, indent=2))
        sys.exit("job errored — see status above")

    files = []
    for node_id, out in entry.get("outputs", {}).items():
        for kind in ("images", "gifs", "videos"):
            for item in out.get(kind, []):
                files.append(item)
                print(f"output [{node_id}] {item.get('subfolder','')}/{item['filename']}")

    if args.out:
        dest = pathlib.Path(args.out)
        dest.mkdir(parents=True, exist_ok=True)
        for item in files:
            query = urllib.parse.urlencode({
                "filename": item["filename"],
                "subfolder": item.get("subfolder", ""),
                "type": item.get("type", "output"),
            })
            target = dest / item["filename"]
            with urllib.request.urlopen(f"{args.host}/view?{query}") as resp:
                target.write_bytes(resp.read())
            print(f"saved {target}")

    print("done")


if __name__ == "__main__":
    main()
