# AIOFM i2i v3 — pixel-law face swap

Workflow: `workflows/aiofm_i2i_v3.json` · replaces both `aiofm_i2i_qwen_zimage`
(character switched — no character conditioning in the graph) and the
Phase-2/3 side of `aiofm_swap_v2` (PuLID is Flux-only and re-rendered
already-correct faces waxy).

**What it does:** drop in a reference post, get the same image back with your
girl's face. Pose, clothing, fabric, lighting, background and crop are the
**original file's pixels, byte-identical** — only the face region is ever
synthesised.

## Why this architecture

Every earlier failure — switched character, painted hair, fabric drift, waxy
skin — came from a model re-rendering pixels that were already correct. v3's
rule: **the reference is law.** One region is rebuilt, everything else is never
touched. Two consequences:

- Preservation is exact by construction, not "usually good".
- The base model never renders the body, so shot type (lingerie/explicit)
  cannot break the pipeline — the model only ever sees a face crop.

Identity is a **rank-32 Z-Image LoRA trained on her** (`f1sher_000002400`,
trigger `F1sher`), on the same architecture as `z_image_turbo_bf16`. There is
no reference-photo "hint" that can lose; the character is baked into the
weights. (LoRA architecture identified from safetensors headers:
`ss_base_model_version: zimage` — check yours with
`scripts/lora_id.py` before assuming.)

## The pipeline

| Stage | Nodes | Job |
|---|---|---|
| Detect | face_yolov8m → SegsToCombinedMask | find the face, any size |
| Crop | InpaintCropImproved, context 1.6×, out 1024² | a 90px face renders at 1024 — detail is invented big, shrunk into place |
| Identity | Z-Image Turbo + her LoRA, KSampler denoise 0.5 | source latent keeps pose/angle/expression; LoRA supplies who it is |
| Mask | APersonMaskGenerator (face only, hair OFF) + GrowMaskWithBlur 8/8 | her hairline/ears/neck stay reference pixels |
| Harmonise | ColorMatch (mkl, 0.9) → FilmGrain 0.03 | steal the scene's white balance + noise floor — kills the three classic tells |
| Composite | ImageCompositeMasked → InpaintStitchImproved | face pixels only; stitcher restores full res |

Previews A (source crop) / B (raw render) / C (harmonised) show which stage
broke it — never tune blind.

## Dials (change one per run)

| Symptom | Dial | Direction |
|---|---|---|
| Not her enough | KSampler denoise 0.5 | ↑ 0.55–0.65 (expression drifts above ~0.6) |
| LoRA style too strong (lips/jaw restyled) | LoRA strength 0.85 | ↓ 0.7 |
| Face looks pasted | GrowMaskWithBlur blur 8 | ↑ 12–16 |
| Colour slightly off | ColorMatch strength 0.9 | ↑ 1.0 / method `hm` |
| Face too clean vs photo | FilmGrain 0.03 | ↑ 0.05 |
| Eyes wrong | prompt | heterochromia is IN the default prompt — keep it |

**Known trait that needs the prompt:** her heterochromia (left brown / right
blue). At denoise 0.5 the LoRA alone does not reliably impose it — the default
prompt pins it explicitly. If you rewrite the prompt, keep those words.

## Requirements (already on pod/volume)

- `z_image_turbo_bf16.safetensors` (diffusion_models — volume)
- `qwen_3_4b.safetensors` (text_encoders; CLIPLoader type **lumina2**)
- `ae.safetensors` (vae — the Flux VAE; Z-Image ships the identical file)
- `f1sher_000002400.safetensors` (loras — volume)
- packs: Impact Pack/Subpack, CropAndStitch (Improved), KJNodes, a-person-mask-generator,
  post-processing (FilmGrain), ComfyUI-KJNodes ColorMatch — all in the image

## Testing / pass bar

`scripts/score_identity.py` (runs on the pod) embeds her 51-image training set
with ArcFace, calibrates the intra-set similarity band ("same girl, different
photo"), and passes a render only if its mean similarity lands inside that
band. Plus eyeball checklist: seam, skin texture, lighting direction,
catchlights, grain continuity.

Remote exec for all of this: `scripts/pod_exec.py` (Jupyter kernel transport —
the image has no sshd; RunPod proxy SSH will always hang at the banner).

## Other characters

Same graph, two widget changes: LoRA file + trigger word in the prompt.
- Sofia: `Sof1a-lehtonen-zti_000001100` · trigger `Sof1a`
- Emma Sunde: `Emma Sund3 Lora_000003800` · trigger `sund3` (or `Emm4` for the
  `Emm4-zit` line)
All Z-Image arch, verified from headers. Wan/LTX LoRAs (`F1scher Wan`,
`LTXfischerLora`) are video-only — they cannot load here.

## Optional prompt-edit branch

The bypassed Qwen-Edit-2511 group ("make the top red") runs **before** detect,
so edits land in the reference and the face pass still overwrites the face
after. Enable only when an edit is wanted — when off, preservation stays
byte-exact.
