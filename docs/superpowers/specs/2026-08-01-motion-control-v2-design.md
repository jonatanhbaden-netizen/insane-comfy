# Motion Control v2 — three-workflow suite

**Date:** 2026-08-01 · **Status:** building (user pre-authorized: "fire it off")
**Replaces:** `insane_motion_control.json` (kept; pure pose-copier, architecturally
unable to do camera moves / off-frame entries / wardrobe changes)

## Research verdicts (4 parallel agents, web-sourced, Aug 2026)

- Open Wan weights stop at **2.2** — 2.5/2.6/2.7 are API-only; "Wan 2.7 open"
  sites are SEO fakes. Wan 2.2 A14B stays the backbone; existing volume models
  and the F1scher Wan character LoRA pair keep working.
- **Camera:** Uni3C ControlNet went **native in ComfyUI core** (July 2026):
  `ModelPatchLoader` + `WanUni3CControlnetApply`, driven by a re-rendered
  trajectory video → exactly repeatable orbits/arcs/push-ins, reusable across
  characters. Backed up by camera LoRAs (ArcShot @0.8 high-noise, handheld @1.7)
  and prompt vocabulary (arcs ≤45°/clip). Distill/lightning LoRAs **suppress
  camera motion** — bypass on HIGH or skip first 2 high-noise steps.
- **Wardrobe:** keyframe-pair recipe — Qwen-Image-Edit makes the "after" still
  (end-state: garment in hand, exact reveal outfit), Wan 2.2 **FLF2V** (native
  `WanFirstLastFrameToVideo`, I2V pair) animates the transition; motion prompt
  describes the physical action. ~98% endpoint adherence; 2–5 seeds per clean
  take; crossfade-morph is the #1 failure (fix: end-state keyframes). VACE
  inpaint swaps outfits for a whole clip but cannot do the *act* of removal.
- **Long/multi-clip:** naive last-frame chaining provably drifts (color +
  identity per hop). **SVI 2.0 Pro** LoRAs (error-recycling fine-tune, KJNodes
  `WanImageToVideoSVIPro`) hold 30–90 s. 81 frames/segment is a hard model
  limit (121 → documented color degradation). Off-frame entries land reliably
  at segment boundaries via per-segment prompts; controlled entry of a
  *specific* object/person is VACE reference-injection (phase 2).
- Vertical: 720p vertical chains unstable → generate 480×832, upscale after
  (SeedVR2 on pod).

## The suite

| File | Purpose | Base models (volume) | New downloads |
|---|---|---|---|
| `aiofm_mc_shot.json` | single shots: motion drive + camera swings | Fun-Control A14B pair | Uni3C fp16 ~2.0 GB → `model_patches/`; ArcShot + handheld LoRAs (Civitai, manual) |
| `aiofm_mc_wardrobe.json` | clothing on/off via keyframe pair | I2V A14B pair | clip_vision_h if absent |
| `aiofm_mc_sequence.json` | 30–90 s chained clips, entries at boundaries | I2V A14B pair | SVI 2.0 Pro LoRA pair ~2.4 GB |

Total new: ~4.3 GB. No Docker rebuild — all node classes verified EXACT on the
running pod (native FLF2V/VACE/Uni3C/Fun-Camera/SVIPro + 114 wrapper nodes).

## Conventions

Titles are the bot-patch contract; character LoRA slots bypassed by default;
canonical Wan negative; 81f/16fps/480×832; ColorMatch after decode; RIFE ×2;
numbered usage Notes with failure modes in every graph.

## Phase 2 (not building now)

Wan2.2-VACE-Fun modules (wrapper path) for masked wardrobe-region control and
frame-pinned reference injection; HoloCine multi-shot once reference-image
identity lands; LTX-2.3 IC-LoRA camera track as alt family.

## Verification

Workflow-level: adversarial verify agent checks JSON/link integrity, every
class_type + widget order against pod `/object_info`, every model filename
against loader options (ON-POD vs NEW-DOWNLOAD vs typo). Render-level: user
renders (pod is theirs); per-graph smoke prompts in the Notes.
