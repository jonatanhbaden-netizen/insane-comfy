# Talking-head pipeline — LTX-2.3 audio-conditioned (9:16)

Workflow: `workflows/aiofm_talking_ltx23.json`

Generates a vertical clip of the character **speaking to camera**, with lipsync
driven by a supplied audio file — not copied from a driving video. Motion, gesture
and expression come from the text prompt.

## Why this replaces the Wan Animate route

| | Wan 2.2 Animate (`Jack-b1`) | LTX-2.3 (this) |
|---|---|---|
| Lipsync source | face crops copied from a driving video | **audio latent** — phoneme-level |
| Needs someone else's footage | yes | **no** |
| Body motion | pose skeleton from driving video | **text prompt** |
| Max clip | 81-frame chunks, seams | 20 s single shot |
| Vertical | crop/retarget | **native** |
| Character LoRA | none in the graph | slot wired in |

## Model manifest (~53 GB, all fetched by `scripts/download_models.sh`)

| File | Folder | Size |
|---|---|---|
| `ltx-2.3-22b-dev-fp8.safetensors` | `checkpoints/` | 29.15 GB |
| `gemma_3_12B_it_fp8_scaled.safetensors` | `text_encoders/` | 13.21 GB |
| `ltx-2.3-22b-distilled-lora-384.safetensors` | `loras/` | 7.61 GB |
| `ltx-2.3-22b-ic-lora-ingredients-0.9.safetensors` | `loras/` | 1.31 GB |
| `gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors` | `loras/` | 0.63 GB |
| `ltx-2.3-spatial-upscaler-x2-1.1.safetensors` | `latent_upscale_models/` | 1.00 GB |
| `ltx-2.3-temporal-upscaler-x2-1.0.safetensors` | `latent_upscale_models/` | 0.26 GB |
| `1xSkinContrast-High-SuperUltraCompact.pth` | `upscale_models/` | 0.18 MB |

The checkpoint carries **both** the video VAE and the audio VAE — there is no
separate audio VAE file. `LTXVAudioVAELoader` points at the same `.safetensors`.

Every node is `comfy-core`. The only custom node used is `FilmGrain`
(`ComfyUI-post-processing-nodes`, added to the Dockerfile). ComfyUI must be
recent enough to have the LTX-2.3 nodes — the image builds from `master`.

## Architecture

```
LoadImage (portrait)  ─┐
LoadAudio (her voice) ─┴─► [ AIOFM Talking Head subgraph ] ─► SaveVideo

  stage 1  base @ 544x960
    EmptyLTXVLatentVideo ─► LTXVImgToVideoInplace(0.7) ─┐
    LTXVAudioVAEEncode ─► SetLatentNoiseMask(0) ────────┴─► LTXVConcatAVLatent
      └─► SamplerCustomAdvanced  euler_ancestral_cfg_pp, 8 sigmas, cfg 1.0

  stage 2  refine @ 1088x1920
    LTXVSeparateAVLatent ─► LTXVLatentUpsampler(x2) ─► LTXVImgToVideoInplace(1.0)
      └─► SamplerCustomAdvanced  euler_cfg_pp, sigmas 0.85/0.725/0.4219/0, cfg 1.0

  out
    VAEDecodeTiled ─► ImageUpscaleWithModel(skin) ─► FilmGrain(0.045) ─► CreateVideo(24fps)
    LTXVAudioVAEDecode ───────────────────────────────────────────────► CreateVideo.audio
```

Frames = `fps x duration + 1`. Default 24 x 5 + 1 = **121**.

Resolution must stay on multiples of 32 **at both stages** — the base runs at
half the final size. `1088x1920` → base `544x960`; both divide cleanly by 32.
`1080` does **not** (33.75), which is why the target is 1088 and you crop to
1080x1920 on export if a platform demands it.

## Dials that matter

| Node | Default | Notes |
|---|---|---|
| Width / Height | 1088 / 1920 | keep /32 clean at half-size too |
| Duration | 5.0 s | raise to 9–15 s once VRAM behaviour is known |
| `LTXVImgToVideoInplace` stage 1 | **0.7** | identity vs motion freedom. ↑ = locks to the reference, stiffer. ↓ = more motion, more drift |
| distilled LoRA | **0.5** | do not run at 1.0 |
| CFG (both guiders) | **1.0** | distilled model. At 1.0 the negative prompt is inert by design |
| `FilmGrain` intensity | 0.045 | 0.06 was tuned for 480p; too coarse at 1080p |
| Character LoRA | bypassed | 0.80–0.90 once trained |
| IC-LoRA Ingredients | bypassed, 1.4 | see caveat below |

## Prompt template

The prompt goes through `TextGenerateLTX2Prompt` (Gemma 3 12B), which also sees
the reference image, so write intent rather than tag soup. Structure:

```
<one paragraph of what happens over time — actions in order>

scene:      <location, light, background>
character:  <appearance, wardrobe, hair, jewellery>
action:     <gestures, laughter, head movement>
camera:     <handheld phone, framing, sway, depth of field>
audio:      <her voice speaking clearly, room tone>
```

Expression and gesture control that works:
- `her eyebrows lift slightly on the stressed words`
- `she breaks into a short genuine laugh partway through`
- `blinks naturally`, `tilting her head a little to one side`
- `one hand comes up briefly to gesture near her chest, then settles`
- `her shoulders shift subtly as she breathes`

For the phone look, prompt the **camera**, not the grade:
`handheld front-facing phone camera held at arm's length, slight natural sway`.
Avoid `cinematic`, `film still`, `shallow depth of field` at strength — they pull
toward the polished look you are trying to avoid.

## IC-LoRA Ingredients caveat

Trained at **768x448 landscape, 121 frames, 24 fps**. At 1088x1920 it is out of
distribution. If you enable it you must also:
1. feed a **reference sheet** (single composite image, black background, no text —
   one clean panel per element: face close-up, full turnaround, wardrobe, location), and
2. switch the prompt to `Reference sheet: ... / Generated video: ...`

A trained character LoRA is the better identity lock. Treat IC-LoRA as the stopgap.

## Character LoRA (LTX-2.3)

The Wan pair `F1scher Wan Lora_*_{high,low}_noise.safetensors` (306 MB each) is a
Wan 2.2 A14B MoE adapter and **cannot** be loaded here. Even LTX 2.0 LoRAs do not
map onto 2.3. Retrain with `musubi-tuner` (helper:
`BitPoet/ltx2.3-musubi-chara-training-gen-helper`) or ai-toolkit, target
`LTX-2.3-22b`, then set slot `#400` to the result at 0.80–0.90 and un-bypass.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Mouth barely moves / no lipsync | `SetLatentNoiseMask` reading the audio latent as fully clean, so the model treats audio as contributing nothing | check `SolidMask` is `0` and sized to Width/Height; confirm audio reached `LTXVAudioVAEEncode` (not silent, not trimmed to 0) |
| Lipsync drifts late in the clip | audio longer than `duration` | `TrimAudioDuration` must match `Duration`; frames = fps x duration + 1 |
| Identity drifts over the clip | no character LoRA; reference too weak | raise stage-1 `LTXVImgToVideoInplace` toward 0.8; train the LoRA |
| Stiff, posed, dead performance | stage-1 strength too high | drop toward 0.6 |
| Plastic skin | grain/skin pass bypassed, or over-denoised | confirm the skin + grain chain runs; do **not** stack extra distill LoRAs |
| Prompt ignored | remember CFG is 1.0 by design — the negative is inert | put the intent in the **positive** prompt; do not raise CFG on a distilled model |
| OOM at stage 2 | 1088x1920 x 217 frames | drop Duration to 5 s, or run base-only to judge, then re-enable refine |
