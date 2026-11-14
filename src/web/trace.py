"""Click-to-trace: follow money upstream / downstream from any account, crossing bank -> trading via owner links."""
from __future__ import annotations

import numpy as np

from ..config import DAY
from .state import State


def _agg_money(data, rows: np.ndarray, other_col: str, me: str):
    tx = data.tx
    sub = tx.iloc[rows]
    out: dict[str, list] = {}
    for o, a, t in zip(sub[other_col].to_numpy(), sub["amount"].to_numpy(), sub["t"].to_numpy()):
        e = out.setdefault(o, [0.0, 0, 1e18, -1e18])
        e[0] += a
        e[1] += 1
        e[2] = min(e[2], t)
        e[3] = max(e[3], t)
    return out


def _agg_trades(data, rows: np.ndarray, me: str):
    tr = data.trades
    sub = tr.iloc[rows]
    down: dict[str, list] = {}   # shares flow seller -> buyer: downstream = I sold to them
    up: dict[str, list] = {}
    for b, s, nt, t in zip(sub["buyer"].to_numpy(), sub["seller"].to_numpy(), sub["notional"].to_numpy(), sub["t"].to_numpy()):
        if s == me:
            tgt, other = down, b
        else:
            tgt, other = up, s
        e = tgt.setdefault(other, [0.0, 0, 1e18, -1e18])
        e[0] += nt
        e[1] += 1
        e[2] = min(e[2], t)
        e[3] = max(e[3], t)
    return down, up


def _top(d: dict, k: int):
    return sorted(d.items(), key=lambda kv: -kv[1][0])[:k]


def trace(st: State, account: str, depth: int = 3, per_node: int = 5, direction: str = "both") -> dict:
    data = st.data
    if account not in data.owner_of:
        raise KeyError(account)
    nodes: dict[str, dict] = {account: dict(id=account, k="d" if account.startswith("D") else "b", dist=0, side="origin")}
    edges: dict[tuple, dict] = {}

    def add_edge(src, dst, kind, e):
        key = (src, dst, kind)
        if key not in edges:
            edges[key] = dict(src=src, dst=dst, kind=kind, amount=round(e[0], 2), n=e[1], t0=round(e[2] / DAY, 3), t1=round(e[3] / DAY, 3))

    def touch(acc, dist, side):
        if acc not in nodes:
            nodes[acc] = dict(id=acc, k="d" if acc.startswith("D") else "b", dist=dist, side=side)
            return True
        if nodes[acc]["side"] != side and nodes[acc]["side"] != "origin":
            nodes[acc]["side"] = "both"
        return False

    for side in (["down", "up"] if direction == "both" else [direction]):
        frontier = [account]
        for d in range(1, depth + 1):
            nxt = []
            for cur in frontier:
                if cur.startswith("B"):
                    rows = (data.send_rows if side == "down" else data.recv_rows).get(cur)
                    if rows is not None and len(rows):
                        agg = _agg_money(data, rows, "receiver" if side == "down" else "sender", cur)
                        for o, e in _top(agg, per_node):
                            if o == cur:
                                continue
                            add_edge(cur, o, "money", e) if side == "down" else add_edge(o, cur, "money", e)
                            if touch(o, d, side):
                                nxt.append(o)
                    # cross into the trading layer through the owner
                    for dm in data.demat_of_owner.get(data.owner_of.get(cur), []):
                        add_edge(cur, dm, "owner", [0, 0, 0, 0]) if side == "down" else add_edge(dm, cur, "owner", [0, 0, 0, 0])
                        if touch(dm, d, side):
                            nxt.append(dm)
                else:
                    rows = data.demat_rows.get(cur)
                    if rows is not None and len(rows):
                        down, up = _agg_trades(data, rows, cur)
                        agg = down if side == "down" else up
                        for o, e in _top(agg, per_node):
                            add_edge(cur, o, "trade", e) if side == "down" else add_edge(o, cur, "trade", e)
                            if touch(o, d, side):
                                nxt.append(o)
                    for b in data.banks_of_owner.get(data.owner_of.get(cur), []):
                        add_edge(b, cur, "owner", [0, 0, 0, 0]) if side == "up" else add_edge(cur, b, "owner", [0, 0, 0, 0])
                        if touch(b, d, side):
                            nxt.append(b)
            frontier = nxt[:60]
    for n in nodes.values():
        n["alerts"] = st.acct_alerts.get(n["id"], [])
        n["owner"] = data.owner_of.get(n["id"], "")
    return dict(origin=account, nodes=list(nodes.values()), edges=list(edges.values()),
                reach=dict(up=sum(1 for n in nodes.values() if n["side"] in ("up", "both")),
                           down=sum(1 for n in nodes.values() if n["side"] in ("down", "both")),
                           flagged=sum(1 for n in nodes.values() if n["alerts"])))
