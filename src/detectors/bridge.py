"""Bridge detectors: link bank accounts and trading accounts through owners and funding sources."""
from __future__ import annotations

import numpy as np

from ..config import DAY

BRIDGE_KEYS = ["funding_overlap", "same_owner_share", "owner_link", "exit_chain_share", "funded_log_inr",
               "demat_link_share", "trade_internal_share", "n_demat_members"]


def _owners_banks(data, members):
    owners = sorted({data.owner_of[m] for m in members if m in data.owner_of})
    bank_owner = {}
    for o in owners:
        for b in data.banks_of_owner.get(o, []):
            bank_owner[b] = o
    return owners, bank_owner


def trade_bridge_features(data, c: dict) -> tuple[dict, dict | None]:
    """For a trade cluster: did its members' owners share a funding source in the money layer, and did the
    money leave again afterwards? Returns (feature dict, bridge-cluster dict or None)."""
    d, tx = data.cfg["detectors"], data.tx
    members = c["accounts"]
    owners, bank_owner = _owners_banks(data, members)
    n_own = len(owners)
    feats = dict(funding_overlap=0.0, same_owner_share=0.0, owner_link=0.0, exit_chain_share=0.0,
                 funded_log_inr=0.0, demat_link_share=np.nan, trade_internal_share=np.nan, n_demat_members=np.nan)
    if len(members) > 1:
        feats["same_owner_share"] = 1.0 - n_own / len(members)
    t_first, t_last = c["t_start"], c["t_end"]
    fund, fund_rows, fund_amt = {}, {}, {}
    for b, o in bank_owner.items():
        rows = data.recv_rows.get(b)
        if rows is None:
            continue
        tt = tx["t"].to_numpy()[rows]
        sel = rows[(tt >= t_first - d["funding_lookback_days"] * DAY) & (tt <= t_first)]
        for r in sel:
            s = tx["sender"].iat[int(r)]
            if s in bank_owner:
                continue
            fund.setdefault(s, set()).add(o)
            fund_rows.setdefault(s, []).append(int(r))
            fund_amt[s] = fund_amt.get(s, 0.0) + float(tx["amount"].iat[int(r)])
    ev = {}
    best = None
    shared = {k: v for k, v in fund.items() if len(v) >= 2}      # a *shared* source funds at least two owners
    if n_own >= 2 and shared:
        best = max(shared, key=lambda s: (len(shared[s]), fund_amt[s]))
        feats["funding_overlap"] = len(fund[best]) / n_own
        feats["funded_log_inr"] = float(np.log10(fund_amt[best] + 1))
        ev.update(funding_source=best, n_owners_funded=len(fund[best]), n_owners=n_own, funded_inr=fund_amt[best])
    feats["owner_link"] = max(feats["funding_overlap"], feats["same_owner_share"])
    exits, exit_rows, exit_amt = {}, {}, {}
    if n_own >= 2:
        for b, o in bank_owner.items():
            rows = data.send_rows.get(b)
            if rows is None:
                continue
            tt = tx["t"].to_numpy()[rows]
            for r in rows[(tt >= t_last) & (tt <= t_last + d["exit_lookahead_days"] * DAY)]:
                dst = tx["receiver"].iat[int(r)]
                if dst in bank_owner:
                    continue
                exits.setdefault(dst, set()).add(o)
                exit_rows.setdefault(dst, []).append(int(r))
                exit_amt[dst] = exit_amt.get(dst, 0.0) + float(tx["amount"].iat[int(r)])
    bridge = None
    exits = {k: v for k, v in exits.items() if len(v) >= 2}
    if exits:
        bdst = max(exits, key=lambda s: (len(exits[s]), exit_amt[s]))
        feats["exit_chain_share"] = len(exits[bdst]) / n_own
        ev.update(exit_account=bdst, n_owners_exiting=len(exits[bdst]), withdrawn_inr=exit_amt[bdst])
        if feats["funding_overlap"] >= 0.5 and feats["exit_chain_share"] >= 0.5 and best is not None:
            banks = sorted({b for b, o in bank_owner.items() if o in fund[best] and o in exits[bdst]})
            accounts = sorted(set(members) | set(banks) | {best, bdst})
            bridge = dict(
                layer="bridge", stock=c.get("stock"), window_start_s=c["window_start_s"], window_end_s=c["window_end_s"],
                t_start=c["t_start"], t_end=c["t_end"], accounts=accounts, nodes=accounts,
                tx_ids=sorted(set(fund_rows[best]) | set(exit_rows[bdst])), trade_ids=list(c["trade_ids"]),
                entry_nodes=[best], exit_nodes=[bdst], features=dict(c["features"]), detectors=dict(c["detectors"]),
                bridge_evidence=ev)
            ev["funded_back_to_exit_share"] = float(exit_amt[bdst] / fund_amt[best]) if fund_amt[best] else 0.0
    c["bridge_evidence"] = ev
    return feats, bridge


def money_bridge_features(data, c: dict) -> dict:
    """For a money cluster: do its members' owners hold trading accounts that trade mostly with each other?"""
    members = c["accounts"]
    dem = []
    n_with = 0
    for m in members:
        ds = data.demat_of_owner.get(data.owner_of.get(m), [])
        if ds:
            n_with += 1
            dem.extend(ds)
    dem = sorted(set(dem))
    feats = dict(funding_overlap=np.nan, same_owner_share=np.nan, owner_link=np.nan, exit_chain_share=np.nan,
                 funded_log_inr=np.nan, demat_link_share=n_with / max(1, len(members)),
                 trade_internal_share=0.0, n_demat_members=len(dem))
    if len(dem) >= 2:
        rows = np.unique(np.concatenate([data.demat_rows[x] for x in dem if x in data.demat_rows] or [np.array([], int)]))
        if len(rows):
            tt = data.trades["t"].to_numpy()[rows]
            rows = rows[(tt >= c["t_start"]) & (tt <= c["t_end"] + 14 * DAY)]
        if len(rows):
            ds = set(dem)
            b = data.trades["buyer"].to_numpy()[rows]
            s = data.trades["seller"].to_numpy()[rows]
            nt = data.trades["notional"].to_numpy()[rows]
            inside = np.array([(x in ds) and (y in ds) for x, y in zip(b, s)])
            feats["trade_internal_share"] = float(nt[inside].sum() / nt.sum()) if nt.sum() else 0.0
            feats["n_internal_trades"] = int(inside.sum())
    return feats
