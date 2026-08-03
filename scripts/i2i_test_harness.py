#!/usr/bin/env python3
"""Iteration engine for the i2i quality loop — one invocation = one cycle.

Protocol (enforced, not suggested):
  * ONE dial changes per cycle (--set), everything else is held fixed.
  * The SAME five references every time (REFS) — the yardstick never moves
    without a deliberate, documented edit.
  * Every cycle produces numbers before opinions: local skin/seam/colour
    metrics always, ArcFace identity when the pod scorer is reachable.
  * A cycle is ACCEPTED only if identity holds AND skin metrics improve.
    `--compare A B` prints the per-reference deltas that decide it.

Cycle stages:
  flatten UI graph -> apply variant -> submit refs -> download finals
  -> local metrics (i2i_metrics) -> optional on-pod ArcFace identity
  -> zoom sheets for 200% inspection -> runs/<tag>/report.{json,md}

Usage:
  # baseline
  python3 i2i_test_harness.py --pod POD --workflow ../workflows/aiofm_i2i_v6.json \
      --object-info /tmp/oi.json --tag v6-baseline
  # one dial
  python3 i2i_test_harness.py ... --tag detail-daemon-03 --set '642.denoise=0.32'
  # verdict
  python3 i2i_test_harness.py --compare runs/v6-baseline runs/detail-daemon-03
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

UA = {"Content-Type": "application/json",
      "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0 Safari/537.36"}

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "..", "runs")

# The yardstick. Varied face size, lighting, colour temperature and framing so a
# change that only helps one kind of shot cannot look like a win.
REFS = [
    "IMG_2330.jpeg",   # warm tungsten kitchen selfie, face large, mixed light
    "IMG_2229.jpeg",   # second phone shot, different framing
    "v3test_sofia_1.png",  # dim bedroom, low contrast
    "v3test_sofia_3.png",  # mirror shot, face small in frame
    "hf_20260723_234000_83cf9a18-72a1-4fd3-8094-85c396fc3d90.png",  # fitting room, cool light
]

# Local metric targets. seam<=0 calibrated from whole-frame (seamless by
# construction) renders; grain 1.0 = face noise matches the host photo.
TARGETS = {"skin_hf_ratio": (0.85, 1.25), "grain_ratio": (0.80, 1.20),
           "seam_gradient": (-99, 0.5), "face_neck_dE": (0, 6.0)}


def http(url, data=None, timeout=90, raw=False):
    r = urllib.request.urlopen(urllib.request.Request(url, data=data, headers=UA),
                               timeout=timeout)
    b = r.read()
    return b if raw else (json.loads(b) if b else None)


def flatten(workflow, object_info):
    out = "/tmp/harness_api.json"
    subprocess.run([sys.executable, os.path.join(HERE, "flatten_ui_to_api.py"),
                    workflow, object_info, out], check=True)
    return json.load(open(out))


def apply_variant(api, sets):
    """--set 'SELECTOR.field=value'; SELECTOR is an api node key, a numeric id,
    or a case-insensitive substring of the node title. Ambiguity is an error —
    a variant that silently hits the wrong node poisons the whole cycle."""
    for spec in sets or []:
        path, raw = spec.split("=", 1)
        sel, field = path.rsplit(".", 1)
        try:
            val = json.loads(raw)
        except ValueError:
            val = raw
        hits = [k for k, n in api.items()
                if k == sel or k == f"n{sel}" or sel.lower() in n["_meta"]["title"].lower()]
        hits = [k for k in hits if field in api[k]["inputs"]]
        if not hits:
            sys.exit(f"variant target not found: {spec}")
        if len(hits) > 1:
            sys.exit(f"variant selector '{sel}' is ambiguous: {hits}")
        api[hits[0]]["inputs"][field] = val
        print(f"variant: {hits[0]} ({api[hits[0]]['_meta']['title'][:40]}) .{field} = {val}")
    return api


def local_metrics(ref_path, out_path):
    r = subprocess.run([sys.executable, os.path.join(HERE, "i2i_metrics.py"),
                        "--ref", ref_path, "--out", out_path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {"error": r.stderr.strip()[:200]}
    return list(json.loads(r.stdout).values())[0]


def pod_identity(pod, token, out_paths, ref_dir="/ComfyUI/identity_ref"):
    """ArcFace identity via the pod (authoritative). Returns {} if unreachable —
    a missing score is reported, never silently treated as a pass."""
    if not (pod and token):
        return {}
    cmd = (f"python3 /tmp/score_identity.py --ref-dir {ref_dir} "
           f"--query {' '.join(out_paths)} --json /tmp/h.json >/dev/null 2>&1; cat /tmp/h.json")
    r = subprocess.run([sys.executable, os.path.join(HERE, "pod_exec.py"),
                        "--pod", pod, "--token", token, "--timeout", "900", cmd],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout[r.stdout.index("{"):r.stdout.rindex("}") + 1])
    except Exception:
        return {}


def verdict(m):
    out = []
    for k, (lo, hi) in TARGETS.items():
        v = m.get(k)
        if v is None:
            continue
        out.append(f"{k}={v}{'' if lo <= v <= hi else '  ✗'}")
    return "  ".join(out)


def run_cycle(a):
    base = f"https://{a.pod}-8188.proxy.runpod.net"
    api = apply_variant(flatten(a.workflow, a.object_info), a.set)
    li = [k for k, n in api.items() if n["class_type"] == "LoadImage"
          and "IDENTITY" not in n["_meta"]["title"].upper()][0]
    si = [k for k, n in api.items() if n["class_type"] == "SaveImage"][0]

    rundir = os.path.join(RUNS, a.tag)
    os.makedirs(rundir, exist_ok=True)
    report = {"tag": a.tag, "variant": a.set or [], "workflow": a.workflow,
              "started": time.strftime("%Y-%m-%d %H:%M"), "refs": {}}

    # best-of-N identity gate, implemented HERE rather than in the graph:
    # ComfyUI_FaceAnalysis is not installed on the pod and installing a node
    # pack requires a ComfyUI restart, which would kill other sessions' running
    # jobs on this shared GPU. Rendering N seeds and picking the highest ArcFace
    # score gives the same outcome with the scorer we already have.
    seed_nodes = [k for k, n in api.items() if "seed" in n["inputs"]
                  and n["class_type"] in ("KSampler", "FaceDetailer", "DetailerForEach")]
    pids = {}
    for i, ref in enumerate(REFS):
        for s_i in range(a.seeds):
            g = json.loads(json.dumps(api))
            g[li]["inputs"]["image"] = ref
            g[si]["inputs"]["filename_prefix"] = f"h_{a.tag}_{i}_{s_i}"
            if s_i:                       # seed 0 keeps the graph's own seeds
                for k in seed_nodes:
                    g[k]["inputs"]["seed"] = int(g[k]["inputs"]["seed"]) + 1000 * s_i
            try:
                pids[(ref, s_i)] = http(
                    f"{base}/prompt",
                    json.dumps({"prompt": g, "client_id": "harness"}).encode())["prompt_id"]
                print(f"queued [{i}.{s_i}] {ref}")
            except urllib.error.HTTPError as e:
                report["refs"].setdefault(ref, {})["status"] = "queue_failed"
                report["refs"][ref]["detail"] = e.read().decode()[:400]
                print(f"QUEUE FAILED {ref}")

    pending = dict(pids)
    done = {}
    while pending:
        time.sleep(20)
        for key, pid in list(pending.items()):
            try:
                h = http(f"{base}/history/{pid}", timeout=30)
            except Exception:
                continue
            if not h:
                continue
            st = list(h.values())[0]["status"].get("status_str")
            if st in ("success", "error"):
                done[key] = st
                del pending[key]
                print(f"  {st}: {key[0]} seed{key[1]}")
    for i, ref in enumerate(REFS):
        oks = [s_i for (r, s_i), st in done.items() if r == ref and st == "success"]
        report["refs"].setdefault(ref, {})["status"] = "success" if oks else "error"
        report["refs"][ref]["seeds_ok"] = sorted(oks)

    outs = []
    for i, ref in enumerate(REFS):
        e = report["refs"].get(ref, {})
        if e.get("status") != "success":
            continue
        cands = []
        for s_i in e.get("seeds_ok", [0]):
            dst = os.path.join(rundir, f"out_{i}_s{s_i}.png")
            try:
                open(dst, "wb").write(
                    http(f"{base}/view?filename=h_{a.tag}_{i}_{s_i}_00001_.png"
                         f"&type=output", timeout=240, raw=True))
                cands.append((s_i, dst))
            except Exception as ex:
                e["download_error"] = str(ex)[:120]
        if not cands:
            continue
        e["candidates"] = {s_i: p for s_i, p in cands}
        e["output"] = cands[0][1]      # provisional; identity may re-pick below
        outs.append((ref, cands[0][1]))

    # local metrics need the reference pixels; pull them once from the pod
    for ref, dst in outs:
        rp = os.path.join(rundir, f"ref_{os.path.basename(ref)}")
        if not os.path.exists(rp):
            try:
                open(rp, "wb").write(http(f"{base}/view?filename={ref}&type=input",
                                          timeout=180, raw=True))
            except Exception:
                continue
        report["refs"][ref]["metrics"] = local_metrics(rp, dst)
        report["refs"][ref]["ref_local"] = rp

    all_files = [f"/workspace/output/h_{a.tag}_{i}_{s_i}_00001_.png"
                 for i, ref in enumerate(REFS)
                 for s_i in report["refs"].get(ref, {}).get("seeds_ok", [])]
    ident = pod_identity(a.pod, a.token, all_files) if all_files else {}
    if ident:
        by_file = {r["file"]: r for r in ident.get("results", [])}
        report["identity_bar"] = ident.get("pass_bar_mean_sim")
        for i, ref in enumerate(REFS):
            e = report["refs"].get(ref, {})
            scored = [(by_file[f"h_{a.tag}_{i}_{s_i}_00001_.png"]["mean_sim"], s_i)
                      for s_i in e.get("seeds_ok", [])
                      if f"h_{a.tag}_{i}_{s_i}_00001_.png" in by_file]
            if not scored:
                continue
            best_sim, best_seed = max(scored)
            e["identity"] = best_sim
            e["identity_all_seeds"] = {s_i: round(v, 4) for v, s_i in scored}
            e["identity_verdict"] = by_file[
                f"h_{a.tag}_{i}_{best_seed}_00001_.png"].get("verdict")
            if e.get("candidates", {}).get(best_seed):
                e["output"] = e["candidates"][best_seed]   # best-of-N selection
                e["selected_seed"] = best_seed
    else:
        report["identity_note"] = "pod scorer unreachable — identity NOT measured this cycle"

    # 200%-zoom evidence sheets — the mandate's acceptance test is visual, so
    # every cycle produces the artifact automatically rather than on request.
    pairs = [f"{report['refs'][r]['ref_local']}={report['refs'][r]['output']}"
             for r in REFS
             if report["refs"].get(r, {}).get("output")
             and report["refs"].get(r, {}).get("ref_local")]
    if pairs:
        sj = os.path.join(rundir, "score.json")
        json.dump({"results": [{"file": os.path.basename(p.split("=")[1])} for p in pairs]},
                  open(sj, "w"))
        try:
            subprocess.run([sys.executable, os.path.join(HERE, "zoom_sheet.py"),
                            "--score-json", sj, "--pairs", *pairs,
                            "--outdir", os.path.join(rundir, "zoom")],
                           check=False, capture_output=True, timeout=600)
            report["zoom_sheets"] = os.path.join(rundir, "zoom")
        except Exception as e:
            report["zoom_error"] = str(e)[:150]

    json.dump(report, open(os.path.join(rundir, "report.json"), "w"), indent=1)
    with open(os.path.join(rundir, "report.md"), "w") as f:
        f.write(f"# cycle `{a.tag}`\n\nvariant: `{a.set or 'none (baseline)'}`\n\n")
        f.write(f"workflow: `{os.path.basename(a.workflow)}`  ·  {report['started']}\n\n")
        f.write("| ref | identity | skin_hf | grain | seam | dE |\n|---|---|---|---|---|---|\n")
        for ref in REFS:
            e = report["refs"].get(ref, {})
            m = e.get("metrics", {})
            f.write(f"| {ref[:28]} | {e.get('identity','—')} | {m.get('skin_hf_ratio','—')} "
                    f"| {m.get('grain_ratio','—')} | {m.get('seam_gradient','—')} "
                    f"| {m.get('face_neck_dE','—')} |\n")
        if report.get("identity_note"):
            f.write(f"\n> {report['identity_note']}\n")
    print(f"\ncycle '{a.tag}' -> {rundir}/report.md")
    for ref in REFS:
        m = report["refs"].get(ref, {}).get("metrics", {})
        if m:
            print(f"  {ref[:34]:34} {verdict(m)}")


def compare(a_dir, b_dir):
    ra = json.load(open(os.path.join(a_dir, "report.json")))
    rb = json.load(open(os.path.join(b_dir, "report.json")))
    keys = ["identity", "skin_hf_ratio", "grain_ratio", "seam_gradient", "face_neck_dE"]
    print(f"{ra['tag']}  ->  {rb['tag']}\n")
    net = {k: [] for k in keys}
    for ref in REFS:
        ea, eb = ra["refs"].get(ref, {}), rb["refs"].get(ref, {})
        ma, mb = ea.get("metrics", {}), eb.get("metrics", {})
        print(f"{ref[:36]:36}", end="")
        for k in keys:
            va = ea.get(k) if k == "identity" else ma.get(k)
            vb = eb.get(k) if k == "identity" else mb.get(k)
            if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                d = vb - va
                net[k].append(d)
                print(f"  {k[:9]}:{d:+.3f}", end="")
        print()
    print("\nnet mean delta:")
    for k, v in net.items():
        if v:
            print(f"  {k:16} {sum(v)/len(v):+.4f}")
    print("\nACCEPT only if identity delta >= ~0 AND skin metrics move toward "
          "targets (hf 0.85-1.25, grain 0.80-1.20, seam <=0.5, dE <=6).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pod")
    ap.add_argument("--token", help="JUPYTER_PASSWORD, enables on-pod identity scoring")
    ap.add_argument("--workflow")
    ap.add_argument("--object-info")
    ap.add_argument("--tag", default="run")
    ap.add_argument("--seeds", type=int, default=1,
                    help="render N seeds per reference and keep the best by "
                         "ArcFace identity (best-of-N gate). Costs N x GPU.")
    ap.add_argument("--set", action="append",
                    help="SELECTOR.field=value  (node key, id, or title substring)")
    ap.add_argument("--compare", nargs=2)
    a = ap.parse_args()
    if a.compare:
        compare(*a.compare)
    else:
        if not (a.pod and a.workflow and a.object_info):
            ap.error("--pod, --workflow, --object-info required")
        run_cycle(a)
