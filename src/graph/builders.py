"""Graph construction, sliding windows, candidate clusters (components + Louvain) and cluster stats."""
from __future__ import annotations

from typing import Iterator

import networkx as nx
import numpy as np
import pandas as pd
from community import community_louvain
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


def sliding_windows(t: np.ndarray, hours: float, stride_hours: float, horizon: float) -> Iterator[tuple]:
    """Yield (window_start, window_end, lo, hi) for a time-sorted array `t`; rows lo:hi lie in the window."""
    w, st = hours * 3600.0, stride_hours * 3600.0
    ws = 0.0
    while ws < horizon:
        lo = int(np.searchsorted(t, ws, "left"))
        hi = int(np.searchsorted(t, ws + w, "left"))
        if hi > lo:
            yield ws, ws + w, lo, hi
        ws += st


def build_multidigraph(df: pd.DataFrame) -> nx.MultiDiGraph:
    """One edge per transfer; keeps tx_id, amount and time as edge attributes."""
    g = nx.MultiDiGraph()
    for tid, s, r, a, t in zip(df["tx_id"], df["sender"], df["receiver"], df["amount"], df["t"]):
        g.add_edge(s, r, key=int(tid), tx_id=int(tid), amount=float(a), t=float(t))
    return g


def aggregate(df: pd.DataFrame) -> nx.DiGraph:
    """Aggregated directed graph: one edge per ordered pair with total amount, count and first/last time."""
    agg = df.groupby(["sender", "receiver"]).agg(amount=("amount", "sum"), count=("amount", "size"),
                                                   t_first=("t", "min"), t_last=("t", "max")).reset_index()
    g = nx.DiGraph()
    g.add_edges_from((r.sender, r.receiver, dict(amount=r.amount, count=int(r.count), t_first=r.t_first,
                                                 t_last=r.t_last)) for r in agg.itertuples())
    return g


def candidate_clusters(df: pd.DataFrame, min_size: int, max_size: int, seed: int = 0,
                       louvain_above: int | None = None) -> list[list]:
    """Candidate clusters for one window: weakly connected components, with Louvain used to split any
    component larger than `max_size`. (Louvain is deliberately not applied to small components: modularity
    optimisation on a tiny isolated chain or cycle splits it in two, which would cut real rings apart.)"""
    codes, uniq = pd.factorize(pd.concat([df["sender"], df["receiver"]], ignore_index=True))
    n = len(df)
    a, b = codes[:n], codes[n:]
    m = coo_matrix((np.ones(n), (a, b)), shape=(len(uniq), len(uniq)))
    k, lab = connected_components(m, directed=False)
    order = np.argsort(lab, kind="stable")
    bounds = np.flatnonzero(np.diff(lab[order])) + 1
    comps = np.split(order, bounds)
    out = []
    for c in comps:
        if len(c) < min_size:
            continue
        nodes = [uniq[i] for i in c]
        if len(nodes) <= (louvain_above or max_size):
            out.append(nodes)
            continue
        sub = df[df["sender"].isin(nodes) & df["receiver"].isin(nodes)]
        ug = nx.Graph()
        for (s_, r_), amt in sub.groupby(["sender", "receiver"])["amount"].sum().items():
            w = float(np.log1p(amt))
            if ug.has_edge(s_, r_):
                ug[s_][r_]["weight"] += w
            else:
                ug.add_edge(s_, r_, weight=w)
        part = community_louvain.best_partition(ug, weight="weight", random_state=seed)
        groups: dict[int, list] = {}
        for node, cid in part.items():
            groups.setdefault(cid, []).append(node)
        out.extend(g for g in groups.values() if min_size <= len(g) <= max_size)
    return out
