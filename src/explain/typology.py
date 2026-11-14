"""Map detector output to a named laundering typology (primary + secondary, with a confidence)."""
from __future__ import annotations

import numpy as np

TYPOLOGY_NAMES = {
    "fan_out": "Dispersion (fan-out)",
    "fan_in": "Aggregation (fan-in)",
    "fan_in_structuring": "Aggregation with structuring (smurfing)",
    "round_trip": "Round-tripping",
    "mule_chain": "Mule / pass-through chain",
    "wash_trading": "Wash / circular trading",
    "loss_booking": "Loss-booking / non-genuine trades",
    "market_layering": "Layering through the market (bank -> trading -> withdrawal)",
    "unclassified_anomaly": "Unclassified anomalous cluster",
}
_DET_TO_TYP = {"structuring": "fan_in_structuring", "fan_in": "fan_in", "fan_out": "fan_out", "round_trip": "round_trip",
               "pass_through": "mule_chain", "wash_trading": "wash_trading", "loss_booking": "loss_booking"}


def label_cluster(c: dict, model_score: float | None = None) -> dict:
    d = c.get("detectors", {})
    cand: dict[str, float] = {}
    for det, info in d.items():
        typ = _DET_TO_TYP.get(det)
        if typ is None:
            continue
        cand[typ] = max(cand.get(typ, 0.0), info["score"])
    if "loss_booking" in cand and "wash_trading" in cand:     # off-market prices rule out plain wash trading
        cand["loss_booking"] = max(cand["loss_booking"], cand["wash_trading"]) + 1e-6
    if "fan_in_structuring" in cand:                 # structuring is the more specific form of aggregation
        cand["fan_in_structuring"] = max(cand["fan_in_structuring"], cand.pop("fan_in", 0.0))
    if c["layer"] == "bridge":
        primary = "market_layering"
        rest = sorted(cand.items(), key=lambda kv: -kv[1])
        secondary = rest[0][0] if rest else None
        base = 0.5 + 0.5 * min(1.0, c["features"].get("exit_chain_share", 0) or 0)
    elif cand:
        ranked = sorted(cand.items(), key=lambda kv: -kv[1])
        primary = ranked[0][0]
        secondary = ranked[1][0] if len(ranked) > 1 else None
        if primary in ("fan_in", "fan_in_structuring") and "mule_chain" in cand:
            secondary = "mule_chain"
        base = ranked[0][1]
    else:
        primary, secondary, base = "unclassified_anomaly", None, 0.0
    ms = (model_score or 0.0) / 100.0
    conf = float(np.clip(0.5 * base + 0.5 * ms if cand or c["layer"] == "bridge" else 0.5 * ms, 0, 1))
    return dict(primary=primary, secondary=secondary, confidence=conf)
