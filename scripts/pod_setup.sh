#!/usr/bin/env bash
# ============================================================================
# NO-DOCKER SETUP — run this inside a plain RunPod PyTorch pod instead of
# building/pushing the custom image.
#
# Pod template: official "RunPod Pytorch 2.4.0"
#   (image runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04 —
#    the exact base image docker/Dockerfile uses)
# Requirements: network volume mounted at /workspace, HTTP port 8188 exposed.
#
# Usage:
#   1. Open the pod's Jupyter (:8888) → upload this file and
#      download_models.sh into /workspace
#   2. In a terminal:  bash /workspace/pod_setup.sh
#   3. Start ComfyUI:  bash /workspace/run_comfy.sh
#
# ComfyUI + custom nodes install into /workspace/ComfyUI → they PERSIST on
# the volume. Only the pip packages live in the container, so on a brand-new
# pod just re-run this script (~3–5 min; clones and models are skipped).
# ============================================================================
set -uo pipefail

VOL=/workspace
COMFY=$VOL/ComfyUI

echo "=== [1/5] system packages ==="
apt-get update -qq && apt-get install -y -qq ffmpeg libgl1 libglib2.0-0 aria2 || true

echo "=== [2/5] ComfyUI + custom nodes (into $COMFY, persistent) ==="
if [ ! -d "$COMFY" ]; then
  git clone https://github.com/comfyanonymous/ComfyUI.git "$COMFY"
fi
pip install -q -r "$COMFY/requirements.txt"

mkdir -p "$COMFY/custom_nodes"
cd "$COMFY/custom_nodes"
for repo in \
  https://github.com/ltdrdata/ComfyUI-Manager \
  https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite \
  https://github.com/Fannovel16/comfyui_controlnet_aux \
  https://github.com/Fannovel16/ComfyUI-Frame-Interpolation \
  https://github.com/kijai/ComfyUI-KJNodes \
  https://github.com/kijai/ComfyUI-WanVideoWrapper \
  https://github.com/ltdrdata/ComfyUI-Impact-Pack \
  https://github.com/ltdrdata/ComfyUI-Impact-Subpack \
  https://github.com/ssitu/ComfyUI_UltimateSDUpscale \
  https://github.com/sipie800/ComfyUI-PuLID-Flux-Enhanced \
  https://github.com/rgthree/rgthree-comfy ; do
  name=$(basename "$repo")
  [ -d "$name" ] || git clone --recursive "$repo"
done

echo "=== [3/5] python deps ==="
for d in "$COMFY"/custom_nodes/*/ ; do
  [ -f "${d}requirements.txt" ] && pip install -q -r "${d}requirements.txt" || true
done
pip install -q insightface==0.7.3 onnxruntime-gpu facexlib timm \
  "huggingface_hub[cli,hf_transfer]" sageattention==1.0.6 || true

echo "=== [4/5] model paths + launcher ==="
mkdir -p "$VOL/models" "$VOL/.cache/huggingface"
cat > "$COMFY/extra_model_paths.yaml" <<'YAML'
runpod_volume:
  base_path: /workspace/models
  is_default: true
  checkpoints: checkpoints
  diffusion_models: |
    diffusion_models
    unet
  text_encoders: |
    text_encoders
    clip
  vae: vae
  loras: loras
  controlnet: controlnet
  clip_vision: clip_vision
  style_models: style_models
  upscale_models: upscale_models
  embeddings: embeddings
  pulid: pulid
  insightface: insightface
  ultralytics: ultralytics
  ultralytics_bbox: ultralytics/bbox
  ultralytics_segm: ultralytics/segm
  sams: sams
YAML

cat > "$VOL/run_comfy.sh" <<'EOF'
#!/usr/bin/env bash
export HF_HOME=/workspace/.cache/huggingface
export HF_HUB_ENABLE_HF_TRANSFER=1
FLAGS="--listen 0.0.0.0 --port 8188 --preview-method auto"
python3 -c "import sageattention" 2>/dev/null && FLAGS="$FLAGS --use-sage-attention"
cd /workspace/ComfyUI
exec python3 main.py $FLAGS
EOF
chmod +x "$VOL/run_comfy.sh"

echo "=== [5/5] models ==="
if [ -f "$VOL/download_models.sh" ]; then
  MODELS_DIR="$VOL/models" bash "$VOL/download_models.sh"
else
  echo "NOTE: /workspace/download_models.sh not found — upload it via Jupyter"
  echo "      and run:  MODELS_DIR=/workspace/models bash /workspace/download_models.sh"
fi

echo ""
echo "=========================================================="
echo " Setup complete. Start ComfyUI with:"
echo "   bash /workspace/run_comfy.sh"
echo " Then open the pod's port-8188 proxy URL."
echo " Load workflows by dragging the two JSON files from your"
echo " Mac straight into the ComfyUI browser tab."
echo "=========================================================="
