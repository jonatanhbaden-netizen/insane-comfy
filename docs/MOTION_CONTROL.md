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

- **MOVE (default):** the girl performs the driving clip's motion in *her*
  scene. No off-frame events possible — the model only knows pose + face.
- **🔁 MIX (the off-frame answer):** un-bypass the two MIX MODE nodes and wire
  them into `WanVideoAnimateEmbeds` (`bg_images` + `mask`). The original reel is
  kept 1:1 — camera moves, hands/objects entering from off-screen, everything —
  and only the person is swapped. **Pick source reels that contain the events
  you want.** Relight LoRA matches her lighting to the scene.

Changed vs b-1 (all reversible, documented in the in-graph Note): 5-LoRA stack
trimmed to relight + lightning-LOW (the 5×@1.0 stack is the documented
plastic-skin/identity-drift cause), NLF pose branch removed (VitPose was
active), empty prompts filled, RunningHub-only nodes replaced with installed
equivalents. Needs: `ComfyUI-WanAnimatePreprocess` pack (in Dockerfile; or
install today via Manager → Install via Git URL, then restart) + download
section 2c models (~20 GB — volume is tight, use `MODELS_LOCAL=true`).

All three: Wan 2.2 A14B, 480×832 vertical, 81 frames/segment, 16 fps → RIFE ×2.
**Generate at 480p vertical and upscale after (SeedVR2)** — 720p vertical chains
are documented-unstable. Character LoRA slots ship bypassed; the Wan-arch
character LoRA on the pod is `f1sher_000002400.safetensors`.

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
