# Make a talking video — quickstart

Five minutes, no theory. Deep reference lives in [TALKING_HEAD.md](TALKING_HEAD.md).

## What you need

| | |
|---|---|
| **1 photo** | Emma, frontal, face big in frame, 1088×1920 |
| **1 audio file** | her voice speaking, WAV, mono, 48 kHz |
| **1 prompt** | what she does while talking |

That's it. No driving video.

## Steps

**1. Open ComfyUI** at `https://<pod-id>-8188.proxy.runpod.net`

**2. Load the workflow** — Workflows → Browse → `aiofm_talking_ltx23`

**3. Drop in your photo** — click the `LoadImage` node, upload. Use a frontal shot
where her face fills a good chunk of the frame. Full-body mirror selfies work badly
here — the face ends up too small to hold detail.

**4. Drop in your audio** — click `LoadAudio`, upload your WAV.

**5. Set the length** — `duration` must be **≥ the length of your audio**, or the
speech gets cut off mid-sentence. 5 s to start. Frames are calculated for you.

**6. Write the prompt.** Fill the template — keep the section labels:

```
She is talking directly to the camera, mid-sentence, natural conversational rhythm.
Her eyebrows lift slightly on the stressed words and she breaks into a short genuine
laugh partway through, tilting her head a little to one side. She blinks naturally.
One hand comes up briefly to gesture near her chest, then settles again.

scene:      sitting in the driver's seat of a parked car, soft overcast daylight
character:  young woman, long blonde hair, small gold necklace, green top
action:     talking to camera, natural laughter mid-sentence, small hand gesture
camera:     handheld front-facing phone camera at arm's length, slight natural sway
audio:      her voice speaking clearly, faint room tone
```

**7. Queue.** First run of a session loads 29 GB of model — slow. After that it's cached.

## The three dials you'll actually touch

| Want | Change |
|---|---|
| Her face drifting off-model | stage-1 `LTXVImgToVideoInplace` **0.7 → 0.8** |
| Too stiff / posed / barely moves | stage-1 `LTXVImgToVideoInplace` **0.7 → 0.6** |
| Too clean, looks rendered | `FilmGrain` intensity **0.045 → 0.06** |

Change **one at a time**, keep the seed fixed, or you won't know what did what.

## Writing prompts that work

**Do** describe things happening in time:
- `she breaks into a short genuine laugh partway through`
- `her eyebrows lift slightly on the stressed words`
- `one hand comes up briefly to gesture, then settles`
- `she blinks naturally`, `slight head turns`

**Don't** use photography words — they pull toward the polished look you don't want:
- ~~`cinematic`~~ ~~`film still`~~ ~~`professional lighting`~~ ~~`8k`~~ ~~`masterpiece`~~

For the phone look, describe the **camera operator**, not the grade:
`handheld front-facing phone camera held at arm's length, slight natural sway`.

## Gotchas

- **CFG is 1.0 on purpose.** The negative prompt does nothing at CFG 1.0 — that's how
  distilled models work. Put what you want in the **positive** prompt. Don't raise CFG.
- **Audio longer than `duration` gets trimmed**, and lipsync will look like it drifts.
  Match them.
- **Both LoRA slots ship bypassed.** Leave them until you have a trained LTX-2.3 LoRA.
  Your Wan `F1scher` LoRA will not load here — wrong architecture.
- **Don't stack speed LoRAs.** The distill LoRA at 0.5 is already there. Adding more is
  exactly what wrecked the `Jack-b1` workflow.

## You still need a real voice

The `emma_voice.wav` in `test-assets/` is macOS text-to-speech. It proves the lipsync
plumbing works; it is **not** shippable audio — it sounds robotic.

For real clips, pick one:

| Option | Norwegian? | Notes |
|---|---|---|
| **ElevenLabs** | yes | Paid API, fastest path to good audio today |
| **Fish Audio S2-Pro** | unconfirmed | 80+ languages claimed, Norwegian not in the confirmed-strong list; runs locally |
| **Record a real voice** | yes | A person reading the script. Best quality, least scalable |

Norwegian is the weak spot across every open TTS I checked — XTTS-v2 and CosyVoice
don't support it at all. Test `emma_voice_no.wav` early to see how the model handles
Norwegian phonemes before committing to a TTS vendor.
