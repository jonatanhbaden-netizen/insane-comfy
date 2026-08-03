#!/usr/bin/env python3
"""GPU-free image metrics for the i2i quality loop.

Identity is measured on the pod with ArcFace (score_identity.py). Everything
else the mandate cares about — skin micro-texture, composite seams, lighting
consistency — is measurable locally from the pixels, and is measured here so
that every cycle produces numbers instead of adjectives.

Metrics (all computed inside face-relative regions derived from an ArcFace
bbox, so they are comparable across references and runs):

  skin_hf_energy      std-dev of the high-frequency residual in a cheek patch.
                      Real camera skin sits in a band; plastic/over-smoothed
                      output falls below it, crunchy AI micro-detail overshoots.
  skin_hf_ratio       cheek HF energy of OUTPUT / same patch in the REFERENCE.
                      1.0 = matched the photo's own texture statistics.
                      < 0.7 plastic;  > 1.4 over-detailed.  This is the single
                      most useful skin number we have.
  grain_ratio         HF energy of the generated face region / HF energy of an
                      untouched body-skin patch in the SAME output. 1.0 means
                      the insert carries the host photo's noise floor; this is
                      the seam-invisibility proxy the mandate asks for.
  seam_gradient       mean |∇| along the jaw/hairline boundary ring minus the
                      mean |∇| of its immediate neighbourhood. > 0 means the
                      boundary is more contrasty than its surroundings, i.e. a
                      visible edge. ~0 is invisible.
  face_neck_dE        CIE-L*a*b* ΔE between mean face skin and mean neck skin.
                      Lighting/colour mismatch of the insert. < 3 imperceptible,
                      > 6 obvious.
  laplacian_var       classic sharpness proxy of the face crop (regression
                      canary for restorer/upscaler changes).

Usage:
  python3 i2i_metrics.py --ref REF.png --out OUT.png --bbox x1 y1 x2 y2 [--json f]
  python3 i2i_metrics.py --score-json score.json --pairs REF=OUT ... --json f
"""
import argparse
import json
import os

import numpy as np
from PIL import Image, ImageFilter


_YUNET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "yunet.onnx")


def detect_face(path):
    """Local (CPU, no pod) largest-face bbox via OpenCV YuNet.

    The pod's ArcFace bbox is authoritative when available — it is the same
    detector that produces the identity score, so regions line up with what
    was measured. This is the offline fallback so a cycle's texture/seam
    numbers never depend on GPU availability.
    """
    try:
        import cv2
    except ImportError:
        return None
    if not os.path.exists(_YUNET):
        return None
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    d = cv2.FaceDetectorYN.create(_YUNET, "", (320, 320), 0.6, 0.3, 5000)
    d.setInputSize((w, h))
    _, faces = d.detect(img)
    if faces is None or len(faces) == 0:
        return None
    f = max(faces, key=lambda r: r[2] * r[3])
    x, y, fw, fh = f[:4]
    return [float(x), float(y), float(x + fw), float(y + fh)]


# ---------------------------------------------------------------- primitives
def _arr(im):
    return np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0


def _lab(rgb):
    """sRGB [0,1] -> CIE L*a*b* (D65). Vectorised, no external deps."""
    m = np.where(rgb > 0.04045, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    mat = np.array([[0.4124, 0.3576, 0.1805],
                    [0.2126, 0.7152, 0.0722],
                    [0.0193, 0.1192, 0.9505]], dtype=np.float32)
    xyz = m @ mat.T
    white = np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
    xyz = xyz / white
    d = 6.0 / 29.0
    f = np.where(xyz > d ** 3, np.cbrt(xyz), xyz / (3 * d * d) + 4.0 / 29.0)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def _hf_energy(im, box, radius=2.0):
    """std-dev of (image - gaussian blur) inside box, luminance only.

    Scale-normalised: measured on a fixed 256px-wide patch so that a 2160px
    output and an 1180px reference are compared at the same spatial frequency
    (otherwise every upscale would look like a texture 'gain')."""
    c = im.crop(box)
    if c.width < 8 or c.height < 8:
        return float("nan")
    scale = 256.0 / max(c.width, 1)
    if scale < 1.0:
        c = c.resize((256, max(1, int(c.height * scale))), Image.LANCZOS)
    g = np.asarray(c.convert("L"), dtype=np.float32)
    b = np.asarray(c.convert("L").filter(ImageFilter.GaussianBlur(radius)),
                   dtype=np.float32)
    return float((g - b).std())


def _regions(w, h, bb):
    x1, y1, x2, y2 = bb
    bw, bh = x2 - x1, y2 - y1
    cx = (x1 + x2) / 2.0

    def clamp(box):
        a, b, c, d = box
        a, b = max(0, int(a)), max(0, int(b))
        c, d = min(w, int(c)), min(h, int(d))
        if c <= a: c = min(w, a + 2)
        if d <= b: d = min(h, b + 2)
        return (a, b, c, d)

    return {
        # cheek: below the eyes, beside the nose — the flattest large skin area
        "cheek": clamp((cx + bw * 0.10, y1 + bh * 0.48, cx + bw * 0.42, y1 + bh * 0.78)),
        "forehead": clamp((cx - bw * 0.20, y1 + bh * 0.06, cx + bw * 0.20, y1 + bh * 0.24)),
        # neck strip well below the jaw — untouched host pixels in a face-only composite
        "neck": clamp((cx - bw * 0.22, y2 + bh * 0.18, cx + bw * 0.22, y2 + bh * 0.42)),
        # body skin far from the face: the host photo's true noise floor
        "body": clamp((cx - bw * 0.75, y2 + bh * 0.55, cx - bw * 0.20, y2 + bh * 0.95)),
        "face": clamp((x1, y1, x2, y2)),
    }


def _boundary_ring(im, bb, thickness_frac=0.06):
    """gradient contrast on the jaw/hairline ring vs its neighbourhood."""
    g = np.asarray(im.convert("L"), dtype=np.float32)
    gx = np.abs(np.diff(g, axis=1, prepend=g[:, :1]))
    gy = np.abs(np.diff(g, axis=0, prepend=g[:1, :]))
    mag = gx + gy
    h, w = mag.shape
    x1, y1, x2, y2 = [int(v) for v in bb]
    bw, bh = x2 - x1, y2 - y1
    t = max(2, int(bh * thickness_frac))

    def band(y0, y1_, x0, x1_):
        y0, y1_ = max(0, y0), min(h, y1_)
        x0, x1_ = max(0, x0), min(w, x1_)
        if y1_ <= y0 or x1_ <= x0:
            return np.array([np.nan])
        return mag[y0:y1_, x0:x1_].ravel()

    on = np.concatenate([
        band(y2 - t, y2 + t, x1, x2),                      # jaw line
        band(y1 - t, y1 + t, x1, x2),                      # hairline
    ])
    near = np.concatenate([
        band(y2 + 3 * t, y2 + 6 * t, x1, x2),              # below jaw
        band(y1 + 3 * t, y1 + 6 * t, x1, x2),              # inside forehead
    ])
    on, near = on[~np.isnan(on)], near[~np.isnan(near)]
    if on.size == 0 or near.size == 0:
        return float("nan")
    return float(on.mean() - near.mean())


# ------------------------------------------------------------------ measure
def measure(ref_path, out_path, bb_out=None, bb_ref=None):
    out = Image.open(out_path)
    ref = Image.open(ref_path)
    if bb_out is None:
        bb_out = detect_face(out_path)
        if bb_out is None:
            return {"error": "no face detected in output"}
    if bb_ref is None:
        bb_ref = detect_face(ref_path)
    if bb_ref is None:
        sx, sy = ref.width / out.width, ref.height / out.height
        bb_ref = [bb_out[0] * sx, bb_out[1] * sy, bb_out[2] * sx, bb_out[3] * sy]

    ro = _regions(out.width, out.height, bb_out)
    rr = _regions(ref.width, ref.height, bb_ref)

    cheek_out = _hf_energy(out, ro["cheek"])
    cheek_ref = _hf_energy(ref, rr["cheek"])
    body_out = _hf_energy(out, ro["body"])

    a = _arr(out.crop(ro["cheek"])).reshape(-1, 3).mean(axis=0)
    b = _arr(out.crop(ro["neck"])).reshape(-1, 3).mean(axis=0)
    lab_a, lab_b = _lab(a[None, None, :])[0, 0], _lab(b[None, None, :])[0, 0]
    dE = float(np.sqrt(((lab_a - lab_b) ** 2).sum()))

    face = np.asarray(out.crop(ro["face"]).convert("L"), dtype=np.float32)
    lap = (face[:-2, 1:-1] + face[2:, 1:-1] + face[1:-1, :-2] + face[1:-1, 2:]
           - 4 * face[1:-1, 1:-1]) if face.size > 16 else np.array([0.0])

    return {
        "skin_hf_energy": round(cheek_out, 4),
        "skin_hf_ref": round(cheek_ref, 4),
        "skin_hf_ratio": round(cheek_out / cheek_ref, 4) if cheek_ref else float("nan"),
        "grain_ratio": round(cheek_out / body_out, 4) if body_out else float("nan"),
        "seam_gradient": round(_boundary_ring(out, bb_out), 4),
        "face_neck_dE": round(dE, 3),
        "laplacian_var": round(float(lap.var()), 2),
    }


VERDICTS = {
    "skin_hf_ratio": (0.70, 1.40, "plastic/over-smoothed", "over-detailed / crunchy"),
    "grain_ratio": (0.65, 1.50, "face smoother than host photo (insert reads fake)",
                    "face noisier than host photo"),
    "seam_gradient": (-999.0, 1.20, "", "visible boundary edge"),
    "face_neck_dE": (-999.0, 6.0, "", "face/neck colour mismatch"),
}


def judge(m):
    flags = []
    for k, (lo, hi, low_msg, high_msg) in VERDICTS.items():
        v = m.get(k)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            flags.append(f"{k}: unmeasurable")
            continue
        if v < lo and low_msg:
            flags.append(f"{k}={v} LOW → {low_msg}")
        elif v > hi and high_msg:
            flags.append(f"{k}={v} HIGH → {high_msg}")
    return flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref")
    ap.add_argument("--out")
    ap.add_argument("--bbox", nargs=4, type=float,
                    help="omit to auto-detect locally (YuNet)")
    ap.add_argument("--score-json")
    ap.add_argument("--pairs", nargs="*", default=[])
    ap.add_argument("--json")
    a = ap.parse_args()

    results = {}
    if a.score_json:
        score = json.load(open(a.score_json))
        bb = {r["file"]: r.get("bbox") for r in score.get("results", [])}
        for pair in a.pairs:
            ref, out = pair.split("=", 1)
            b = bb.get(os.path.basename(out))   # None -> local detector
            m = measure(ref, out, b, bb.get(os.path.basename(ref)))
            m["flags"] = judge(m)
            results[out] = m
    else:
        m = measure(a.ref, a.out, a.bbox)
        m["flags"] = judge(m)
        results[a.out] = m

    print(json.dumps(results, indent=1))
    if a.json:
        json.dump(results, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
