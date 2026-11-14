"""Layer-2 candidate clusters: strongly connected groups in the per-stock trade graph (plus busy hubs)."""
from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd

from ..detectors.trade import loss_score, trade_alerts, trade_features, wash_score
from .builders import sliding_windows

NAN_TRADE = dict(t_n_members=np.nan, t_n_trades=np.nan, t_n_days=np.nan, t_internal_share=np.nan,
                 t_net_pos_ratio=np.nan, t_max_pair_trades=np.nan, t_reversal_days=np.nan, t_dev_abs_mean=np.nan,
                 t_dev_abs_max=np.nan, t_pnl_asym=np.nan, t_vol_share_stock=np.nan, t_liq_adj_volume=np.nan,
                 t_log_notional=np.nan, t_n_ext_cp=np.nan, t_total_trades=np.nan)


def build_trade_clusters(data, t_range: tuple | None = None) -> list[dict]:
    cfg, tr = data.cfg, data.trades
    g = cfg["graph"]
    daily = tr.groupby(["stock", "day"])["qty"].sum().groupby(level=0).median().to_dict()
    out = []
    for ws, we, lo, hi in sliding_windows(tr["t"].to_numpy(), g["trade_window_hours"], g["trade_stride_hours"], data.horizon):
        if t_range and (we < t_range[0] or ws > t_range[1]):
            continue
        win = tr.iloc[lo:hi]
        for stock, ws_ in win.groupby("stock"):
            dg = nx.DiGraph()
            dg.add_edges_from(zip(ws_["seller"], ws_["buyer"]))
            med = float(daily.get(stock, 1.0))
            for comp in nx.strongly_connected_components(dg):
                if len(comp) < 2 or len(comp) > g["max_cluster_size"]:
                    continue
                members = sorted(comp)
                f, internal = trade_features(ws_, members, med)
                if f["t_n_trades"] < 4:
                    continue
                is_cycle = True                      # a strongly connected group with >= 2 members contains a cycle
                als = trade_alerts(stock, members, internal, f, is_cycle, cfg)
                f["wash_score"] = wash_score(f, is_cycle, cfg["detectors"]["wash_min_internal_share"])
                f["loss_score"] = loss_score(f)
                f["n_detectors"] = len(als)
                dets = {a["typology"]: dict(score=a["score"], evidence=a["evidence"]) for a in als}
                f["wash_score"] = dets.get("wash_trading", {}).get("score", 0.0)
                f["loss_score"] = dets.get("loss_booking", {}).get("score", 0.0)
                out.append(dict(layer="trade", stock=stock, window_start_s=ws, window_end_s=we,
                                t_start=float(internal["t"].min()), t_end=float(internal["t"].max()),
                                accounts=members, nodes=members, tx_ids=[], trade_ids=internal["trade_id"].astype(int).tolist(),
                                entry_nodes=[str(internal.iloc[0]["seller"])], exit_nodes=[str(internal.iloc[-1]["buyer"])],
                                features=f, detectors=dets))
            # busy hubs (market-maker-like): many trades, many counterparties, both sides; kept as negatives
            cnt = pd.concat([ws_["buyer"], ws_["seller"]]).value_counts()
            for hub in cnt.index[cnt >= 15]:
                sub = ws_[(ws_["buyer"] == hub) | (ws_["seller"] == hub)]
                cps = set(sub["buyer"]) | set(sub["seller"])
                cps.discard(hub)
                if len(cps) < 10 or sub["buyer"].eq(hub).all() or sub["seller"].eq(hub).all():
                    continue
                f, internal = trade_features(ws_, [hub], med)
                f.update(t_n_trades=int(len(sub)), n_detectors=0, wash_score=0.0, loss_score=0.0)
                out.append(dict(layer="trade", stock=stock, window_start_s=ws, window_end_s=we,
                                t_start=float(sub["t"].min()), t_end=float(sub["t"].max()), accounts=[hub], nodes=[hub],
                                tx_ids=[], trade_ids=sub["trade_id"].astype(int).tolist(), entry_nodes=[], exit_nodes=[],
                                features=f, detectors={}))
    return out
