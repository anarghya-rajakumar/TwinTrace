"""Layer-1 candidate clusters: components/Louvain per sliding window, features, detector evidence."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import DAY
from ..detectors.money import add_known, compute_pass_events, money_alerts
from .builders import candidate_clusters, sliding_windows

DET_KEYS = {"fan_out": "fan_out_score", "fan_in": "fan_in_score", "structuring": "structuring_score",
            "round_trip": "roundtrip_score", "pass_through": "passthrough_score"}
H = 3600.0


def _edge_roles(sub: pd.DataFrame):
    snd, rcv = set(sub["sender"]), set(sub["receiver"])
    sources = sorted(snd - rcv)
    sinks = sorted(rcv - snd)
    if not sources or not sinks:               # cycles / loops: origin of the earliest transfer
        first = sub.iloc[0]
        last = sub.iloc[-1]
        sources = sources or [first["sender"]]
        sinks = sinks or [last["receiver"]]
    return sources, sinks


def _window_clusters(data, dfw: pd.DataFrame, comps: list, alerts: list, ws: float, we: float) -> list[dict]:
    cfg, thr = data.cfg, data.cfg["threshold_inr"]
    lo_b, hi_b = cfg["detectors"]["structuring_band"]
    comp_of = {n: i for i, nodes in enumerate(comps) for n in nodes}
    cs = dfw["sender"].map(comp_of)
    cr = dfw["receiver"].map(comp_of)
    mask = (cs.notna() & (cs == cr)).to_numpy()
    internal = dfw[mask].copy()
    internal["cid"] = cs[mask].astype(int).to_numpy()
    internal["near"] = ((internal["amount"] >= lo_b * thr) & (internal["amount"] < hi_b * thr)).astype(float)
    internal["bin"] = np.floor(internal["t"] / 43200.0)
    if internal.empty:
        return []
    g = internal.groupby("cid")
    f = g.agg(n_tx=("amount", "size"), amt_sum=("amount", "sum"), amt_mean=("amount", "mean"),
              amt_std=("amount", "std"), n1=("amount", "size"), near=("near", "mean"), known=("known", "mean"),
              tmin=("t", "min"), tmax=("t", "max"))
    f["amt_std"] = f["amt_std"].fillna(0.0) * np.sqrt((f["n1"] - 1).clip(lower=0) / f["n1"])   # population std
    f["max_out"] = internal.groupby(["cid", "sender"])["receiver"].nunique().groupby(level=0).max()
    f["max_in"] = internal.groupby(["cid", "receiver"])["sender"].nunique().groupby(level=0).max()
    f["conc"] = internal.groupby(["cid", "bin"]).size().groupby(level=0).max() / f["n_tx"]

    by_comp: dict[int, list] = {}
    for a in alerts:
        ids = [comp_of[x] for x in a["accounts"] if x in comp_of]
        if ids:
            by_comp.setdefault(int(pd.Series(ids).mode().iloc[0]), []).append(a)

    T, AMT = data.tx["t"].to_numpy(), data.tx["amount"].to_numpy()
    out = []
    groups = dict(tuple(g))
    for cid, row in f.iterrows():
        als = by_comp.get(int(cid), [])
        if row["n_tx"] < 4 and not als:
            continue
        nodes = comps[int(cid)]
        sub = groups[cid].sort_values("t")
        # closedness: share of the members' money (+/-7 days around the window) that stays inside the cluster
        rows = np.concatenate([data.acct_rows[n] for n in nodes if n in data.acct_rows])
        rows = np.unique(rows)
        rows = rows[(T[rows] >= ws - 7 * DAY) & (T[rows] < we + 7 * DAY)]
        mem = np.array([data.code_of[n] for n in nodes])
        inside = np.isin(data.s_code[rows], mem) & np.isin(data.r_code[rows], mem)
        int_amt, ext_amt = AMT[rows[inside]].sum(), AMT[rows[~inside]].sum()
        feats = dict(
            n_nodes=len(nodes), n_tx=int(row["n_tx"]), log_amount=float(np.log10(row["amt_sum"] + 1)),
            amount_cv=float(row["amt_std"] / row["amt_mean"]) if row["amt_mean"] else 0.0,
            near_thr_share=float(row["near"]), max_in_deg=int(row["max_in"]), max_out_deg=int(row["max_out"]),
            hub_ratio=float(max(row["max_in"], row["max_out"]) / max(1, len(nodes) - 1)),
            internal_share=float(int_amt / (int_amt + ext_amt)) if int_amt + ext_amt else 1.0,
            known_share=float(row["known"]), span_hours=float((row["tmax"] - row["tmin"]) / H),
            time_conc=float(row["conc"]), tx_per_node=float(row["n_tx"] / len(nodes)))
        dets = {}
        for a in als:
            cur = dets.get(a["typology"])
            if cur is None or a["score"] > cur["score"]:
                dets[a["typology"]] = a
        for typ, key in DET_KEYS.items():
            feats[key] = dets[typ]["score"] if typ in dets else 0.0
        feats["n_detectors"] = sum(1 for k in DET_KEYS.values() if feats[k] > 0)
        rt = dets.get("round_trip", {}).get("evidence", {})
        pt = dets.get("pass_through", {}).get("evidence", {})
        feats["retention_mean"] = rt.get("retention_mean", np.nan)
        feats["pass_ratio_mean"] = pt.get("ratio_mean", np.nan)
        feats["dwell_median_hours"] = pt.get("dwell_median_hours", np.nan)
        feats["regular_days"] = pt.get("prior_regular_days", np.nan)
        feats["n_inflows_max"] = pt.get("n_inflows_max", np.nan)

        if als:
            accounts = sorted({x for a in als for x in a["accounts"]})
            entry = sorted({x for a in als for x in a["entry_nodes"]})
            exit_ = sorted({x for a in als for x in a["exit_nodes"]})
            tx_ids = sorted({i for a in als for i in a["tx_ids"]})
            t_start, t_end = min(a["t_start"] for a in als), max(a["t_end"] for a in als)
        else:
            accounts = sorted(nodes)
            entry, exit_ = _edge_roles(sub)
            tx_ids = sub["tx_id"].astype(int).tolist()
            t_start, t_end = float(row["tmin"]), float(row["tmax"])
        out.append(dict(layer="money", window_start_s=ws, window_end_s=we, t_start=float(t_start), t_end=float(t_end),
                        accounts=accounts, nodes=sorted(nodes), tx_ids=tx_ids, trade_ids=[], entry_nodes=entry,
                        exit_nodes=exit_, features=feats, detectors={k: dict(score=v["score"], evidence=v["evidence"])
                                                                   for k, v in dets.items()},
                        ext_amount_inr=float(ext_amt), int_amount_inr=float(int_amt)))
    return out


def build_money_clusters(data, events: pd.DataFrame | None = None, t_range: tuple | None = None) -> list[dict]:
    g = data.cfg["graph"]
    events = compute_pass_events(data) if events is None else events
    tx, out = data.tx, []
    for ws, we, lo, hi in sliding_windows(tx["t"].to_numpy(), g["window_hours"], g["stride_hours"], data.horizon):
        if t_range and (we < t_range[0] or ws > t_range[1]):
            continue
        dfw = add_known(tx.iloc[lo:hi], ws, data.cfg["detectors"]["recurrence_gap_hours"])
        comps = candidate_clusters(dfw, g["min_cluster_size"], g["max_cluster_size"], seed=data.cfg["seed"])
        if not comps:
            continue
        out += _window_clusters(data, dfw, comps, money_alerts(data, dfw, ws, we, events), ws, we)
    return out
