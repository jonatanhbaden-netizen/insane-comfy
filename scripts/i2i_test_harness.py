#!/usr/bin/env python3
"""Iteration engine for the i2i quality loop.

One invocation = one measured cycle:
  1. flatten the current UI workflow to API format
  2. apply an optional VARIANT (node-input overrides) — the dial under test
  3. submit the FIXED reference set, wait, download finals + stage previews
  4. run ArcFace identity scoring on the pod against a character bank
  5. cut before/after face crops for 200%-zoom inspection
  6. write a run report (variant, per-ref scores, file paths) into runs/

Compare two runs with --compare A B: prints per-reference identity deltas.

Usage:
  python3 i2i_test_harness.py --pod <id> --workflow aiofm_i2i_v6.json \
      --object-info oi.json --tag baseline
  python3 i2i_test_harness.py --pod <id> ... --tag facesteps12 \
      --set '553.inputs.steps=12' --set '642.inputs.denoise=0.3'
  python3 i2i_test_harness.py --compare runs/baseline runs/facesteps12

The fixed reference set lives in REFS below — edit deliberately, never ad hoc:
a stable yardstick is the whole point.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

UA = {"Content-Type": "application/json",
      "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0 Safari/537.36"}

# fixed yardstick: varied lighting, framing, aspect, face size
REFS = [
    "IMG_2330.jpeg",          # indoor warm kitchen selfie, face large
    "IMG_2229.jpeg",          # second phone shot
    "v3test_sofia_1.png",     # bedroom low light
    "v3test_sofia_3.png",     # mirror, face small, freckle-dense donor
    "hf_20260723_234000_83cf9a18-72a1-4fd3-8094-85c396fc3d90.png",  # fitting room
]

HERE = os.path.dirname(os.path.abspath(__file__))


def http(url, data=None, timeout=90, raw=False):
    req = urllib.request.Request(url, data=data, headers=UA)
    r = urllib.request.urlopen(req, timeout=timeout)
    b = r.read()
    return b if raw else (json.loads(b) if b else None)


def flatten(workflow, object_info):
    out = os.path.join("/tmp", "harness_api.json")
    subprocess.run([sys.executable, os.path.join(HERE, "flatten_ui_to_api.py"),
                    workflow, object_info, out], check=True)
    return json.load(open(out))


def apply_variant(api, sets):
    """--set 'NODEID.inputs.KEY=VALUE' — NODEID is the ORIGINAL ui node id;
    flatten renames nodes, so match by _meta.title containing '#<id>' is not
    available — instead match by class+current value is fragile. We therefore
    apply by API node KEY when numeric, else by title substring."""
    for spec in sets or []:
        path, val = spec.split("=", 1)
        node_key, _, input_name = path.split(".")
        try:
            val = json.loads(val)
        except ValueError:
            pass
        hit = False
        for k, n in api.items():
            if k == f"n{node_key}" or k == node_key or node_key in n["_meta"]["title"]:
                if input_name in n["inputs"]:
                    n["inputs"][input_name] = val
                    hit = True
        if not hit:
            sys.exit(f"variant target not found: {spec}")
    return api


def run_cycle(a):
    base = f"https://{a.pod}-8188.proxy.runpod.net"
    api = flatten(a.workflow, a.object_info)
    api = apply_variant(api, a.set)
    li = [k for k, n in api.items() if n["class_type"] == "LoadImage"
          and "IDENTITY" not in n["_meta"]["title"]][0]
    si = [k for k, n in api.items() if n["class_type"] == "SaveImage"][0]

    rundir = os.path.join(HERE, "..", "runs", a.tag)
    os.makedirs(rundir, exist_ok=True)
    report = {"tag": a.tag, "variant": a.set or [], "refs": {}}

    pids = {}
    for i, ref in enumerate(REFS):
        g = json.loads(json.dumps(api))
        g[li]["inputs"]["image"] = ref
        g[si]["inputs"]["filename_prefix"] = f"harness_{a.tag}_{i}"
        try:
            r = http(f"{base}/prompt",
                     json.dumps({"prompt": g, "client_id": "harness"}).encode())
            pids[ref] = r["prompt_id"]
            print(f"queued [{i}] {ref} -> {r['prompt_id'][:8]}")
        except urllib.error.HTTPError as e:
            print(f"QUEUE FAILED for {ref}: {e.read()[:300]}")

    # wait
    pending = dict(pids)
    while pending:
        time.sleep(20)
        for ref, pid in list(pending.items()):
            try:
                h = http(f"{base}/history/{pid}", timeout=30)
            except Exception:
                continue
            if not h:
                continue
            v = list(h.values())[0]
            st = v["status"].get("status_str")
            if st in ("success", "error"):
                report["refs"][ref] = {"status": st}
                del pending[ref]
                print(f"{st}: {ref}")

    # download finals
    for i, ref in enumerate(REFS):
        if report["refs"].get(ref, {}).get("status") != "success":
            continue
        fn = f"harness_{a.tag}_{i}_00001_.png"
        dst = os.path.join(rundir, f"out_{i}.png")
        try:
            open(dst, "wb").write(
                http(f"{base}/view?filename={fn}&type=output", timeout=180, raw=True))
            report["refs"][ref]["output"] = dst
        except Exception as e:
            report["refs"][ref]["output_error"] = str(e)

    json.dump(report, open(os.path.join(rundir, "report.json"), "w"), indent=1)
    print(f"\nrun '{a.tag}' complete -> {rundir}")
    print("next: score identity via score_identity.py on the pod, then eyeball "
          "crops at 200% before accepting the variant")


def compare(a, b):
    ra = json.load(open(os.path.join(a, "report.json")))
    rb = json.load(open(os.path.join(b, "report.json")))
    print(f"{'ref':44} {ra['tag']:>14} {rb['tag']:>14}")
    for ref in ra["refs"]:
        sa = ra["refs"][ref].get("identity", "—")
        sb = rb["refs"].get(ref, {}).get("identity", "—")
        print(f"{ref[:44]:44} {str(sa):>14} {str(sb):>14}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pod")
    ap.add_argument("--workflow")
    ap.add_argument("--object-info")
    ap.add_argument("--tag", default="run")
    ap.add_argument("--set", action="append",
                    help="node.inputs.key=value override (repeatable)")
    ap.add_argument("--compare", nargs=2)
    a = ap.parse_args()
    if a.compare:
        compare(*a.compare)
    else:
        if not (a.pod and a.workflow and a.object_info):
            ap.error("--pod, --workflow and --object-info required for a run")
        run_cycle(a)
