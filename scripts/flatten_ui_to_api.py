#!/usr/bin/env python3
"""Flatten AIOFM i2i v4 (subgraphs + Set/Get) to runnable ComfyUI API format.

Subgraph boundary convention (verified in the file):
  internal link origin_id == -10  -> comes from the instance's input slot N
  internal link target_id == -20  -> feeds the instance's output slot N
  the def's inputs[]/outputs[] arrays are slot-indexed.
"""
import json, sys

LINKY = {"MODEL","CLIP","VAE","IMAGE","MASK","LATENT","CONDITIONING","STRING","SIGMAS",
         "SAMPLER","GUIDER","NOISE","OPTIONS","GUIDES","BBOX_DETECTOR","SEGM_DETECTOR",
         "SAM_MODEL","UPSCALE_MODEL","BASIC_PIPE","DETAILER_PIPE","SEEDVR2_DIT","SEEDVR2_VAE",
         "SEEDVR2_MODEL","LUT","COMFY_AUTOGROW_V3","DETAILER_HOOK","SEGS","MASK_MAPPING"}
SCALARS = {"INT","FLOAT","BOOLEAN","STRING","COMBO",
           # dynamic combo serializes its selection as one widget slot; nodes whose
           # dynamic sub-widgets also serialize are listed in SPECIAL_WIDGETS
           "COMFY_DYNAMICCOMBO_V3"}
CTRL = {"fixed","increment","decrement","randomize"}

# V3 dynamic-combo nodes: the class spec doesn't enumerate their widget stream,
# so map widgets_values slots to API input names explicitly (widget order as
# serialized by the frontend). Linked slots still resolve to links.
SPECIAL_WIDGETS = {
    "ResizeImageMaskNode": ["resize_type", "resize_type.width",
                            "resize_type.height", "resize_type.crop",
                            "scale_method"],
    # valid while sampling_mode == "off" (no sampling_mode.* sub-widgets serialize)
    "TextGenerateLTX2Prompt": ["prompt", "max_length", "sampling_mode"],
}


def norm_links(links):
    out = []
    for l in links:
        if isinstance(l, dict):
            out.append(dict(id=l["id"], o=l["origin_id"], os=l["origin_slot"],
                            t=l["target_id"], ts=l["target_slot"], type=l.get("type")))
        else:
            out.append(dict(id=l[0], o=l[1], os=l[2], t=l[3], ts=l[4], type=l[5]))
    return out


def flatten(ui, oi):
    subdefs = {str(s["id"]): s for s in ui.get("definitions", {}).get("subgraphs", [])}
    api = {}
    gid = [0]
    def newg():
        gid[0] += 1
        return f"n{gid[0]}"
    emit_cache = {}   # (scope, node_id) -> gid

    def get_scope(scope_key, nodes, links, boundary):
        nd = {n["id"]: n for n in nodes}
        set_link = {}
        for n in nodes:
            if n["type"] == "SetNode" and n.get("widgets_values"):
                nm = n["widgets_values"][0]
                for i in n.get("inputs", []):
                    if i.get("link") is not None:
                        set_link[nm] = i["link"]
        lby = {l["id"]: l for l in links}
        # producers: (target_id,target_slot) not needed; we walk by finding link whose t==node,ts==slot
        return dict(nodes=nd, links=links, lby=lby, set_link=set_link, boundary=boundary)

    scopes = {}

    def link_into(scope, node_id, slot):
        """find the link feeding (node_id, slot) within scope; return link dict or None."""
        for l in scopes[scope]["links"]:
            if l["t"] == node_id and l["ts"] == slot:
                return l
        return None

    def resolve(scope, node_id, slot):
        """Resolve (scope,node_id,slot) to a concrete (gid, out_slot). Hops Set/Get,
        Reroute, and subgraph boundaries."""
        S = scopes[scope]
        # boundary input node
        if node_id == -10:
            src = S["boundary"].get(slot)
            return src  # already a resolved (gid, slot) in the PARENT
        n = S["nodes"].get(node_id)
        if n is None:
            return None
        t = n["type"]
        if t == "GetNode":
            nm = n["widgets_values"][0]
            # find the SetNode's feeding link in this scope
            lid = S["set_link"].get(nm)
            if lid is None:
                return None
            l = S["lby"][lid]
            return resolve(scope, l["o"], l["os"])
        if t in ("Reroute", "Reroute (rgthree)"):
            l = link_into(scope, node_id, 0)
            if l is None:
                return None
            return resolve(scope, l["o"], l["os"])
        if t in subdefs:
            # producing node is a subgraph instance -> its output slot `slot`
            return expand_instance(scope, node_id)[slot]
        # bypassed node (mode 2/4): pass an input of the same type through to
        # the requested output slot, exactly as the ComfyUI frontend does
        if n.get("mode") in (2, 4):
            outs = oi.get(t, {}).get("output", [])
            want = outs[slot] if slot < len(outs) else None
            # find an input link of the same type (fallback: first image/any link)
            cand = None
            for i in n.get("inputs", []):
                if i.get("link") is None:
                    continue
                if want is None or i.get("type") == want:
                    cand = i["link"]; break
            if cand is None:
                for i in n.get("inputs", []):
                    if i.get("link") is not None:
                        cand = i["link"]; break
            if cand is not None:
                l = S["lby"][cand]
                return resolve(scope, l["o"], l["os"])
            return None
        # real leaf node
        return (emit(scope, node_id), slot)

    def emit(scope, node_id):
        key = (scope, node_id)
        if key in emit_cache:
            return emit_cache[key]
        S = scopes[scope]
        n = S["nodes"][node_id]
        g = newg()
        emit_cache[key] = g
        spec = oi.get(n["type"], {}).get("input", {})
        order = []
        for sec in ("required", "optional"):
            for k, v in spec.get(sec, {}).items():
                order.append((k, v[0]))
        entry = {"inputs": {}, "class_type": n["type"],
                 "_meta": {"title": n.get("title", n["type"])}}
        linked = {i["name"]: i["link"] for i in n.get("inputs", []) if i.get("link") is not None}
        # widget stream. Widget-backed inputs ALWAYS occupy a widgets_values slot,
        # even when converted to a link (the frontend keeps a placeholder), so the
        # slot must be consumed either way or everything after it misaligns.
        wvraw = n.get("widgets_values") or []
        if isinstance(wvraw, dict):
            # VHS nodes (VHS_VideoCombine / VHS_LoadVideo) serialize widgets
            # as a name->value dict, not a positional stream. Assign by name;
            # links win over widget values; UI-only keys are dropped.
            UI_ONLY = {"videopreview", "choose video to upload"}
            for k, v in wvraw.items():
                if k in UI_ONLY or k in linked:
                    continue
                entry["inputs"][k] = v
            for k, lk in linked.items():
                l = S["lby"].get(lk)
                r = resolve(scope, l["o"], l["os"]) if l else None
                if r:
                    entry["inputs"][k] = [r[0], r[1]]
            api[g] = entry
            return g
        wv = list(wvraw)
        wi = 0
        seen = set()
        smap = SPECIAL_WIDGETS.get(n["type"])
        if smap is not None:
            for k in smap:
                seen.add(k)
                if k in linked:
                    l = S["lby"].get(linked[k])
                    r = resolve(scope, l["o"], l["os"]) if l else None
                    if r:
                        entry["inputs"][k] = [r[0], r[1]]
                    elif wi < len(wv):
                        entry["inputs"][k] = wv[wi]
                elif wi < len(wv):
                    entry["inputs"][k] = wv[wi]
                wi += 1
            for k, lk in linked.items():
                if k in seen:
                    continue
                l = S["lby"].get(lk)
                r = resolve(scope, l["o"], l["os"]) if l else None
                if r:
                    entry["inputs"][k] = [r[0], r[1]]
            api[g] = entry
            return g
        for k, tp in order:
            seen.add(k)
            widgetish = isinstance(tp, list) or (isinstance(tp, str) and tp in SCALARS)
            if k in linked:
                l = S["lby"].get(linked[k])
                r = resolve(scope, l["o"], l["os"]) if l else None
                if r:
                    entry["inputs"][k] = [r[0], r[1]]
                elif widgetish and wi < len(wv):
                    # dangling boundary link (unconnected promoted widget):
                    # fall back to the placeholder value
                    entry["inputs"][k] = wv[wi]
                if widgetish:
                    wi += 1
                    if k.endswith("seed") and wi < len(wv) and wv[wi] in CTRL:
                        wi += 1
                continue
            if not widgetish:
                continue
            if wi < len(wv):
                entry["inputs"][k] = wv[wi]; wi += 1
                if k.endswith("seed") and wi < len(wv) and wv[wi] in CTRL:
                    wi += 1
        # autogrow sub-inputs ("values.a" on ComfyMathExpression etc.) are not in
        # the class spec by name — pass linked ones through under their dotted name
        for k, lk in linked.items():
            if k in seen or "." not in k:
                continue
            l = S["lby"].get(lk)
            r = resolve(scope, l["o"], l["os"]) if l else None
            if r:
                entry["inputs"][k] = [r[0], r[1]]
        api[g] = entry
        return g

    inst_cache = {}
    def expand_instance(scope, inst_id):
        key = (scope, inst_id)
        if key in inst_cache:
            return inst_cache[key]
        S = scopes[scope]
        inst = S["nodes"][inst_id]
        sub = subdefs[inst["type"]]
        # boundary_in: for each input slot of the instance, resolve the external link
        boundary = {}
        for idx, i in enumerate(inst.get("inputs", [])):
            if i.get("link") is not None:
                l = S["lby"].get(i["link"])
                if l:
                    boundary[idx] = resolve(scope, l["o"], l["os"])
        child_key = scope + "/" + str(inst_id)
        scopes[child_key] = get_scope(child_key, sub["nodes"], norm_links(sub.get("links", [])), boundary)
        # outputs: map each output slot to internal producer
        outs = {}
        for oidx, _o in enumerate(sub.get("outputs", [])):
            # find internal link whose target is -20 slot oidx
            prod = None
            for l in scopes[child_key]["links"]:
                if l["t"] == -20 and l["ts"] == oidx:
                    prod = resolve(child_key, l["o"], l["os"]); break
            outs[oidx] = prod
        inst_cache[key] = outs
        return outs

    # top scope
    scopes[""] = get_scope("", ui["nodes"], norm_links(ui["links"]), {})
    # emit everything reachable from active sink nodes
    SINKS = {"SaveImage", "SaveVideo", "SaveAudio", "SaveAudioMP3", "SaveAudioOpus",
             "PreviewImage", "PreviewAudio", "PreviewAny", "SaveAnimatedWEBP",
             # VHS terminal writer — the sink of every aiofm_mc_* master
             "VHS_VideoCombine"}
    save_ids = [n["id"] for n in ui["nodes"]
                if n["type"] in SINKS and n.get("mode") not in (2, 4)]
    for sid in save_ids:
        emit("", sid)

    # Anything Everywhere: broadcast each AE node's input to every unconnected
    # required input of the same type (the frontend does this implicitly)
    bcast = {}
    for n in ui["nodes"]:
        if "Anything Everywhere" in n["type"]:
            for i in n.get("inputs", []):
                lk = i.get("link")
                if lk is None:
                    continue
                l = scopes[""]["lby"].get(lk)
                if not l:
                    continue
                r = resolve("", l["o"], l["os"])
                if r and i.get("type") and i["type"] != "*":
                    bcast[i["type"]] = r
    for g, node in list(api.items()):
        req = oi.get(node["class_type"], {}).get("input", {}).get("required", {})
        for k, sp in req.items():
            tp = sp[0]
            if isinstance(tp, str) and tp in bcast and k not in node["inputs"]:
                node["inputs"][k] = [bcast[tp][0], bcast[tp][1]]
    # resolve SaveImage inputs (emit only walks widgets; force input resolution)
    # emit() already resolved inputs recursively. Return.
    return api


def validate(api):
    errs = []
    ids = set(api)
    for nid, node in api.items():
        for k, v in node["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                if v[0] not in ids:
                    errs.append(f"{nid}({node['class_type']}).{k} -> missing {v[0]}")
    return errs


if __name__ == "__main__":
    ui = json.load(open(sys.argv[1]))
    oi = json.load(open(sys.argv[2]))
    api = flatten(ui, oi)
    errs = validate(api)
    if errs:
        for e in errs[:30]:
            print("ERR", e, file=sys.stderr)
        print(f"{len(errs)} link errors", file=sys.stderr)
        sys.exit(1)
    json.dump(api, open(sys.argv[3], "w"))
    print(f"OK {len(api)} api nodes")
