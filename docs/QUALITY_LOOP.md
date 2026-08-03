# The i2i quality loop — standing protocol

The workflow is never finished. This document is the operating procedure for
raising its quality floor, and the rules below are binding on every cycle.

**Scope:** our own original AI characters (Emma Fischer / Emm4 / Sofia). The
real-person face-replacement lineage stays out of this loop.

---

## Non-negotiable targets

| Axis | Target | How it is judged |
|---|---|---|
| Skin realism | real human skin at 200% zoom — pores, micro-texture, oil/dry variation. Never plastic, never crunchy | `skin_hf_ratio` in 0.85–1.25 **and** the SKIN row of the zoom sheet |
| Identity | zero drift in geometry, age, expression, distinctive marks | ArcFace `mean_sim` ≥ the character's calibrated bar (Fischer: 0.524) and no drop vs the previous accepted cycle |
| Photographic, not "AI" | reads as a photo of that person, not a render | `grain_ratio` ≈ 1.0, `seam_gradient` ≤ 0, `face_neck_dE` ≤ 6, plus eyes-on judgement |

A change that improves one axis and costs another is **rejected**, not traded.

---

## The loop

```
  1 pick the highest-leverage experiment from the queue below
  2 change EXACTLY ONE dial
  3 python3 scripts/i2i_test_harness.py --pod P --token T \
        --workflow ../workflows/aiofm_i2i_vN.json --object-info /tmp/oi.json \
        --tag <descriptive-tag> --set 'SELECTOR.field=value'
  4 python3 scripts/i2i_test_harness.py --compare runs/<prev> runs/<new>
  5 zoom sheets: scripts/zoom_sheet.py --score-json … --pairs ref=out …
     → judge SKIN, JAW, HAIRLINE, EYES rows by eye at 200%
  6 ACCEPT (new tag becomes the reference run, commit the graph) or
    REJECT (document why in runs/<tag>/report.md — a rejected experiment that
    is written down is worth as much as an accepted one)
  7 return to 1 — never stop at "good enough"
```

### The yardstick (do not move casually)

Five references in `i2i_test_harness.REFS`, chosen so a change cannot look
good by helping only one kind of shot: warm tungsten close-up, second phone
framing, dim low-contrast bedroom, mirror shot with a small face, cool-light
fitting room. Editing this list is a deliberate act: note it in the commit and
re-baseline afterwards — old runs are not comparable across a yardstick change.

### Metrics

`scripts/i2i_metrics.py` — CPU-only, no pod required (local YuNet face
detection; the pod's ArcFace bbox is used instead when available, because it is
the same detector that produces the identity score).

| metric | meaning | target |
|---|---|---|
| `skin_hf_ratio` | cheek high-frequency energy, output ÷ reference | 0.85–1.25 (<0.7 plastic, >1.4 crunchy) |
| `grain_ratio` | face HF ÷ untouched body-skin HF in the same frame | 0.80–1.20 (1.0 = insert carries the host photo's noise floor) |
| `seam_gradient` | boundary-ring gradient minus its neighbourhood | ≤ 0 (calibrated: seamless whole-frame renders measure −1 to −2) |
| `face_neck_dE` | CIE-Lab ΔE, face skin vs neck skin | ≤ 6 |
| `laplacian_var` | face sharpness | regression canary only |

Identity is **never** inferred from these. If the pod scorer is unreachable the
report says identity was not measured — a missing measurement is never
recorded as a pass.

---

## Measured state (2026-08-03)

From `runs/v5-preloop-observed` (single reference — superseded by the first
real five-reference baseline):

| render | skin_hf | grain | seam | dE |
|---|---|---|---|---|
| v5 full chain incl. POST | 1.49 | 3.37 | 4.15 | 2.2 |
| v5, POST bypassed | 1.22 | 1.53 | −1.39 | 8.9 |
| v4.3 face-detailer only | 0.81 | 1.10 | 1.15 | 23.5 |

**What this establishes**

1. POST processing is measurably the worst configuration on skin, grain and
   seam simultaneously — bypassing it (v5.2) was correct, and the numbers now
   say so independently of anyone's eye.
2. Whole-frame renders sit at seam ≈ −1 to −2. That is the calibration for
   v6's composite: **seam_gradient ≤ 0 means the boundary is invisible**.
3. Two defects are now quantified rather than described: `grain_ratio` ≈ 1.5
   (the generated face carries ~50% more noise than the host photo) and
   `face_neck_dE` ≈ 9 (insert colour/lighting is off).

**Open, unmeasured:** v6's face-only composite has never been rendered. Its
first five-reference baseline is cycle 0 of the loop.

---

## Graph discipline

`aiofm_i2i_v6.json` is the **frozen baseline graph**. Experiments get their own
file (`v7`, `v8`, …) so that a cycle changes exactly one thing and the baseline
stays reproducible. An experiment graph must be output-identical to its parent
at the dial's neutral value — v7 at `hf_attenuation = 0.0` renders exactly what
v6 renders, which is what makes the comparison honest.

**Serialization law (learned the hard way, 2026-08-03):** ComfyUI keeps a
placeholder slot in `widgets_values` for *every* widget-backed input, including
ones converted to links. Emitting only the unlinked widgets shifts every later
value out of position — the v6 `StringConcatenate` nodes shipped a 1-element
array where the class needs 3, so `delimiter` fell off the end and every run
died with "Required input is missing: delimiter". The builder now emits full
placeholder arrays; `flatten_ui_to_api.py` enforces the same rule when reading.
Any new node built by hand must obey it.

## Experiment queue

Ranked by (expected joint gain on skin + identity) ÷ (GPU cost). One per cycle.
Sources verified live 2026-08-03; full research in the session record.

| # | experiment | change | why it is high leverage | cost |
|---|---|---|---|---|
| 1 | **Grain matching** (BUILT — `workflows/aiofm_i2i_v7.json`) | one dial `hf_attenuation`: blend the composited face toward its own low-pass, inside the face mask only. Sweep 0.20 / 0.35 / 0.50 against the v6 baseline | attacks the measured `grain_ratio` 1.5 directly. Deliberately the simple form first — fully understood semantics, one variable. If attenuation alone overshoots `skin_hf_ratio` downward, escalate to 1b | built, needs 1 cycle |
| 1b | **Grain transplant** (escalation if 1 trades skin for grain) | frequency-separate the untouched original and recombine its HF over the face's low-pass at partial strength — RES4LYF `Frequency Separation Hard Light LAB` is already installed on the pod (verify its 3-in/3-out semantics on a throwaway graph first) | the face then carries the camera's *own* noise — same ISO, same luminance dependence — which synthetic grain can never match | ~2h build |
| 2 | **Face-crop-scoped ColorMatch** | wrap the finish in Inpaint-CropAndStitch, ColorMatch on the face crop against its surrounding skin (strength 0.4–0.6) | attacks the measured `face_neck_dE` ≈ 9; whole-frame stats can't fix a local mismatch | ~1–2h |
| 3 | **Best-of-4 identity gate** | batch the detailer over 4 seeds, `FaceEmbedDistance` each vs the identity photo, select argmax | raises worst-case identity without touching any dial that costs skin; also gives per-seed identity variance | 4× detailer only |
| 4 | **Character LoRA retrain (rank 16, Z-Image Base / de-turbo adapter, optional ArcFace anchor)** | replace the fried rank-32 checkpoint | the current LoRA is the hard ceiling on identity — it produces noise at strength 1.0, so identity can never be pushed | ~1 GPU-day |
| 5 | **Laplacian-pyramid composite** | swap `ImageCompositeMasked` for multi-band blending | low frequencies (tone, lighting) blend wide while pores/strands transition sharply — the principled fix for boundaries | ~1h |
| 6 | **Detail Daemon / Lying Sigma in the detailer** | wrap the sampler, dishonesty −0.03…−0.05 | more genuine pore density at *lower* denoise, which also helps identity retention; free at inference | ~1h + sweep |
| 7 | **Realistic-Snapshot skin LoRA stacked** | character LoRA + skin LoRA at 0.3/0.5/0.7 | pushes skin high-frequency statistics toward camera-real at the source | ~45min |
| 8 | **BFS Head V5 swap LoRA on the Qwen stage** | add after the Lightning LoRA | task-trained head transfer vs bare 2511 behaviour | ~1h |
| 9 | **Z-Image Base low-denoise skin pass** | second SEGS pass, CFG 3–4, denoise 0.15–0.25, negative "plastic, waxy, airbrushed" | the un-distilled model can express real negatives; Turbo at CFG 1 cannot | ~12GB + 1h |
| 10 | **SeedVR2 7B-sharp fp16 on native nodes** | swap the restore stage | current runtime is fp8 on custom nodes | ~17GB |
| 11 | **VITMatte hair-edge alpha** | replace binary-ish union mask with a real alpha matte | hair needs fractional alpha; no amount of blurring a binary mask makes strands | ~1h |

**Confirmed by research, no cycle needed:** restore-before-detail is correct
current practice — never append a restorer after the detailer (it treats
generated skin as degradation and re-smooths it). No open restorer preserves
sensor noise, which is why experiment 1 transplants it instead.

**Do not spend cycles on:** SUPIR (benchmarks below SeedVR2 for skin),
GFPGAN/CodeFormer (512-crop era, plastic), uniform FilmGrain as the noise fix,
PuLID/InstantID for Qwen-2511 or Z-Image (do not exist for these architectures),
whole-frame degrain→composite→regrain (would modify the original pixels we are
deliberately preserving).

---

## First GPU session, in order

1. `scripts/reassemble_loras.sh` via `pod_exec.py` — installs the Emm4
   checkpoints (sha-pinned; `Emm4-zit_000001200` still needs re-upload)
2. restore `qwen_3_4b` to the container disk if the pod was recreated
3. stage the five references into the pod's input directory
4. **cycle 0**: v6 baseline across all five refs, no variant — this is the
   number every later cycle is measured against
5. cycle 1: experiment 1 (grain transplant), then compare, accept or reject
6. keep going

Park (needs a human decision, not a cycle): volume expansion beyond 250GB,
whether to delete older model families to make room, and whether to spend a
GPU-day on the LoRA retrain (experiment 4 — highest absolute identity gain).
