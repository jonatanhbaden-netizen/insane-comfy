#!/usr/bin/env bash
# Reassemble split-uploaded LoRA parts on the pod (run via pod_exec.py).
#
# Parts are uploaded through ComfyUI's /upload/image (100MB request cap) into
# /workspace/input/loraxfer/ as <name>.part_aa, <name>.part_ab, ...
# The manifest below pins the sha256 of each ORIGINAL file; a reassembled file
# that does not match is deleted, never installed.
set -uo pipefail
SRC=/workspace/input/loraxfer
DST=/workspace/models/loras
declare -A SHA=(
  ["Emm4-zit_000001000"]="4828740f9a8d732a4ab00dea872ffc5714caa1f6566b11b243d8a8ae2f367b4e"
  ["Emm4-zit_000001100"]="fcec80869984532391a8ad125377fc86e2ef7b7ac17561b3eda10b985090c37a"
  ["Emm4-zit_000001200"]="1fb5fdd21baa45a2edc0b5cf2d61641ff9b6ad8624ff1493952bce457ac8d36b"
  ["Emm4-sund3-zit_000001200"]="1f81754ee084d3649702bfe26461961a0a9e4977ea97a10b63de24f37ddf7ae8"
  ["Emm4-zit_000002000"]="5b717a5cc4c27252dc5a283e7bfa2c4ba799c3574b19526ad3a1f39811d9b596"
  ["Emm4-zit_000002250"]="721d4857b03276108d170d21dcf9ed73c970809a9f6083ab5508b5f3bd2b811c"
)
mkdir -p "$DST"
for name in "${!SHA[@]}"; do
  if [ -f "$DST/$name.safetensors" ]; then
    have=$(sha256sum "$DST/$name.safetensors" | cut -d' ' -f1)
    [ "$have" = "${SHA[$name]}" ] && { echo "OK (already installed): $name"; continue; }
  fi
  parts=$(ls "$SRC/$name".part_* 2>/dev/null | sort)
  [ -z "$parts" ] && { echo "MISSING PARTS: $name"; continue; }
  cat $parts > "/tmp/$name.safetensors"
  have=$(sha256sum "/tmp/$name.safetensors" | cut -d' ' -f1)
  if [ "$have" = "${SHA[$name]}" ]; then
    mv "/tmp/$name.safetensors" "$DST/$name.safetensors"
    echo "INSTALLED: $name"
  else
    rm -f "/tmp/$name.safetensors"
    echo "SHA MISMATCH (parts corrupt/incomplete): $name"
  fi
done
