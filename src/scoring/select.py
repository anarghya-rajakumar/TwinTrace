"""Cross-window de-duplication and validation-split threshold selection."""
from __future__ import annotations

import numpy as np

from ..config import DAY, split_of
from ..eval.metrics import GroundTruth, evaluate


def dedupe(alerts: list[dict], overlap: float = 0.5, max_gap_days: float = 14.0) -> list[dict]:
    """Greedy non-maximum suppression: the same ring seen in several sliding windows becomes one alert
    (highest score wins). Alerts only merge if their accounts overlap and their times are close."""
    kept: list[dict] = []
    index: dict[str, list[int]] = {}
    # near-ties go to the cross-layer chain: if a trade cluster extends into bank -> trade -> withdrawal, report that
    for a in sorted(alerts, key=lambda x: (-x.get("prio", 0), -round(x["score"], 1), 0 if x["layer"] == "bridge" else 1, -x["score"])):
        accts = set(a["accounts"])
        dup = False
        cand = {k for x in accts for k in index.get(x, ())}
        for k in cand:
            b = kept[k]
            inter = len(accts & set(b["accounts"]))
            if inter / min(len(accts), len(b["accounts"])) >= overlap and abs(a["t_start"] - b["t_start"]) <= max_gap_days * DAY:
                dup = True
                break
        if not dup:
            kept.append(a)
            for x in accts:
                index.setdefault(x, []).append(len(kept) - 1)
    return kept


def choose_threshold(alerts: list[dict], gt: GroundTruth, target_fpr: float, split: str = "val", scope: str = "all",
                     n_grid: int = 40, f1_tolerance: float = 0.03) -> float:
    """Threshold on the validation split. Among thresholds whose false-positive rate stays within the target, find the best
    F1, then take the LOWEST threshold whose F1 is within `f1_tolerance` of it. (Taking the arg-max alone is fragile:
    classifier scores saturate, and the arg-max can sit on a razor edge inside a plateau of near-identical scores,
    discarding many true positives for the sake of one false positive.) If no threshold qualifies, take the strictest."""
    cfg = gt.cfg
    alerts = [a for a in alerts if split_of(a["t_start"], cfg) == split]
    sc = np.array([a["score"] for a in alerts])
    if len(sc) == 0:
        return 101.0
    grid = np.unique(np.quantile(sc, np.linspace(0.75, 0.9995, n_grid)))
    ok: list[tuple[float, float]] = []
    for thr in grid:
        m = evaluate(dedupe([a for a in alerts if a["score"] >= thr]), gt, split, scope)
        if m["fpr"] <= target_fpr:
            ok.append((float(thr), m["f1"]))
    if not ok:
        return float(grid[-1])
    best = max(f for _, f in ok)
    return min(t for t, f in ok if f >= best - f1_tolerance)
