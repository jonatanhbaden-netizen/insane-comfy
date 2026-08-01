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

The ASR stage (`granite-speech-4.1-2b`, ~2 GB) is **not** in the manifest —
TTS-Audio-Suite auto-downloads it from HuggingFace on first use, so the first run
after a fresh boot takes a couple of minutes longer.

Every node is `comfy-core`. The only custom node used is `FilmGrain`
(`ComfyUI-post-processing-nodes`, added to the Dockerfile). ComfyUI must be
recent enough to have the LTX-2.3 nodes — the image builds from `master`.

## Prompt pipeline (rebuilt 2026-08-01)

Lipsync is **structural**, not something you type. Motion is derived from what she
actually says.

```
TrimAudioDuration ─┬─► LTXVAudioVAEEncode ────────────► lipsync latent
                   └─► #450 Granite ASR ─► #451 transcript
                                              │
  #452 director instruction (fixed) ──────────┤
  #319 LOOK block (the only box you edit) ────┴─► #453/#454 concat
                                                      │
                                                      ▼
                                            #342 TextGenerateLTX2Prompt
                                              sampling_mode = off   ← deterministic
                                              max_length    = 512
                                                      │
  #455 🔒 LOCKED lipsync clause ──────────────────────┤
                                                      ▼
                                     #456 concat ─► #306 CLIPTextEncode
```

The locked clause is concatenated **after** Gemma, so Gemma cannot rewrite it away.
That is what makes lipsync unconditional. Because ASR sits **downstream of the
trim**, the transcript covers exactly the audio segment being rendered.

Two `PreviewAny` nodes expose the intermediate state: `#457` the transcript,
`#458` the final prompt that reaches the encoder. Check these first when output
looks wrong.

**Motion signature (added 2026-08-01).** The director instruction (`#452`) carries
a "HER PERFORMANCE STYLE" block distilled from the six reference clips in
`motion-refs/` (another AI character — movement vocabulary only, no appearance
words, so nothing of her identity can leak). It constrains Gemma's choreography:
near-constant head tilts/rolls, face-led expression (laughs, pouts, eye-widening),
hands as brief accents only, shoulder shimmy, lean-in to confide, heavy continuous chest bounce (locked block + bounce-driving choreography). Gestures still land where the
transcript's meaning puts them — the signature only decides *how* they look.
To retune the style, re-derive from new refs and replace that block; do not edit
the sentences ad hoc or the style drifts from the corpus. The LOOK camera line is
propped-static to match the refs (revert to handheld+sway if a clip needs it).

**Why this exists.** Gemma previously ran at `temperature 0.7`, so every run
produced a different prompt — and with no knowledge of the audio it *invented* the
speech. Measured on `emma_voice.wav`, which says *"okay so i have to tell you what
happened this morning…"*, Gemma generated a **gym instructor** saying *"Remember to
engage your core throughout the entire exercise,"* then choreographed a hand
gesture onto the invented word *"engage."* The motion was never random; it was
choreographed to a script that did not exist.

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
| `LTXVImgToVideoInplace` stage 1 | **1.0** | motion is audio-driven here, so full anchor injection costs little. Drop to 0.85–0.9 only if performance goes static |
| Refine sigmas (`#289`) | **0.60, 0.55, 0.48, 0.40, 0.30, 0.15, 0** | identity-critical. At the old 0.85 start, stage 2 regenerated ~85% of the face from prior at the res where iris color is decided — that erased the heterochromia. densified 2026-08-01 after a fuzzy/flat render; add or remove steps below 0.60 to trade detail vs speed, never go back to 0.85 |
| Refine reference (`#296.image`) | **clean #297** | stage 2 gets the native 1088×1920 image. The preprocessed (yuv420p CRF-18) copy killed iris chroma; it now feeds stage 1 only |
| `img_compression` (stage 1) | 18 | keep. 0 = out-of-distribution conditioning (frozen video); >18 loses detail |
| distilled LoRA | **0.5** | do not run at 1.0 |
| CFG (both guiders) | **1.0** | distilled model. At 1.0 the negative prompt is inert by design |
| Finishing chain | Sharpen(1, 0.5) → ColorCorrect(+10c/+10s) → FilmGrain 0.03 | all cheap pixel ops, seconds not minutes. The skin/pore GAN (`#403`) is parked BYPASSED — slow and can halo; un-bypass only for hero clips |
| Character LoRA | **on, `_1250` @ 0.9** | test band 0.8–1.2; total stack with distilled must stay < 2.0. Step down 0.1 at a time if motion/lipsync stiffens; more checkpoints (2000+) worth training |
| IC-LoRA Ingredients | bypassed, 1.4 | see caveat below |

Identity text (her heterochromia) lives in the **🔒 LOCKED block (#455)** — it must
sit *post-Gemma*, because Gemma's performance paragraph never carries appearance.
Phrased as "one eye warm brown, the other pale blue-gray" (repeated verbatim, no
weighting — Gemma-3 encoder, not CLIP; left/right phrasing tends to swap sides).
Text is a supporting layer only: the refine-sigma + clean-reference + LoRA changes
are what actually hold the eyes.

## Writing the LOOK block (#319 — the only box you edit)

Performance and lipsync are no longer yours to write — the director instruction
and locked clause own those. The LOOK block describes only what the *frame* looks
like:

```
scene:      <location, light, background>
character:  <appearance, wardrobe, hair, jewellery>
camera:     <handheld phone, framing, sway>
audio:      <room tone character>
```

Do **not** put gesture or expression lines here — they would fight the
transcript-derived performance. If a specific beat matters (e.g. a laugh), say it
in one short line and keep it consistent with what the audio actually contains.

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
| Eye color / fine identity drifts after frame 1 | refine start sigma too high, degraded stage-2 reference, or char LoRA off | verified failure mode 2026-08-01: heterochromia held at t=0, gone by t=1.2s. Keep `#289` at 0.60 start, `#296.image` on the clean #297 feed, LoRA ≥0.8 |
| She's stiff / motion died after identity fixes | LoRA too strong or stage-1 at 1.0 too tight | drop LoRA 0.1 at a time toward 0.6 first, then stage-1 to 0.85 |
| Gestures don't match the speech | transcript wrong or empty | read `#457` (transcript preview). Wrong language → set `#451 language`; silence/music → Granite returns junk, fix the audio |
| Prompt looks wrong / off-style | Gemma output drifted | read `#458` (final prompt preview) — the locked clause must lead, then a ≤90-word performance paragraph, no quoted dialogue |
| Same seed, different motion between runs | someone set `#342 sampling_mode` back to `on` | keep it `off`; determinism was verified 2026-08-01 |
| Mouth barely moves / no lipsync | `SetLatentNoiseMask` reading the audio latent as fully clean, so the model treats audio as contributing nothing | check `SolidMask` is `0` and sized to Width/Height; confirm audio reached `LTXVAudioVAEEncode` (not silent, not trimmed to 0) |
| Lipsync drifts late in the clip | audio longer than `duration` | `TrimAudioDuration` must match `Duration`; frames = fps x duration + 1 |
| Identity drifts over the clip | no character LoRA; reference too weak | raise stage-1 `LTXVImgToVideoInplace` toward 0.8; train the LoRA |
| Stiff, posed, dead performance | stage-1 strength too high | drop toward 0.6 |
| Plastic skin | grain/skin pass bypassed, or over-denoised | confirm the skin + grain chain runs; do **not** stack extra distill LoRAs |
| Prompt ignored | remember CFG is 1.0 by design — the negative is inert | put the intent in the **positive** prompt; do not raise CFG on a distilled model |
| OOM at stage 2 | 1088x1920 x 217 frames | drop Duration to 5 s, or run base-only to judge, then re-enable refine |
