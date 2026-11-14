"""Layer-2 (trade) cluster features and detectors: wash trading and loss-booking, liquidity-adjusted."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import make_alert


def trade_features(win_stock: pd.DataFrame, members: list, stock_median_daily_vol: float) -> tuple[dict, pd.DataFrame]:
    """Features of a candidate trade cluster inside one stock-window. Returns (features, internal trades)."""
    mem = set(members)
    b_in, s_in = win_stock["buyer"].isin(mem), win_stock["seller"].isin(mem)
    internal = win_stock[b_in & s_in]
    touched = win_stock[b_in | s_in]
    vol_int, vol_tot = float(internal["qty"].sum()), float(touched["qty"].sum())
    # net position vs gross volume over every trade the members did in this stock and window
    net = {}
    gross = 0.0
    for col, sign in (("buyer", 1.0), ("seller", -1.0)):
        sub = touched[touched[col].isin(mem)]
        for m, q in sub.groupby(col)["qty"].sum().items():
            net[m] = net.get(m, 0.0) + sign * float(q)
            gross += float(q)
    net_ratio = float(sum(abs(v) for v in net.values()) / gross) if gross else 1.0
    pair = np.where(internal["buyer"] < internal["seller"], internal["buyer"] + "|" + internal["seller"],
                    internal["seller"] + "|" + internal["buyer"]) if len(internal) else np.array([])
    max_pair = int(pd.Series(pair).value_counts().max()) if len(pair) else 0
    rev_days = 0
    if len(internal):
        tmp = internal.assign(pair=pair, d=internal["day"])
        for (_, _), g in tmp.groupby(["pair", "d"]):
            if g["buyer"].nunique() > 1 and len(g) >= 2:
                rev_days += 1
    cash = {}
    for m in mem:
        cash[m] = float(internal.loc[internal["seller"] == m, "notional"].sum() - internal.loc[internal["buyer"] == m, "notional"].sum())
    gross_notional = float(internal["notional"].sum())
    dev = internal["dev"].abs() if len(internal) else pd.Series([0.0])
    ext_cp = set(touched["buyer"]).union(touched["seller"]) - mem
    n_days = int(internal["day"].nunique()) if len(internal) else 0
    f = dict(t_n_members=len(mem), t_n_trades=int(len(internal)), t_n_days=n_days,
             t_internal_share=vol_int / vol_tot if vol_tot else 0.0, t_net_pos_ratio=net_ratio,
             t_max_pair_trades=max_pair, t_reversal_days=rev_days, t_dev_abs_mean=float(dev.mean()),
             t_dev_abs_max=float(dev.max()),
             t_pnl_asym=float(max((abs(v) for v in cash.values()), default=0.0) / gross_notional) if gross_notional else 0.0,
             t_vol_share_stock=vol_int / float(win_stock["qty"].sum()) if len(win_stock) else 0.0,
             t_liq_adj_volume=vol_int / max(1.0, stock_median_daily_vol),
             t_log_notional=float(np.log10(gross_notional + 1)), t_n_ext_cp=len(ext_cp),
             t_total_trades=int(len(touched)))
    return f, internal


def wash_score(f: dict, is_cycle: bool, min_share: float) -> float:
    share_q = float(np.clip((f["t_internal_share"] - min_share) / 0.4, 0, 1))
    net_q = 1 - min(1.0, f["t_net_pos_ratio"] / 0.3)
    size_q = min(1.0, f["t_n_trades"] / 12)
    liq_q = min(1.0, np.log10(1 + f["t_liq_adj_volume"]))
    return share_q * (0.4 + 0.6 * net_q) * (0.5 + 0.5 * size_q) * (0.6 + 0.4 * liq_q) * (1.0 if is_cycle else 0.5)


def loss_score(f: dict) -> float:
    rep_q = min(1.0, f["t_reversal_days"] / 3)
    dev_q = float(np.clip((f["t_dev_abs_mean"] - 0.05) / 0.25, 0, 1))       # zero when trades are at market price
    pnl_q = min(1.0, f["t_pnl_asym"] / 0.15)
    return rep_q * dev_q * (0.3 + 0.7 * pnl_q)


def trade_alerts(stock: str, members: list, internal: pd.DataFrame, f: dict, is_cycle: bool, cfg: dict) -> list[dict]:
    d = cfg["detectors"]
    out = []
    if len(internal) == 0:
        return out
    t0_, t1_ = float(internal["t"].min()), float(internal["t"].max())
    first_seller = str(internal.iloc[0]["seller"])
    last_buyer = str(internal.iloc[-1]["buyer"])
    common = dict(stock=stock, **{k: v for k, v in f.items()})
    if f["t_n_trades"] >= d["wash_min_trades"] and f["t_internal_share"] >= d["wash_min_internal_share"]:
        sc = wash_score(f, is_cycle, d["wash_min_internal_share"])
        ev = dict(common, internal_volume_share=f["t_internal_share"], net_position_ratio=f["t_net_pos_ratio"],
                  n_trades=f["t_n_trades"], n_accounts=len(members), n_days=f["t_n_days"], cycle=bool(is_cycle),
                  gross_qty=int(internal["qty"].sum()))
        out.append(make_alert("trade", "wash_trading", members, [], sc, ev, [first_seller], [last_buyer], t0_, t1_,
                              trade_ids=internal["trade_id"]))
    if f["t_n_trades"] >= d["loss_min_trades"] and f["t_dev_abs_mean"] >= d["loss_min_deviation"] and f["t_reversal_days"] >= 2:
        sc = loss_score(f)
        ev = dict(common, n_trades=f["t_n_trades"], reversal_days=f["t_reversal_days"],
                  mean_price_deviation=f["t_dev_abs_mean"], max_price_deviation=f["t_dev_abs_max"],
                  pnl_asymmetry=f["t_pnl_asym"], n_accounts=len(members))
        out.append(make_alert("trade", "loss_booking", members, [], sc, ev, [first_seller], [last_buyer], t0_, t1_,
                              trade_ids=internal["trade_id"]))
    return out
