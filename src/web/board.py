"""Payload for the investigation board: nodes, timed events, alerts, planted rings (ground truth), headline metrics."""
from __future__ import annotations

import numpy as np

from ..config import DAY, split_bounds
from .state import GROUPS, State


def _kind(a: str) -> str:
    return "d" if a.startswith("D") else "b"


MIN_SCORE = 50.0   # alerts below this never reach the board (keeps the layout fast and the picture readable)


def build_board(st: State, bg_tx: int = 1000, bg_trades: int = 220, seed: int = 7) -> dict:
    data = st.data
    alerts = [a for a in st.alerts if a["score"] >= MIN_SCORE or a.get("live")]
    tx = data.tx.set_index("tx_id")
    tr = data.trades.set_index("trade_id")
    nodes: dict[str, int] = {}
    node_list: list[dict] = []

    def nid(acc: str) -> int:
        if acc not in nodes:
            nodes[acc] = len(node_list)
            node_list.append(dict(id=acc, k=_kind(acc)))
        return nodes[acc]

    ev: dict[tuple, list] = {}

    def add_money(tid: int, ai: int, ri: int) -> None:
        key = ("m", tid)
        if key in ev:
            if ai >= 0 and ev[key][5] < 0:
                ev[key][5] = ai
            if ri >= 0 and ev[key][6] < 0:
                ev[key][6] = ri
            return
        r = tx.loc[tid]
        ev[key] = [round(r["t"] / DAY, 4), nid(r["sender"]), nid(r["receiver"]), round(float(r["amount"]), 2), 0, ai, ri]

    def add_trade(tid: int, ai: int, ri: int) -> None:
        key = ("t", tid)
        if key in ev:
            if ai >= 0 and ev[key][5] < 0:
                ev[key][5] = ai
            if ri >= 0 and ev[key][6] < 0:
                ev[key][6] = ri
            return
        r = tr.loc[tid]
        ev[key] = [round(r["t"] / DAY, 4), nid(r["seller"]), nid(r["buyer"]), round(float(r["notional"]), 2), 1, ai, ri]

    for ai, a in enumerate(alerts):
        for t in a["tx_ids"]:
            add_money(t, ai, -1)
        for t in a["trade_ids"]:
            add_trade(t, ai, -1)
    rings = data.rings
    for ri, r in enumerate(rings):
        for t in list(r["tx_ids"]) + list(r.get("funding_tx_ids", [])):
            add_money(t, -1, ri)
        for t in r["trade_ids"]:
            add_trade(t, -1, ri)

    rng = np.random.default_rng(seed)
    used_m = {k[1] for k in ev if k[0] == "m"}
    pool = np.array([i for i in tx.index if i not in used_m])
    for tid in rng.choice(pool, size=min(bg_tx, len(pool)), replace=False):
        add_money(int(tid), -1, -1)
    used_t = {k[1] for k in ev if k[0] == "t"}
    poolt = np.array([i for i in tr.index if i not in used_t])
    for tid in rng.choice(poolt, size=min(bg_trades, len(poolt)), replace=False):
        add_trade(int(tid), -1, -1)

    events = sorted(ev.values(), key=lambda e: e[0])
    # owner links between a bank account and its trading account, where both are on the board
    owners = []
    seen = set()
    for acc, i in list(nodes.items()):
        o = data.owner_of.get(acc)
        if acc.startswith("D") and o:
            for b in data.banks_of_owner.get(o, []):
                if b in nodes and (nodes[b], i) not in seen:
                    seen.add((nodes[b], i))
                    owners.append([nodes[b], i])

    a_light = []
    for ai, a in enumerate(alerts):
        a_light.append(dict(
            id=a["alert_id"], i=ai, typ=a["typology"], name=a["typology_name"], layer=a["layer"], grp=GROUPS[a["layer"]],
            score=float(a["score"]), t0=round(a["t_start"] / DAY, 3), t1=round(a["t_end"] / DAY, 3), n=len(a["accounts"]),
            amt=round(a["evidence"].get("amount_inr", 0.0), 0), split=a["split"], dflt=bool(a.get("above_default", False)),
            hit=bool(a["truth"]["matched_rings"]), ring=a["truth"]["matched_rings"][:1],
            acc=[nodes[x] for x in a["accounts"] if x in nodes],
            entry=[nodes[x] for x in a["entry_nodes"] if x in nodes], exit=[nodes[x] for x in a["exit_nodes"] if x in nodes],
            live=bool(a.get("live", False))))
    ring_light = []
    det: dict[str, list] = {}
    for ai, a in enumerate(alerts):
        if a.get("above_default"):
            for rid in a["truth"]["matched_rings"]:
                det.setdefault(rid, []).append(ai)
    for ri, r in enumerate(rings):
        ring_light.append(dict(id=r["ring_id"], i=ri, typ=r["typology"], layer=r["layer"], split=r.get("split", ""),
                               t0=round(r["t_start"] / DAY, 3), acc=[nodes[x] for x in r["accounts"] if x in nodes],
                               det=det.get(r["ring_id"], [])))

    res = st.results
    head = res[res["headline"]]
    methods = {}
    for _, r in head.iterrows():
        methods[r["method"]] = dict(precision=r["precision"], recall=r["recall"], f1=r["f1"], fpr=r["fpr"], alerts=int(r["alerts"]),
                                    per1000=r["alerts_per_1000_accounts"], found=int(r["rings_found"]), rings=int(r["rings"]),
                                    scorer=r["scorer"])
    bounds = {k: [v[0] / DAY, v[1] / DAY] for k, v in split_bounds(st.cfg).items()}
    return dict(
        t0=str(data.t0), days=st.cfg["n_days"], splits=bounds, thresholds=st.thresholds, nodes=node_list, events=events,
        owners=owners, alerts=a_light, rings=ring_light, methods=methods, threshold_inr=st.cfg["threshold_inr"], min_score=MIN_SCORE,
        n_accounts=int(len(st.accounts)), headline_scorer=st.meta.get("headline_scorer"))
