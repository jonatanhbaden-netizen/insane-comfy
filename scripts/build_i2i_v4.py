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

# Character-agnostic prompt plumbing: ONE box holds the character (trigger
# word + traits). Both the Qwen instruction and the main positive are built
# from it with StringConcatenate, so switching girls = swap the LoRA in the
# loader + edit this one box. No other node mentions the character.
CHARACTER_DEFAULT = (
    "F1sher, golden blonde shoulder-length bob with a middle part, "
    "heterochromia, left eye warm brown, right eye light blue"
)
# "her face, hair and skin become X" vs "keep pose/outfit/background" — the
# explicit split is what makes Qwen restructure the HAIR instead of treating
# it as part of "keep everything unchanged" (live finding: listed as a mere
# trait, the bob loses to the preservation clause and reference hair stays).
QWEN_TEMPLATE_PRE = (
    "Replace the woman in image 1 with this woman: "
)
# Face-conditional: on faceless references (back shots, cropped, turned away)
# Qwen must NOT invent or reveal a face to satisfy a face-swap instruction —
# it applies only the attributes the shot can show (hair, skin, body).
QWEN_TEMPLATE_POST = (
    ". Apply only what is visible in image 1: if her face is visible, "
    "replace the face with the described woman's face. If her face is NOT "
    "visible (turned away, cropped out of frame, or hidden), do not add, "
    "reveal or rotate a face — keep the exact head pose and change only her "
    "hair and skin tone to match the description. The described hairstyle "
    "and hair color fully replace the original hair in all cases. Keep her "
    "exact facial expression from image 1 — do not change the expression. "
    "Do not add any clothing, coverage or fabric that is not in image 1; "
    "keep exactly the same garments and the same amount of exposed skin. "
    "Keep image 1's exact pose, body position, outfit, clothing, "
    "accessories, background, framing, camera angle and lighting completely "
    "unchanged. "
    "Photorealistic, natural skin texture. If several people are in image 1, "
    "replace only the person I specify here:"
)
POSITIVE_SUFFIX = (
    ", natural skin texture with visible pores and fine detail, candid phone "
    "photo"
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
    # + stages 3/4 (v4.1: their whole-frame LoRA repaint drifted clothing/
    # body off the reference and double-softened the frame — identity now
    # lives solely in the face detailer, exactness in the Qwen frame)
    for nid in (518, 519, 28, 110, 521, 522, 111, 436, 189, 437):
        if nid in nodes:
            doomed.add(nid)
    for nid, n in nodes.items():
        if n["type"] in ("SetNode", "GetNode") and n.get("widgets_values"):
            if str(n["widgets_values"][0]) in (
                    "Stage 1 Latent", "Stage 2 Latent", "Stage 3 Latent",
                    "Stage 4 Latent", "Stage 3 Seed", "Stage 4 Seed"):
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

    # main positive text arrives via the CHARACTER concat (wired below);
    # the widget value remains only as an inert fallback
    nodes[6]["widgets_values"] = [CHARACTER_DEFAULT + POSITIVE_SUFFIX]

    # detailer VAE 556 (top level): fluxvae1dev -> ae
    if 556 in nodes:
        nodes[556]["widgets_values"] = ["ae.safetensors"]

    # MODELS + FACE subgraph definition edits
    for sg in d.get("definitions", {}).get("subgraphs", []):
        for n in sg.get("nodes", []):
            if n["type"] == "VAELoader" and n.get("widgets_values") and "ultraflux" in str(n["widgets_values"][0]).lower():
                n["widgets_values"] = ["ae.safetensors"]
            if n["type"] == "AdvancedImageDenoiser":
                w = n.get("widgets_values", [])
                for i, v in enumerate(w):
                    if v == 0.41:
                        w[i] = 0.15
            if n["type"] == "CRT Post-Process Suite":
                w = n.get("widgets_values", [])
                # its internal-upscaler toggle ships OFF, but the widget still
                # names the manager's absent 4kNomos model and trips the
                # missing-model check — point it at a model that exists
                for i, v in enumerate(w):
                    if isinstance(v, str) and "Nomos" in v:
                        w[i] = "4x-UltraSharp.pth"
            if str(sg.get("id", "")).startswith(("dfb392f5", "d39950fa")):
                # photo-fed latents: nearest-exact latent upscale turns the
                # encoded photo's hard edges into stair-step spikes that the
                # noise-injected samplers render as physical tears (live
                # bisection: stage 3 clean, stage 4 shredded). bilinear is the
                # photo-latent-safe choice; DetailBoost re-sharpens after.
                if n["type"] == "LatentUpscale" and n["widgets_values"][0] == "nearest-exact":
                    n["widgets_values"][0] = "bilinear"
            # (stage-3 ladder step reverted 2026-08-02: it was compensating
            # for the encoder bug; with binding fixed it only added drift —
            # stage 3 runs the professional's 0.50 denoise / 0.40 inject)
            if n["type"] == "ImageScaleBy" and str(sg.get("id", "")).startswith("c6d045e4"):
                # v4.1: SeedVR2 receives the 896x1152 Qwen frame directly —
                # the pro's half-res round trip assumed a 1344px sampled
                # frame; halving 896 would starve the restorer
                w = n.get("widgets_values", [])
                for i, v in enumerate(w):
                    if v == 0.5:
                        w[i] = 1.0

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

    def wire(src, sslot, dst, iname, typ, reuse=None, widget=False):
        L[0] += 1
        lid = reuse if reuse is not None else L[0]
        # reuse an existing input entry (e.g. a widget the professional had
        # converted and left disconnected) — a duplicate name would win the
        # frontend's binding with its null link and silently blank the value
        entry = next((i for i in dst["inputs"] if i.get("name") == iname), None)
        if entry is None:
            entry = {"name": iname, "type": typ}
            dst["inputs"].append(entry)
        entry["link"] = lid
        if widget:
            entry["widget"] = {"name": iname}
        links[lid] = [lid, src["id"], sslot, dst["id"], dst["inputs"].index(entry), typ]
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
    char = mk(620, "PrimitiveStringMultiline", [X, 1330], [CHARACTER_DEFAULT],
              "◆ CHARACTER — trigger word + traits (swap girl HERE + LoRA loader)", [420, 160])
    char["outputs"] = [{"name": "STRING", "type": "STRING", "links": [], "slot_index": 0}]
    tpre = mk(621, "PrimitiveStringMultiline", [X + 380, 1330], [QWEN_TEMPLATE_PRE], "[template] swap pre")
    tpre["outputs"] = [{"name": "STRING", "type": "STRING", "links": [], "slot_index": 0}]
    tpost = mk(622, "PrimitiveStringMultiline", [X + 380, 1480], [QWEN_TEMPLATE_POST],
               "[template] swap post — add edits / which person at the end", [420, 160])
    tpost["outputs"] = [{"name": "STRING", "type": "STRING", "links": [], "slot_index": 0}]
    cat1 = mk(623, "StringConcatenate", [X + 760, 1330], [""], "pre+character")
    cat1["outputs"] = [{"name": "STRING", "type": "STRING", "links": [], "slot_index": 0}]
    cat2 = mk(624, "StringConcatenate", [X + 760, 1440], [""], "+post = swap instruction")
    cat2["outputs"] = [{"name": "STRING", "type": "STRING", "links": [], "slot_index": 0}]
    psuf = mk(625, "PrimitiveStringMultiline", [X + 380, 1660], [POSITIVE_SUFFIX], "[template] positive suffix")
    psuf["outputs"] = [{"name": "STRING", "type": "STRING", "links": [], "slot_index": 0}]
    cat3 = mk(626, "StringConcatenate", [X + 760, 1550], [""], "character+suffix = main positive")
    cat3["outputs"] = [{"name": "STRING", "type": "STRING", "links": [], "slot_index": 0}]

    q_pos = mk(608, "TextEncodeQwenImageEditPlus", [X + 380, 80], [QWEN_TEMPLATE_PRE + CHARACTER_DEFAULT + QWEN_TEMPLATE_POST],
               "[stage0] SWAP INSTRUCTION — 2+ people? say WHICH at the end: 'the woman on the left'", [420, 220])
    q_pos["outputs"] = [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [], "slot_index": 0}]
    q_neg = mk(609, "TextEncodeQwenImageEditPlus", [X + 380, 340], [""], "[stage0] negative")
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
    stage0_prev = mk(619, "PreviewImage", [X + 760, 700], None, "STAGE 0 — judge the swap here", [300, 300])

    # character/template plumbing
    wire(tpre, 0, cat1, "string_a", "STRING")
    wire(char, 0, cat1, "string_b", "STRING")
    wire(cat1, 0, cat2, "string_a", "STRING")
    wire(tpost, 0, cat2, "string_b", "STRING")
    wire(cat2, 0, q_pos, "prompt", "STRING", widget=True)
    wire(char, 0, cat3, "string_a", "STRING")
    wire(psuf, 0, cat3, "string_b", "STRING")
    wire(cat3, 0, nodes[6], "text", "STRING", widget=True)

    # explicit wires — every input connected so the Anything-Everywhere
    # broadcasters cannot inject the Z-Image model/clip into Stage 0
    wire(ref, 0, conform, "image", "IMAGE")
    wire(q_unet, 0, q_lora, "model", "MODEL")
    wire(q_lora, 0, q_shift, "model", "MODEL")
    wire(q_shift, 0, q_norm, "model", "MODEL")
    wire(q_clip, 0, q_pos, "clip", "CLIP")
    wire(q_vae, 0, q_pos, "vae", "VAE")
    wire(conform, 0, q_pos, "image1", "IMAGE")
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
    wire(cmatch, 0, stage0_prev, "images", "IMAGE")

    # LoRA model tap (feeds the texture pass and the FACE detailer)
    mget = mk(618, "GetNode", [X + 760, 1050], ["Model with LoRA"], "Get_Model with LoRA")
    mget["outputs"] = [{"name": "MODEL", "type": "MODEL", "links": [], "slot_index": 0}]

    # v4.2 TEXTURE PASS — the manager's texture mechanism (noise inject +
    # Clown DetailBoost + perlin) at a structure-frozen denoise. His 0.5
    # rewrote clothing and pose; 0.18 can only rewrite micro-texture, which
    # is exactly the pore/film detail Qwen's synthetic-smooth skin lacks.
    tvget = mk(630, "GetNode", [X + 1140, 80], ["Ultra Flux VAE"], "Get_Ultra Flux VAE")
    tvget["outputs"] = [{"name": "VAE", "type": "VAE", "links": [], "slot_index": 0}]
    tenc = mk(631, "VAEEncode", [X + 1140, 180], None, "[texture] encode")
    tenc["outputs"] = [{"name": "LATENT", "type": "LATENT", "links": [], "slot_index": 0}]
    tnoise = mk(632, "InjectLatentNoise+", [X + 1140, 290],
                [4242, "fixed", 0.10, "false"], "[texture] micro noise 0.10")
    tnoise["outputs"] = [{"name": "LATENT", "type": "LATENT", "links": [], "slot_index": 0}]
    tshift = mk(633, "ModelSamplingAuraFlow", [X + 1140, 400], [7], "[texture] shift 7")
    tshift["outputs"] = [{"name": "MODEL", "type": "MODEL", "links": [], "slot_index": 0}]
    tshark = mk(634, "SharkOptions_Beta", [X + 1140, 500], ["perlin", 1, 1, False], "[texture] perlin")
    tshark["outputs"] = [{"name": "options", "type": "OPTIONS", "links": [], "slot_index": 0}]
    tboost = mk(635, "ClownOptions_DetailBoost_Beta", [X + 1140, 610],
                [1.2, "model", "hard", 0.5, 1, 3], "[texture] DetailBoost 1.2")
    tboost["outputs"] = [{"name": "options", "type": "OPTIONS", "links": [], "slot_index": 0}]
    tclown = mk(636, "ClownsharKSampler_Beta", [X + 1140, 720],
                [0.52, "linear/euler", "beta57", 9, 9, 0.18, 1, 4242, "fixed", "standard", True],
                "◆ TEXTURE — denoise 0.18 (structure-frozen)", [340, 300])
    tclown["outputs"] = [{"name": "output", "type": "LATENT", "links": [], "slot_index": 0},
                         {"name": "denoised", "type": "LATENT", "links": [], "slot_index": 1},
                         {"name": "options", "type": "OPTIONS", "links": [], "slot_index": 2}]
    tdec = mk(637, "VAEDecode", [X + 1140, 1060], None, "[texture] decode")
    tdec["outputs"] = [{"name": "IMAGE", "type": "IMAGE", "links": [], "slot_index": 0}]

    wire(cmatch, 0, tenc, "pixels", "IMAGE")
    wire(tvget, 0, tenc, "vae", "VAE")
    wire(tenc, 0, tnoise, "latent", "LATENT")
    wire(mget, 0, tshift, "model", "MODEL")
    wire(tshift, 0, tclown, "model", "MODEL")
    wire(nodes[6], 0, tclown, "positive", "CONDITIONING")
    wire(nodes[7], 0, tclown, "negative", "CONDITIONING")
    wire(tnoise, 0, tclown, "latent_image", "LATENT")
    wire(tshark, 0, tclown, "options 2", "OPTIONS")
    wire(tboost, 0, tclown, "options 3", "OPTIONS")
    wire(tclown, 0, tdec, "samples", "LATENT")
    wire(tvget, 0, tdec, "vae", "VAE")

    # face detailer now reads the re-textured frame (reuse link 6519)
    wire(tdec, 0, nodes[553], "image", "IMAGE", reuse=6519)

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
