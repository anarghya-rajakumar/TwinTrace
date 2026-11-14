"""Rule-based baseline: the kind of per-transaction threshold logic the problem statement compares against."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import DAY

WEEK = 7 * DAY


def _alerts_from(df: pd.DataFrame, rule: str, layer: str, id_col: str, when: str = "t") -> list[dict]:
    """One alert per (account, week): the way alert queues are normally consolidated."""
    out = []
    if df.empty:
        return out
    df = df.assign(wk=(df[when] // WEEK).astype(int))
    for (acct, _), g in df.groupby(["account", "wk"]):
        out.append(dict(alert_id=None, layer=layer, typology=rule, accounts=[str(acct)],
                        tx_ids=g[id_col].astype(int).tolist() if layer == "money" else [],
                        trade_ids=g[id_col].astype(int).tolist() if layer == "trade" else [],
                        score=1.0, evidence=dict(rule=rule, n_events=int(len(g))),
                        entry_nodes=[], exit_nodes=[], t_start=float(g[when].min()), t_end=float(g[when].max())))
    return out


def rule_baseline(data) -> list[dict]:
    cfg = data.cfg
    b, thr = cfg["baseline"], cfg["threshold_inr"]
    tx, tr = data.tx, data.trades
    out: list[dict] = []

    # R1: any transaction at or above the reporting threshold -> both parties
    big = tx[tx["amount"] >= thr]
    both = pd.concat([big[["tx_id", "t", "sender"]].rename(columns={"sender": "account"}),
                      big[["tx_id", "t", "receiver"]].rename(columns={"receiver": "account"})])
    out += _alerts_from(both, "rule_large_transaction", "money", "tx_id")

    # R2: more than N transactions in one day
    day = (tx["t"] // DAY).astype(int)
    legs = pd.concat([tx[["tx_id", "t", "sender"]].rename(columns={"sender": "account"}).assign(day=day),
                      tx[["tx_id", "t", "receiver"]].rename(columns={"receiver": "account"}).assign(day=day)])
    cnt = legs.groupby(["account", "day"])["tx_id"].transform("size")
    out += _alerts_from(legs[cnt > b["max_tx_per_day"]], "rule_high_frequency", "money", "tx_id")

    # R3: many sub-threshold deposits into one account in a short window (structuring)
    near = tx[(tx["amount"] >= 0.9 * thr) & (tx["amount"] < thr)].sort_values("t")
    win = b["structuring_window_hours"] * 3600.0
    rows = []
    for acct, g in near.groupby("receiver"):
        t = g["t"].to_numpy()
        j = np.searchsorted(t, t + win, "right") - np.arange(len(t))
        hit = j >= b["structuring_min_deposits"]
        if hit.any():
            rows.append(g[hit].rename(columns={"receiver": "account"})[["tx_id", "t", "account"]])
    if rows:
        out += _alerts_from(pd.concat(rows), "rule_structuring", "money", "tx_id")

    # R4: volume spike (stock-day volume >> its median) plus a large order -> buyer and seller
    day_vol = tr.groupby(["stock", "day"])["qty"].sum()
    med_vol = day_vol.groupby(level=0).transform("median")
    spike = (day_vol / med_vol > b["volume_spike_multiple"]).rename("spike")
    med_q = tr.groupby("stock")["qty"].transform("median")
    t2 = tr.join(spike, on=["stock", "day"])
    sel = t2[(t2["spike"] == True) & (t2["qty"] > b["large_order_qty_multiple"] * med_q)]  # noqa: E712
    legs = pd.concat([sel[["trade_id", "t", "buyer"]].rename(columns={"buyer": "account"}),
                      sel[["trade_id", "t", "seller"]].rename(columns={"seller": "account"})])
    out += _alerts_from(legs, "rule_volume_spike_large_order", "trade", "trade_id")
    return out
