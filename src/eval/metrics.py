"""Evaluation: alert-to-ring matching and metrics on a time-based split."""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from ..config import split_bounds, split_of

TYPOLOGY_FAMILY = {  # which alert typologies count as naming a ring's typology correctly
    "fan_out": {"fan_out"}, "fan_in_structuring": {"fan_in_structuring", "structuring", "fan_in"},
    "round_trip": {"round_trip"}, "mule_chain": {"mule_chain", "pass_through"},
    "wash_trading": {"wash_trading"}, "loss_booking": {"loss_booking"}, "market_layering": {"market_layering"},
}


SCOPES = {"all": None, "money": {"money"}, "trade": {"trade", "bridge"}}


def match_alert(accts: set, ring_accts: set, frac: float) -> bool:
    inter = len(accts & ring_accts)
    return inter > 0 and (inter / len(accts) >= frac or inter / len(ring_accts) >= frac)


class GroundTruth:
    """Pre-indexed rings / innocents / activity for fast repeated evaluation."""

    def __init__(self, data):
        self.cfg = data.cfg
        self.frac = data.cfg["eval"]["match_fraction"]
        self.rings = {r["ring_id"]: r for r in data.rings}
        self.ring_sets = {k: set(r["accounts"]) for k, r in self.rings.items()}
        self.idx: dict[str, list] = defaultdict(list)
        for k, s in self.ring_sets.items():
            for a in s:
                self.idx[a].append(k)
        self.ring_accounts = set(self.idx)
        self.bounds = split_bounds(data.cfg)
        tx, tr = data.tx, data.trades
        all_acc = set(data.accounts["account_id"])
        self.innocent_all = all_acc - self.ring_accounts
        self.active: dict[str, set] = {}
        for name, (lo, hi) in self.bounds.items():
            a = set(tx.loc[(tx["t"] >= lo) & (tx["t"] < hi), "sender"]) | set(tx.loc[(tx["t"] >= lo) & (tx["t"] < hi), "receiver"])
            b = set(tr.loc[(tr["t"] >= lo) & (tr["t"] < hi), "buyer"]) | set(tr.loc[(tr["t"] >= lo) & (tr["t"] < hi), "seller"])
            self.active[name] = a | b
        self.n_active = {k: len(v) for k, v in self.active.items()}
        self.n_innocent_active = {k: len(v - self.ring_accounts) for k, v in self.active.items()}

    def matches(self, accounts) -> list[str]:
        accts = set(accounts)
        cand = {r for a in accts for r in self.idx.get(a, ())}
        return [r for r in cand if match_alert(accts, self.ring_sets[r], self.frac)]


def alert_split(alert: dict, cfg: dict) -> str:
    return split_of(alert["t_start"], cfg)


def evaluate(alerts: list[dict], gt: GroundTruth, split: str = "test", scope: str = "all") -> dict:
    """scope: 'all' = every ring and alert; 'money' = Layer-1 rings and alerts only; 'trade' = trade and
    bridge rings and alerts only."""
    cfg = gt.cfg
    layers = SCOPES[scope]
    rings = {k: r for k, r in gt.rings.items() if r["split"] == split and (layers is None or r["layer"] in layers)}
    al = [a for a in alerts if alert_split(a, cfg) == split and (layers is None or a["layer"] in layers)]
    tp, hit, flagged = 0, set(), set()
    typ_ok, typ_n = 0, 0
    for a in al:
        flagged.update(a["accounts"])
        ms = [m for m in gt.matches(a["accounts"]) if m in rings]
        if ms:
            tp += 1
            hit.update(ms)
            best = ms[0]
            typ_n += 1
            typ_ok += a.get("typology") in TYPOLOGY_FAMILY.get(gt.rings[best]["typology"], {gt.rings[best]["typology"]})
    fp_acc = flagged - gt.ring_accounts
    n_al = len(al)
    prec = tp / n_al if n_al else 0.0
    rec = len(hit) / len(rings) if rings else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    per_typ = {}
    for typ in sorted({r["typology"] for r in rings.values()}):
        ids = [k for k, r in rings.items() if r["typology"] == typ]
        per_typ[typ] = sum(k in hit for k in ids) / len(ids)
    return dict(precision=prec, recall=rec, f1=f1,
                fpr=len(fp_acc & gt.active[split]) / max(1, gt.n_innocent_active[split]),
                alerts=n_al, alerts_per_1000_accounts=1000.0 * n_al / max(1, gt.n_active[split]),
                rings=len(rings), rings_found=len(hit), true_alerts=tp,
                typology_accuracy=typ_ok / typ_n if typ_n else 0.0, per_typology_recall=per_typ)
