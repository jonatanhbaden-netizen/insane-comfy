"""MC tuning battery: upload assets, render variants, measure, log.

Usage:
  battery.py smoke                 -> 49-frame validation render
  battery.py run B0                -> baseline battery (current file settings)
  battery.py run <tag> k=v k=v     -> battery with knob overrides
Results append to results.jsonl; videos land in out/<tag>/.
"""
import json, mimetypes, sys, time, urllib.request, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import animate_api as A
import metrics

MC = Path(__file__).parent
OUT = MC / "out"
RESULTS = MC / "results.jsonl"
ASSETS = Path("/Users/jonatanbaden/Desktop/AIOFM SYSTEM")

REF_IMAGE = ASSETS / "test-assets/emma_reference.png"
BATTERY = [
    # name, driving clip, frames (30fps, padded grid), what it stresses
    ("slow_talk", ASSETS / "motion-refs/ref01.mp4", 337, "slow motion, face fidelity"),
    ("fast_gesture", ASSETS / "motion-refs/ref06.mp4", 225, "fast hands, direction changes"),
    ("long_481", ASSETS / "motion-refs/ref04.mp4", 481, "long-sequence drift/windows"),
]


def upload(path):
    path = Path(path)
    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: {ctype}\r\n\r\n").encode() \
        + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{A.BASE}/upload/image", data=body,
        headers={"User-Agent": "Mozilla/5.0",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST")
    r = json.loads(urllib.request.urlopen(req, timeout=600).read())
    return r["name"]


def ensure_assets():
    names = {}
    for p in [REF_IMAGE] + [b[1] for b in BATTERY]:
        names[p.name] = upload(p)
        print(f"  uploaded {p.name} -> {names[p.name]}", flush=True)
    return names


def render(tag, case, video_name, image_name, num_frames, extra):
    ov = A.knobs(video=video_name, image=image_name, seed=4242,
                 num_frames=num_frames, frame_cap=num_frames,
                 prefix=f"mc/{tag}_{case}", **extra)
    api = A.build_api(ov)
    res = A.queue(api)
    if "prompt_id" not in res:
        print(f"QUEUE FAIL {tag}/{case}: {json.dumps(res)[:1500]}", flush=True)
        return None
    pid = res["prompt_id"]
    print(f"  {tag}/{case} queued {pid[:8]}", flush=True)
    entry = A.wait(pid)
    if not entry:
        print(f"  {tag}/{case} TIMEOUT", flush=True)
        return None
    st = entry.get("status", {})
    if st.get("status_str") == "error":
        msgs = [m for m in st.get("messages", []) if "error" in str(m).lower()]
        print(f"  {tag}/{case} RENDER ERROR: {json.dumps(msgs)[:1200]}", flush=True)
        return None
    outs = A.outputs(entry)
    if not outs:
        print(f"  {tag}/{case} no video output", flush=True)
        return None
    dest = OUT / tag
    dest.mkdir(parents=True, exist_ok=True)
    local = dest / f"{case}.mp4"
    A.fetch(outs[0], local)
    return local


def run_battery(tag, extra):
    names = ensure_assets()
    t0 = time.time()
    for case, clip, nframes, stress in BATTERY:
        t1 = time.time()
        local = render(tag, case, names[clip.name], names[REF_IMAGE.name], nframes, extra)
        row = {"tag": tag, "case": case, "knobs": {k: v for k, v in extra.items()},
               "render_s": int(time.time() - t1)}
        if local:
            row["metrics"] = metrics.report(str(clip), str(local))
            row["file"] = str(local)
        else:
            row["metrics"] = None
        with open(RESULTS, "a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"  {tag}/{case}: {json.dumps(row.get('metrics'))} "
              f"({row['render_s']}s)", flush=True)
    print(f"BATTERY {tag} COMPLETE in {int(time.time()-t0)//60} min", flush=True)


def parse_kv(argv):
    out = {}
    for kv in argv:
        k, v = kv.split("=", 1)
        try:
            v = json.loads(v)
        except Exception:
            pass
        out[k] = v
    return out


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "smoke":
        names = ensure_assets()
        local = render("smoke", "s49", names["ref01.mp4"],
                       names["emma_reference.png"], 49, {})
        print("SMOKE:", "PASS " + str(local) if local else "FAIL")
    elif cmd == "run":
        tag = sys.argv[2]
        run_battery(tag, parse_kv(sys.argv[3:]))
