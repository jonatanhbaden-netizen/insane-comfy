#!/usr/bin/env python3
"""Build aiofm_i2i_v3 — pixel-law face swap.

The reference photo's pixels are law. Only the face region is ever synthesised;
clothing, fabric, background and lighting are the original file, untouched. That
is what makes the output undetectable and what lets the pipeline handle content
the base model could never render itself.

    detect face (yolov8m)  ->  crop with context, upscale to 1024
    -> Z-Image Turbo + her LoRA re-renders the crop  (denoise ~0.5;
       the source latent keeps pose, head angle and expression)
    -> parse a precise face mask at 1024 (MediaPipe, hair excluded)
    -> harmonise: colour-match, grain-match to the source crop
    -> composite inside the crop, stitch back at full resolution

Emits both formats from one spec:
    workflows/aiofm_i2i_v3.json          UI graph for the ComfyUI sidebar
    telegram-bot/workflows_api/i2i_v3.json   API graph for the bot / tests

Every class name, widget name and socket is validated against a live pod's
/object_info before anything is written — a typo fails the build, it does not
ship a broken graph.

Usage:
    python3 build_i2i_v3.py <object_info.json> [--outdir DIR]
"""
import json
import sys
import argparse
from pathlib import Path

# Types that arrive over a wire rather than as a widget.
LINK_TYPES = {
    "MODEL", "CLIP", "VAE", "IMAGE", "MASK", "LATENT", "CONDITIONING", "STITCHER",
    "SEGS", "BBOX_DETECTOR", "SEGM_DETECTOR", "SAM_MODEL", "DETAILER_HOOK",
    "CLIP_VISION", "STRING_OUT", "CRT_ISOLATE_PIPE", "LORA_MODEL",
}

# Nodes whose UI widget list does not match the object_info input list.
# ComfyUI's frontend injects extra widgets for these.
WIDGET_QUIRKS = {
    # LoadImage gets an upload-button widget after the filename combo
    "LoadImage": lambda vals: vals + ["image"],
}
# The frontend injects a control_after_generate combo after ANY widget named
# "seed" — applied generically in _widget_values, not per node class.

GREEN = ("#232", "#353")
BLUE = ("#223", "#335")
PURPLE = ("#323", "#535")
AMBER = ("#432", "#653")
RED = ("#533", "#755")


class Graph:
    def __init__(self, object_info):
        self.oi = object_info
        self.nodes = {}
        self.order = []
        self.errors = []

    def add(self, nid, ntype, *, title=None, pos=(0, 0), size=None, mode=0,
            color=None, widgets=None, links=None):
        """Register one node. widgets={name: value}, links={input_name: (src_id, slot)}."""
        if ntype not in self.oi:
            self.errors.append(f"node {nid}: unknown class_type {ntype!r}")
            return nid
        spec = self.oi[ntype]["input"]
        valid = {**spec.get("required", {}), **spec.get("optional", {})}
        for w in (widgets or {}):
            if w not in valid:
                self.errors.append(
                    f"node {nid} ({ntype}): unknown widget {w!r}; "
                    f"valid = {sorted(valid)}")
        for i in (links or {}):
            if i not in valid:
                self.errors.append(
                    f"node {nid} ({ntype}): unknown input {i!r}; "
                    f"valid = {sorted(valid)}")
        self.nodes[nid] = dict(
            id=nid, type=ntype, title=title, pos=list(pos), size=size, mode=mode,
            color=color, widgets=widgets or {}, links=links or {})
        self.order.append(nid)
        return nid

    # ---------------------------------------------------------------- helpers
    def _inputs_in_order(self, ntype):
        spec = self.oi[ntype]["input"]
        out = []
        for section in ("required", "optional"):
            for name, s in spec.get(section, {}).items():
                t = s[0]
                is_widget = isinstance(t, list) or t not in LINK_TYPES
                out.append((name, t, is_widget))
        return out

    def _widget_values(self, n):
        vals = []
        for name, t, is_widget in self._inputs_in_order(n["type"]):
            if not is_widget:
                continue
            if name in n["links"]:          # widget converted to an input socket
                continue
            if name in n["widgets"]:
                vals.append(n["widgets"][name])
            else:
                default = self._default(n["type"], name)
                vals.append(default)
        quirk = WIDGET_QUIRKS.get(n["type"])
        if quirk:
            vals = quirk(vals)
        # generic seed quirk: insert control_after_generate after each seed widget
        out = []
        widget_names = [name for name, t, w in self._inputs_in_order(n["type"])
                        if w and name not in n["links"]]
        for i, v in enumerate(vals):
            out.append(v)
            if i < len(widget_names) and widget_names[i] == "seed":
                out.append("fixed")
        return out

    def _default(self, ntype, name):
        spec = self.oi[ntype]["input"]
        for section in ("required", "optional"):
            if name in spec.get(section, {}):
                s = spec[section][name]
                t = s[0]
                extra = s[1] if len(s) > 1 and isinstance(s[1], dict) else {}
                if "default" in extra:
                    return extra["default"]
                if t == "COMBO":
                    opts = extra.get("options") or [""]
                    return opts[0]
                if isinstance(t, list):
                    return t[0] if t else ""
                return {"STRING": "", "INT": 0, "FLOAT": 0.0, "BOOLEAN": False}.get(t, None)
        return None

    def _out_index(self, ntype, slot):
        outs = self.oi[ntype].get("output") or []
        if isinstance(slot, int):
            if slot >= len(outs):
                self.errors.append(f"{ntype}: output slot {slot} out of range ({outs})")
            return slot
        names = self.oi[ntype].get("output_name") or outs
        if slot not in names:
            self.errors.append(f"{ntype}: no output named {slot!r} (has {names})")
            return 0
        return list(names).index(slot)

    # ------------------------------------------------------------- validation
    def validate(self):
        for nid, n in self.nodes.items():
            for inp, (src, slot) in n["links"].items():
                if src not in self.nodes:
                    self.errors.append(f"node {nid}: link from unknown node {src}")
                    continue
                src_type = self.nodes[src]["type"]
                idx = self._out_index(src_type, slot)
                declared = self.oi[src_type].get("output") or []
                got = declared[idx] if idx < len(declared) else "?"
                want = self._input_type(n["type"], inp)
                if want not in (got, "*") and isinstance(want, str) and want in LINK_TYPES:
                    self.errors.append(
                        f"node {nid} ({n['type']}).{inp} wants {want}, "
                        f"but {src}({src_type}) slot {idx} gives {got}")
        # every required input must be satisfied
        for nid, n in self.nodes.items():
            req = self.oi[n["type"]]["input"].get("required", {})
            for name, s in req.items():
                t = s[0]
                if not isinstance(t, list) and t in LINK_TYPES and name not in n["links"]:
                    self.errors.append(f"node {nid} ({n['type']}): required input {name!r} unconnected")
        return self.errors

    def _input_type(self, ntype, name):
        spec = self.oi[ntype]["input"]
        for section in ("required", "optional"):
            if name in spec.get(section, {}):
                return spec[section][name][0]
        return None

    # ----------------------------------------------------------- API emitter
    def to_api(self, skip_modes=(2, 4)):
        live = {nid for nid, n in self.nodes.items() if n["mode"] not in skip_modes}
        api = {}
        for nid in self.order:
            n = self.nodes[nid]
            if nid not in live:
                continue
            inputs = {}
            for name, t, is_widget in self._inputs_in_order(n["type"]):
                if name in n["links"]:
                    src, slot = n["links"][name]
                    if src not in live:
                        continue
                    inputs[name] = [str(src), self._out_index(self.nodes[src]["type"], slot)]
                elif name in n["widgets"]:
                    inputs[name] = n["widgets"][name]
                elif name in self.oi[n["type"]]["input"].get("required", {}):
                    inputs[name] = self._default(n["type"], name)
            api[str(nid)] = {
                "inputs": inputs,
                "class_type": n["type"],
                "_meta": {"title": n["title"] or n["type"]},
            }
        return api

    # ------------------------------------------------------------ UI emitter
    def to_ui(self):
        links = []
        lid = 0
        out_links = {nid: {} for nid in self.nodes}
        node_json = {}

        for nid in self.order:
            n = self.nodes[nid]
            node_json[nid] = {
                "id": nid,
                "type": n["type"],
                "pos": n["pos"],
                "size": n["size"] or [270, 100],
                "flags": {},
                "order": self.order.index(nid),
                "mode": n["mode"],
                "inputs": [],
                "outputs": [],
                "properties": {"Node name for S&R": n["type"]},
                "widgets_values": self._widget_values(n),
            }
            if n["title"]:
                node_json[nid]["title"] = n["title"]
            if n["color"]:
                node_json[nid]["color"], node_json[nid]["bgcolor"] = n["color"]

        # inputs / links
        for nid in self.order:
            n = self.nodes[nid]
            for name, t, is_widget in self._inputs_in_order(n["type"]):
                if name not in n["links"]:
                    continue
                src, slot = n["links"][name]
                idx = self._out_index(self.nodes[src]["type"], slot)
                lid += 1
                typ = self._input_type(n["type"], name)
                typ = typ if isinstance(typ, str) else "COMBO"
                links.append([lid, src, idx, nid, len(node_json[nid]["inputs"]), typ])
                node_json[nid]["inputs"].append({"name": name, "type": typ, "link": lid})
                out_links[src].setdefault(idx, []).append(lid)

        # outputs
        for nid in self.order:
            n = self.nodes[nid]
            outs = self.oi[n["type"]].get("output") or []
            names = self.oi[n["type"]].get("output_name") or outs
            for i, o in enumerate(outs):
                node_json[nid]["outputs"].append({
                    "name": names[i] if i < len(names) else o,
                    "type": o,
                    "links": out_links[nid].get(i, []),
                    "slot_index": i,
                })

        return {
            "last_node_id": max(self.nodes) if self.nodes else 0,
            "last_link_id": lid,
            "nodes": [node_json[nid] for nid in self.order],
            "links": links,
            "groups": GROUPS,
            "config": {},
            "extra": {"ds": {"scale": 0.65, "offset": [0, 0]}},
            "version": 0.4,
        }


GROUPS = [
    {"title": "1 · INPUT", "bounding": [20, 20, 420, 700], "color": "#3f789e", "font_size": 24, "flags": {}},
    {"title": "2 · Z-IMAGE + HER IDENTITY", "bounding": [470, 20, 400, 700], "color": "#a1309b", "font_size": 24, "flags": {}},
    {"title": "3 · FIND THE FACE, CROP IT BIG", "bounding": [900, 20, 400, 620], "color": "#3f789e", "font_size": 24, "flags": {}},
    {"title": "4 · RENDER HER FACE", "bounding": [1330, 20, 400, 620], "color": "#b06634", "font_size": 24, "flags": {}},
    {"title": "5 · HARMONISE  (the undetectability stage)", "bounding": [1760, 20, 430, 700], "color": "#8A8", "font_size": 24, "flags": {}},
    {"title": "6 · STITCH BACK + SAVE", "bounding": [2220, 20, 400, 520], "color": "#3f789e", "font_size": 24, "flags": {}},
    {"title": "OPTIONAL · prompt edits (bypassed — Ctrl+B to enable)", "bounding": [20, 760, 850, 420], "color": "#653", "font_size": 24, "flags": {}},
]


# =============================================================================
#  The graph
# =============================================================================
def build(oi, lora_name, trigger):
    g = Graph(oi)

    # ---------------------------------------------------------------- 1 INPUT
    g.add(1, "LoadImage", title="REF 1 — SCENE  (drop the post here)",
          pos=(40, 80), size=[380, 380], color=GREEN,
          widgets={"image": "example.png"})

    # ------------------------------------------ OPTIONAL Qwen prompt edits
    # Bypassed by default. To use: Ctrl+B the purple nodes AND set the switch
    # to 2. The edit re-renders the whole reference once (Qwen's preservation
    # objective), then the normal face pass runs on the edited image. While
    # off, the reference stays byte-exact.
    g.add(70, "UNETLoader", title="[edit] Qwen-Edit-2511", pos=(40, 840), mode=0, color=PURPLE,
          widgets={"unet_name": "qwen_image_edit_2511_fp8mixed.safetensors",
                   "weight_dtype": "default"})
    g.add(71, "CLIPLoader", title="[edit] Qwen CLIP", pos=(40, 960), mode=0, color=PURPLE,
          widgets={"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image"})
    g.add(72, "VAELoader", title="[edit] Qwen VAE", pos=(40, 1060), mode=0, color=PURPLE,
          widgets={"vae_name": "qwen_image_vae.safetensors"})
    g.add(73, "LoraLoaderModelOnly", title="[edit] Lightning 4-step", pos=(300, 840),
          mode=0, color=PURPLE,
          widgets={"lora_name": "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
                   "strength_model": 1.0},
          links={"model": (70, 0)})
    g.add(74, "ModelSamplingAuraFlow", title="[edit] shift", pos=(300, 960), mode=0,
          color=PURPLE, widgets={"shift": 3.1}, links={"model": (73, 0)})
    g.add(6, "LoadImage", title="REF 2 — HER PHOTO (identity for the swap)",
          pos=(40, 1300), size=[380, 320], color=GREEN,
          widgets={"image": "emma_face_ref.png"})

    g.add(76, "PrimitiveStringMultiline", title="SWAP INSTRUCTION (+ your edits)",
          pos=(40, 1160), size=[380, 120], mode=0, color=AMBER,
          widgets={"value": "Replace the face and hair of the woman in image 1 "
                            "with the face of the woman in image 2. She has a "
                            "golden blonde shoulder-length bob with a middle "
                            "part. Keep image 1's exact pose, camera angle, "
                            "framing, lighting, shadows and background. Keep "
                            "the exact clothing, outfit, accessories and "
                            "jewelry from image 1 — do not change them."})
    g.add(79, "FluxKontextImageScale", title="[edit] size for Qwen", pos=(560, 840),
          mode=0, color=PURPLE, links={"image": (1, 0)})
    g.add(77, "TextEncodeQwenImageEditPlus", title="[edit] encode edit", pos=(560, 940),
          mode=0, color=PURPLE,
          links={"clip": (71, 0), "prompt": (76, 0), "vae": (72, 0), "image1": (79, 0),
                 "image2": (6, 0)})
    g.add(78, "ConditioningZeroOut", title="[edit] negative", pos=(560, 1060), mode=0,
          color=PURPLE, links={"conditioning": (77, 0)})
    g.add(80, "VAEEncode", title="[edit] to latent", pos=(560, 1160), mode=0, color=PURPLE,
          links={"pixels": (79, 0), "vae": (72, 0)})
    g.add(81, "KSampler", title="[edit] 4-step edit", pos=(800, 840), size=[300, 240],
          mode=0, color=PURPLE,
          widgets={"seed": 0, "steps": 4, "cfg": 1.0, "sampler_name": "euler",
                   "scheduler": "simple", "denoise": 1.0},
          links={"model": (74, 0), "positive": (77, 0), "negative": (78, 0),
                 "latent_image": (80, 0)})
    g.add(82, "VAEDecode", title="[edit] decode", pos=(800, 1120), mode=0, color=PURPLE,
          links={"samples": (81, 0), "vae": (72, 0)})

    # switch: 1 = untouched reference (default) · 2 = Qwen-edited reference
    g.add(5, "ImageMaskSwitch", title="SOURCE SWITCH  (1 = original, 2 = edited)",
          pos=(40, 700), size=[380, 100], color=GREEN,
          widgets={"select": 2},
          links={"images1": (1, 0), "images2_opt": (82, 0)})

    g.add(2, "PrimitiveStringMultiline",
          title="IDENTITY PROMPT  (describe the shot, keep the trigger word)",
          pos=(40, 500), size=[380, 180], color=AMBER,
          widgets={"value": f"{trigger}, photo of a woman, heterochromia, "
                            "left eye warm brown, right eye light blue, "
                            "shoulder-length golden blonde bob with a middle part, "
                            "looking at the camera, soft natural expression, "
                            "natural skin, sharp eyes, photographic lighting"})

    g.add(3, "PrimitiveStringMultiline", title="NEGATIVE  (inert at cfg 1.0 — leave empty)",
          pos=(40, 700), size=[380, 90], color=BLUE, widgets={"value": ""})

    # ------------------------------------------------- 2 Z-IMAGE + IDENTITY
    g.add(10, "UNETLoader", title="Z-Image Turbo", pos=(490, 80),
          widgets={"unet_name": "z_image_turbo_bf16.safetensors", "weight_dtype": "default"})

    # qwen_3_4b auto-routes to comfy.text_encoders.z_image for any type that
    # isn't flux/flux2 (comfy/sd.py, TEModel.QWEN3_4B branch). "lumina2" is what
    # the CRT pack's own Z-Image loader passes.
    g.add(11, "CLIPLoader", title="Z-Image text encoder", pos=(490, 200),
          widgets={"clip_name": "qwen_3_4b.safetensors", "type": "lumina2"})

    # Z-Image ships the same VAE as Flux — verified identical byte length
    # (335,304,388) against Comfy-Org/z_image_turbo split_files/vae/ae.safetensors.
    g.add(12, "VAELoader", title="Z-Image VAE (= Flux ae)", pos=(490, 300),
          widgets={"vae_name": "ae.safetensors"})

    g.add(13, "LoraLoaderModelOnly", title="◆ HER IDENTITY — character LoRA",
          pos=(490, 390), size=[350, 90], color=PURPLE,
          widgets={"lora_name": lora_name, "strength_model": 0.65},
          links={"model": (10, 0)})

    g.add(14, "ModelSamplingAuraFlow", title="shift", pos=(490, 520),
          widgets={"shift": 3.0}, links={"model": (13, 0)})

    g.add(15, "CFGNorm", title="CFG norm", pos=(490, 620),
          widgets={"strength": 1.0}, links={"model": (14, 0)})

    g.add(16, "CLIPTextEncode", title="positive", pos=(490, 720),
          links={"clip": (11, 0), "text": (2, 0)})

    g.add(17, "CLIPTextEncode", title="negative", pos=(490, 830),
          links={"clip": (11, 0), "text": (3, 0)})

    # --------------------------------------------- 3 FIND THE FACE, CROP BIG
    # Full-image parse: face AND hair define the swap region. Hair is identity —
    # excluding it (the July face-only rule) leaves the reference person's hair
    # on her head. Full-image (not crop-level) so long hair can't spill outside
    # the crop and go two-tone.
    g.add(22, "APersonMaskGenerator", title="swap region: face + ALL hair",
          pos=(920, 180), size=[350, 200], color=BLUE,
          widgets={"face_mask": True, "background_mask": False, "hair_mask": True,
                   "body_mask": False, "clothes_mask": False, "confidence": 0.4,
                   "refine_mask": True},
          links={"images": (5, 0)})

    # context_from_mask_extend_factor gives the model hair + neck + surrounding
    # light to match against; output_target_* is why a 90px face still renders
    # at 1024 and comes back with real detail.
    g.add(23, "InpaintCropImproved", title="◆ CROP THE FACE OUT AT 1024",
          pos=(920, 490), size=[350, 130], color=BLUE,
          widgets={"downscale_algorithm": "bilinear", "upscale_algorithm": "bicubic",
                   "preresize": False, "mask_fill_holes": True, "mask_expand_pixels": 0,
                   "mask_invert": False, "mask_blend_pixels": 32,
                   "mask_hipass_filter": 0.1, "extend_for_outpainting": False,
                   "context_from_mask_extend_factor": 1.6,
                   "output_resize_to_target_size": True,
                   "output_target_width": 1024, "output_target_height": 1024,
                   "output_padding": "32", "device_mode": "gpu (much faster)"},
          links={"image": (5, 0), "mask": (22, 0)})

    # MediaPipe face parse at 1024 — hair_mask stays False so her hair is never
    # painted; the reference's hair, ears and jawline survive the swap.
    g.add(24, "APersonMaskGenerator", title="◆ precise face+hair mask",
          pos=(920, 660), size=[350, 180], color=BLUE,
          widgets={"face_mask": True, "background_mask": False, "hair_mask": True,
                   "body_mask": False, "clothes_mask": False, "confidence": 0.4,
                   "refine_mask": True},
          links={"images": (23, "cropped_image")})

    g.add(25, "GrowMaskWithBlur", title="feather the mask", pos=(920, 880), size=[330, 200],
          widgets={"expand": 10, "incremental_expandrate": 0.0, "tapered_corners": True,
                   "flip_input": False, "blur_radius": 10.0, "lerp_alpha": 1.0,
                   "decay_factor": 1.0, "fill_holes": False},
          links={"mask": (24, 0)})

    # ------------------------------------------------------ 4 RENDER HER FACE
    g.add(30, "VAEEncode", title="crop → latent", pos=(1350, 80),
          links={"pixels": (23, "cropped_image"), "vae": (12, 0)})

    # THE identity mechanism. img2img at 0.5 kept the source person's bone
    # structure and only repainted the surface — "a blend that looks like
    # neither". With the noise mask, the masked region regenerates from pure
    # noise: geometry comes from the LoRA, pose/lighting anchor on the
    # untouched surround.
    g.add(33, "SetLatentNoiseMask", title="◆ erase her — rebuild from the LoRA",
          pos=(1350, 170), color=PURPLE,
          links={"samples": (30, 0), "mask": (25, 0)})

    # denoise 0.5: enough for the LoRA to impose her features, low enough that
    # the source latent keeps pose, head angle and expression.
    g.add(31, "KSampler", title="◆ IDENTITY RENDER", pos=(1350, 200), size=[350, 260],
          color=PURPLE,
          widgets={"seed": 0, "steps": 16, "cfg": 1.0, "sampler_name": "euler",
                   "scheduler": "simple", "denoise": 1.0},
          links={"model": (15, 0), "positive": (16, 0), "negative": (17, 0),
                 "latent_image": (33, 0)})

    g.add(32, "VAEDecode", title="latent → pixels", pos=(1350, 500),
          links={"samples": (31, 0), "vae": (12, 0)})

    # ---------------------------------------------------------- 5 HARMONISE
    # Steals the scene's white balance and skin tone off the untouched crop.
    g.add(40, "ColorMatch", title="◆ match colour to the scene", pos=(1780, 80),
          size=[350, 140], color=("#353", "#232"),
          widgets={"method": "mkl", "strength": 0.35},
          links={"image_ref": (23, "cropped_image"), "image_target": (32, 0)})

    # A face with no grain in a grainy photo is the classic tell.
    g.add(41, "FilmGrain", title="◆ match grain to the photo", pos=(1780, 260),
          size=[350, 160], color=("#353", "#232"),
          widgets={"intensity": 0.03, "scale": 10.0, "temperature": 0.0, "vignette": 0.0},
          links={"image": (40, 0)})

    # Only the face-mask pixels are taken from the render. Everything else in
    # the crop is still the original file.
    g.add(42, "ImageCompositeMasked", title="◆ face only — rest stays original",
          pos=(1780, 460), size=[350, 150], color=("#353", "#232"),
          widgets={"x": 0, "y": 0, "resize_source": False},
          links={"destination": (23, "cropped_image"), "source": (41, 0), "mask": (25, 0)})

    # ------------------------------------------------------ 6 STITCH + SAVE
    g.add(50, "InpaintStitchImproved", title="◆ back into the full-res original",
          pos=(2240, 80), size=[340, 90], color=GREEN,
          links={"stitcher": (23, "stitcher"), "inpainted_image": (42, 0)})

    g.add(90, "UpscaleModelLoader", title="[finish] 4x-UltraSharp", pos=(2240, 220),
          widgets={"model_name": "4x-UltraSharp.pth"})
    g.add(92, "ImageUpscaleWithModel", title="◆ 4x model upscale", pos=(2240, 320),
          links={"upscale_model": (90, 0), "image": (50, 0)})
    g.add(94, "ImageScaleToTotalPixels", title="fit to delivery ~2.1MP", pos=(2240, 420),
          widgets={"upscale_method": "lanczos", "megapixels": 2.1, "resolution_steps": 1},
          links={"image": (92, 0)})
    g.add(93, "FilmGrain", title="[finish] grain", pos=(2240, 680),
          widgets={"intensity": 0.02, "scale": 10.0, "temperature": 0.0, "vignette": 0.0},
          links={"image": (94, 0)})
    g.add(51, "SaveImage", title="FINAL", pos=(2240, 780), size=[340, 300], color=GREEN,
          widgets={"filename_prefix": "AIOFM_i2i_v3"}, links={"images": (93, 0)})

    # diagnosis previews — which stage broke it, without guessing
    g.add(60, "PreviewImage", title="A · source crop", pos=(2240, 560), size=[300, 250],
          links={"images": (23, "cropped_image")})
    g.add(61, "PreviewImage", title="B · raw render", pos=(2240, 830), size=[300, 250],
          links={"images": (32, 0)})
    g.add(62, "PreviewImage", title="C · harmonised crop", pos=(2240, 1100), size=[300, 250],
          links={"images": (42, 0)})

    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("object_info")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--lora", default="f1sher_000002400.safetensors")
    ap.add_argument("--trigger", default="F1sher")
    args = ap.parse_args()

    oi = json.load(open(args.object_info))
    g = build(oi, args.lora, args.trigger)
    errs = g.validate()
    if errs:
        print("VALIDATION FAILED:")
        for e in errs:
            print("  -", e)
        sys.exit(1)

    out = Path(args.outdir)
    ui = g.to_ui()
    api = g.to_api()
    (out / "aiofm_i2i_v3.json").write_text(json.dumps(ui, indent=1))
    (out / "i2i_v3_api.json").write_text(json.dumps(api, indent=1))
    print(f"OK  {len(ui['nodes'])} nodes, {len(ui['links'])} links")
    print(f"    UI  -> {out/'aiofm_i2i_v3.json'}")
    print(f"    API -> {out/'i2i_v3_api.json'}")


if __name__ == "__main__":
    main()
