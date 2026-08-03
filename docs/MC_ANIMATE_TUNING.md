# MC Animate — beast-mode tuning log

Continuous improvement loop, started 2026-08-03. Every iteration: seed-locked
A/B on a fixed battery, numeric metrics, keep only changes that advance motion
fidelity AND temporal stability together.

## Harness

- `scratchpad/mc/animate_api.py` — UI→API converter (schema-driven widget
  mapping, Get/Set resolution), parameterized render queue.
- `scratchpad/mc/metrics.py` — motion_corr + motion_lag (optical-flow
  cross-correlation vs driving clip), flicker index (2nd-order luminance,
  low-motion masked), drift_slope (histogram walk vs first frame),
  broken_frames (5σ diff spikes). Sanity-validated: same-file corr=1.0 lag=0.
- `scratchpad/mc/battery.py` — fixed battery, results to results.jsonl.

## Battery v1 (fixed, seed 4242)

| case | clip | frames | stresses |
|---|---|---|---|
| slow_talk | ref01 | 337 | slow motion, face fidelity |
| fast_gesture | ref06 | 225 | fast hands, direction changes |
| long_481 | ref04 | 481 | drift across context windows |

Gaps (need user-supplied clips): walking/locomotion, physical contact with the
subject, multiple subjects (Animate is single-subject by design — masks pick
one person; multi-subject is out of scope for this architecture).

## Bugs found & fixed by the harness before any tuning

1. **Mix-mode silently disconnected** — the MIX driving-frames Get node had a
   mojibake name that matched no Set node; mask+bg were never fed (browser and
   API alike). Fixed: exact name copy.
2. **Long-reel crash** — `frame_load_cap` 900 vs `num_frames` 481: any reel
   >16 s produced RepeatImageBatch "negative dimension". Fixed: cap = frames.
3. **Mask node malformed** — 6 widget values vs 7 required (missing
   `refine_mask`); silent until execution. Fixed: full person mask
   (face+hair+body+clothes), confidence 0.4, refine on.

## Iteration log

### It-0 smoke (49f, ref01, Mix): pipeline PASS, identity FAIL
Output preserved the driving reel scene 1:1 (Mix architecture ✓) but the
subject remained the driving girl — Emma not injected. Wiring dump proves
ref/clip-vision path correct and history proves her file loaded. Open
hypotheses: (A) mask polarity inverted, (B) driving-face crops at
face_strength 1.0 overpower reference identity. Discriminating smokes S2
(mask inverted) and S3 (face_strength 0.4) queued.

### It-1 discrimination (S2 mask-flip, S3 face 0.4): both still driving-girl
Outputs differ by content hash (overrides verified in runtime prompts) but only
subtly — identity unchanged in all three. Mask polarity and face strength are
NOT the root cause; the replacement conditioning is far too weak in this
configuration. Source reading (wrapper nodes.py 1220-1350): bg/mask handling
splits on a `looping` flag — windowed mode passes bg_images+mask through the
sampler per-window; single-window mode only pre-fuses them into the initial
latent. Our smokes ran single-window (window==frames, as does the stock graph
wiring). The b-1 original NEVER ran replacement at all (no mask nodes), so this
path was unproven territory.

**S4 queued**: identical smoke but windowed (97 frames / window 49) — if Emma
appears, root cause confirmed as path-dependent replacement.

Also learned: 200px strip comparison declared three subtly-different renders
"identical" — strips are for coarse judgment only; hashes and metrics decide.

### It-2 official-config conformance (S5): still driving-girl
Applied the reference implementation's full config (dedicated distill @1.2,
6 steps, window 77, clip-vision center crop, mask grow 10 + blockify 32,
context-options off). Identity still unchanged. Eliminated: LoRA arch, steps,
window mode, crop, mask alignment as root cause.

### It-3 ROOT CAUSE — background pixel leak (S6): **EMMA APPEARS** ✅
The official pipeline runs `DrawMaskOnImage` to BLACK OUT the person region in
the background frames before they condition the model. We fed raw frames, so
the bg conditioning still contained the driving girl's pixels — the model
reconstructed her from there, overriding every identity signal. One node, total
identity flip. Wired into the shipped graph: bg_images now = driving frames
with the grown+blockified person mask painted black. S6 shows Emma (face,
hair, even her reference outfit) performing the driving motion in the intact
original scene.

**Correctness phase complete. Quality phase begins: B0 baseline battery with
the working config, then measured A/B iterations.**

### Loop suspended 2026-08-03 (pod stopped by user) — resume state

Correctness phase: COMPLETE. Quality phase: baseline battery interrupted before
completion; quality A/Bs not yet run.

**Best measured state (S6, 97f smoke, ref01):** motion_corr 0.894, motion_lag 0,
flicker 1.466 (real-footage reference ≈0.88), drift_slope -1.24, broken 2.
Tracking is strong with zero phase error; temporal flicker ~66% above real
footage is the primary quality gap.

**Resume plan (one command each, in order):**
1. `POD_ID=<pod> wsenv/bin/python newpod_setup.py` — restore models (~4 min;
   refetch script now includes ALL 10 files incl. the distill LoRA).
2. `POD_ID=<pod> wsenv/bin/python battery.py run B0` — baseline battery.
3. A/B queue, one knob per tag, keep only if BOTH motion_corr and flicker hold:
   - `run colormatch colormatch=mkl` (embeds colormatch; targets window-boundary
     flicker + drift)
   - `run vitposeH vitpose=vitpose_h_wholebody_model.onnx` (needs the H model +
     its .bin in models/detection — 2.4 GB, HF Kijai/vitpose_comfy)
   - `run steps8 steps=8` and distill 1.2→1.0 sweep
   - relight-off-in-Move sanity check
4. Long-sequence: window-boundary flicker localization on long_481 (correlate
   flicker spikes with 77-frame window seams).

Harness lives in the session scratchpad `mc/` (animate_api.py, metrics.py,
battery.py) — network-hardened, pod-agnostic via POD_ID env.
