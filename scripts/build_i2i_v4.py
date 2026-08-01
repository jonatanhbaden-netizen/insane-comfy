#!/usr/bin/env python3
"""Build AIOFM_I2I_v4 by transforming the manager's AIBT2I workflow (T2I -> I2I).

Not a rebuild — a surgical edit of the original file, so every subgraph,
Set/Get alias, sampler widget array and muted state the professional tuned
survives byte-for-byte unless a change is explicitly listed here.

The conversion (from the reviewed design):
  - Stages 1+2 (pure T2I composition) and both empty-latent entries removed.
  - New STAGE 0: Qwen-Image-Edit-2511 swaps the person in the reference photo
    (denoise 1.0 — structure is anchored by the edit model's reference latents,
    not the starting noise), ColorMatch pins the source grade, then the result
    grafts into the untouched chain at the "Stage 2 Latent" SetNode.
  - Stages 3/4 + FACE detailer + SeedVR2 + POST run verbatim, now with
    f1sher @ 0.6 on the "Model with LoRA" path (and explicitly wired into the
    FACE detailer, which the AE broadcasters previously fed base-model).
  - EYE/PUSSY/BREAST/PHONE detailers deleted: their .pt weights are private
    and absent, and EYE's baked "symmetrical eyes, blue iris" prompt would
    destroy the mandatory heterochromia.
  - ultraflux VAE -> ae.safetensors (byte-identical family), fluxvae1dev ->
    ae.safetensors, SaveImage added (the original ended at a PreviewImage).

Usage: python3 build_i2i_v4.py <AIBT2I.json> <object_info.json> [--out FILE]
"""
import argparse
import json
import sys

QWEN_PROMPT = (
    "Replace the woman with a different woman: F1sher, golden blonde "
    "shoulder-length bob with a middle part, heterochromia, left eye warm "
    "brown, right eye light blue. Keep the exact same pose, outfit, clothing, "
    "accessories, background, framing, camera angle and lighting completely "
    "unchanged. Photorealistic, natural skin texture."
)
MAIN_POSITIVE = (
    "F1sher, golden blonde shoulder-length bob with a middle part, "
    "heterochromia, left eye warm brown, right eye light blue, natural skin "
    "texture with visible pores and fine detail, candid phone photo"
)

DELETE_TYPES_BY_TITLEHINT = {}  # populated at runtime for previews wired to dead nodes


def die(msg):
    print("FATAL:", msg)
    sys.exit(1)


def combo_options(oi, ntype, name):
    for section in ("required", "optional"):
        spec = oi.get(ntype, {}).get("input", {}).get(section, {})
        if name in spec:
            s = spec[name]
            if s[0] == "COMBO":
                return (s[1] or {}).get("options", [])
            if isinstance(s[0], list):
                return s[0]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("object_info")
    ap.add_argument("--out", default="aiofm_i2i_v4.json")
    a = ap.parse_args()

    d = json.load(open(a.src))
    oi = json.load(open(a.object_info))
    nodes = {n["id"]: n for n in d["nodes"]}
    links = {l[0]: l for l in d["links"]}

    def node_by_setget(name, kind):
        for n in d["nodes"]:
            if n["type"] == kind and n.get("widgets_values") and n["widgets_values"][0] == name:
                return n
        return None

    # ------------------------------------------------------------ deletions
    doomed = set()

    # empty-latent entries + their aliases
    for nid, n in nodes.items():
        if n["type"] == "EmptySD3LatentImage":
            doomed.add(nid)
        if n["type"] in ("SetNode", "GetNode") and n.get("widgets_values"):
            if "Empty Latent" in str(n["widgets_values"][0]):
                doomed.add(nid)
            if n["widgets_values"][0] in ("Stage 1 Image", "Stage 2 Image"):
                doomed.add(nid)

    # stage 1 + 2 instances and their seeds (known ids from dissection)
    for nid in (518, 519, 28, 110):
        if nid in nodes:
            doomed.add(nid)

    # dead detailers
    for nid in (551, 546, 547, 549, 543, 544):
        if nid in nodes:
            doomed.add(nid)

    # the rgthree seed feeding the deleted PUSSY detailer (source of link 6499)
    if 6499 in links:
        doomed.add(links[6499][1])

    # detector providers for the deleted NSFW detailers: their .pt files are
    # absent, and once 546/547 die they feed nothing — but the frontend still
    # flags their missing models, so they must go, not just dangle
    for nid, n in nodes.items():
        if n["type"] == "UltralyticsDetectorProvider" and n.get("widgets_values"):
            if any(x in str(n["widgets_values"][0]) for x in ("nipple", "pussy")):
                doomed.add(nid)

    # previews / mask previews / comparer attached to doomed nodes
    changed = True
    while changed:
        changed = False
        for nid, n in list(nodes.items()):
            if nid in doomed:
                continue
            if n["type"] in ("PreviewImage", "MaskPreview+", "Image Comparer (rgthree)"):
                srcs = []
                for i in n.get("inputs", []):
                    lk = i.get("link")
                    if lk is not None and lk in links:
                        srcs.append(links[lk][1])
                if srcs and all(s in doomed for s in srcs):
                    doomed.add(nid)
                    changed = True

    # keep the final preview 535 (POST output) — it survives because 552 lives

    # ------------------------------------------------------------ rewires
    # FACE(553).image -> HAND(542).image   (bridging over deleted EYE/PUSSY/BREAST)
    links[6509] = [6509, 553, 2, 542, 0, "IMAGE"]
    for i in nodes[542]["inputs"]:
        if i["name"] == "image":
            i["link"] = 6509
    # HAND(542).image -> BODY(539).image   (bridging over deleted PHONE)
    links[6505] = [6505, 542, 0, 539, 0, "IMAGE"]
    for i in nodes[539]["inputs"]:
        if i["name"] == "image":
            i["link"] = 6505

    # ------------------------------------------------------------ widget edits
    # LoRA 527: manager's private persona -> f1sher @ 0.6 (hard cap, overbaked)
    nodes[527]["widgets_values"] = ["f1sher_000002400.safetensors", 0.6]

    # main positive prompt -> Fischer identity block
    nodes[6]["widgets_values"] = [MAIN_POSITIVE]

    # detailer VAE 556 (top level): fluxvae1dev -> ae
    if 556 in nodes:
        nodes[556]["widgets_values"] = ["ae.safetensors"]

    # MODELS + FACE subgraph definition edits
    for sg in d.get("definitions", {}).get("subgraphs", []):
        for n in sg.get("nodes", []):
            if n["type"] == "VAELoader" and n.get("widgets_values") and "ultraflux" in str(n["widgets_values"][0]).lower():
                n["widgets_values"] = ["ae.safetensors"]
            if n["type"] == "CRT Post-Process Suite":
                w = n.get("widgets_values", [])
                # its internal-upscaler toggle ships OFF, but the widget still
                # names the manager's absent 4kNomos model and trips the
                # missing-model check — point it at a model that exists
                for i, v in enumerate(w):
                    if isinstance(v, str) and "Nomos" in v:
                        w[i] = "4x-UltraSharp.pth"
            if n["type"] == "FaceDetailer":
                w = n.get("widgets_values", [])
                # denoise 0.40 -> 0.45: locate it right after res_2s/bong_tangent
                for i in range(len(w) - 2):
                    if w[i] == "res_2s" and w[i + 1] == "bong_tangent" and w[i + 2] == 0.4:
                        w[i + 2] = 0.45

    # ------------------------------------------------------------ Stage 0 build
    NEW = []
    L = [7000]

    def mk(nid, ntype, pos, widgets=None, title=None, size=None):
        n = {"id": nid, "type": ntype, "pos": pos, "size": size or [300, 110],
             "flags": {}, "order": 0, "mode": 0, "inputs": [], "outputs": [],
             "properties": {"Node name for S&R": ntype},
             "widgets_values": widgets or []}
        if title:
            n["title"] = title
        NEW.append(n)
        nodes[nid] = n
        return n

    def wire(src, sslot, dst, iname, typ, reuse=None):
        L[0] += 1
        lid = reuse if reuse is not None else L[0]
        links[lid] = [lid, src["id"], sslot, dst["id"], len(dst["inputs"]), typ]
        dst["inputs"].append({"name": iname, "type": typ, "link": lid})
        while len(src["outputs"]) <= sslot:
            src["outputs"].append({"name": typ, "type": typ, "links": [], "slot_index": len(src["outputs"])})
        src["outputs"][sslot].setdefault("links", []).append(lid)
        return lid

    # keep_proportion option sanity for ImageResizeKJv2
    kp = combo_options(oi, "ImageResizeKJv2", "keep_proportion")
    kp_crop = "crop" if "crop" in kp else ("resize" if "resize" in kp else (kp[0] if kp else "resize"))

    X = -3200
    ref = mk(600, "LoadImage", [X, 80], ["example.png", "image"],
             "REF — the post to replicate", [340, 340])
    ref["outputs"] = [{"name": "IMAGE", "type": "IMAGE", "links": [], "slot_index": 0},
                      {"name": "MASK", "type": "MASK", "links": [], "slot_index": 1}]
    conform = mk(601, "ImageResizeKJv2", [X, 470],
                 [896, 1152, "lanczos", kp_crop, "0, 0, 0", "center", 2],
                 "conform to 7:9 (chain hardcodes 896x1152)")
    conform["outputs"] = [{"name": "IMAGE", "type": "IMAGE", "links": [], "slot_index": 0},
                          {"name": "width", "type": "INT", "links": [], "slot_index": 1},
                          {"name": "height", "type": "INT", "links": [], "slot_index": 2}]
    q_unet = mk(602, "UNETLoader", [X, 650], ["qwen_image_edit_2511_fp8mixed.safetensors", "default"], "[stage0] Qwen-Edit")
    q_unet["outputs"] = [{"name": "MODEL", "type": "MODEL", "links": [], "slot_index": 0}]
    q_clip = mk(603, "CLIPLoader", [X, 760], ["qwen_2.5_vl_7b_fp8_scaled.safetensors", "qwen_image", "default"], "[stage0] Qwen CLIP")
    q_clip["outputs"] = [{"name": "CLIP", "type": "CLIP", "links": [], "slot_index": 0}]
    q_vae = mk(604, "VAELoader", [X, 870], ["qwen_image_vae.safetensors"], "[stage0] Qwen VAE")
    q_vae["outputs"] = [{"name": "VAE", "type": "VAE", "links": [], "slot_index": 0}]
    q_lora = mk(605, "LoraLoaderModelOnly", [X, 980],
                ["Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors", 1.0], "[stage0] Lightning 4-step")
    q_lora["outputs"] = [{"name": "MODEL", "type": "MODEL", "links": [], "slot_index": 0}]
    q_shift = mk(606, "ModelSamplingAuraFlow", [X, 1100], [3.1])
    q_shift["outputs"] = [{"name": "MODEL", "type": "MODEL", "links": [], "slot_index": 0}]
    q_norm = mk(607, "CFGNorm", [X, 1200], [1.0, False])
    q_norm["outputs"] = [{"name": "patched_model", "type": "MODEL", "links": [], "slot_index": 0}]
    q_pos = mk(608, "TextEncodeQwenImageEdit", [X + 380, 80], [QWEN_PROMPT],
               "[stage0] SWAP INSTRUCTION (append edits here)", [420, 220])
    q_pos["outputs"] = [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [], "slot_index": 0}]
    q_neg = mk(609, "TextEncodeQwenImageEdit", [X + 380, 340], [""], "[stage0] negative")
    q_neg["outputs"] = [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [], "slot_index": 0}]
    q_enc = mk(610, "VAEEncode", [X + 380, 470])
    q_enc["outputs"] = [{"name": "LATENT", "type": "LATENT", "links": [], "slot_index": 0}]
    q_k = mk(611, "KSampler", [X + 380, 600], [7, "fixed", 4, 1.0, "euler", "simple", 1.0],
             "[stage0] 4-step edit", [340, 260])
    q_k["outputs"] = [{"name": "LATENT", "type": "LATENT", "links": [], "slot_index": 0}]
    q_dec = mk(612, "VAEDecode", [X + 380, 900])
    q_dec["outputs"] = [{"name": "IMAGE", "type": "IMAGE", "links": [], "slot_index": 0}]
    cmatch = mk(613, "ColorMatch", [X + 760, 80], ["mkl", 0.35, True],
                "pin source grade (max 0.35)")
    cmatch["outputs"] = [{"name": "image", "type": "IMAGE", "links": [], "slot_index": 0}]
    down = mk(614, "ImageResizeKJv2", [X + 760, 260],
              [672, 864, "lanczos", "resize", "0, 0, 0", "center", 2],
              "down to 672x864 graft point")
    down["outputs"] = [{"name": "IMAGE", "type": "IMAGE", "links": [], "slot_index": 0},
                       {"name": "width", "type": "INT", "links": [], "slot_index": 1},
                       {"name": "height", "type": "INT", "links": [], "slot_index": 2}]
    vget = mk(615, "GetNode", [X + 760, 450], ["Ultra Flux VAE"], "Get_Ultra Flux VAE")
    vget["outputs"] = [{"name": "VAE", "type": "VAE", "links": [], "slot_index": 0}]
    genc = mk(616, "VAEEncode", [X + 760, 560], None, "graft encode (ae VAE)")
    genc["outputs"] = [{"name": "LATENT", "type": "LATENT", "links": [], "slot_index": 0}]
    stage0_prev = mk(619, "PreviewImage", [X + 760, 700], None, "STAGE 0 — judge the swap here", [300, 300])

    # explicit wires — every input connected so the Anything-Everywhere
    # broadcasters cannot inject the Z-Image model/clip into Stage 0
    wire(ref, 0, conform, "image", "IMAGE")
    wire(q_unet, 0, q_lora, "model", "MODEL")
    wire(q_lora, 0, q_shift, "model", "MODEL")
    wire(q_shift, 0, q_norm, "model", "MODEL")
    wire(q_clip, 0, q_pos, "clip", "CLIP")
    wire(q_vae, 0, q_pos, "vae", "VAE")
    wire(conform, 0, q_pos, "image", "IMAGE")
    wire(q_clip, 0, q_neg, "clip", "CLIP")
    wire(conform, 0, q_enc, "pixels", "IMAGE")
    wire(q_vae, 0, q_enc, "vae", "VAE")
    wire(q_norm, 0, q_k, "model", "MODEL")
    wire(q_pos, 0, q_k, "positive", "CONDITIONING")
    wire(q_neg, 0, q_k, "negative", "CONDITIONING")
    wire(q_enc, 0, q_k, "latent_image", "LATENT")
    wire(q_k, 0, q_dec, "samples", "LATENT")
    wire(q_vae, 0, q_dec, "vae", "VAE")
    wire(conform, 0, cmatch, "image_ref", "IMAGE")
    wire(q_dec, 0, cmatch, "image_target", "IMAGE")
    wire(cmatch, 0, down, "image", "IMAGE")
    wire(down, 0, genc, "pixels", "IMAGE")
    wire(vget, 0, genc, "vae", "VAE")
    wire(cmatch, 0, stage0_prev, "images", "IMAGE")

    # graft: reuse link 1235 into SetNode 211 ("Stage 2 Latent")
    set211 = nodes.get(211) or die("SetNode 211 'Stage 2 Latent' not found")
    wire(genc, 0, set211, "LATENT", "LATENT", reuse=1235)
    set211["inputs"] = [i for i in set211["inputs"] if i.get("link") == 1235]

    # FACE detailer gets the LoRA model explicitly (was AE-broadcast base model)
    mget = mk(618, "GetNode", [X + 760, 1050], ["Model with LoRA"], "Get_Model with LoRA")
    mget["outputs"] = [{"name": "MODEL", "type": "MODEL", "links": [], "slot_index": 0}]
    face = nodes[553]
    for i in face["inputs"]:
        if i["name"] == "model" and i.get("link") is None:
            L[0] += 1
            links[L[0]] = [L[0], 618, 0, 553,
                           face["inputs"].index(i), "MODEL"]
            i["link"] = L[0]
            mget["outputs"][0]["links"].append(L[0])

    # SaveImage on the POST output (original chain ended at a preview)
    save = mk(617, "SaveImage", [1600, 80], ["AIOFM_i2i_v4"], "FINAL", [340, 320])
    wire(nodes[552], 0, save, "images", "IMAGE")

    # ------------------------------------------------------------ apply deletions
    for nid in doomed:
        nodes.pop(nid, None)
    d["nodes"] = [n for n in d["nodes"] if n["id"] in nodes] + NEW
    # drop links touching doomed nodes, prune output lists
    dead_links = {lid for lid, l in links.items() if l[1] in doomed or l[3] in doomed}
    for lid in dead_links:
        links.pop(lid)
    for n in d["nodes"]:
        for o in n.get("outputs", []):
            if o.get("links"):
                o["links"] = [x for x in o["links"] if x in links]
        for i in n.get("inputs", []):
            if i.get("link") is not None and i["link"] not in links:
                i["link"] = None
    d["links"] = [links[k] for k in sorted(links)]
    d["last_node_id"] = max(nodes)
    d["last_link_id"] = max(links)

    # ------------------------------------------------------------ validation
    errs = []
    ids = set(nodes)
    for lid, l in links.items():
        if l[1] not in ids or l[3] not in ids:
            errs.append(f"link {lid} references missing node ({l[1]}->{l[3]})")
    for n in d["nodes"]:
        for i in n.get("inputs", []):
            lk = i.get("link")
            if lk is not None and lk not in links:
                errs.append(f"node {n['id']} input {i['name']} dangling link {lk}")
    # every GetNode name must have a SetNode
    setnames = {n["widgets_values"][0] for n in d["nodes"] if n["type"] == "SetNode" and n.get("widgets_values")}
    for n in d["nodes"]:
        if n["type"] == "GetNode" and n.get("widgets_values"):
            if n["widgets_values"][0] not in setnames:
                errs.append(f"GetNode {n['id']} '{n['widgets_values'][0]}' has no SetNode")
    if errs:
        for e in errs:
            print(" -", e)
        die(f"{len(errs)} validation errors")

    json.dump(d, open(a.out, "w"))
    print(f"OK: {len(d['nodes'])} nodes, {len(d['links'])} links -> {a.out}")
    print(f"deleted {len(doomed)} nodes; Stage 0 added {len(NEW)}")


if __name__ == "__main__":
    main()
