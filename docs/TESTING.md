# Testing & First-Load Verification

## 0. Honest caveat (read once)

The two workflow JSONs use exact node/input names for ComfyUI core nodes and
the pinned custom node packs. Core-node widgets are stable; **custom node packs
occasionally reorder or add widgets between versions**. The one-time checklist
below catches any drift in two minutes. After that, save your verified copy
(Workflows → Save As) and the point is moot forever.

## 1. First load checklist (one-time, ~5 min)

Open each workflow → if any node is bright red: Manager → *Install Missing
Custom Nodes* → Restart. Then eyeball these widget values against the intent:

**insane_motion_control.json**
- [ ] Both Fun-Control UNET loaders point at `wan2.2_fun_control_*_fp8_scaled` (HIGH on top)
- [ ] CLIPLoader: `umt5_xxl_fp8_e4m3fn_scaled` + type `wan`
- [ ] VHS LoadVideo: force_rate 16, frame_load_cap 81
- [ ] DWPose: hands/body/face `enable`, resolution 1024
- [ ] HIGH sampler: 20 steps, cfg 3.5, start 0 end 10, add_noise enable, leftover noise enable
- [ ] LOW sampler: 20 steps, cfg 3.5, start 10, add_noise disable
- [ ] Both ModelSamplingSD3: shift 8.0
- [ ] RIFE: rife49, multiplier 2 · VideoCombine: 32 fps, crf 17
- [ ] Lightning LoRA nodes are purple (bypassed); bottom I2V group is muted

**insane_image_to_image.json**
- [ ] UNETLoader: `flux1-dev-fp8-e4m3fn` with weight_dtype `fp8_e4m3fn`
- [ ] DualCLIPLoader: clip_l + t5xxl fp8 scaled, type `flux`
- [ ] CN stages top→bottom read DEPTH 0.60 / CANNY 0.45 / POSE 0.65 (pose bypassed)
- [ ] ApplyPulidFlux: weight 0.85, start 0.0, end 1.0 (extra widgets your pack
      may show, e.g. fusion method — leave at defaults)
- [ ] KSampler: 28 steps, **cfg 1.0**, euler/beta, denoise 0.50
- [ ] FaceDetailer: guide 512, max 1024, cfg 1.0, denoise 0.45
- [ ] Ultimate Upscale: 2.0×, denoise 0.22, 1024 tiles, cfg 1.0
- [ ] Redux apply + character LoRA nodes are purple (bypassed)

If a custom node shows obviously shuffled values (e.g. a string where a number
belongs), fix per the titles/notes — every intended value is also documented in
`docs/PARAMETERS.md`.

## 2. Smoke test A — image-to-image (~5 min)

1. Upload any 1–2 MP photo as `input_image.png`, any clean frontal face render
   as `face_reference.png` (or bypass ApplyPulidFlux to skip identity).
2. Queue with defaults. First queue downloads DepthAnythingV2 + DWPose +
   EVA-CLIP (watch the log; one-time).
3. Expect three saves in `output/insane_i2i/`: base ≈ 25–35 s after models are
   resident; full chain ≈ 2–3 min.
4. Pass criteria: 01_base follows the input's composition at denoise 0.5;
   02 has a visibly cleaner face; 03 is ~2× the working resolution, no tile seams.

## 3. Smoke test B — motion control (~15 min)

1. Upload a character still (ideally a 02/03 output from smoke test A) and a
   5-second single-person motion clip you have rights to.
2. Run the **Lightning preset first** (note ③ in-canvas: enable both ⚡ LoRAs,
   4 steps, cfg 1.0, shift 5.0) at 832×480 — ~60–120 s. Confirms the whole
   chain end-to-end cheaply. First queue downloads RIFE 4.9.
3. Pass criteria: output in `output/insane_motion/`, subject follows the clip's
   motion, no skeleton ghosting. Skeleton visible in output = your control
   video is the DWPose *render* being interpreted as content — check the DWPose
   node is connected via the pose ImageScale into `control_video` (not `ref_image`).
4. Flip back to max quality (bypass LoRAs, 20 steps, cfg 3.5, shift 8.0,
   1280×720) and rerun the same seed for the real result.

## 4. API smoke test

```bash
# on the pod (or via the proxy URL from anywhere)
python3 /workspace/comfy_api_client.py exported_api.json \
  --host http://127.0.0.1:8188 --set "<ksampler-id>.inputs.seed=1" --out /workspace/output/api_test
```

Exported API JSON comes from Workflow → Export (API) after you've verified the
UI version. Muted/bypassed branches are dropped automatically on export.

## 5. Known first-run latencies

| Event | Cost | Recurs? |
|---|---|---|
| Boot with DOWNLOAD_MODELS=true, empty volume | 20–60 min | no (volume persists) |
| First img2img queue (DepthAnything/DWPose/EVA-CLIP) | +1–3 min | no |
| First motion queue (RIFE weights) | +30 s | no |
| First queue after switching workflows (model swap) | +1–2 min | on every switch — see PARAMETERS.md VRAM notes |
