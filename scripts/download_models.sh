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
  # Flux VAE — pulled from the ungated schnell repo (identical ae.safetensors)
  dl "black-forest-labs/FLUX.1-schnell" "ae.safetensors" "$MODELS_DIR/vae"

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
