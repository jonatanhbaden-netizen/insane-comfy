# pre-loop observed baseline (IMG_2330 only)

Measured from renders this session produced before the harness existed.
Not a substitute for a real five-reference v6 baseline — it exists so the
first GPU cycle has something to beat.

| render | skin_hf | grain | seam | dE | sharp |
|---|---|---|---|---|---|
| v5 full chain incl. POST | 1.4879 | 3.368 | 4.1534 | 2.215 | 443.7 |
| v5 chain, POST bypassed | 1.224 | 1.5346 | -1.3949 | 8.918 | 365.6 |
| v4.3 face-detailer output only | 0.8063 | 1.0952 | 1.1476 | 23.486 | 176.89 |

**Read:** POST processing is measurably the worst on every axis (hf 1.49 over-detailed, grain 3.37, seam 4.15) — bypassing it was correct. Whole-frame renders sit at seam ≈ -1 to -2, which calibrates the target for v6's composite boundary: **seam_gradient ≤ 0 = invisible**. Two quantified open defects: grain_ratio ~1.5 (generated face carries more noise than the host photo) and face_neck_dE ~9 (insert lighting/colour off).