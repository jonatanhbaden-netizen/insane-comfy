# Talking-head prompt pipeline — automatic lipsync + audio-correlated motion

**Date:** 2026-08-01
**Target:** `workflows/aiofm_talking_ltx23.json`
**Status:** design approved, pending implementation plan

Node IDs below are the **subgraph-local** IDs inside `AIOFM Talking Head (LTX-2.3)`
(`98ee9e5b-467b-40aa-a534-36033f27d0b4`). In API-format exports the same node is
`340:NNN`.

## Problem

Three complaints, four root causes. All verified against the graph and against
`/object_info` on a live pod (`xhdpa8jf73tgqr`, 2200 node classes).

| Complaint | Root cause |
|---|---|
| "the prompt is weird" | `#306 CLIPTextEncode.text` is wired to `#342 TextGenerateLTX2Prompt` output. The `#319 Prompt` box feeds **only** Gemma. The operator never touches the real conditioning. |
| "the motion is weird" | `#342` runs `sampling_mode: on`, `temperature 0.7`, `top_k 64`, `top_p 0.95`. Identical inputs produce a **different prompt every run**, therefore different motion every run. |
| "I always have to tell it to lipsync" | Nothing preserves speaking intent through Gemma's rewrite. `#314` (negative) already contains `mouth out of sync` and `closed mouth while speaking`, but **both guiders run `cfg: 1.0`, which makes the negative inert**. That guard has never fired. |
| "motion should correlate with the audio" | No path exists from audio *content* to the prompt. Audio reaches the model only as a latent (`#332 → #328 → #327 → #326/#287`), which drives lipsync but carries no semantics to the motion side. |

Secondary: `#342 max_length` is set to `256`; the node default is `512`.

## Goals

1. Lipsync is **structural**, never dependent on operator prompt text.
2. Body motion and expression correlate **semantically** with what she is saying —
   gestures relate to content. Explicitly *not* beat-synced to timestamps (LTX
   conditions on one prompt for the whole clip; per-frame scheduling does not exist
   here without chunking, which reintroduces seams).
3. Same inputs produce the same prompt.
4. Operator edits exactly one text box: the look/scene description.

## Non-goals

- Sampler, sigma, resolution, LoRA, upscale and grain chains are untouched.
- The Telegram bot (`telegram-bot/`) is out of scope this pass.
- Timestamp-accurate gesture placement.

## Test 0 — RESOLVED 2026-08-01: audio input is ignored, ASR stage required

`TextGenerateLTX2Prompt` exposes an **optional `audio` input** (`["AUDIO", {}]`).
Tested on pod `xhdpa8jf73tgqr`: two `TextGenerateLTX2Prompt` nodes, identical
`clip`/`prompt`/`image`, `sampling_mode: off`, one with `audio` wired and one
without.

**Result: outputs were byte-for-byte identical.** The `audio` input has no effect —
consistent with Gemma 3 12B being a text+image model. The ASR stage is required
and the design below stands unchanged.

### Secondary finding — Gemma fabricates the speech, and choreographs to the fabrication

The same run transcribed the audio with Granite for ground truth:

| | Content |
|---|---|
| **Gemma's generated prompt** | *"The woman speaks in a confident, encouraging voice, **'Remember to engage your core throughout the entire exercise.'** As she says 'engage,' she gently presses her fingers into her lower abdomen, demonstrating the action… The subtle sound of **gym equipment** operating in the background…"* |
| **Actual audio (`emma_voice.wav`)** | *"okay so i have to tell you what happened this morning because honestly i still cannot believe it i was standing there completely frozen and then i just started laughing"* |

Gemma invented a fitness instructor: fabricated dialogue, fabricated location,
fabricated ambient audio — then **choreographed a specific hand gesture to a
specific invented word** (`presses her fingers into her lower abdomen` on
*"engage"*).

This is the mechanism behind "the motion is weird." The gestures were never
random; they were precisely timed to a script that does not exist. It also means
the `#455` locked clause alone would not have been sufficient — the transcript
must reach Gemma, or it will keep filling the vacuum with invention.

Run time 54 s including cold model loads. Granite ASR worked first attempt with
no tuning, and `sampling_mode: off` confirmed deterministic.

## Architecture

```
LoadImage #269 ─────────────────────────► #297 Resize ─► #294 ─► #334 Preprocess ─► (unchanged)
                                              │
LoadAudio #276 / RecordAudio #339 ─► #332 TrimAudioDuration
                                          ├──────────────► #328 LTXVAudioVAEEncode   (lipsync, unchanged)
                                          │
                                          └──► [NEW #451] ✏️ ASR Transcribe ──► transcript (STRING)
                                                    ▲
                                               [NEW #450] ⚙️ Granite ASR Engine

  [NEW #452] Director instruction (fixed STRING)  ┐
  transcript from #451                            ├─► [NEW #453/#454] StringConcatenate ×2
  [#319] LOOK block (operator-editable)           ┘                    │
                                                                       ▼
                                                        #342 TextGenerateLTX2Prompt
                                                          sampling_mode      = off
                                                          max_length         = 512
                                                          use_default_template = see §Risks
                                                          image = #297
                                                                       │ generated_text
  [NEW #455] 🔒 LOCKED SPEAKING CLAUSE (fixed STRING) ──────────────────┤
                                                                       ▼
                                    [NEW #456] StringConcatenate ──► #306 CLIPTextEncode
                                      string_a = LOCKED   ← first, dominates token weighting
                                      string_b = generated_text
                                      delimiter = " "
```

Two properties do the work:

- The locked clause is concatenated **downstream of Gemma**, so Gemma cannot
  rewrite or drop it. Lipsync stops being a thing the operator remembers to type.
- Gemma **digests** the transcript and is instructed to emit only performance
  language. The spoken words themselves never enter the conditioning, so there is
  no risk of LTX rendering the transcript as on-screen subtitles. This is the
  reason Gemma stays in the graph rather than being bypassed.

## New nodes

| ID | Class | Purpose |
|---|---|---|
| #450 | `GraniteASREngineNode` | `model_name: granite-speech-4.1-2b`, `device: auto`, `do_sample: false`, `asr_use_forced_aligner: true`. Deterministic. |
| #451 | `UnifiedASRTranscribeNode` | `engine ← #450`, `audio ← #332`, `language: English`, `task: transcribe`, `timestamps: none`. Output `text` only; `asr_timing_data` unused (goal 2 is semantic, not timed). |
| #452 | `PrimitiveStringMultiline` | Director instruction. Fixed. |
| #453, #454 | `StringConcatenate` | Assemble instruction + transcript + look block. |
| #455 | `PrimitiveStringMultiline` | Locked speaking clause. Titled `🔒 LOCKED — do not edit`. |
| #456 | `StringConcatenate` | Locked clause + Gemma output → `#306`. |

`StringConcatenate` emits `string_a + delimiter + string_b`. Exact wiring:

| Node | `string_a` | `string_b` | `delimiter` |
|---|---|---|---|
| #453 | #452 instruction | #451 `text` | `\n\nTRANSCRIPT:\n` |
| #454 | #453 | #319 look block | `\n\nSETTING:\n` |
| #456 | #455 locked clause | #342 `generated_text` | ` ` (single space) |

`#454` → `#342.prompt`. `#456` → `#306.text`.

New node IDs 450–456 are free: the graph's `last_node_id` is 422.

`StringConcatenate` is comfy-core (`string_a`, `string_b`, `delimiter`).
Granite and the ASR node come from `TTS-Audio-Suite`, already cloned in
`docker/Dockerfile:75`. **No new dependencies.**

## Text content

**#455 — locked speaking clause** (concatenated first, post-Gemma, not editable):

> She is speaking directly into the camera the entire time. Her lips, jaw and
> tongue move in precise synchronisation with every word of the spoken audio,
> mouth clearly articulating each syllable as she forms the words. Her mouth is
> never closed or still while she speaks.

**#452 — director instruction** (pre-Gemma, fixed):

> You are writing a video prompt. Below is a transcript of what the woman in the
> image is saying, followed by a description of the setting. Write ONE paragraph
> of at most 90 words describing only her physical performance while she says
> these words: hand gestures, facial expression, head movement and posture, and
> how they shift as her meaning shifts. Choose gestures that fit the meaning of
> what she is saying. Do not quote or write any of her words. Do not mention
> text, captions, subtitles or writing of any kind. Do not describe the setting,
> lighting or her clothing. Output only the paragraph.

**#319 — look block** (the only operator-editable box). Retitle to
`LOOK — scene / character / camera (edit this)`. Existing scene/character/camera
template content stays; the performance and lipsync sentences currently in it are
removed, since #452 and #455 now own that.

## Risks and open questions

**`use_default_template` — RESOLVED: it is a no-op.** A/B tested on the pod:
`True` and `False` with identical director text produced **byte-identical**
output. The lever is the director text itself. A stricter closing paragraph
("ONE paragraph, ≤90 words, output only the paragraph, never quote her words")
eliminated quoted dialogue, cut 132→81 words, and flipped the style tag from
`cinematic` to `handheld`. That strict text is what shipped in #452; the
template flag stays at its default `True`.

**VRAM.** Granite 2B (~4 GB) loads alongside LTX-22B-fp8 (~24 GB) and
Gemma-12B-fp8 (~13 GB). Comfortable on the 96 GB RTX PRO 6000 Blackwell; would
need revisiting on a smaller card.

**Transcript quality.** Raw Granite output is unpunctuated. If Gemma reads intent
poorly, insert `ASRPunctuationTruecaseNode` (English Fullstop + Truecase, ~210 MB)
between #451 and #453. Deferred until observed necessary.

## Testing

Fix both `RandomNoise` seeds (`#285`, `#286`) to a constant for the whole test
pass, otherwise prompt changes and noise changes are confounded.

1. **Determinism** — run the same inputs twice with `sampling_mode: off`. `#343
   PreviewAny` must show identical text both times.
2. **Lipsync is unconditional** — empty the #319 look block entirely. Mouth must
   still track the audio.
3. **Semantic correlation** — two clips, same portrait and same look block, two
   audio files with clearly different content (e.g. an excited list of three
   things vs. a quiet confession). `#343` must show visibly different gesture
   descriptions, and the rendered motion must differ accordingly.
4. **No subtitle leakage** — confirm no rendered text appears, and that `#343`
   contains none of her literal words.

## Out of scope, recorded

- **Graph drift:** `#400` Character LoRA is **bypassed** in this repo's UI graph,
  but **live at `strength_model: 0.4`** with `LTXfischerLora_000000750.safetensors`
  in `telegram-bot/workflows_api/talking.json`. The two have diverged. Not touched
  here; flagged so it is not mistaken for a regression later.
- **Inert negative prompt:** `#314` is retitled to note it is inert at cfg 1.0.
  The string is left intact — it costs nothing and becomes live if cfg ever moves
  off 1.0, which the distilled model does not currently allow.
- `#294 ResizeImagesByLongerEdge` is marked DEPRECATED and re-scales the already
  correctly-sized reference to an off-grid 870×1536. Real, separate, untouched here.
- Frame-count grid (`fps × duration + 1` must land on 8n+1) and the 20 s OOM
  ceiling. Separate issue, bot-side.
