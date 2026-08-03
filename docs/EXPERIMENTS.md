# i2i quality loop — experiment queue

Standing mandate: skin real under 200% zoom AND identity fidelity, advancing
together. One change per cycle, measured on the fixed five-reference yardstick
(`scripts/i2i_test_harness.py`), accepted only on clear net gain on both axes.
Ranked by expected joint gain / GPU cost. Sourced from the 2026-08-03 four-lens
research sweep (all availability links fetched and verified live that day).

## How a cycle runs
1. `i2i_test_harness.py --pod <id> --workflow <ui.json> --object-info <oi> --tag <name> [--set node.inputs.key=val]`
2. Identity: `score_identity.py` on the pod (ArcFace vs character bank; bar =
   intra-set p05). Skin/boundary: `zoom_sheet.py` sheets (FACE/EYES 2×,
   JAW+HAIRLINE strips 2×, cheek SKIN 3×), judged against the previous accepted run.
3. Accept → t