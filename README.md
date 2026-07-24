# INSANE COMFYUI SYSTEM — Wan 2.2 Motion Control + Flux Image-to-Image on RunPod

Two production ComfyUI pipelines and the full RunPod environment to run them:

1. **`workflows/insane_motion_control.json`** — pose/motion-driven video of your
   original character (Wan 2.2 Fun-Control, two-expert MoE, native ComfyUI nodes),
   with a muted pure image-to-video branch, Lightning speed preset, and RIFE
   interpolation to 32 fps.
2. **`workflows/insane_image_to_image.json`** — maximum-precision img2img
   (Flux.1-dev fp8) with multi-ControlNet (depth + canny + optional pose via
   ControlNet Union Pro 2.0), PuLID-Flux identity lock, optional Redux style
   transfer, FaceDetailer, and 4×-UltraSharp + 2× tiled refine.

**Scope note:** this system generates and animates *your own synthetic
character* (reference images, character LoRA, PuLID on your character's face).
It deliberately contains no third-party-footage face replacement, no voice
cloning, and no lipsync. Use motion clips you have rights to; don't point the
identity tools at real people who haven't consented.

## Why Wan 2.2 (July 2026)

Alibaba's open-weight line stops at **Wan 2.2** — 2.5/2.6 stayed API-only and
the "Wan 2.7 open weights" pages circulating are SEO squatter sites. Wan 2.2
A14B (fp8-scaled, Comfy-Org repackaged) remains the open-source ceiling for
controllable video, and everything here is drop-in swappable if newer open
weights land: replace the two UNET files, keep the graph.

## Folder structure (this repo)

```
comfyui-runpod/
├── README.md                  ← you are here (deployment guide below)
├── .env.example               ← env vars documented
├── docker/
│   ├── Dockerfile             ← ComfyUI + all custom nodes, CUDA 12.4 / torch 2.4
│   ├── start.sh               ← entrypoint: volume setup → model download → ComfyUI
│   └── extra_model_paths.yaml ← maps model folders onto /workspace
├── scripts/
│   ├── download_models.sh     ← fetches every model (~95 GB), idempotent
│   └── comfy_api_client.py    ← headless queue/poll/download helper (stdlib only)
├── workflows/
│   ├── insane_motion_control.json
│   └── insane_image_to_image.json
└── docs/
    ├── PARAMETERS.md          ← every dial, recommended ranges, quality vs speed
    └── TESTING.md             ← smoke tests + first-load verification checklist
```

## Runtime layout (on the pod)

```
/ComfyUI                       ← baked into the image (code + custom nodes)
/workspace                     ← RunPod NETWORK VOLUME (persistent)
├── models/                    ← everything download_models.sh fetches
│   ├── diffusion_models/      ← Wan 2.2 pairs + flux1-dev fp8
│   ├── text_encoders/         ← umt5-xxl, clip_l, t5-xxl
│   ├── vae/  loras/  controlnet/  clip_vision/  style_models/
│   ├── pulid/  insightface/  ultralytics/  sams/  upscale_models/
├── model_cache/               ← auto-downloaded DWPose/DepthAnything/RIFE weights
├── .cache/huggingface/        ← HF cache (EVA-CLIP for PuLID lives here)
├── input/   output/           ← symlinked into ComfyUI
└── workflows/                 ← copies of the two workflow JSONs
```

## Deployment on RunPod (A100 80GB)

### 1. Build & push the image

```bash
cd comfyui-runpod
docker build -t YOURUSER/insane-comfy:1.0 -f docker/Dockerfile .
docker push YOURUSER/insane-comfy:1.0
```

(Apple Silicon: add `--platform linux/amd64`.)

### 2. Create the network volume

RunPod → Storage → New Network Volume, **200 GB**, in a region with A100 80GB
availability (models alone are ~95 GB; the rest is outputs + caches headroom).
The volume is the expensive-to-rebuild asset — pods are disposable, the volume
is not. One volume can back many pods in the same region (scale-out workers).

### 3. Create the pod template

- **Image:** `YOURUSER/insane-comfy:1.0`
- **Volume:** attach the network volume at `/workspace`
- **Expose HTTP ports:** `8188` (ComfyUI), `8888` (Jupyter, optional)
- **Container disk:** 30 GB
- **Env vars** (see `.env.example`): first boot set `DOWNLOAD_MODELS=true`
  (plus `HF_TOKEN` + `WITH_REDUX=true` if you want Redux). After the volume is
  populated, set `DOWNLOAD_MODELS=false` for ~30-second boots.

### Alternative: no Docker build (start today)

Don't want to build/push an image? Deploy the **official "RunPod Pytorch 2.4.0"
template** (same base image this Dockerfile uses), attach the network volume at
`/workspace`, expose HTTP port **8188** in addition to 8888, then upload
`scripts/pod_setup.sh` + `scripts/download_models.sh` to `/workspace` via the
pod's Jupyter and run:

```bash
bash /workspace/pod_setup.sh      # one-time: ComfyUI + nodes + models → volume
bash /workspace/run_comfy.sh      # start ComfyUI on :8188
```

ComfyUI and all models live on the volume, so they survive pod swaps; on a
fresh pod just re-run `pod_setup.sh` (~3–5 min, everything heavy is skipped).
Load the workflows by dragging the two JSON files into the ComfyUI browser tab.

### 4. First boot

Deploy an **A100 80GB SXM** pod on the template. First boot downloads ~95 GB
(20–60 min depending on region bandwidth — watch the container logs). Then open
the pod's `:8188` proxy URL → ComfyUI. Both workflows are pre-loaded in the
sidebar (Workflows → Browse). First queue of each workflow auto-downloads the
small annotator weights (DWPose, DepthAnythingV2, RIFE, EVA-CLIP) — one-time,
persisted to the volume.

### 5. Run

Follow the numbered **Note nodes inside each workflow** — they document every
group, preset, and dial. Deeper reference: `docs/PARAMETERS.md`. Smoke tests
and the first-load verification checklist: `docs/TESTING.md`.

### Headless / API use

Tune a workflow in the UI, export via *Workflow → Export (API)*, then:

```bash
python3 scripts/comfy_api_client.py my_wf_api.json \
  --host https://<pod-id>-8188.proxy.runpod.net \
  --set "12.inputs.text=your prompt here" --set "28.inputs.seed=42" \
  --out ./results
```

## Model inventory (what download_models.sh fetches)

| Model | File(s) | Size | Source |
|---|---|---|---|
| Wan 2.2 Fun-Control A14B | `wan2.2_fun_control_{high,low}_noise_14B_fp8_scaled` | 2×~15 GB | Comfy-Org/Wan_2.2_ComfyUI_Repackaged |
| Wan 2.2 I2V A14B | `wan2.2_i2v_{high,low}_noise_14B_fp8_scaled` | 2×~15 GB | Comfy-Org/Wan_2.2_ComfyUI_Repackaged |
| UMT5-XXL fp8 | `umt5_xxl_fp8_e4m3fn_scaled` | ~7 GB | Comfy-Org/Wan_2.1_ComfyUI_repackaged |
| Wan VAE | `wan_2.1_vae` | ~0.3 GB | Comfy-Org |
| Lightning 4-step LoRAs | i2v v1 pair + t2v 1217 pair | ~2.6 GB | Comfy-Org + lightx2v/Wan2.2-Distill-Loras |
| Flux.1-dev fp8 | `flux1-dev-fp8-e4m3fn` | ~12 GB | Kijai/flux-fp8 |
| Flux text encoders | `clip_l`, `t5xxl_fp8_e4m3fn_scaled` | ~5.5 GB | comfyanonymous/flux_text_encoders |
| Flux VAE | `ae` | ~0.3 GB | black-forest-labs/FLUX.1-schnell (ungated) |
| ControlNet Union Pro 2.0 | renamed on download | ~6.6 GB | Shakker-Labs |
| PuLID-Flux | `pulid_flux_v0.9.1` | ~1.1 GB | guozinan/PuLID |
| antelopev2 (insightface) | 5 onnx files | ~0.4 GB | DIAMONIK7777/antelopev2 |
| sigCLIP vision (Redux) | `sigclip_vision_patch14_384` | ~0.9 GB | Comfy-Org |
| Redux style model (opt) | `flux1-redux-dev` | ~0.1 GB | BFL (gated — HF_TOKEN) |
| face YOLO + SAM + upscaler | `face_yolov8m`, `sam_vit_b`, `4x-UltraSharp` | ~0.5 GB | Bingsu / Meta / Kim2091 |

**Total ≈ 95 GB.** Auto-downloaded at first use (persisted): DWPose, DepthAnythingV2, RIFE 4.9, EVA-CLIP.

## VRAM & performance (approximate)

| Task | A100 80GB | Notes |
|---|---|---|
| Motion control 1280×720×81f, 20 steps | ~8–12 min, ~40–55 GB peak | fp8 experts load sequentially |
| Same, Lightning preset (4 steps) | ~60–120 s | drafts/iteration |
| Motion control 832×480 draft | ~3× faster than 720p | |
| img2img full pipeline @1.5 MP + 2× refine | ~2–3 min, ~30–40 GB peak | base ≈ 25–35 s of that |

**H100 80GB:** same workflows, roughly 1.6–2× faster (better fp8 throughput);
sage attention auto-enables on both. **Smaller GPUs (≤48 GB):** works with
`COMFY_ARGS="--use-sage-attention --lowvram"` and/or 832×480 video, but A100/H100
is the intended tier. Never run both workflows concurrently on one 80 GB card.

## Quality-vs-speed cheat sheet

- **Video finals:** 20 steps, cfg 3.5, shift 8.0, LoRAs bypassed, 720p.
- **Video drafts:** Lightning LoRAs on, 4 steps, cfg 1.0, shift 5.0, 480p.
- **Image finals:** 28 steps, guidance 3.5, denoise 0.4–0.55, full detail+upscale chain.
- **Image drafts:** 20 steps, mute FaceDetailer + Ultimate Upscale groups (Ctrl+M), judge the 01_base save.
- The two systems compound: build the character still in img2img → feed it to
  motion control as the reference. Best-in-class identity consistency comes from
  a trained character LoRA in both graphs; this repo gives the LoRA slots.

## Troubleshooting

- **Red nodes on load** → Manager → Install Missing Custom Nodes → Restart. The
  image pre-installs everything, so this normally only happens if a node pack
  renamed something after an update — see `docs/TESTING.md` checklist.
- **First queue hangs a while** → annotator weights downloading (one-time, watch logs).
- **PuLID `No face detected`** → face reference too small/profile/dark; use a
  clean frontal crop, face ≥ 512 px.
- **OOM at 720p video** → close the img2img workflow's loaded models (Manager →
  Free model and node cache), or add `--lowvram`, or drop to 832×480.
- **Redux download 403** → gated: accept the FLUX.1-Redux-dev license on HF with
  the same account as `HF_TOKEN`.
- **Downloads failed on boot** → re-run `bash /download_models.sh` in the pod
  terminal; it resumes/skips existing files.
