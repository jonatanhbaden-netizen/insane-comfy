#!/usr/bin/env python3
"""Assemble a complete LTX-2.3 talking-head prompt from a saved preset.

The point: stop hand-writing prompts. Pick a motion preset that already works,
name a scene, point at your audio. Beat timings are stored as fractions of clip
length, so the same preset scales to a 5s or a 15s clip automatically.

    python3 build_prompt.py --preset talking_about_outfit --scene car_passenger \
                            --audio ~/Downloads/voice.mp3

    python3 build_prompt.py --list          # show available presets and scenes
"""
import argparse, json, os, subprocess, sys, textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "action_presets.json")

# Fixed opening. Carries the trigger word and the skin-texture request, which has
# to be POSITIVE because CFG is 1.0 and the negative prompt is inert.
HEAD = (
    "{trigger}, she is talking directly to the camera, mid-sentence, natural "
    "conversational rhythm. Her eyebrows lift slightly on the stressed words. She "
    "blinks naturally and her shoulders shift subtly as she breathes and speaks. "
    "Visible skin pores and fine facial texture, faint freckles across her nose and "
    "cheeks, slight natural redness around the nostrils, fine peach fuzz catching the "
    "light, unretouched skin, subtle uneven skin tone."
)
CAMERA = ("handheld front-facing phone camera held at arm's length, slight natural "
          "sway, chest-up framing")


def audio_duration(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, check=True).stdout.strip()
        return float(out)
    except Exception:
        return None


def build_action(beats, dur):
    """Turn fractional beats into a timed sentence the model can follow.

    Absolute time cues ("around 2 seconds in") steer LTX noticeably better than
    vague ordering ("then she..."), which is the whole reason for storing fractions.
    """
    parts = []
    for frac, text in beats:
        t = frac * dur
        if frac == 0.0:
            parts.append(f"she begins with {text}")
        elif t < 1.0:
            parts.append(f"almost immediately {text}")
        else:
            parts.append(f"around {t:.1f} seconds in {text}")
    return "; ".join(parts)


def main():
    lib = json.load(open(LIB))
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset")
    ap.add_argument("--scene")
    ap.add_argument("--audio", help="used only to read the duration")
    ap.add_argument("--duration", type=float, help="override, in seconds")
    ap.add_argument("--trigger", default="f1scher")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list or not (a.preset and a.scene):
        print("\nPRESETS")
        for k, v in lib["presets"].items():
            print(f"  {k:24s} {v['use_for']}")
        print("\nSCENES")
        for k in lib["scenes"]:
            print(f"  {k}")
        print("\nexample:")
        print("  python3 build_prompt.py --preset excited_news --scene bedroom "
              "--audio voice.mp3\n")
        return 0

    if a.preset not in lib["presets"]:
        print(f"unknown preset '{a.preset}' — run --list"); return 1
    if a.scene not in lib["scenes"]:
        print(f"unknown scene '{a.scene}' — run --list"); return 1

    dur = a.duration or (audio_duration(a.audio) if a.audio else None)
    if dur is None:
        print("need --audio or --duration"); return 1

    beats = lib["presets"][a.preset]["beats"]
    prompt = "\n\n".join([
        HEAD.format(trigger=a.trigger),
        f"scene: {lib['scenes'][a.scene]}",
        f"action: {build_action(beats, dur)}",
        f"camera: {CAMERA}",
        f"audio: her voice speaking clearly, {lib['ambience'].get(a.scene, 'faint room tone')}",
    ])

    print("=" * 72)
    print(prompt)
    print("=" * 72)
    print(f"\n  duration : {dur:.2f}s   -> set the workflow's `duration` to {dur:.1f}")
    print(f"  frames   : {int(round(24*dur))+1}  (fps 24)")
    print(f"  preset   : {a.preset}  ({lib['presets'][a.preset]['use_for']})")
    print("\n  Copy the block above into the prompt box on the AIOFM Talking Head node.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
