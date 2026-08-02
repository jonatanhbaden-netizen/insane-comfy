#!/usr/bin/env python3
"""Score whether a generated face is actually her.

Runs on the pod — insightface and antelopev2 are already installed there for
PuLID. Builds an embedding bank from her real training images, then measures
each candidate against it with ArcFace cosine similarity.

The bar is calibrated, not guessed: her own training photos are scored against
each other first, which gives the range that "the same person, different photo,
different lighting" actually occupies for this face. A render has to land inside
that range. A fixed threshold like 0.6 would be a number pulled from the air;
the 5th percentile of her own intra-set spread is a claim you can defend.

    python3 score_identity.py --ref-dir /workspace/identity_ref \
                              --query /workspace/output/AIOFM_i2i_v3_00001_.png
"""
import argparse
import glob
import json
import os
import sys

import numpy as np


def load_app():
    from insightface.app import FaceAnalysis
    for root in ("/ComfyUI/models/insightface", "/workspace/models/insightface"):
        if os.path.isdir(os.path.join(root, "models", "antelopev2")):
            app = FaceAnalysis(name="antelopev2", root=root,
                               providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
            app.prepare(ctx_id=0, det_size=(640, 640))
            return app
    sys.exit("antelopev2 not found on this pod")


_last_bbox = {}


def embed(app, path, largest_only=True):
    import cv2
    img = cv2.imread(path)
    if img is None:
        return None
    faces = app.get(img)
    if not faces:
        _last_bbox["bbox"] = None
        return None
    if largest_only:
        faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
                   reverse=True)
    _last_bbox["bbox"] = faces[0].bbox
    e = faces[0].normed_embedding
    return np.asarray(e, dtype=np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref-dir", required=True)
    ap.add_argument("--query", nargs="+", required=True)
    ap.add_argument("--json", help="write results here")
    a = ap.parse_args()

    app = load_app()

    ref_paths = sorted(sum([glob.glob(os.path.join(a.ref_dir, e))
                            for e in ("*.jpg", "*.jpeg", "*.png", "*.webp")], []))
    bank, missed = [], 0
    for p in ref_paths:
        e = embed(app, p)
        if e is None:
            missed += 1
        else:
            bank.append(e)
    if len(bank) < 5:
        sys.exit(f"only {len(bank)} usable reference faces — need at least 5")
    bank = np.stack(bank)

    # calibration: how similar are her own photos to each other?
    sims = bank @ bank.T
    iu = np.triu_indices(len(bank), k=1)
    intra = sims[iu]
    band = {
        "n_refs": int(len(bank)),
        "refs_without_face": int(missed),
        "intra_mean": float(intra.mean()),
        "intra_std": float(intra.std()),
        "intra_p05": float(np.percentile(intra, 5)),
        "intra_p50": float(np.percentile(intra, 50)),
        "intra_min": float(intra.min()),
    }
    pass_bar = band["intra_p05"]

    queries = []
    for q in a.query:
        paths = sorted(glob.glob(os.path.join(q, "*"))) if os.path.isdir(q) else [q]
        for p in paths:
            if not p.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                continue
            e = embed(app, p)
            if e is None:
                queries.append({"file": os.path.basename(p), "error": "no face detected"})
                continue
            s = bank @ e
            entry = {
                "file": os.path.basename(p),
                "path": os.path.abspath(p),
                "mean_sim": float(s.mean()),
                "max_sim": float(s.max()),
                "pct_of_refs_beaten": float((intra < s.mean()).mean() * 100),
                "verdict": "PASS" if s.mean() >= pass_bar else "FAIL",
            }
            # face bbox for downstream zoom-sheet cropping (largest face)
            bb = _last_bbox.get("bbox")
            if bb is not None:
                entry["bbox"] = [int(v) for v in bb]
            queries.append(entry)

    out = {"calibration": band, "pass_bar_mean_sim": pass_bar, "results": queries}
    print(json.dumps(out, indent=1))
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
