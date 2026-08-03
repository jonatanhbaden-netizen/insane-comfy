# MC Animate tuning harness

Requires: `pip install websocket-client opencv-python-headless numpy` (a venv is fine).
All scripts take `POD_ID=<runpod id>` as env.

    python newpod_setup.py                    # boot-wait + model restore + verify
    python battery.py smoke                   # 49-frame end-to-end validation
    python battery.py run B0                  # baseline battery -> results.jsonl
    python battery.py run <tag> steps=8 ...   # A/B variant (knobs in animate_api.K)
    python pod_exec.py '<shell command>'      # exec on pod via Jupyter terminal

Loop state, metrics definitions, and the A/B queue: docs/MC_ANIMATE_TUNING.md.
