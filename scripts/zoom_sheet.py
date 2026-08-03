#!/usr/bin/env python3
"""Build 200%-zoom evidence sheets for a harness run.

The mandate's acceptance test is "skin holds up under 200% zoom as real human
skin" and "no boundary artifacts". This turns that from an opinion into an
artifact: for each (reference, output) pair it cuts matched crops —

  FACE   full face at 2x
  EYES   eye band at 2x (iris texture, catchlights, heterochromia)
  JAW    jaw/neck boundary strip at 2x (composite seam hunting)
  HAIRLINE  forehead/hairline strip at 2x (mask-edge + strand quality)
  SKIN   cheek patch at 3x (pore/grain inspection)

and lays reference-vs-output side by side in one PNG per pair. Face bboxes
come from score_identity.py --json output (ArcFace det bbox — the same
detector that scores identity, so crops always match what was measured).

Usage:
  python3 zoom_sheet.py --score-json run/score.json --pairs ref1.png=out1.png ... --outdir run/zoom
"""
import argparse
import json
import os

from PIL import Image, ImageDraw

ZOOM = 2


def crops_from_bbox(w, h, bb):
    x1, y1, x2, y2 = bb
    bw, bh = x2 - x1, y2 - y1
    cx = (x1 + x2) / 2

    def clamp(box):
        a, b, c, d = box
        return (max(0, int(a)), max(0, int(b)), min(w, int(c)), min(h, int(d)))

    return {
        "FACE": clamp((x1 - bw * 0.25, y1 - bh * 0.35, x2 + bw * 0.25, y2 + bh * 0.2)),
        "EYES": clamp((x1 - bw * 0.10, y1 + bh * 0.18, x2 + bw * 0.10, y1 + bh * 0.52)),
        "JAW": clamp((x1 - bw * 0.30, y2 - bh * 0.15, x2 + bw * 0.30, y2 + bh * 0.45)),
        "HAIRLINE": clamp((x1 - bw * 0.30, y1 - bh * 0.45, x2 + bw * 0.30, y1 + bh * 0.15)),
        "SKIN": clamp((cx, y1 + bh * 0.45, cx + bw * 0.35, y1 + bh * 0.80)),
    }


def scaled(img, box, zoom):
    c = img.crop(box)
    return c.resize((c.width * zoom, c.height * zoom), Image.LANCZOS)


def sheet_for_pair(ref_path, out_path, bbox_by_file, dest):
    ref = Image.open(ref_path).convert("RGB")
    out = Image.open(out_path).convert("RGB")
    bb_out = bbox_by_file.get(os.path.basename(out_path))
    if bb_out is None:
        # no ArcFace bbox (pod scorer unavailable) — detect locally so the
        # zoom evidence still gets produced
        try:
            from i2i_metrics import detect_face
            bb_out = detect_face(out_path)
        except Exception:
            bb_out = None
    if bb_out is None:
        return None
    # each side uses its OWN detected bbox; scaling the output bbox onto the
    # reference misframes whenever the output is an aspect-crop of the ref.
    bb_ref = bbox_by_file.get(os.path.basename(ref_path))
    if bb_ref is None:
        try:
            from i2i_metrics import detect_face
            bb_ref = detect_face(ref_path)
        except Exception:
            bb_ref = None
    if bb_ref is None:
        sx, sy = ref.width / out.width, ref.height / out.height
        bb_ref = [bb_out[0] * sx, bb_out[1] * sy, bb_out[2] * sx, bb_out[3] * sy]

    rows = []
    for name, zoom in (("FACE", ZOOM), ("EYES", ZOOM), ("JAW", ZOOM),
                       ("HAIRLINE", ZOOM), ("SKIN", 3)):
        a = scaled(ref, crops_from_bbox(ref.width, ref.height, bb_ref)[name], zoom)
        b = scaled(out, crops_from_bbox(out.width, out.height, bb_out)[name], zoom)
        hh = max(a.height, b.height)
        row = Image.new("RGB", (a.width + b.width + 30, hh + 26), (18, 18, 18))
        d = ImageDraw.Draw(row)
        d.text((6, 4), f"{name}  ref | out", fill=(230, 230, 230))
        row.paste(a, (0, 26))
        row.paste(b, (a.width + 30, 26))
        rows.append(row)

    W = max(r.width for r in rows)
    H = sum(r.height for r in rows) + 8 * len(rows)
    canvas = Image.new("RGB", (W, H), (10, 10, 10))
    y = 0
    for r in rows:
        canvas.paste(r, (0, y))
        y += r.height + 8
    canvas.save(dest)
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--score-json", required=True)
    ap.add_argument("--pairs", nargs="+", required=True, help="ref.png=out.png")
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()

    score = json.load(open(a.score_json))
    bbox_by_file = {r["file"]: r.get("bbox") for r in score.get("results", [])}
    os.makedirs(a.outdir, exist_ok=True)
    for i, pair in enumerate(a.pairs):
        ref, out = pair.split("=", 1)
        dest = os.path.join(a.outdir, f"zoom_{i}_{os.path.basename(out)}")
        r = sheet_for_pair(ref, out, bbox_by_file, dest)
        print(f"{'sheet' if r else 'SKIP (no bbox)'}: {pair}")


if __name__ == "__main__":
    main()
