# AIOFM Swap v2 — character swap + freeform editing

Workflow: `workflows/aiofm_swap_v2.json` · replaces the failed `aiofm_i2i_qwen_zimage` approach.

**What it does:** drop in any reference image, drop in one photo of your girl, and get the
reference image back with *her* in it — same pose, same clothing and fabric detail, same
lighting and background. A single instruction box gives Nano-Banana-style freeform editing
("change the lighting to sunset", "make her look over her shoulder") with identity kept.

## Why v2 is architecturally different (post-mortem of v1)

v1 pushed a finished composition through a text-to-image refinement pipeline whose whole
job is to re-render the frame — identity and preservation fought over one denoise value and
both lost. **v2 separates them with masks:**

| Phase | Job | Why it can't break the others |
|---|---|---|
| 1 — Qwen-Edit-2511 | The swap + all freeform edits | It's an *editing* model — preserving the rest of the frame is its native objective |
| 2 — Flux + PuLID FaceDetailer | Identity, precisely | High denoise (0.42) but **only inside the detected face mask** — background is untouched by definition |
| 3 — UltimateSDUpscale 2× | Texture + resolution | Denoise 0.16 is physically too low to change composition |

Identity gets aggression where it needs it; preservation gets near-zero denoise everywhere
else; they never compete.

**Deliberate omission — no ControlNet stack in the main path.** Depth/pose/edge locks would
duplicate what Qwen-Edit already does natively, and they directly fight freeform edits (a
pose ControlNet vetoes "change the pose slightly"). ControlNet Union Pro 2.0 is on the
volume if a locked-structure variant is ever wanted; see Extensions below.

## The three inputs

| Slot | What to put in it |
|---|---|
| **REF 1 – SCENE** | The image to replicate (any source) |
| **REF 2 – HER FACE** | One clean, frontal, well-lit photo of your girl. **This is the identity** — it feeds both the Qwen swap and the PuLID lock. Face ≥512px, no sunglasses, no heavy filter |
| **REF 3 – OPTIONAL** | Bypassed by default. Un-bypass (Ctrl+B) for a second identity angle, or a clothing/background reference — then mention "image 3" in the instruction |
| **EDIT INSTRUCTION** | Ships with the swap instruction. Append freeform edits as extra sentences |

Freeform edit examples (append to the default text, one per line):
- `Change the lighting to warm golden-hour sunlight from the left.`
- `Recolor the lingerie to deep red, keep the same lace pattern.`
- `Move the camera slightly lower and closer.`
- `Remove the necklace.` / `Add small gold hoop earrings.`

## Node-by-node with settings

### Phase 1 — swap (Qwen-Image-Edit-2511)
| Node | Setting | Range / notes |
|---|---|---|
| UNETLoader | `qwen_image_edit_2511_fp8mixed` | |
| CLIPLoader | `qwen_2.5_vl_7b_fp8_scaled`, type `qwen_image` | |
| VAELoader | `qwen_image_vae` | |
| LoraLoaderModelOnly | Lightning 4-step @ **1.0** | don't lower — sampler is tuned for it |
| ModelSamplingAuraFlow | shift **3.1** | leave |
| CFGNorm | 1.0 | leave |
| FluxKontextImageScale | — | sizes REF 1 to Qwen's ~1MP canvas |
| KSampler | **4 steps, cfg 1.0, euler/simple, denoise 1.0** | denoise 1.0 is correct here — the reference enters through the edit conditioning, not the latent |
| Preview "PHASE 1" | | **judge identity/composition HERE before anything else** |

### Phase 2 — identity lock (Flux.1-dev + PuLID, masked)
| Node | Setting | Range |
|---|---|---|
| UNETLoader | `flux1-dev-fp8-e4m3fn` | |
| DualCLIPLoader | clip_l + t5xxl fp8, type flux | |
| ApplyPulidFlux | **weight 0.9**, start 0.0, end 1.0 | 0.8–1.0. Raise → more her, stiffer; lower → softer likeness |
| FluxGuidance | 3.5 | 3.0–4.0 |
| FaceDetailer | guide 768 / max 1024, **20 steps, cfg 1.0, euler/beta, denoise 0.42**, feather 8, bbox `face_yolov8m` + SAM `vit_b` | denoise 0.35 (subtle) – 0.50 (strong re-render). This is the main identity dial |

### Phase 3 — finish
| Node | Setting | Range |
|---|---|---|
| UltimateSDUpscale | ×2, 4x-UltraSharp, **12 steps, cfg 1.0, euler/beta, denoise 0.16**, tiles 1024², Half-Tile seam fix | denoise 0.12–0.20 **hard cap** — above that tiles start inventing |
| FilmGrain | 0.04 / scale 12 | 0.03–0.07 |
| SaveImage | `AIOFM_swap` | |
| *(bypassed)* skin-contrast pass | `1xSkinContrast` | can yellow teeth — A/B before trusting |
| *(bypassed)* SeedVR2 ×2 → 4K | 7B sharp fp8, defaults from the developer's pipeline | enable all three nodes together; weights auto-download on first use |

## Safe starting preset

Everything ships at the preset: PuLID 0.9 · FaceDetailer 0.42 · USDU 0.16 · grain 0.04.
Change **one dial per run**. Decision tree:

1. Phase 1 preview wrong (not her / composition broken) → fix REF 2 photo or instruction. Do not touch later phases.
2. Final face not her enough → FaceDetailer denoise ↑ 0.50, then PuLID ↑ 1.0.
3. Face looks pasted / lighting mismatch → FaceDetailer denoise ↓ 0.35, feather ↑ 16.
4. Fabric/lace lost detail → USDU denoise ↓ 0.12.
5. Skin too clean → grain ↑ 0.06; consider the Klein pass (below) before the skin-contrast node.

## Install / models

Every node pack and model is **already in the image and on the volume/pod** — nothing to
install. For a fresh environment: packs = comfy-core + Impact Pack/Subpack +
PuLID-Flux-Enhanced + UltimateSDUpscale + post-processing-nodes (+ SeedVR2 optional);
models = Qwen-Edit-2511 set (`Comfy-Org/Qwen-Image-Edit_ComfyUI` + Lightning LoRA),
`Kijai/flux-fp8` flux1-dev, `guozinan/PuLID` pulid_flux_v0.9.1, antelopev2, clip_l +
t5xxl fp8, `ae.safetensors`, `Kim2091/UltraSharp`. All already scripted in
`scripts/download_models.sh`.

## How to use (non-expert)

1. Load `aiofm_swap_v2` from the sidebar
2. REF 1 → the picture you want to copy
3. REF 2 → one good photo of your girl's face
4. (Optional) add edit sentences to the instruction box
5. Run. Look at **PHASE 1 preview first** — that's the swap. The final save is the
   polished version of exactly that image
6. Not right? Follow the decision tree above. One dial per run.

## SDXL / Pony fallback

If your character exists only as an SDXL/Pony LoRA: keep Phases 1 and 3, and in Phase 2
replace the Flux chain with a CheckpointLoader (your SDXL model) + LoraLoader (your
character LoRA) + IPAdapter FaceID v2 into the same FaceDetailer (cfg ~5, dpmpp_2m/karras,
denoise 0.45). The mask architecture is model-agnostic; only the sampler settings change.

## Self-critique — three weaknesses vs. a perfect Nano-Banana-class editor, and what was done

1. **Body identity beyond the face.** PuLID locks the face; body type comes only from
   Qwen's read of REF 2. *Mitigation built in:* REF 3 slot for a second/body reference +
   instruction language ("body should match the woman in image 2"). *Full fix later:* a
   Flux character LoRA for her (dataset exists) dropped into Phase 2/3 — slots already wired
   for it architecturally.
2. **Micro-pattern fidelity through the swap.** Qwen re-synthesises the person's clothing;
   exact lace repeats can drift ~5%. *Mitigation built in:* instruction explicitly pins
   "clothing, fabric details, accessories"; USDU capped at 0.16 so Phase 3 can't add drift.
   *Full fix later:* masked composite of the original garment region back over the output
   when the pose is unchanged.
3. **Working resolution.** Qwen composes at ~1MP; fine detail is reconstructed, not carried,
   until Phase 3 upscales. *Mitigation built in:* 4x-UltraSharp + tiled Flux refine to 2K,
   optional SeedVR2 to 4K. *Next A/B (already queued):* Flux.2 Klein 4B as the Phase 3
   refiner model — drop-in swap for the USDU model input once
   `flux-2-klein` is downloaded; expected to beat flux1-dev on skin texture per the
   Krea/Klein dual-pass pattern.

## Extensions (documented, not built — deliberately)

- **Locked-structure variant:** insert ControlNet Union Pro 2.0 (depth from REF 1 via
  DepthAnythingV2, weight 0.6 + soft-edge 0.4) into Phase 1's conditioning when zero
  structural drift is required and no structural edits are wanted. Both models are on the
  volume; it costs freeform editing.
- **External mask input:** advanced users can route their own mask into a
  MaskDetailerPipe (present in the environment) in place of FaceDetailer's detector.
