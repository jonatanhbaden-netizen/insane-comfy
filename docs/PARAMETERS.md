# Parameter Reference — every dial, recommended ranges

The Note nodes inside each workflow cover day-to-day use; this file is the
deeper reference for tuning.

---

## Workflow 1 — insane_motion_control.json

### Sampling (the two KSamplerAdvanced nodes)

Wan 2.2 A14B is a two-expert MoE. The HIGH-noise expert owns motion and
composition, the LOW-noise expert owns texture and detail. The split point is
the single most quality-relevant setting after step count.

| Setting | Max quality (default) | Lightning preset | Notes |
|---|---|---|---|
| steps (both nodes) | 20 | 4 | 24–30 buys marginal gains at 720p |
| cfg (both) | 3.5 | 1.0 | 3.0–4.5 usable; >5 = fried colors |
| sampler / scheduler | euler / simple | euler / simple | dpmpp_2m also fine at 20 steps |
| HIGH: start / end | 0 / 10 | 0 / 2 | end = steps/2 always |
| LOW: start / end | 10 / 10000 | 2 / 10000 | start = HIGH end |
| ModelSamplingSD3 shift | 8.0 | 5.0 | 7–9 full / 5 lightning; lower shift = more motion freedom, higher = more prompt discipline |
| Lightning LoRA strength | (bypassed) | 1.0 | up to 1.5 on HIGH if motion goes limp |

The seed lives on the HIGH sampler (`add_noise: enable`); the LOW sampler
continues its leftover noise (`add_noise: disable`, seed irrelevant).

### Resolution / length ladder

| Use | Setting |
|---|---|
| Drafts | 832×480 × 81 frames |
| Finals horizontal | 1280×720 × 81 |
| Finals vertical (Reels) | 720×1280 × 81 — change BOTH ImageScale nodes AND the Fun-Control node |
| Longer shots | keep 81 frames; chain segments (last frame → next reference) rather than raising length; >81 costs VRAM and temporal stability |

81 frames @ 16 fps = 5.06 s → RIFE ×2 → 32 fps. For 24/48 fps deliverables set
RIFE multiplier 3 and VideoCombine frame_rate 48.

### DWPose

- `resolution 1024` default; drop to 512 if the skeleton flickers between frames.
- hands/body/face detection all enabled — disable face if the pose source face
  is noisy and you see face jitter transferring.

### Export

VHS VideoCombine: h264 mp4 @ crf 17 (visually lossless-ish). For master files
set crf 12–14; for direct social upload crf 19–21 is fine. `save_metadata: true`
embeds the workflow in the file — handy provenance.

---

## Workflow 2 — insane_image_to_image.json

### The master dial: KSampler denoise

| Denoise | Effect |
|---|---|
| 0.20–0.35 | relight / retexture; structure ~untouched |
| 0.40–0.55 | balanced re-render (default 0.50) |
| 0.60–0.75 | heavy reimagining; ControlNets carry the layout |
| >0.80 | effectively txt2img with a color hint — raise CN strengths |

### Guidance & steps

- FluxGuidance 3.5 default. 2.5–3.0 softer/photographic; 4.0–4.5 stricter,
  more contrast. KSampler **cfg stays 1.0 always** (Flux uses guidance, not CFG;
  cfg >1 doubles runtime and usually degrades).
- 28 steps euler/beta. 20 for drafts, 32–40 for gnarly detail scenes.

### ControlNet stages (Union Pro 2.0)

| Stage | strength | end_percent | When to change |
|---|---|---|---|
| DEPTH | 0.60 | 0.60 | 0.70/0.80 for structure-only restyles |
| CANNY | 0.45 | 0.50 | 0.60/0.70 for line-faithful work; drop to 0.35 when pose stage is on |
| POSE (bypassed) | 0.65 | 0.70 | enable for people shots that must hold pose |

Rules of thumb: total "control pressure" (sum of strengths) beyond ~1.6 starts
to crunch Flux's detail; release (end_percent) at 0.5–0.7 so the last steps run
free. Soft-edge instead of canny: swap the Canny node for an AnyLine/soft-edge
preprocessor from controlnet_aux — same Apply stage, no other change.

### Identity (PuLID + LoRA)

- PuLID weight: 0.70–0.80 subtle · **0.85 default** · 0.95–1.05 maximum lock.
- start_at 0.1–0.2 if the face locks in before composition settles.
- Character LoRA 0.7–0.9 + PuLID 0.6–0.8 is the strongest stack — LoRA carries
  body/hair/style, PuLID nails facial geometry.
- FaceDetailer inherits the PuLID'd model, so the face pass reinforces identity.

### Detail & upscale

- FaceDetailer: denoise 0.45 (0.30 gentle · 0.55 rebuild), guide 512→1024.
- Ultimate Upscale: 2.0× @ denoise 0.22 (0.15 safest · 0.30 textured but can
  drift), 1024 tiles, seam fix None (raise to Band Pass if you ever see seams,
  denoise 0.25+ territory).
- Want 4 K+? Run 03_final back through with upscale_by 2.0 again rather than
  one 4× pass — two gentle passes beat one aggressive one.

### Redux (when enabled)

strength 0.3–0.5 subtle grade/mood transfer · 0.6–0.8 strong look transfer
(begins overriding the text prompt). `strength_type: multiply`.

---

## VRAM management

- ComfyUI keeps the last-used models resident. Switching between the two
  workflows on one pod: Manager → **Free model and node cache** first, or expect
  a slow first queue while it swaps ~40 GB.
- `--lowvram` (via `COMFY_ARGS`) trades ~15–25% speed for headroom.
- Sage attention (auto-enabled) saves both VRAM and time on A100/H100 — if you
  suspect it of artifacts on some future node pack, launch with
  `COMFY_ARGS="--preview-method auto"` to disable it and compare.
