# AIOFM i2i v4 — the working image-to-image (operator manual)

Workflow: `workflows/aiofm_i2i_v4.json` · rebuilt from the manager's AIBT2I by
`scripts/build_i2i_v4.py` (transform of `~/Downloads/AIBT2I.json`, validated
against live `/object_info`). Supersedes v3 and all earlier i2i graphs.

## What it does

Reference post in → same shot out — pose, outfit, exposed-skin level,
background, framing, lighting, facial expression — with **your character** in
it, at ~2160×2776.

## The chain (one job per stage — do not give a stage two jobs)

| Stage | Engine | Job | Key dials |
|---|---|---|---|
| STAGE 0 | Qwen-Edit-2511 + Lightning (Plus encoder — the old encoder silently ignores the reference) | the swap; exactness of everything that isn't her | denoise 1.0 fixed |
| TEXTURE | Clown + perlin + DetailBoost 1.2 on the LoRA model | rewrite micro-texture over Qwen's plastic skin | denoise **0.18** (0.22 if still clean; 0.25 hard cap — above that clothing drift returns) |
| FACE detailer | Impact FaceDetailer, LoRA model, guide 