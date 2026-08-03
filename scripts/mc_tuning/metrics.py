"""Temporal/motion metrics for the MC tuning loop.

All metrics are comparative (lower/higher is better vs a baseline run on the
SAME driving clip + seed) — they rank A/B variants, they are not absolutes.

  motion:   optical-flow magnitude correlation + lag between driving & output
  flicker:  mean second-order temporal luminance derivative (jitter/strobing)
  drift:    slow color/structure walk over time (linear trend of dist-to-first)
  breaks:   frames whose diff-to-previous spikes >5 sigma (broken/dropped frames)
"""
import cv2
import numpy as np


def frames(path, max_frames=600, scale_w=256):
    cap = cv2.VideoCapture(str(path))
    out = []
    while len(out) < max_frames:
        ok, f = cap.read()
        if not ok:
            break
        h, w = f.shape[:2]
        nh = int(h * scale_w / w)
        out.append(cv2.resize(f, (scale_w, nh)))
    cap.release()
    return out


def gray(fs):
    return [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in fs]


def flow_energy(fs):
    """per-frame global motion magnitude via Farneback flow"""
    g = gray(fs)
    e = []
    for a, b in zip(g[:-1], g[1:]):
        fl = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        e.append(float(np.mean(np.linalg.norm(fl, axis=2))))
    return np.array(e)


def motion_metrics(drive_path, out_path, fps_ratio=1.0):
    """corr: how faithfully output motion tracks driving motion (higher better)
       lag:  frames of phase offset at max cross-correlation (0 is perfect)"""
    ed = flow_energy(frames(drive_path))
    eo = flow_energy(frames(out_path))
    n = min(len(ed), len(eo))
    if n < 20:
        return {"corr": None, "lag": None}
    ed, eo = ed[:n], eo[:n]
    ed = (ed - ed.mean()) / (ed.std() + 1e-8)
    eo = (eo - eo.mean()) / (eo.std() + 1e-8)
    best_corr, best_lag = -2, 0
    for lag in range(-8, 9):
        if lag >= 0:
            c = float(np.mean(ed[:n-lag] * eo[lag:n])) if n - lag > 10 else -2
        else:
            c = float(np.mean(ed[-lag:n] * eo[:n+lag])) if n + lag > 10 else -2
        if c > best_corr:
            best_corr, best_lag = c, lag
    return {"corr": round(best_corr, 4), "lag": best_lag}


def flicker_index(path):
    """second-order luminance derivative, masked to LOW-motion regions so real
       motion doesn't count as flicker (lower better)"""
    g = gray(frames(path))
    if len(g) < 5:
        return None
    vals = []
    for i in range(1, len(g) - 1):
        d1 = np.abs(g[i] - g[i-1])
        acc = np.abs(g[i+1] - 2*g[i] + g[i-1])
        still = d1 < np.percentile(d1, 60)          # low-motion mask
        if still.sum() > 100:
            vals.append(float(np.mean(acc[still])))
    return round(float(np.mean(vals)), 4) if vals else None


def drift_slope(path):
    """linear slope of histogram distance to FIRST frame over time — slow
       color/identity walk (closer to 0 better)"""
    fs = frames(path)
    if len(fs) < 20:
        return None
    def h(f):
        x = cv2.calcHist([f], [0, 1, 2], None, [8, 8, 8], [0, 256]*3)
        return cv2.normalize(x, x).flatten()
    h0 = h(fs[0])
    d = [float(cv2.compareHist(h0, h(f), cv2.HISTCMP_BHATTACHARYYA)) for f in fs]
    t = np.arange(len(d), dtype=np.float32)
    slope = float(np.polyfit(t, np.array(d, dtype=np.float32), 1)[0])
    return round(slope * 1000, 4)                    # per-1000-frames scale


def broken_frames(path):
    """count frames whose diff-to-prev spikes >5 sigma above median (breaks/pops)"""
    g = gray(frames(path))
    if len(g) < 10:
        return None
    d = np.array([float(np.mean(np.abs(a - b))) for a, b in zip(g[:-1], g[1:])])
    med, mad = np.median(d), np.median(np.abs(d - np.median(d))) + 1e-8
    return int(np.sum(d > med + 5 * 1.4826 * mad))


def report(drive_path, out_path):
    m = motion_metrics(drive_path, out_path)
    return {
        "motion_corr": m["corr"], "motion_lag": m["lag"],
        "flicker": flicker_index(out_path),
        "drift_slope": drift_slope(out_path),
        "broken_frames": broken_frames(out_path),
    }


if __name__ == "__main__":
    import sys, json
    print(json.dumps(report(sys.argv[1], sys.argv[2]), indent=1))
