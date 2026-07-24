#!/usr/bin/env bash
# ============================================================================
# Registers the "insane-comfy" pod template on RunPod via API.
#
# Needs a real RunPod API key (console.runpod.io → Settings → API Keys).
# Provide it either way:
#   RUNPOD_API_KEY=rpa_xxx bash scripts/create_runpod_template.sh
# or save it for runpodctl first (then no env var needed):
#   runpodctl config --apiKey rpa_xxx
#
# Override the image with IMAGE=... (default: ghcr.io build from this repo).
# ============================================================================
set -euo pipefail

IMAGE="${IMAGE:-ghcr.io/jonatanhbaden-netizen/insane-comfy:1.0}"
NAME="${NAME:-insane-comfy}"

KEY="${RUNPOD_API_KEY:-}"
if [ -z "$KEY" ] && [ -f "$HOME/.runpod/config.toml" ]; then
  KEY=$(grep -m1 -o "apikey *= *['\"][^'\"]*['\"]" "$HOME/.runpod/config.toml" \
        | sed "s/.*['\"]\(.*\)['\"]/\1/")
fi
if [ -z "$KEY" ] || [ "${#KEY}" -lt 20 ]; then
  echo "No valid RunPod API key found (env RUNPOD_API_KEY or ~/.runpod/config.toml)."
  echo "Create one at console.runpod.io → Settings → API Keys."
  exit 1
fi

echo "Creating template '$NAME' → $IMAGE"

# --- try REST v1 first -------------------------------------------------------
HTTP=$(curl -s -o /tmp/rp_tpl_resp.json -w "%{http_code}" \
  -X POST https://rest.runpod.io/v1/templates \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d @- <<JSON
{
  "name": "$NAME",
  "imageName": "$IMAGE",
  "ports": ["8188/http", "8888/http"],
  "containerDiskInGb": 30,
  "volumeInGb": 0,
  "volumeMountPath": "/workspace",
  "env": { "DOWNLOAD_MODELS": "true", "WITH_REDUX": "false" },
  "isServerless": false
}
JSON
)
if [ "$HTTP" = "200" ] || [ "$HTTP" = "201" ]; then
  echo "REST OK:"; cat /tmp/rp_tpl_resp.json; echo; exit 0
fi
echo "REST returned HTTP $HTTP — falling back to GraphQL"
cat /tmp/rp_tpl_resp.json 2>/dev/null; echo

# --- GraphQL fallback ---------------------------------------------------------
curl -s -X POST "https://api.runpod.io/graphql?api_key=$KEY" \
  -H "Content-Type: application/json" \
  -d @- <<JSON
{"query": "mutation { saveTemplate(input: { name: \"$NAME\", imageName: \"$IMAGE\", dockerArgs: \"\", containerDiskInGb: 30, volumeInGb: 0, volumeMountPath: \"/workspace\", ports: \"8188/http,8888/http\", env: [ { key: \"DOWNLOAD_MODELS\", value: \"true\" }, { key: \"WITH_REDUX\", value: \"false\" } ], isServerless: false, readme: \"INSANE ComfyUI — Wan 2.2 motion control + Flux img2img. Attach a 200GB network volume at /workspace. First boot downloads ~95GB of models.\" }) { id name imageName } }"}
JSON
echo
