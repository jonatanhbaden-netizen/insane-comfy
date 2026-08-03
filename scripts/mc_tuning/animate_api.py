"""UI->API converter + parameterized runner for aiofm_mc_animate.json.

Resolves GetNode/SetNode virtual links (browser-only) and bypassed nodes into
an executable API graph, then exposes knobs for the tuning loop.
"""
import copy, json, time, urllib.request, urllib.parse, uuid
from pathlib import Path

WF = Path(__file__).resolve().parents[2] / "workflows/aiofm_mc_animate.json"
POD = __import__("os").environ.get("POD_ID", "aixyeznme5subj")
BASE = f"https://{POD}-8188.proxy.runpod.net"
UA = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}

FRONTEND = {"Note", "MarkdownNote", "Reroute", "PreviewImage"}   # dropped in API graph

_OI = None


def _object_info():
    global _OI
    if _OI is None:
        r = urllib.request.Request(f"{BASE}/object_info",
                                   headers={"User-Agent": "Mozilla/5.0"})
        _OI = json.loads(urllib.request.urlopen(r, timeout=120).read())
    return _OI


_CONNECTION_TYPES = None


def _widget_names(schema, class_type):
    """input names that are widgets (primitive/COMBO), in schema order"""
    d = schema.get(class_type)
    if not d:
        return []
    names = []
    for grp in ("required", "optional"):
        for name, spec in (d["input"].get(grp) or {}).items():
            t = spec[0] if isinstance(spec, (list, tuple)) and spec else None
            if isinstance(t, list):                      # COMBO options
                names.append(name)
            elif t in ("INT", "FLOAT", "STRING", "BOOLEAN") or \
                    (isinstance(t, str) and t.startswith("COMFY_DYNAMICCOMBO")):
                names.append(name)
    return names


def build_api(overrides=None, mix_mode=True):
    """Return API-format prompt dict. overrides: {(node_id, widget_or_input): value}"""
    g = json.loads(WF.read_text())
    nodes = {n["id"]: n for n in g["nodes"]}
    links = {l[0]: l for l in g["links"]}

    # --- resolve Set/Get virtual wiring: setter name -> (origin_id, origin_slot)
    set_src = {}
    for n in nodes.values():
        if n["type"] == "SetNode":
            lk = (n.get("inputs") or [{}])[0].get("link")
            if lk in links:
                l = links[lk]
                set_src[n["widgets_values"][0]] = (l[1], l[2])

    def resolve(oid, oslot):
        """follow through Set/Get/Reroute to a real node output"""
        seen = 0
        while seen < 20:
            seen += 1
            n = nodes.get(oid)
            if n is None:
                return None
            if n["type"] == "GetNode":
                key = n["widgets_values"][0]
                if key not in set_src:
                    return None
                oid, oslot = set_src[key]
                continue
            if n["type"] == "Reroute":
                lk = (n.get("inputs") or [{}])[0].get("link")
                if lk not in links:
                    return None
                l = links[lk]
                oid, oslot = l[1], l[2]
                continue
            if n.get("mode") == 4 and not mix_mode:      # bypassed & staying bypassed
                return None
            return (oid, oslot)
        return None

    schema = _object_info()
    api = {}
    for nid, n in nodes.items():
        if n["type"] in FRONTEND or n["type"] in ("GetNode", "SetNode"):
            continue
        if n.get("mode") == 4 and not mix_mode:
            continue
        # map widgets_values against the POD SCHEMA's widget order (authoritative)
        inputs = {}
        wv = n.get("widgets_values")
        wnames = _widget_names(schema, n["type"])
        if isinstance(wv, list):
            cur = 0
            for name in wnames:
                if cur >= len(wv):
                    break
                inputs[name] = wv[cur]
                cur += 1
                if name in ("seed", "noise_seed") and cur < len(wv) \
                        and wv[cur] in ("fixed", "randomize", "increment", "decrement"):
                    cur += 1
        elif isinstance(wv, dict):
            for name, val in wv.items():
                if name not in ("videopreview",):
                    inputs[name] = val
        for si, i in enumerate(n.get("inputs") or []):
            lk = i.get("link")
            if lk is None or lk not in links:
                continue
            l = links[lk]
            r = resolve(l[1], l[2])
            if r is not None:
                inputs[i["name"]] = [str(r[0]), r[1]]
            # if unresolved (points into bypassed/virtual dead end) leave widget value
        api[str(nid)] = {"class_type": n["type"], "inputs": inputs}

    # control_after_generate cleanup + seed fix
    for nid, an in api.items():
        an["inputs"].pop("control_after_generate", None)
        an["inputs"].pop("upload", None)
        an["inputs"].pop("choose video to upload", None)

    for (nid, key), val in (overrides or {}).items():
        if val is None:
            api[str(nid)]["inputs"].pop(key, None)
        else:
            api[str(nid)]["inputs"][key] = val
    return api



def _open(req, timeout, tries=5):
    import time as _t
    last = None
    for k in range(tries):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError:
            raise                                     # real HTTP errors surface
        except Exception as e:                        # resets, timeouts, DNS
            last = e
            _t.sleep(min(5 * (k + 1), 30))
    raise last


def queue(api_graph):
    body = json.dumps({"prompt": api_graph, "client_id": uuid.uuid4().hex}).encode()
    req = urllib.request.Request(f"{BASE}/prompt", data=body, headers=UA, method="POST")
    try:
        return json.loads(_open(req, 120).read())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:3000]}


def wait(pid, timeout=7200, poll=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = urllib.request.Request(f"{BASE}/history/{pid}", headers={"User-Agent": "Mozilla/5.0"})
        try:
            h = json.loads(_open(r, 60).read())
        except Exception:
            time.sleep(poll); continue
        if pid in h:
            return h[pid]
        time.sleep(poll)
    return None


def outputs(entry):
    out = []
    for o in (entry or {}).get("outputs", {}).values():
        for f in (o.get("images") or o.get("gifs") or []):
            if str(f.get("filename", "")).endswith(".mp4"):
                out.append(f)
    return out


def fetch(f, dest):
    q = urllib.parse.urlencode({"filename": f["filename"],
                                "subfolder": f.get("subfolder", ""), "type": "output"})
    r = urllib.request.Request(f"{BASE}/view?{q}", headers={"User-Agent": "Mozilla/5.0"})
    Path(dest).write_bytes(_open(r, 600).read())
    return dest


# ---- knob helpers (node ids from the UI graph) ------------------------------
K = {
    "video":        (275, "video"),
    "image":        (299, "image"),
    "seed":         (222, "seed"),
    "steps":        (222, "steps"),
    "cfg":          (222, "cfg"),
    "shift":        (222, "shift"),
    "scheduler":    (222, "scheduler"),
    "num_frames":   (330, "value"),
    "frame_cap":    (300, "value"),
    "colormatch":   (295, "colormatch"),
    "lora0_str":    (276, "strength_0"),   # relight
    "lora1":        (276, "lora_1"),       # lightning
    "lora1_str":    (276, "strength_1"),
    "vitpose":      (204, "vitpose_model"),
    "prefix":       (285, "filename_prefix"),
    "pos_prompt":   (278, "positive_prompt"),
}


def knobs(**kw):
    ov = {}
    for k, v in kw.items():
        nid, key = K[k]
        ov[(nid, key)] = v
    return ov


if __name__ == "__main__":
    import sys
    api = build_api()
    print(f"api graph: {len(api)} nodes")
    if "--dump" in sys.argv:
        print(json.dumps(api, indent=1)[:4000])
