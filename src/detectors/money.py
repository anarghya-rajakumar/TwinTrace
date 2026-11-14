"""Layer-1 (bank transfer) detectors. Each returns Alert dicts (see common.make_alert)."""
from __future__ import annotations

from bisect import bisect_right
from itertools import islice

import networkx as nx
import numpy as np
import pandas as pd

from .common import make_alert

H = 3600.0


def add_known(dfw: pd.DataFrame, ws: float, gap_hours: float) -> pd.DataFrame:
    """Causal regularity flag: the ordered pair already transacted before this window started."""
    dfw = dfw.copy()
    dfw["known"] = (dfw["pair_first_t"] < ws - gap_hours * H).astype(float)
    return dfw


# ------------------------------------------------------------------ fan-in / fan-out / structuring
def fan_alerts(dfw: pd.DataFrame, cfg: dict) -> list[dict]:
    d, thr = cfg["detectors"], cfg["threshold_inr"]
    lo_b, hi_b = d["structuring_band"]
    out: list[dict] = []
    for role, other, typ in (("sender", "receiver", "fan_out"), ("receiver", "sender", "fan_in")):
        agg = dfw.groupby(role).agg(n_cp=(other, "nunique"), n_tx=("amount", "size"))
        hubs = agg.index[agg["n_cp"] >= d["fan_min_counterparties"]]
        if len(hubs) == 0:
            continue
        sub_all = dfw[dfw[role].isin(hubs)]
        for hub, sub in sub_all.groupby(role):
            amt = sub["amount"].to_numpy()
            cv = float(amt.std(ddof=0) / amt.mean()) if len(amt) > 1 else 0.0
            n_cp = int(sub[other].nunique())
            span_h = float((sub["t"].max() - sub["t"].min()) / H)
            known = float(sub["known"].mean())
            ev = dict(hub=str(hub), n_counterparties=n_cp, n_tx=int(len(sub)), total_inr=float(amt.sum()),
                      amount_cv=cv, span_hours=span_h, known_share=known, new_pair_share=1.0 - known,
                      max_piece_share=float(amt.max() / amt.sum()))
            cps = sorted(set(sub[other]))
            score = min(1.0, n_cp / 12) * (0.5 + 0.5 * (1 - min(1.0, cv))) * (1 - known)
            if typ == "fan_out":
                out.append(make_alert("money", "fan_out", [hub] + cps, sub["tx_id"], score, ev, [hub], cps,
                                      sub["t"].min(), sub["t"].max()))
            else:
                out.append(make_alert("money", "fan_in", [hub] + cps, sub["tx_id"], score, ev, cps, [hub],
                                      sub["t"].min(), sub["t"].max()))
                band = (amt >= lo_b * thr) & (amt < hi_b * thr)
                n_struct = int(band.sum())
                if n_struct >= d["structuring_min_tx"]:
                    bs = sub[band]
                    ev2 = dict(ev, n_structured=n_struct, structured_share=float(n_struct / len(sub)),
                               structured_total_inr=float(bs["amount"].sum()), threshold_inr=float(thr),
                               band_low_inr=float(lo_b * thr), band_high_inr=float(amt[band].max()),
                               n_structured_senders=int(bs["sender"].nunique()))
                    sc = min(1.0, n_struct / 8) * (n_struct / len(sub)) ** 0.5 * (1 - known)
                    out.append(make_alert("money", "structuring", [hub] + sorted(set(bs["sender"])), bs["tx_id"], sc, ev2,
                                          sorted(set(bs["sender"])), [hub], bs["t"].min(), bs["t"].max()))
    return out


# ------------------------------------------------------------------ round tripping
def roundtrip_alerts(dfw: pd.DataFrame, cfg: dict, max_cycles_per_scc: int = 300) -> list[dict]:
    d = cfg["detectors"]
    edges: dict[tuple, list] = {}
    for s, r, t, a, i, k in zip(dfw["sender"], dfw["receiver"], dfw["t"], dfw["amount"], dfw["tx_id"], dfw["known"]):
        edges.setdefault((s, r), []).append((t, a, i, k))
    for v in edges.values():
        v.sort()
    g = nx.DiGraph()
    g.add_edges_from(edges)
    out, seen = [], set()
    for comp in nx.strongly_connected_components(g):
        if not 3 <= len(comp) <= 40:
            continue
        sub = g.subgraph(comp)
        for cyc in islice(nx.simple_cycles(sub, length_bound=d["roundtrip_max_len"]), max_cycles_per_scc):
            n = len(cyc)
            if n < 3:
                continue
            best = None
            for st in range(n):
                rot = cyc[st:] + cyc[:st]
                t_prev, path, ok = -1e18, [], True
                for u, v in zip(rot, rot[1:] + rot[:1]):
                    lst = edges[(u, v)]
                    j = bisect_right([x[0] for x in lst], t_prev)
                    if j >= len(lst):
                        ok = False
                        break
                    path.append(lst[j])
                    t_prev = lst[j][0]
                if not ok:
                    continue
                dur = path[-1][0] - path[0][0]
                amts = np.array([p[1] for p in path])
                ratios = amts[1:] / amts[:-1]
                if dur > d["roundtrip_max_hours"] * H:
                    continue
                if ratios.min() < d["roundtrip_min_retention"] or ratios.max() > 1.05:
                    continue
                if best is None or dur < best[0]:
                    best = (dur, rot, path, ratios)
            if best is None:
                continue
            dur, rot, path, ratios = best
            key = frozenset(rot)
            if key in seen:
                continue
            seen.add(key)
            amts = np.array([p[1] for p in path])
            known = float(np.mean([p[3] for p in path]))
            ev = dict(n_hops=n, retention_min=float(ratios.min()), retention_mean=float(ratios.mean()),
                      duration_hours=float(dur / H), amount_start_inr=float(amts[0]), amount_end_inr=float(amts[-1]),
                      returned_share=float(amts[-1] / amts[0]), origin=str(rot[0]), known_share=known)
            q = float(np.clip((ratios.mean() - 0.8) / 0.19, 0, 1))
            score = (0.5 + 0.5 * q) * (1 - known) * (0.6 + 0.4 * min(1.0, n / 4))
            out.append(make_alert("money", "round_trip", rot, [p[2] for p in path], score, ev, [rot[0]], [rot[0]],
                                  path[0][0], path[-1][0]))
    return out


# ------------------------------------------------------------------ pass-through / mule chains
def compute_pass_events(data) -> pd.DataFrame:
    """Global pass-through events: an outflow that (almost) equals what flowed in within the previous
    few hours. Computed once; windows and the regularity feature reuse it."""
    d = data.cfg["detectors"]
    t, amt = data.tx["t"].to_numpy(), data.tx["amount"].to_numpy()
    maxd = d["passthrough_max_dwell_hours"] * H
    rows = []
    for a, send in data.send_rows.items():
        recv = data.recv_rows.get(a)
        if recv is None:
            continue
        rt = t[recv]
        cs = np.concatenate([[0.0], np.cumsum(amt[recv])])
        for o in send:
            to = t[o]
            lo = int(np.searchsorted(rt, to - maxd, "left"))
            hi = int(np.searchsorted(rt, to, "left"))
            if hi <= lo:
                continue
            ins = cs[hi] - cs[lo]
            if ins < d["passthrough_min_amount"]:
                continue
            ratio = amt[o] / ins
            if d["passthrough_min_ratio"] <= ratio <= 1.02:
                rows.append((a, to, int(o), float(ins), hi - lo, float(ratio), float(to - rt[hi - 1]),
                             tuple(int(x) for x in recv[lo:hi])))
    return pd.DataFrame(rows, columns=["account", "t_out", "row_out", "in_sum", "n_in", "ratio", "dwell", "rows_in"])


def passthrough_alerts(data, events: pd.DataFrame, ws: float, we: float) -> list[dict]:
    if events.empty:
        return []
    ev = events[(events["t_out"] >= ws) & (events["t_out"] < we)]
    if ev.empty:
        return []
    tx = data.tx
    parent: dict = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pass_accts = set(ev["account"])
    for e in ev.itertuples():
        find(e.account)
        recv = tx["receiver"].iat[e.row_out]
        if recv in pass_accts:
            parent[find(e.account)] = find(recv)
        for r_in in e.rows_in:
            snd = tx["sender"].iat[r_in]
            if snd in pass_accts:
                parent[find(e.account)] = find(snd)
    groups: dict = {}
    for e in ev.itertuples():
        groups.setdefault(find(e.account), []).append(e)
    hist = events.groupby("account")["t_out"].apply(lambda s: np.sort(s.to_numpy()))
    out = []
    for evs in groups.values():
        accts = {e.account for e in evs}
        rows_in = {r for e in evs for r in e.rows_in}
        rows_out = {e.row_out for e in evs}
        rows = sorted(rows_in | rows_out)
        senders = {tx["sender"].iat[r] for r in rows_in} - accts
        sinks = {tx["receiver"].iat[r] for r in rows_out} - accts
        involved = accts | senders | sinks
        ratios = np.array([e.ratio for e in evs])
        dwell = np.array([e.dwell for e in evs]) / H
        n_in_max = max(e.n_in for e in evs)
        regular = 0
        for a in accts:
            prior = hist.get(a)
            if prior is not None:
                days = np.unique(np.floor(prior[prior < ws - 3600] / 86400.0))
                regular = max(regular, len(days))
        first_in = min(tx["amount"].iat[r] for r in rows_in) if rows_in else 0.0
        t_first = float(min(tx["t"].iat[r] for r in rows))
        t_last = float(max(tx["t"].iat[r] for r in rows))
        out_amts = [tx["amount"].iat[r] for r in rows_out]
        ev_d = dict(n_pass_accounts=len(accts), n_chain_accounts=len(involved), ratio_min=float(ratios.min()),
                    ratio_mean=float(ratios.mean()), dwell_median_hours=float(np.median(dwell)),
                    dwell_max_hours=float(dwell.max()), n_inflows_max=int(n_in_max), prior_regular_days=int(regular),
                    amount_in_inr=float(sum(e.in_sum for e in evs) / max(1, len(evs))), amount_out_inr=float(max(out_amts)),
                    retained_share=float(np.prod(ratios)), source=str(sorted(senders)[0]) if senders else "",
                    sink=str(sorted(sinks)[0]) if sinks else "")
        chain = min(1.0, len(accts) / 3)
        speed = 1 - min(1.0, float(np.median(dwell)) / d_max(data))
        score = (0.4 + 0.6 * chain) * (0.5 + 0.5 * speed) * (1.0 / n_in_max) ** 0.5 / (1 + regular)
        out.append(make_alert("money", "pass_through", involved, tx["tx_id"].iloc[rows], score, ev_d,
                              senders or accts, sinks or accts, t_first, t_last))
    return out


def d_max(data) -> float:
    return float(data.cfg["detectors"]["passthrough_max_dwell_hours"])


def money_alerts(data, dfw: pd.DataFrame, ws: float, we: float, events: pd.DataFrame) -> list[dict]:
    if "known" not in dfw:
        dfw = add_known(dfw, ws, data.cfg["detectors"]["recurrence_gap_hours"])
    return fan_alerts(dfw, data.cfg) + roundtrip_alerts(dfw, data.cfg) + passthrough_alerts(data, events, ws, we)
