# AIOFM i2i v3 — reference post in, your girl out

Workflow: `workflows/aiofm_i2i_v3.json` · bot graph: `telegram-bot/workflows_api/i2i_v3.json`

Drop in a reference post + one face photo of your girl → the same shot with
**her** in it: her face, her hair, heterochromia correct, scene/pose/outfit/
lighting preserved, delivered at full resolution.

## Architecture: two engines, each covering the other's weakness

| Stage | Engine | What it's trusted with | What it must NOT do |
|---|---|---|---|
| 1 · frame swap | Qwen-Edit-2511 (4-step Lightning) | whole-frame coherence: hair replacement, shadows, strand physics, outfit/scene preservation | exact identity (~90% likeness is its ceiling) |
| 2 · identity stamp | Z-Image Turbo + her LoRA, **masked inpaint** | exact face identity + heterochromia at 1024px | frame layout (mask keeps it in the face+hair region) |
| 3 · finish | SeedVR2 3B + grain 0.02 | delivery resolution (~1088 short side) | content changes (it's an upscaler) |

Stage 2 is **SetLatentNoiseMask inpainting, not img2img**: the face region is
rebuilt from noise so geometry comes from the LoRA, while the unmasked surround
anchors pose and lighting. ColorMatch runs at 0.35 (mkl) + FilmGrain 0.03
against the source crop before compositing.

## Hard-won constants (validated live 2026-08-01 — change at your peril)

- **LoRA strength 0.6–0.7, shipped at 0.65.** `f1sher_000002400` is overbaked:
  at 1.0 it produces pure noise, at 0.6 it produces her. If a render turns
  smeary or the skin goes bumpy, the strength crept too high.
- **Identity ref = a FACE crop** (`emma_face_ref.png`). A full-body reference
  makes Qwen import her outfit into the scene. Face-only kills the leak.
- **Heterochromia lives in the prompt** ("left eye warm brown, right eye light
  blue") — the LoRA alone drops it. Same for "golden blonde shoulder-length
  bob". Keep both if you edit the prompt.
- **The swap instruction pins clothing to image 1 explicitly** ("Keep the exact
  clothing, outfit, accessories and jewelry from image 1 — do not change
  them."). Without that sentence Qwen swaps outfits.
- ColorMatch ≤ 0.35: at 0.9 it drags recolored hair back toward the source's
  hair color statistics.

## Approaches that FAILED — do not resurrect

1. **Z-Image 4-stage refine over a composed frame** (`aiofm_i2i_qwen_zimage`):
   no character conditioning in the graph → switched characters entirely.
2. **Face-mask img2img at denoise 0.5** on someone else's photo: keeps the
   source person's bone structure, repaints only the surface → "a blend that
   looks like neither".
3. **Face+hair inpaint on the raw reference**: hair identity can't be fixed in
   a face-region mask — removed hair leaves orphan strands on the chest and
   shadow smears under the jaw (MediaPipe only masks hair near the head).
4. **Flux + PuLID identity phase** (swap v2): PuLID is Flux-only (can never use
   a Z-Image LoRA) and re-rendered already-correct faces waxy.

## Inputs

| Node | What |
|---|---|
| REF 1 — SCENE | the post to replicate (any source) |
| REF 2 — HER PHOTO | **face crop** of your girl (identity for the Qwen swap) |
| SWAP INSTRUCTION | ships correct; append extra edit sentences at the end ("make the top red") |
| IDENTITY PROMPT | trigger word + traits for the LoRA stamp — keep heterochromia + bob wording |

## Per-character setup (all verified Z-Image arch — see `scripts/lora_id.py`)

| Character | LoRA | trigger |
|---|---|---|
| Emma Fischer | `f1sher_000002400` @ 0.65 | `F1sher` |
| Sofia Lehtonen | `Sof1a-lehtonen-zti_000001100` | `Sof1a` |
| Emma Sunde | `Emma Sund3 Lora_000003800` | `sund3` |

New character: swap the LoRA widget + trigger word + REF 2 photo + trait
wording (eyes/hair) in both prompt boxes. Wan/LTX LoRAs are video-only and
cannot load here.

## Verification loop (how "can't tell" is measured, not vibed)

`scripts/score_identity.py` on the pod: ArcFace embeddings of her 51 training
images → intra-set similarity band → a render passes only if its mean
similarity lands inside the band (bar = intra p05 = **0.524** for Fischer).
Run 1 (identity-preserving path) scored 0.616. Plus eyeball checklist: eyes,
hairline, jaw shadow, orphan strands, seams, grain continuity.

Remote ops: `scripts/pod_exec.py` (Jupyter kernel — the image has no sshd,
RunPod proxy SSH hangs forever at the banner). Model files >100 MB: split -b
85m, upload parts via `/upload/image`, cat them together with pod_exec.

## Rebuilding the graph

`scripts/build_i2i_v3.py <object_info.json>` — validates every class, widget
and socket against a live pod's `/object_info` and emits both UI and API
formats. A typo fails the build instead of shipping a broken graph.
