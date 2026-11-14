"""Alert dict factory shared by all detectors."""
from __future__ import annotations

import numpy as np


def _py(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    return x


def clean(d: dict) -> dict:
    return {k: (_py(v) if not isinstance(v, (list, dict)) else v) for k, v in d.items()}


def make_alert(layer: str, typology: str, accounts, tx_ids, score: float, evidence: dict, entry_nodes,
               exit_nodes, t_start: float, t_end: float, trade_ids=None) -> dict:
    return dict(
        alert_id=None, layer=layer, typology=typology,
        accounts=sorted({str(a) for a in accounts}),
        tx_ids=[int(i) for i in tx_ids], trade_ids=[int(i) for i in (trade_ids if trade_ids is not None else [])],
        score=float(max(0.0, min(1.0, score))),
        evidence={k: _py(v) for k, v in evidence.items()},
        entry_nodes=[str(a) for a in entry_nodes], exit_nodes=[str(a) for a in exit_nodes],
        t_start=float(t_start), t_end=float(t_end),
    )
