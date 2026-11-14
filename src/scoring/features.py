"""Cluster feature table and the feature sets used by each method."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..detectors.bridge import BRIDGE_KEYS

MONEY_F = ["n_nodes", "n_tx", "log_amount", "amount_cv", "near_thr_share", "max_in_deg", "max_out_deg", "hub_ratio",
           "internal_share", "known_share", "span_hours", "time_conc", "tx_per_node", "fan_out_score", "fan_in_score",
           "structuring_score", "roundtrip_score", "passthrough_score", "n_detectors", "retention_mean",
           "pass_ratio_mean", "dwell_median_hours", "regular_days", "n_inflows_max"]
TRADE_F = ["t_n_members", "t_n_trades", "t_n_days", "t_internal_share", "t_net_pos_ratio", "t_max_pair_trades",
           "t_reversal_days", "t_dev_abs_mean", "t_dev_abs_max", "t_pnl_asym", "t_vol_share_stock",
           "t_liq_adj_volume", "t_log_notional", "t_n_ext_cp", "t_total_trades", "wash_score", "loss_score"]
BRIDGE_F = list(BRIDGE_KEYS)
ALL_F = MONEY_F + TRADE_F + BRIDGE_F + ["is_trade"]

FEATURE_SETS = {
    "single_layer": MONEY_F,
    "two_layer_no_bridge": MONEY_F + TRADE_F + ["is_trade"],
    "twintrace": ALL_F,
}
LAYERS = {"single_layer": {"money"}, "two_layer_no_bridge": {"money", "trade"}, "twintrace": {"money", "trade", "bridge"}}

LABELS = {
    "n_nodes": "accounts in cluster", "n_tx": "transfers in cluster", "log_amount": "total amount", "amount_cv": "amount similarity",
    "near_thr_share": "share just under threshold", "max_in_deg": "fan-in breadth", "max_out_deg": "fan-out breadth",
    "hub_ratio": "hub concentration", "internal_share": "money staying inside the cluster", "known_share": "pairs seen before (regularity)",
    "span_hours": "activity span", "time_conc": "time clustering", "tx_per_node": "transfers per account",
    "fan_out_score": "fan-out detector", "fan_in_score": "fan-in detector", "structuring_score": "structuring detector",
    "roundtrip_score": "round-trip detector", "passthrough_score": "pass-through detector", "n_detectors": "detectors fired",
    "retention_mean": "per-hop retention", "pass_ratio_mean": "inflow/outflow ratio", "dwell_median_hours": "dwell time",
    "regular_days": "repeat pass-through days", "n_inflows_max": "inflow count",
    "t_n_members": "trading accounts", "t_n_trades": "internal trades", "t_n_days": "active trading days",
    "t_internal_share": "volume staying inside the group", "t_net_pos_ratio": "net position vs gross volume",
    "t_max_pair_trades": "repeat trades per pair", "t_reversal_days": "same-day reversal days",
    "t_dev_abs_mean": "off-market price deviation", "t_dev_abs_max": "max price deviation", "t_pnl_asym": "profit/loss asymmetry",
    "t_vol_share_stock": "share of stock volume", "t_liq_adj_volume": "liquidity-adjusted volume",
    "t_log_notional": "traded value", "t_n_ext_cp": "outside counterparties", "t_total_trades": "all member trades",
    "wash_score": "wash-trading detector", "loss_score": "loss-booking detector", "funding_overlap": "shared funding source",
    "same_owner_share": "same-owner accounts", "owner_link": "owner / funding link", "exit_chain_share": "cash-out chain",
    "funded_log_inr": "funded amount", "demat_link_share": "members with trading accounts",
    "trade_internal_share": "members trade mostly with each other", "n_demat_members": "linked trading accounts",
    "is_trade": "trade-layer cluster",
}


def feature_frame(clusters: list[dict]) -> pd.DataFrame:
    rows = []
    for c in clusters:
        r = dict(c["features"])
        r["is_trade"] = float(c["layer"] in ("trade", "bridge"))
        rows.append(r)
    df = pd.DataFrame(rows).reindex(columns=ALL_F)
    return df.astype(float)


def hand_components(df: pd.DataFrame) -> pd.DataFrame:
    """Explainable 0..1 components behind the hand-weighted score. NaN (not applicable) counts as 0."""
    g = lambda c: df[c].fillna(0.0).astype(float) if c in df else pd.Series(0.0, index=df.index)  # noqa: E731
    det = pd.concat([g(c) for c in ["fan_out_score", "fan_in_score", "structuring_score", "roundtrip_score",
                                    "passthrough_score", "wash_score", "loss_score"]], axis=1).max(axis=1)
    closed = np.where(df["is_trade"] > 0, g("t_internal_share"), g("internal_share"))
    comps = pd.DataFrame(index=df.index)
    comps["best detector score"] = det
    comps["multiple detectors fired"] = (g("n_detectors") / 2).clip(0, 1)
    comps["money stays inside the group"] = closed
    comps["not a recurring relationship"] = np.where(df["is_trade"] > 0, 1.0, 1 - g("known_share"))
    comps["time clustering"] = g("time_conc")
    comps["similar amounts"] = np.where(df["is_trade"] > 0, 1 - g("t_net_pos_ratio").clip(0, 1), 1 - g("amount_cv").clip(0, 1))
    comps["just under threshold"] = g("near_thr_share")
    comps["off-market pricing"] = (g("t_dev_abs_mean") / 0.3).clip(0, 1)
    comps["shared funding / owner"] = g("owner_link")
    comps["cash-out chain"] = g("exit_chain_share")
    comps["members trade with each other"] = g("trade_internal_share")
    return comps


HAND_PRIOR = {
    "best detector score": 30, "multiple detectors fired": 5, "money stays inside the group": 10,
    "not a recurring relationship": 10, "time clustering": 5, "similar amounts": 5, "just under threshold": 5,
    "off-market pricing": 5, "shared funding / owner": 15, "cash-out chain": 10, "members trade with each other": 5,
}
