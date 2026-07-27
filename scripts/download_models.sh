#!/usr/bin/env bash
# ============================================================================
# Downloads every model required by:
#   workflows/insane_motion_control.json   (Wan 2.2 Fun-Control + I2V)
#   workflows/insane_image_to_image.json   (Flux.1-dev + Union Pro 2 + PuLID)
#
# Idempotent — already-present files are skipped, safe to re-run.
# Target: /workspace/models (override with MODELS_DIR=/path).
# Total: ~95 GB. Use a >= 200 GB network volume (models + outputs + HF cache).
#
# Env:
#   HF_TOKEN     only needed for WITH_REDUX=true (gated flux1-redux-dev)
#   WITH_REDUX   "true" to fetch the Redux style model (default false)
#   SKIP_WAN     "true" to skip video models (img2img-only pod)
#   SKIP_FLUX    "true" to skip Flux models (video-only pod)
# ============================================================================
set -uo pipefail

MODELS_DIR="${MODELS_DIR:-/workspace/models}"
export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-1}"

# hf (new) vs huggingface-cli (old) — use whichever exists
if command -v hf >/dev/null 2>&1; then
  HF_CLI="hf"
elif command -v huggingface-cli >/dev/null 2>&1; then
  HF_CLI="huggingface-cli"
else
  echo "FATAL: huggingface cli not found (pip install 'huggingface_hub[cli]')"; exit 1
fi

FAILED=0

# dl <repo> <path-in-repo> <dest_dir> [dest_name]
dl() {
  local repo="$1" file="$2" dir="$3" name="${4:-$(basename "$2")}"
  if [ -f "$dir/$name" ]; then
    echo "  ✓ exists: $name"
    return 0
  fi
  mkdir -p "$dir"
  echo "  ↓ $repo :: $file"
  local tmp="$dir/.hfdl.$$"
  if $HF_CLI download "$repo" "$file" --local-dir "$tmp" >/dev/null; then
    mv "$tmp/$file" "$dir/$name"
    rm -rf "$tmp"
    echo "  ✓ done:   $name"
  else
    rm -rf "$tmp"
    echo "  ✗ FAILED: $repo :: $file"
    FAILED=1
  fi
}

# dl_url <url> <dest_dir> <dest_name>  — plain https download
dl_url() {
  local url="$1" dir="$2" name="$3"
  if [ -f "$dir/$name" ]; then
    echo "  ✓ exists: $name"
    return 0
  fi
  mkdir -p "$dir"
  echo "  ↓ $url"
  if curl -fL --retry 3 -o "$dir/.dl.$$" "$url"; then
    mv "$dir/.dl.$$" "$dir/$name"
    echo "  ✓ done:   $name"
  else
    rm -f "$dir/.dl.$$"
    echo "  ✗ FAILED: $url"
    FAILED=1
  fi
}

WAN_22_REPO="Comfy-Org/Wan_2.2_ComfyUI_Repackaged"
WAN_21_REPO="Comfy-Org/Wan_2.1_ComfyUI_repackaged"

# ============================================================================
if [ "${SKIP_WAN:-false}" != "true" ]; then
  echo "=== [1/6] Wan 2.2 video models (~63 GB) ==="

  # Fun-Control pair — pose/motion-driven generation (primary branch)
  dl "$WAN_22_REPO" "split_files/diffusion_models/wan2.2_fun_control_high_noise_14B_fp8_scaled.safetensors" "$MODELS_DIR/diffusion_models"
  dl "$WAN_22_REPO" "split_files/diffusion_models/wan2.2_fun_control_low_noise_14B_fp8_scaled.safetensors"  "$MODELS_DIR/diffusion_models"

  # I2V pair — pure image-to-video (alt branch)
  dl "$WAN_22_REPO" "split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors" "$MODELS_DIR/diffusion_models"
  dl "$WAN_22_REPO" "split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"  "$MODELS_DIR/diffusion_models"

  # Shared text encoder + VAE
  dl "$WAN_21_REPO" "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" "$MODELS_DIR/text_encoders"
  dl "$WAN_22_REPO" "split_files/vae/wan_2.1_vae.safetensors" "$MODELS_DIR/vae"

  echo "=== [2/6] Wan 2.2 Lightning 4-step LoRAs (~2.6 GB) ==="
  # I2V pair (alt branch speed preset)
  dl "$WAN_22_REPO" "split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors" "$MODELS_DIR/loras"
  dl "$WAN_22_REPO" "split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors"  "$MODELS_DIR/loras"
  # T2V-based pair (works with Fun-Control speed preset)
  dl "lightx2v/Wan2.2-Distill-Loras" "wan2.2_t2v_A14b_high_noise_lora_rank64_lightx2v_4step_1217.safetensors" "$MODELS_DIR/loras"
  dl "lightx2v/Wan2.2-Distill-Loras" "wan2.2_t2v_A14b_low_noise_lora_rank64_lightx2v_4step_1217.safetensors"  "$MODELS_DIR/loras"
fi

# ============================================================================
if [ "${SKIP_FLUX:-false}" != "true" ]; then
  echo "=== [3/6] Flux.1-dev backbone (~18 GB) ==="
  dl "Kijai/flux-fp8" "flux1-dev-fp8-e4m3fn.safetensors" "$MODELS_DIR/diffusion_models"
  dl "comfyanonymous/flux_text_encoders" "clip_l.safetensors" "$MODELS_DIR/text_encoders"
  dl "comfyanonymous/flux_text_encoders" "t5xxl_fp8_e4m3fn_scaled.safetensors" "$MODELS_DIR/text_encoders"
  # Flux VAE — BFL gated their repos (401 anonymous); Comfy-Org mirror serves
  # the byte-identical ae.safetensors (335,304,388 bytes) openly
  dl "Comfy-Org/Lumina_Image_2.0_Repackaged" "split_files/vae/ae.safetensors" "$MODELS_DIR/vae" "ae.safetensors"

  echo "=== [4/6] Control + identity stack (~8 GB) ==="
  # One ControlNet, all modes (canny / soft edge / depth / pose / gray),
  # no mode-selector node needed in 2.0
  dl "Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro-2.0" "diffusion_pytorch_model.safetensors" \
     "$MODELS_DIR/controlnet" "FLUX.1-dev-ControlNet-Union-Pro-2.0.safetensors"

  # PuLID-Flux identity adapter
  dl "guozinan/PuLID" "pulid_flux_v0.9.1.safetensors" "$MODELS_DIR/pulid"

  # insightface antelopev2 (face embedding for PuLID)
  ANTELOPE="$MODELS_DIR/insightface/models/antelopev2"
  for f in 1k3d68.onnx 2d106det.onnx genderage.onnx glintr100.onnx scrfd_10g_bnkps.onnx; do
    dl "DIAMONIK7777/antelopev2" "$f" "$ANTELOPE"
  done

  # sigCLIP vision (Redux conditioning encoder)
  dl "Comfy-Org/sigclip_vision_384" "sigclip_vision_patch14_384.safetensors" "$MODELS_DIR/clip_vision"

  if [ "${WITH_REDUX:-false}" = "true" ]; then
    echo "--- Redux style model (GATED — requires HF_TOKEN + accepted license) ---"
    dl "black-forest-labs/FLUX.1-Redux-dev" "flux1-redux-dev.safetensors" "$MODELS_DIR/style_models"
  else
    echo "--- skipping gated flux1-redux-dev (set WITH_REDUX=true to fetch) ---"
  fi

  echo "=== [5/6] Detail + upscale stack (~0.5 GB) ==="
  dl "Bingsu/adetailer" "face_yolov8m.pt" "$MODELS_DIR/ultralytics/bbox"
  dl_url "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth" "$MODELS_DIR/sams" "sam_vit_b_01ec64.pth"
  dl "Kim2091/UltraSharp" "4x-UltraSharp.pth" "$MODELS_DIR/upscale_models"
fi

# ============================================================================
# LTX-2.3 talking-head stack. Every node in aiofm_talking_ltx23.json is
# comfy-core, so this is weights-only — no custom node pack needed.
if [ "${SKIP_LTX:-false}" != "true" ]; then
  # RunPod network volumes can be badly contended — EU-NL-1 measured ~9 MB/s in
  # both directions on 2026-07-27, which made a 29 GB checkpoint take ~50 min to
  # reach VRAM on every single boot. LTX_LOCAL=true fetches this stack onto the
  # pod's LOCAL container disk instead (fast NVMe), trading persistence for speed:
  # it dies with the pod, but re-downloading from HF beats reading a slow volume.
  # Needs container disk >= 70 GB. extra_model_paths.yaml searches it first.
  LTX_DIR="$MODELS_DIR"
  if [ "${LTX_LOCAL:-false}" = "true" ]; then
    LTX_DIR="${LTX_LOCAL_DIR:-/local-models}"
    echo "=== [LTX-2.3] using LOCAL disk: $LTX_DIR (LTX_LOCAL=true) ==="
    mkdir -p "$LTX_DIR"
    avail_gb=$(df -BG --output=avail "$LTX_DIR" 2>/dev/null | tail -1 | tr -dc '0-9')
    if [ -n "$avail_gb" ] && [ "$avail_gb" -lt 60 ]; then
      echo "  !! only ${avail_gb}GB free on $LTX_DIR — need ~55GB."
      echo "  !! falling back to the network volume. Redeploy with a bigger container disk."
      LTX_DIR="$MODELS_DIR"
    fi
  fi
  echo "=== [LTX-2.3] Audio-conditioned talking-head stack (~53 GB) -> $LTX_DIR ==="

  # 22B transformer. Also carries the video VAE *and* the audio VAE — the
  # LTXVAudioVAELoader node points at this same file, there is no separate
  # audio VAE download.
  dl "Lightricks/LTX-2.3-fp8" "ltx-2.3-22b-dev-fp8.safetensors" "$LTX_DIR/checkpoints"

  # Gemma 3 12B text encoder. The official template ships fp4_mixed (9.45 GB);
  # we take fp8_scaled (13.21 GB) instead — prompt adherence is a known weak
  # point of the fp4 quant and we have the VRAM for it.
  dl "Comfy-Org/ltx-2" "split_files/text_encoders/gemma_3_12B_it_fp8_scaled.safetensors" \
     "$LTX_DIR/text_encoders"

  # 8-step distillation LoRA — applied at strength 0.5, not 1.0.
  dl "Lightricks/LTX-2.3" "ltx-2.3-22b-distilled-lora-384.safetensors" "$LTX_DIR/loras"

  # Reference-sheet identity LoRA. Trained 768x448 / 121f / 24fps, so it is
  # out-of-distribution at 1088x1920 — bypassed in the workflow by default.
  # GATED: verified 401 without auth. Needs HF_TOKEN + the license accepted on
  # the same HF account, exactly like flux1-redux-dev.
  if [ -n "${HF_TOKEN:-}" ]; then
    dl "Lightricks/LTX-2.3-22b-IC-LoRA-Ingredients" \
       "ltx-2.3-22b-ic-lora-ingredients-0.9.safetensors" "$LTX_DIR/loras"
  else
    echo "  — skipping IC-LoRA Ingredients (gated; set HF_TOKEN + accept the"
    echo "    license at hf.co/Lightricks/LTX-2.3-22b-IC-LoRA-Ingredients)."
    echo "    Not required: it is bypassed in aiofm_talking_ltx23.json by default."
  fi

  # Abliterated LoRA for the built-in Gemma prompt enhancer (TextGenerateLTX2Prompt).
  dl "Comfy-Org/ltx-2" "split_files/loras/gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors" \
     "$LTX_DIR/loras"

  # Latent upscalers. x2 spatial is wired into stage 2 of the workflow;
  # temporal x2 is for the 24 -> 48 fps test (replaces RIFE).
  dl "Lightricks/LTX-2.3" "ltx-2.3-spatial-upscaler-x2-1.1.safetensors" \
     "$LTX_DIR/latent_upscale_models"
  dl "Lightricks/LTX-2.3" "ltx-2.3-temporal-upscaler-x2-1.0.safetensors" \
     "$LTX_DIR/latent_upscale_models"

  # Skin/pore texture restore (1x, CC0, 181 KB) — the anti-plastic pass.
  dl "notkenski/upscalers" "1xSkinContrast-High-SuperUltraCompact.pth" \
     "$LTX_DIR/upscale_models"
fi

# ============================================================================
echo "=== [6/6] Notes on auto-downloaded weights ==="
echo "  • DWPose (yolox_l.onnx + dw-ll torchscript) and DepthAnythingV2 download"
echo "    on first use into /workspace/model_cache/ctrl_aux (persisted)."
echo "  • RIFE rife49.pth downloads on first use into model_cache/frame_interp."
echo "  • EVA-CLIP (PuLID) downloads on first use into the HF cache on the volume."

echo ""
echo "=== disk usage ==="
du -sh "$MODELS_DIR" 2>/dev/null || true

if [ "$FAILED" -ne 0 ]; then
  echo ""
  echo "!!! Some downloads FAILED — scroll up for ✗ lines and re-run this script."
  exit 1
fi
echo "=== all downloads complete ==="
