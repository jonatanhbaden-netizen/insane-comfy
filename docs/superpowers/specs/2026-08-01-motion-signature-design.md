# Motion signature — her typical motion, learned once

**Date:** 2026-08-01 · **Status:** implemented same day
**Target:** `workflows/aiofm_talking_ltx23.json` node `#452` (director instruction)

## Decision

User has 6 reference clips (`motion-refs/ref01–06.mp4`, another AI character,
car-seat talking-head format) showing a consistent motion style, and wants every
generated Emma clip to move that way — style learned once, no per-run work.

Chosen approach: **motion signature as text**, distilled by frame-strip analysis
of the corpus and baked into the director instruction as a required movement
vocabulary. Rejected: motion LoRA (identity-leak risk from the other character,
training cost, LoRA-stack ceiling ~2.0 — revisit only if the text ceiling
disappoints); per-run video into Gemma's `video` input (1 FPS sampling too
coarse, per-run work, appearance-leak risk).

## Observed signature (source of truth for the #452 block)

From 8-frame strips of all six clips + one 2 fps dense strip (ref01):

- Head never still: micro-tilts, slow side-to-side rolls, chin dips with an
  up-through-lashes look, glances away and back — every ~0.5 s.
- Face is the primary instrument: big smiles → laughs (head tips back), playful
  pouts between phrases, eyes widen on emphasis, close briefly on savored words,
  roll up while recalling.
- Hands are rare accents: ~2 appearances per 6 s, <1 s each (finger point, palm
  to chest, finger-counting), then out of frame. Both-hands-to-head only for big
  mock-exasperation beats.
- Posture: settled into the seat, subtle shoulder shimmy on sassy lines, small
  lean toward camera to confide.
- Chest has soft natural weight — visible gentle bounce carried by every laugh,
  shimmy and lean (explicit user requirement).
- Camera in refs is propped-static, not handheld → LOOK camera line switched to
  propped-static (reversible per clip).

## Constraints honored

- Movement vocabulary only — **zero appearance words** from the reference
  character may enter the signature (identity must not leak).
- Signature lives **pre-Gemma** (director #452): it shapes choreography, while
  meaning-placement still comes from the transcript. Locked lipsync/identity
  block (#455) untouched.
- Retuning = re-derive from a refreshed corpus, replace the whole block.

## Verification

Unrendered as of writing (pod reclaimed by user for i2i). Test on next render:
read `#458` FINAL PROMPT — Gemma's paragraph should choreograph transcript
content using signature vocabulary (tilts/pouts/rare hand accents), not generic
gestures, and contain no appearance words for the reference character.
