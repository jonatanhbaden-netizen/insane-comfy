# Motion Control v2 — four workflows, pick by shot type

Replaces `insane_motion_control.json` for new work (old file kept). Research-based
design: see `superpowers/specs/2026-08-01-motion-control-v2-design.md` for why.

| I want… | Use | File |
|---|---|---|
| **copy a reel's performance 1:1** (the main workhorse) | **MC ANIMATE** | `aiofm_mc_animate.json` |
| fresh shot, motion guidance + camera moves | **MC SHOT** | `aiofm_mc_shot.json` |
| her taking off / changing clothing | **MC WARDROBE** | `aiofm_mc_wardrobe.json` |
| 30–90 s continuous content, invented events | **MC SEQUENCE** | `aiofm_mc_sequence.json` |

## MC ANIMATE — performance transfer (adapted from the b-1 workflow)

Wan 2.2 Animate + VitPose: the user-preferred motion copier, cleaned to run on
our pod. Two modes:

- **🔁 MIX (DEFAULT, and the off-frame answer):** the original reel is kept
  1:1 — background, camera moves, hands/objects entering from off-screen,
  everything — and only the person is replaced with your girl. **Pick source
  reels that already contain the events you want.** Relight LoRA matches her
  lighting to the scene. Verified working end-to-end (see below).
- **MOVE:** bypass the MIX MODE node group (mask-gen, grow, blockify, blackout)
  and she performs the driving motion in *her own* scene from the reference
  image. No off-frame events are possible in this mode — the model only ever
  sees pose + face crops, so anything entering frame is hallucinated.

**2026-08-03 — Mix mode verified working end-to-end** (proof render:
`test-assets/mc_animate_working_proof_s6.mp4`). The critical fix chain, found by
the tuning harness (`scripts/mc_tuning/`, log `docs/MC_ANIMATE_TUNING.md`):
bg frames must have the person region **blacked out** (`DrawMaskOnImage`) or the
model reconstructs the original girl from the leaked pixels; mask grown 10px +
blockified to the 32px latent grid; dedicated distill
`lightx2v_I2V_14B_480p_cfg_step_distill_rank64` @1.2 (NOT the expert-pair
distills); 6 steps; windowed mode (frame_window 77, context-options
disconnected); clip-vision crop `center`. Measured on the 97-frame smoke:
motion correlation 0.894 with zero lag; flicker ~66% above real footage is the
open quality target (A/B queue in the tuning log).

Changed vs b-1: 5-LoRA stack replaced (the 5×@1.0 stack is the documented
plastic-skin cause), NLF pose branch removed, empty prompts filled,
RunningHub-only nodes replaced, long-reel crash fixed (frame cap = frames).
Needs: `ComfyUI-WanAnimatePreprocess` pack (in Dockerfile) + section 2c models
+ the pod-side restore script `/workspace/refetch_local_models.sh` after any
pod stop (container-disk models, ~4 min).

All four: Wan 2.2 A14B, 480×832 vertical, **generate at 480p and upscale after
(SeedVR2)** — 720p vertical is documented-unstable. Character LoRA slots ship
bypassed; the Wan-arch character LoRA on the pod is `f1sher_000002400.safetensors`.
Frame budgets differ per workflow: MC ANIMATE runs one continuous clip in 77-frame
internal windows (`num_frames` and `frame_load_cap` must match, or long reels
crash); MC SEQUENCE chains 81-frame segments.

## MC SHOT — motion + camera

Inputs: character reference image + driving video (motion source).
Pose (DWPose, default) copies **body motion only**. The bypassed DepthAnything
branch copies **motion + the driving clip's camera move** but locks you to its
scene geometry — switch with Ctrl+B on both nodes.

Camera, three tiers:
1. **Prompt only** (free): one move per clip as its own sentence — "push in",
   "tracking shot", "arc left around her, under 45 degrees". Orbits beyond ~45°
   get ignored or warp.
2. **Camera LoRAs** (bypassed slots): ArcShot @0.8 for partial arcs, Handheld
   @1.7 for documentary drift. **Civitai downloads — manual** (auth wall):
   Civitai model 1787324 (ArcShot Wan2.2 I2V high-noise) and 2592748 (Shaky
   handheld). Drop in `loras/`, fix the slot filename to match, un-bypass.
3. **Uni3C** (bypassed branch): exact, repeatable trajectories. Feed a
   "trajectory render" video (the start frame re-rendered along a camera path).
   Build once per aspect ratio, reuse across all girls forever. If her
   performance freezes, lower `end_percent` toward 0.3 — camera is decided in
   the early diffusion steps.

**Lightning/distill LoRAs kill camera motion.** They ship bypassed here. If you
need the speed, accept weaker camera or take the first 2 high-noise steps
undistilled.

## MC WARDROBE — clothing changes

1. Make **Keyframe B** with the i2i workflow (Qwen-Edit): same woman, same room,
   same light, **end state of the action** — shirt in her hand / shoes on the
   floor, hair slightly mussed, exact reveal outfit visible. End-state keyframes
   force acted motion; same-pose outfit swaps produce a crossfade.
2. Load Keyframe A (before) + Keyframe B (after), write the motion prompt with
   both hands explicit: "she crosses her arms, grips the hem, pulls the shirt up
   over her head in one motion, drops it aside."
3. One garment per 81-frame clip. Loose garments are dramatically easier than
   tight. Never mention the removed garment late in the prompt.
4. Expect **2–5 seeds per clean take** — that is the state of the art, not a bug.
   The classic failure is tugging-without-removal or a dissolve; reseed first,
   then strengthen the end-state of Keyframe B.
5. Multi-garment sequences: chain clips where B becomes the next A — but every
   keyframe must be a **clean Qwen-Edit still, never a decoded video frame**
   (color drift accumulates).

## MC SEQUENCE — long clips, entries at boundaries

Three chained 81-frame segments (bypass the SEGMENT 3 group for shorter runs),
SVI 2.0 Pro LoRAs active on both experts, ColorMatch pinning every segment to
segment 1's palette, different fixed seed per segment.

- Per-segment prompts are **state + motion** ("she is sitting on the bed,
  laughing, leaning back"), not narrative.
- **Things entering from off-frame go at segment boundaries**: write "a man's
  hand enters from the right and hands her a drink" into the NEXT segment's
  prompt. Mid-segment entries are a lottery.
- 81 frames per segment is a hard model limit — 121 gives documented color
  degradation and sped-up motion. Do not "just try it."
- Keep distill LoRAs off or ≤0.6 in chains (slow-motion + color-shift cause #1).

## Models

| File | Status |
|---|---|
| Wan 2.2 Fun-Control + I2V A14B pairs, UMT5, VAE, lightning LoRAs | on volume |
| `Wan21_Uni3C_controlnet_fp16.safetensors` → `model_patches/` | auto (`download_models.sh` [2b]) |
| `SVI_v2_PRO_Wan2.2-I2V-A14B_{HIGH,LOW}_lora_rank_128_fp16.safetensors` → `loras/` | auto (2b) |
| ArcShot (Civitai 1787324), Handheld (Civitai 2592748) | **manual browser download** |

`SKIP_MOTION_CONTROL=true` skips section 2b on boot.
