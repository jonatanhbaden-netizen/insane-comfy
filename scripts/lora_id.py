#!/usr/bin/env python3
"""Identify the base architecture of .safetensors LoRA files by reading only the header."""
import json, struct, sys, os, glob, tarfile

def header(fobj):
    n = struct.unpack("<Q", fobj.read(8))[0]
    return json.loads(fobj.read(n))

def classify(keys, meta):
    k = " ".join(keys[:400])
    hints = []
    if "double_blocks" in k and "single_blocks" in k: hints.append("FLUX")
    if "img_mlp" in k or "txt_mlp" in k: hints.append("FLUX-ish")
    if "self_attn" in k and "cross_attn" in k and "ffn" in k: hints.append("WAN")
    if "transformer_blocks" in k and "attn1" in k and "attn2" in k: hints.append("LTX/DiT")
    if "down_blocks" in k or "lora_te1" in k or "lora_te2" in k: hints.append("SDXL/SD15")
    if "img_in" in k and "txt_in" in k: hints.append("FLUX-core")
    if "noise_refiner" in k or "context_refiner" in k: hints.append("Z-IMAGE/Lumina")
    if "layers." in k and "attention" in k: hints.append("LUMINA-ish")
    # metadata clues
    for f in ("ss_base_model_version","modelspec.architecture","ss_network_module",
              "ss_sd_model_name","base_model","ss_base_model","architecture"):
        if f in meta: hints.append(f"{f}={meta[f]}")
    return hints

def report(path, keys, meta, size):
    hints = classify(keys, meta)
    tk = [x for x in keys if x != "__metadata__"]
    sample = tk[:3]
    print(f"\n### {path}  ({size/1e6:.0f} MB, {len(tk)} tensors)")
    print("  hints: " + (", ".join(dict.fromkeys(hints)) or "UNKNOWN"))
    print("  keys : " + " | ".join(sample))
    if meta:
        keep = {a: b for a, b in meta.items() if any(s in a.lower() for s in
                ("base","arch","network","model","dim","alpha","resolution","train"))}
        if keep:
            print("  meta : " + json.dumps(keep)[:600])

def do_file(p):
    try:
        with open(p, "rb") as f:
            h = header(f)
        report(p, list(h.keys()), h.get("__metadata__", {}) or {}, os.path.getsize(p))
    except Exception as e:
        print(f"\n### {p} -> ERROR {e}")

for p in sys.argv[1:]:
    do_file(p)
