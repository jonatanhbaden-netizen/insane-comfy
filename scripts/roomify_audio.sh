#!/usr/bin/env bash
# ============================================================================
# roomify_audio.sh — make studio-dry TTS sound like it was recorded on a phone
# in a real place.
#
#   ./roomify_audio.sh <input.mp3|wav> <preset> [output.wav]
#
# Presets: car | bedroom | kitchen | bathroom | outdoor | office
#
# Three things get added, because all three are missing from TTS:
#   1. Early reflections / reverb  — the room itself
#   2. Ambience bed                — traffic, room tone, air
#   3. Phone-mic character         — band-limit, compression, tiny saturation
#
# Real phone recordings have all three. TTS has none, which is why clean
# synthetic speech over a car interior reads as dubbed.
# ============================================================================
set -euo pipefail

IN="${1:?usage: roomify_audio.sh <input> <preset> [output]}"
PRESET="${2:?pick a preset: car bedroom kitchen bathroom outdoor office}"
OUT="${3:-}"
[ -z "$OUT" ] && OUT="${IN%.*}_${PRESET}.wav"

# --- per-preset room + ambience ---------------------------------------------
# REV   : aecho <in_gain>:<out_gain>:<delays ms>:<decays>  — early reflections
# TONE  : EQ shaping for the space
# AMB   : synthesised ambience bed (noise shaped to suit the room)
# AMBVOL: how loud the bed sits under the voice
case "$PRESET" in
  car)
    REV="aecho=0.85:0.75:11|19|29:0.35|0.24|0.15"
    TONE="equalizer=f=250:t=q:w=1.1:g=3,equalizer=f=5000:t=q:w=2:g=-3"
    AMB="anoisesrc=c=brown:a=0.5,lowpass=f=280,volume=2.2"
    AMBVOL="0.42" ;;
  bedroom)
    REV="aecho=0.85:0.8:17|31|52:0.4|0.28|0.18"
    TONE="equalizer=f=4000:t=q:w=2:g=-2"
    AMB="anoisesrc=c=pink:a=0.25,lowpass=f=850,volume=1.2"
    AMBVOL="0.16" ;;
  kitchen)
    REV="aecho=0.85:0.82:24|45|68|95:0.45|0.32|0.22|0.14"
    TONE="equalizer=f=2600:t=q:w=1.6:g=3"
    AMB="anoisesrc=c=pink:a=0.3,lowpass=f=1300,volume=1.3"
    AMBVOL="0.20" ;;
  bathroom)
    REV="aecho=0.85:0.88:32|58|89|126|170:0.55|0.42|0.32|0.24|0.16"
    TONE="equalizer=f=3200:t=q:w=2:g=4"
    AMB="anoisesrc=c=pink:a=0.15,lowpass=f=1000,volume=0.9"
    AMBVOL="0.12" ;;
  outdoor)
    REV="aecho=0.9:0.6:8:0.12"
    TONE="anull"
    AMB="anoisesrc=c=brown:a=0.55,lowpass=f=1600,highpass=f=100,volume=2.0"
    AMBVOL="0.50" ;;
  office)
    REV="aecho=0.85:0.78:19|36|58:0.38|0.26|0.17"
    TONE="anull"
    AMB="anoisesrc=c=pink:a=0.28,lowpass=f=1150,volume=1.2"
    AMBVOL="0.18" ;;
  *) echo "unknown preset: $PRESET"; exit 1 ;;
esac

# --- phone mic character -----------------------------------------------------
# Phone mics compress hard and roll off both ends. Skipping this is the main
# reason "reverb added" still sounds like studio audio in a room.
PHONE="acompressor=threshold=-24dB:ratio=6:attack=5:release=120:makeup=4,aexciter=level_in=1:level_out=1:amount=1.2:drive=4,alimiter=limit=0.95"

DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$IN")

# Filter order matters. The phone-mic band-limit must be applied LAST, after the
# ambience mix — otherwise reverb tails, the exciter and the noise bed re-introduce
# the exact frequencies the phone mic is supposed to have removed, and the result
# still sounds like a studio recording with reverb on it.
BANDLIMIT="highpass=f=170,lowpass=f=7800"

ffmpeg -y -loglevel error \
  -i "$IN" \
  -f lavfi -t "$DUR" -i "$AMB" \
  -filter_complex "\
     [0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=mono,\
          ${TONE},${REV},${PHONE}[voice];\
     [1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=mono,\
          volume=${AMBVOL}[amb];\
     [voice][amb]amix=inputs=2:duration=first:dropout_transition=0:weights='1 1',\
          ${BANDLIMIT},loudnorm=I=-16:TP=-1.5:LRA=11[out]" \
  -map "[out]" -ac 1 -ar 48000 -c:a pcm_s16le "$OUT"

echo "  wrote $OUT"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT" | xargs printf "  duration: %.2fs\n"
ffmpeg -hide_banner -nostats -i "$OUT" -af volumedetect -f null /dev/null 2>&1 \
  | grep -E "mean_volume|max_volume" | sed 's/^/  /'
