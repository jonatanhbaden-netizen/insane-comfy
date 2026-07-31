# ============================================================================
# INSANE COMFYUI SYSTEM — RunPod image
# Wan 2.2 (Fun-Control + I2V) video + Flux.1-dev img2img, A100 80GB primary
#
# Build:   docker build -t youruser/insane-comfy:1.0 -f docker/Dockerfile .
# Push:    docker push youruser/insane-comfy:1.0
#
# Models are NOT baked in — they live on the RunPod network volume
# (/workspace) and are fetched on first boot by /download_models.sh.
# ============================================================================

# CUDA 12.8 / torch 2.8 → runs on Blackwell (RTX PRO 6000, B200/B300),
# Hopper (H100/H200) and Ampere (A100) alike.
FROM runpod/pytorch:1.1.0-cu1281-torch280-ubuntu2204

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgl1 libglib2.0-0 aria2 curl build-essential python3-dev \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# ComfyUI core. COMFYUI_REF pins a release tag for reproducible builds —
# override at build time: --build-arg COMFYUI_REF=v0.x.y
# ---------------------------------------------------------------------------
ARG COMFYUI_REF=master
RUN git clone https://github.com/comfyanonymous/ComfyUI.git /ComfyUI \
    && cd /ComfyUI \
    && git checkout ${COMFYUI_REF} \
    && pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Custom nodes.
#   Manager          — node installs/updates from the UI
#   VideoHelperSuite — video load/combine
#   controlnet_aux   — DWPose, DepthAnythingV2 preprocessors
#   Frame-Interp     — RIFE 4.9
#   KJNodes + WanVideoWrapper — power-user Wan tooling (native nodes are the
#                      default in the shipped workflows; wrapper is optional)
#   Impact Pack/Subpack — FaceDetailer + YOLO face detection
#   UltimateSDUpscale — tiled refine upscale
#   PuLID-Flux-Enhanced — Flux identity adapter
#   rgthree          — QoL (progress, groups muting)
#
# Second block (RES4LYF onward) is what workflows/aiofm_i2i_qwen_zimage.json
# needs — ClownsharKSampler, SeedVR2, the post-processing chain, detailer
# helpers. Without these that workflow loads as a wall of red nodes.
# ---------------------------------------------------------------------------
RUN cd /ComfyUI/custom_nodes \
    && git clone https://github.com/ltdrdata/ComfyUI-Manager.git \
    && git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git \
    && git clone https://github.com/Fannovel16/comfyui_controlnet_aux.git \
    && git clone https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git \
    && git clone https://github.com/kijai/ComfyUI-KJNodes.git \
    && git clone https://github.com/kijai/ComfyUI-WanVideoWrapper.git \
    && git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git \
    && git clone https://github.com/ltdrdata/ComfyUI-Impact-Subpack.git \
    && git clone --recursive https://github.com/ssitu/ComfyUI_UltimateSDUpscale.git \
    && git clone https://github.com/sipie800/ComfyUI-PuLID-Flux-Enhanced.git \
    && git clone https://github.com/rgthree/rgthree-comfy.git \
    && git clone https://github.com/EllangoK/ComfyUI-post-processing-nodes.git \
    && git clone https://github.com/ClownsharkBatwing/RES4LYF.git \
    && git clone https://github.com/cubiq/ComfyUI_essentials.git \
    && git clone https://github.com/chrisgoringe/cg-use-everywhere.git \
    && git clone https://github.com/lquesada/ComfyUI-Inpaint-CropAndStitch.git \
    && git clone https://github.com/djbielejeski/a-person-mask-generator.git \
    && git clone https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler.git \
    && git clone https://github.com/erosDiffusion/ComfyUI-EulerDiscreteScheduler.git \
    && git clone https://github.com/PGCRT/CRT-Nodes.git \
    && git clone https://github.com/MONKEYFOREVER2/ComfyUI-CameraForensicRealism.git \
    && git clone https://github.com/MONKEYFOREVER2/comfyui-advanced-denoiser.git

RUN for d in /ComfyUI/custom_nodes/*/ ; do \
        if [ -f "${d}requirements.txt" ]; then \
            pip install -r "${d}requirements.txt" || echo "WARN: deps failed for ${d}"; \
        fi; \
    done

# insightface/facexlib → PuLID + DWPose. sageattention 1.x is Triton-based
# (no CUDA compile) and works on A100/H100; start.sh only enables the flag
# if the import succeeds.
RUN pip install \
        insightface==0.7.3 \
        onnxruntime-gpu \
        facexlib \
        timm \
        "huggingface_hub[cli,hf_transfer]" \
        sageattention==1.0.6

# SageAttention 2.x built from source with Blackwell (sm_120) kernels —
# quantized attention, big speedup on long video sequences, visually lossless.
# Guarded: if the build fails the image still ships (SDPA fallback on
# Blackwell; sage 1.0.6 above already covers Ampere/Hopper via Triton).
RUN pip install ninja packaging \
    && ( git clone --depth 1 https://github.com/thu-ml/SageAttention /tmp/sage \
         && cd /tmp/sage \
         && TORCH_CUDA_ARCH_LIST="12.0" MAX_JOBS=2 pip install --no-build-isolation . \
         || echo "WARN: SageAttention2 build failed — SDPA fallback on Blackwell" ) \
    && rm -rf /tmp/sage

# Build-time sanity check: the python that pip installs into must be able to
# import the core stack. Fails the CI build if the env is ever split again.
RUN PY=$(sed -n '1s/^#!//p' "$(command -v pip)") \
    && echo "pip's python: $PY" \
    && $PY -c "import torch, sqlalchemy, yaml, sageattention; print('env OK — torch', torch.__version__)"

COPY docker/extra_model_paths.yaml /ComfyUI/extra_model_paths.yaml
COPY scripts/download_models.sh /download_models.sh
COPY workflows /workflows
COPY docker/start.sh /start.sh
RUN chmod +x /start.sh /download_models.sh

EXPOSE 8188 8888

CMD ["/start.sh"]
