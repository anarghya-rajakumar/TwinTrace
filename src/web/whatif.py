"""What-if: change the alert thresholds and recompute the benchmark metrics live."""
from __future__ import annotations

from ..eval.metrics import evaluate
from .state import GROUPS, State


def metrics_at(st: State, money: float | None = None, trade: float | None = None, split: str = "test") -> dict:
    thr = dict(st.thresholds)
    if money is not None:
        thr["money"] = float(money)
    if trade is not None:
        thr["trade"] = float(trade)
    sel = [a for a in st.alerts if a["score"] >= thr[GROUPS[a["layer"]]]]
    m = evaluate(sel, st.gt, split, "all")
    return dict(thresholds=thr, split=split, precision=m["precision"], recall=m["recall"], f1=m["f1"], fpr=m["fpr"],
                alerts=m["alerts"], per1000=m["alerts_per_1000_accounts"], rings=m["rings"], found=m["rings_found"],
                per_typology=m["per_typology_recall"], shown=len(sel))
