"""Data prep for the investigator's left-to-right fund-flow view (kept out of the UI so it can be tested)."""
from __future__ import annotations

from collections import defaultdict, deque

import numpy as np
import pandas as pd

from ..config import DAY


def _depths(nodes: list, edges: list[tuple], sources: list) -> dict:
    """Column index of each node: shortest hop count from the entry nodes along the direction of money."""
    adj = defaultdict(list)
    for u, v in edges:
        adj[u].append(v)
    depth = {s: 0 for s in sources if s in nodes}
    q = deque(depth)
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v not in depth:
                depth[v] = depth[u] + 1
                q.append(v)
    for n in nodes:                         # unreachable nodes (e.g. after cycles) sit after the reached ones
        depth.setdefault(n, max(depth.values(), default=0) + 1)
    return depth


def money_flow(alert: dict, tx: pd.DataFrame, ext_k: int = 3, ext_days: float = 7.0) -> dict:
    """Nodes with (x, y, role) and aggregated edges for a money alert. Roles: entry, exit, internal, ext_in, ext_out."""
    sub = tx[tx["tx_id"].isin(alert["tx_ids"])]
    nodes = [n for n in alert["accounts"]]
    edges_df = sub.groupby(["sender", "receiver"]).agg(amount=("amount", "sum"), n=("amount", "size"),
                                                      t=("t", "min")).reset_index()
    edges = [(r.sender, r.receiver) for r in edges_df.itertuples()]
    entry = [n for n in alert["entry_nodes"] if n in nodes] or nodes[:1]
    exit_ = [n for n in alert["exit_nodes"] if n in nodes] or nodes[-1:]
    depth = _depths(nodes, edges, entry)
    max_d = max(depth.values(), default=0)
    pos, role = {}, {}
    cols: dict[int, list] = defaultdict(list)
    for n in nodes:
        cols[depth[n] + 1].append(n)
        role[n] = "entry" if n in entry else "exit" if n in exit_ else "internal"
    # external counterparties just outside the cluster, around the alert window
    t0_, t1_ = alert["t_start"], alert["t_end"]
    win = tx[(tx["t"] >= t0_ - ext_days * DAY) & (tx["t"] <= t1_ + ext_days * DAY)]
    ext_edges = []
    mem = set(nodes)
    inn = win[win["receiver"].isin(entry) & ~win["sender"].isin(mem)].groupby(["sender", "receiver"])["amount"].sum()
    for (s, r), a in inn.sort_values(ascending=False).head(ext_k).items():
        ext_edges.append((s, r, a))
        role[s] = "ext_in"
        cols[0].append(s)
    out = win[win["sender"].isin(exit_) & ~win["receiver"].isin(mem)].groupby(["sender", "receiver"])["amount"].sum()
    for (s, r), a in out.sort_values(ascending=False).head(ext_k).items():
        ext_edges.append((s, r, a))
        role[r] = "ext_out"
        cols[max_d + 2].append(r)
    for x, members in cols.items():
        for i, n in enumerate(sorted(set(members))):
            pos[n] = (x, (i - (len(set(members)) - 1) / 2) * 1.0)
    all_edges = [dict(src=r.sender, dst=r.receiver, amount=float(r.amount), n=int(r.n), kind="money") for r in edges_df.itertuples()]
    all_edges += [dict(src=s, dst=r, amount=float(a), n=0, kind="external") for s, r, a in ext_edges]
    return dict(pos=pos, role=role, edges=all_edges, columns=max_d + 3)


def bridge_flow(alert: dict, tx: pd.DataFrame, trades: pd.DataFrame, owner_of: dict) -> dict:
    """Four columns: funder | bank accounts | trading accounts | cash-out account, with trades between the
    trading accounts and owner links between a bank account and its trading account."""
    accts = alert["accounts"]
    demat = [a for a in accts if a.startswith("D")]
    banks = [a for a in accts if a.startswith("B")]
    funder = [n for n in alert["entry_nodes"] if n in accts]
    exit_ = [n for n in alert["exit_nodes"] if n in accts]
    banks_mid = [b for b in banks if b not in funder and b not in exit_]
    cols = {0: funder, 1: banks_mid, 2: demat, 3: exit_}
    pos, role = {}, {}
    for x, members in cols.items():
        for i, n in enumerate(sorted(members)):
            pos[n] = (x, (i - (len(members) - 1) / 2) * 1.0)
            role[n] = "entry" if x == 0 else "exit" if x == 3 else "internal"
    edges = []
    sub = tx[tx["tx_id"].isin(alert["tx_ids"])].groupby(["sender", "receiver"]).agg(amount=("amount", "sum"), n=("amount", "size")).reset_index()
    edges += [dict(src=r.sender, dst=r.receiver, amount=float(r.amount), n=int(r.n), kind="money") for r in sub.itertuples()]
    tr = trades[trades["trade_id"].isin(alert["trade_ids"])]
    inner = tr[tr["buyer"].isin(demat) & tr["seller"].isin(demat)]
    g = inner.groupby(["seller", "buyer"]).agg(amount=("notional", "sum"), n=("qty", "size")).reset_index()
    edges += [dict(src=r.seller, dst=r.buyer, amount=float(r.amount), n=int(r.n), kind="trade") for r in g.itertuples()]
    dem_of = {}
    for d in demat:
        dem_of[owner_of.get(d)] = d
    for b in banks_mid:
        d = dem_of.get(owner_of.get(b))
        if d:
            edges.append(dict(src=b, dst=d, amount=0.0, n=0, kind="owner"))
    return dict(pos=pos, role=role, edges=edges, columns=4)


def trade_flow(alert: dict, trades: pd.DataFrame) -> dict:
    """Share flow among the trading accounts of a trade alert (seller -> buyer)."""
    tr = trades[trades["trade_id"].isin(alert["trade_ids"])]
    nodes = list(alert["accounts"])
    g = tr.groupby(["seller", "buyer"]).agg(amount=("notional", "sum"), n=("qty", "size")).reset_index()
    edges = [dict(src=r.seller, dst=r.buyer, amount=float(r.amount), n=int(r.n), kind="trade") for r in g.itertuples()]
    pairs = [(e["src"], e["dst"]) for e in edges]
    first_seller = tr.sort_values("t")["seller"].iloc[0] if len(tr) else (nodes[0] if nodes else None)
    depth = _depths(nodes, pairs, [first_seller])
    cols: dict[int, list] = defaultdict(list)
    for n in nodes:
        cols[depth[n]].append(n)
    pos = {n: (x, (i - (len(m) - 1) / 2) * 1.0) for x, m in cols.items() for i, n in enumerate(sorted(m))}
    role = {n: ("entry" if n == first_seller else "internal") for n in nodes}
    return dict(pos=pos, role=role, edges=edges, columns=max(depth.values(), default=0) + 1)


def alert_flow(alert: dict, data_tx: pd.DataFrame, data_trades: pd.DataFrame, owner_of: dict) -> dict:
    if alert["layer"] == "bridge":
        return bridge_flow(alert, data_tx, data_trades, owner_of)
    if alert["layer"] == "trade":
        return trade_flow(alert, data_trades)
    return money_flow(alert, data_tx)
