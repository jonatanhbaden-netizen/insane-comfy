#!/usr/bin/env bash
# ============================================================================
# Container entrypoint — prepares the network volume, seeds workflows,
# optionally downloads models, then launches ComfyUI.
#
# Env vars (set on the RunPod template):
#   HF_TOKEN          HuggingFace token — required once for gated files
#                     (flux1-redux-dev). Everything else is ungated.
#   DOWNLOAD_MODELS   "true" (default) → run /download_models.sh on boot.
#                     Set "false" once the volume is populated for fast boots.
#   WITH_REDUX        "true" to also fetch the gated Redux style model.
#   JUPYTER_PASSWORD  If set, JupyterLab starts on :8888 with this token.
#   COMFY_ARGS        Extra/override args for ComfyUI (replaces auto flags).
# ============================================================================
set -uo pipefail

VOL=/workspace
COMFY=/ComfyUI

echo "=== INSANE COMFY :: boot $(date -u +%FT%TZ) ==="

# --- volume layout ----------------------------------------------------------
mkdir -p \
  "$VOL/models/diffusion_models" \
  "$VOL/models/text_encoders" \
  "$VOL/models/vae" \
  "$VOL/models/loras" \
  "$VOL/models/controlnet" \
  "$VOL/models/clip_vision" \
  "$VOL/models/style_models" \
  "$VOL/models/pulid" \
  "$VOL/models/insightface/models" \
  "$VOL/models/ultralytics/bbox" \
  "$VOL/models/ultralytics/segm" \
  "$VOL/models/sams" \
  "$VOL/models/upscale_models" \
  "$VOL/models/checkpoints" \
  "$VOL/models/embeddings" \
  "$VOL/input" "$VOL/output" "$VOL/workflows" \
  "$VOL/model_cache/ctrl_aux" "$VOL/model_cache/frame_interp" \
  "$VOL/.cache/huggingface"

# HF cache on the volume → EVA-CLIP (PuLID) etc. persist across pods
export HF_HOME="$VOL/.cache/huggingface"

# --- persist auto-downloaded annotator/interpolation weights -----------------
rm -rf "$COMFY/custom_nodes/comfyui_controlnet_aux/ckpts"
ln -s  "$VOL/model_cache/ctrl_aux" "$COMFY/custom_nodes/comfyui_controlnet_aux/ckpts"
rm -rf "$COMFY/custom_nodes/ComfyUI-Frame-Interpolation/ckpts"
ln -s  "$VOL/model_cache/frame_interp" "$COMFY/custom_nodes/ComfyUI-Frame-Interpolation/ckpts"

# --- input/output on the volume ----------------------------------------------
rm -rf "$COMFY/output" && ln -s "$VOL/output" "$COMFY/output"
rm -rf "$COMFY/input"  && ln -s "$VOL/input"  "$COMFY/input"

# --- seed the two workflows into the UI sidebar + volume ---------------------
mkdir -p "$COMFY/user/default/workflows"
cp -n /workflows/*.json "$COMFY/user/default/workflows/" 2>/dev/null || true
cp -n /workflows/*.json "$VOL/workflows/" 2>/dev/null || true

# --- models -------------------------------------------------------------------
if [ "${DOWNLOAD_MODELS:-true}" = "true" ]; then
  echo "=== model download (set DOWNLOAD_MODELS=false to skip) ==="
  bash /download_models.sh || echo "!!! download_models.sh reported errors — check above"
fi

# --- optional JupyterLab -------------------------------------------------------
if [ -n "${JUPYTER_PASSWORD:-}" ]; then
  echo "=== starting JupyterLab on :8888 ==="
  jupyter lab --ip=0.0.0.0 --port=8888 --allow-root --no-browser \
    --ServerApp.token="$JUPYTER_PASSWORD" --notebook-dir="$VOL" \
    > "$VOL/jupyter.log" 2>&1 &
fi

# --- launch ComfyUI ------------------------------------------------------------
AUTO_FLAGS="--preview-method auto"
# sage attention: enable only on pre-Blackwell GPUs (SageAttention 1.x has no
# sm_100/sm_120 kernels; Blackwell runs great on default SDPA)
if python3 -c "
import sys, torch, sageattention
cc = torch.cuda.get_device_capability()
sys.exit(0 if cc[0] < 10 else 1)" 2>/dev/null; then
  AUTO_FLAGS="$AUTO_FLAGS --use-sage-attention"
  echo "sageattention enabled (pre-Blackwell GPU)"
else
  echo "running with default SDPA attention (Blackwell GPU or sageattention unavailable)"
fi

cd "$COMFY"
echo "=== starting ComfyUI on :8188 ==="
exec python3 main.py --listen 0.0.0.0 --port 8188 ${COMFY_ARGS:-$AUTO_FLAGS}
