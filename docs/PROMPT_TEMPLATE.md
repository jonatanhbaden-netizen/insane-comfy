# Prompt template — paste this, edit two lines

Paste the whole thing into the prompt box on the `AIOFM Talking Head` node.
Everything outside the **EDIT** block stays identical every single run.

---

## The template

```
f1scher, she is talking directly to the camera, mid-sentence, natural conversational
rhythm. Her eyebrows lift slightly on the stressed words. She blinks naturally and her
shoulders shift subtly as she breathes and speaks. Visible skin pores and fine facial
texture, faint freckles across her nose and cheeks, slight natural redness around the
nostrils, fine peach fuzz catching the light, unretouched skin, subtle uneven skin tone.

>>> EDIT BELOW <<<

scene: SETTING GOES HERE
action: ACTION GOES HERE
>>> EDIT ABOVE <<<

camera: handheld front-facing phone camera held at arm's length, slight natural sway,
chest-up framing
audio: her voice speaking clearly, faint room tone
```

Two lines change per video. Everything else is fixed.

---

## Why each fixed part is there

| Part | Reason |
|---|---|
| `f1scher` first | Trigger word — activates the character LoRA. Without it the LoRA barely fires |
| Skin texture sentence | **CFG is 1.0, so the negative prompt does nothing.** Realistic skin must be requested in the positive prompt or you get the airbrushed look |
| No face description | The LoRA carries her face. Describing it competes with the LoRA and causes drift |
| Camera line | "Handheld phone at arm's length" is what makes it read as phone footage rather than a film shot |
| Blink / breathe / eyebrow | Micro-motion. Without it faces go waxy and still between mouth movements |

**Never add:** `smooth skin`, `flawless`, `perfect`, `beautiful`, `glowing`, `cinematic`,
`film still`, `8k`, `masterpiece`. Every one of those pulls toward the polished CGI look.

---

## Writing the `action:` line

Three rules, in order of impact.

**1. Give a start, a move, and an end.** "Small hand gesture" gives the model nowhere to
go, so it does nothing. Say where the hand begins, what it does, where it ends up.

**2. Anchor it in time** — `within the first second`, `midway through`, `near the end`.
This spreads motion across the clip instead of averaging into one static pose.

**3. Name a real gesture** rather than describing motion abstractly.

### Copy-paste actions

```
action: she starts with both hands in her lap, lifts her right hand to shoulder height
        and turns the palm up as she makes a point midway through, then lowers it back down
```
```
action: within the first second she brushes her hair behind her ear, then rests that hand
        on her thigh, breaking into a short genuine laugh near the end
```
```
action: she counts on her fingers as she lists things, holding her hand up near her chest,
        tilting her head to one side between points
```
```
action: she turns her palm upward and moves her hand in small circles as she explains,
        bringing it to her chest when she laughs midway through
```
```
action: she gestures toward the camera with an open hand near the start, then folds her
        arms loosely, glancing away briefly and back
```

### Scene lines

```
scene: sitting in the driver's seat of a parked car, soft overcast daylight through
       the windscreen, blurred street behind her
```
```
scene: sitting on the edge of a bed in a bright bedroom, soft window light from the left,
       white duvet and a plant visible behind her
```
```
scene: standing in a kitchen leaning against the counter, warm afternoon light,
       out-of-focus cupboards behind her
```

---

## The reference image decides what can move

If her hand is planted somewhere prominent in the reference photo, it tends to **stay
there** no matter what the action line says — image conditioning beats text on anything
spatial. That is what froze her arm in earlier runs.

**For gesture-heavy clips, pick reference photos where her hands are low, relaxed, or out
of frame.** Or crop the reference chest-up so there's no hand to freeze.

---

## If it still looks too clean

In order of impact:

1. **Bypass `Skin / pore detail restore`** (Ctrl+B). It is a *contrast* model — it browns
   skin and hardens teeth. Often better off.
2. **`FilmGrain` intensity 0.045 → 0.06–0.07.** Sensor noise is a large part of why phone
   footage reads as real.
3. **Stage-1 `LTXVImgToVideoInplace` 0.7 → 0.6** for more motion, `→ 0.8` to hold identity.
4. Do **not** raise CFG to make the negative prompt work. The model is distilled and
   expects 1.0; raising it degrades output.

---

## Note on the prompt enhancer

Your prompt passes through `Generate LTX2 Prompt` (Gemma 3 12B) before reaching the model.
Check the `Preview as Text` node after a run and confirm two things survived:

- the trigger word **`f1scher`** is still present
- it has **not** prepended `Style: realistic — cinematic`

If either fails, set `use_default_template` to **false** on that node so only your text
reaches the model.
