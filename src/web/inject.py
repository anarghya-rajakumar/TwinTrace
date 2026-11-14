"""Plant a fresh laundering ring into the live data and see whether TwinTrace (and the rule baseline) catch it."""
from __future__ import annotations

import copy
import json
import time

import numpy as np
import pandas as pd

from ..config import DAY, split_of
from ..data_gen import money_rings, trades as trade_gen
from ..data_gen.world import World
from ..eval.baseline import rule_baseline
from ..eval.metrics import GroundTruth
from ..graph.prep import data_from_frames
from ..scoring.features import feature_frame, hand_components
from ..scoring.select import dedupe
from .state import GROUPS, State

SIZE_KEY = {"fan_out": "fan_out", "fan_in_structuring": "fan_in", "round_trip": "round_trip", "mule_chain": "mule_chain",
            "wash_trading": "wash_trading", "loss_booking": "loss_booking", "market_layering": "bridge"}
ABBR = {"fan_out": "FO", "fan_in_structuring": "FI", "round_trip": "RT", "mule_chain": "MC", "wash_trading": "WT",
        "loss_booking": "LB", "market_layering": "BR"}
MONEY_FN = {"fan_out": money_rings.fan_out, "fan_in_structuring": money_rings.fan_in_structuring,
            "round_trip": money_rings.round_trip, "mule_chain": money_rings.mule_chain}
TRADE_FN = {"wash_trading": trade_gen.wash_ring, "loss_booking": trade_gen.loss_booking_pair,
            "market_layering": trade_gen.bridge_ring}
TYPOLOGIES = list(SIZE_KEY)


class MarketStub:
    """Price paths rebuilt from the saved daily closes, so injected trades sit at realistic prices."""

    def __init__(self, cfg: dict, prices: pd.DataFrame):
        self.tickers = cfg["data"]["tickers"]
        self.kind = {k: v["kind"] for k, v in self.tickers.items()}
        self.close = {}
        for stock, g in prices.groupby("stock"):
            arr = g.sort_values("date")["close"].to_numpy(dtype=float)
            self.close[stock] = np.concatenate([arr, np.repeat(arr[-1], 6)])

    def price_at(self, sym, t):
        c = self.close[sym]
        t = np.asarray(t, dtype=float)
        d = np.floor(t / DAY).astype(int)
        f = t / DAY - d
        return c[d] * (1 - f) + c[d + 1] * f


def _make_world(st: State, cfg: dict, rng: np.random.Generator) -> World:
    data = st.data
    banks = st.accounts[st.accounts["layer"] == "bank"]["account_id"].to_numpy(dtype=object)
    activity = np.array([len(data.acct_rows.get(b, [])) for b in banks], dtype=float)
    w = World(cfg, rng, banks, activity, dict(data.owner_of))
    busy = {a for r in data.rings for a in r["accounts"]} | {a for h in data.hards for a in h["accounts"]}
    w._pool = [b for b in w._pool if b not in busy]
    w.bank_of_owner = {}
    for b in banks:
        w.bank_of_owner.setdefault(data.owner_of[b], b)
    w.weekdays = trade_gen.weekday_list(cfg)
    dem = st.accounts[st.accounts["layer"] == "demat"]["account_id"].to_numpy(dtype=object)
    w.background_demat = [d for d in dem if d not in busy]
    w.demat_owner = {d: data.owner_of[d] for d in dem}
    w._demat_n = len(dem)
    return w


def _sanitize(o):
    return json.loads(json.dumps(o, default=lambda x: x.item() if hasattr(x, "item") else str(x)))


def plant(st: State, typology: str, stealth: float = 0.6, size: int | None = None, start_day: float | None = None,
          seed: int | None = None) -> dict:
    if typology not in SIZE_KEY:
        raise ValueError(f"unknown typology {typology}")
    from ..pipeline import _cand, build_alert, build_all_clusters, label_clusters
    from ..explain.typology import label_cluster
    t_wall = time.time()
    with st.lock:
        cfg_base = st.cfg
        cfg = copy.deepcopy(cfg_base)
        cfg["stealth"] = float(stealth)
        if size:
            lo_hi = [int(size), int(size)]
            if typology != "loss_booking":
                cfg["ring_size"][SIZE_KEY[typology]] = lo_hi
        rng = np.random.default_rng(seed if seed is not None else int(time.time() * 1000) % (2 ** 31))
        w = _make_world(st, cfg, rng)
        prices = pd.read_parquet(__import__("src.config", fromlist=["processed_dir"]).processed_dir() / "prices.parquet")
        mkt = MarketStub(cfg, prices)
        if typology in MONEY_FN:
            MONEY_FN[typology](w, 0.5)
        else:
            TRADE_FN[typology](w, mkt, 0.5)
        ring = w.rings[-1]
        old = ring["ring_id"]
        k = len(st.injected) + 1
        rid = f"LIVE-{ABBR[typology]}-{k:02d}"
        ring["ring_id"] = rid

        mrows = [(t, s, r, a, f, rid if tag == old else rid + ":fund" if tag == old + ":fund" else tag)
                 for (t, s, r, a, f, tag) in w.money.rows]
        trows = [(t, st_, b, s, p, q, rid if tag == old else tag) for (t, st_, b, s, p, q, tag) in w.trades.rows]
        core = [t for (t, *_rest, tag) in trows if tag == rid] if ring["layer"] in ("trade", "bridge") else \
            [r[0] for r in mrows if r[5] == rid]
        core = core or [r[0] for r in mrows]
        horizon = cfg["n_days"] * DAY
        target = (start_day if start_day is not None else float(rng.uniform(60, 80))) * DAY
        target = max(target, 11 * DAY)
        delta = target - min(core)
        alls = [r[0] for r in mrows] + [r[0] for r in trows]
        top = max(alls) + delta
        if top > horizon - 3600:
            delta -= top - (horizon - 3600)
        mrows = [(t + delta, *rest) for (t, *rest) in mrows]
        trows = [(t + delta, *rest) for (t, *rest) in trows]

        T0 = st.data.t0
        next_tx = int(st.raw_tx["tx_id"].max()) + 1
        next_tr = int(st.raw_trades["trade_id"].max()) + 1
        new_tx = pd.DataFrame({
            "tx_id": np.arange(next_tx, next_tx + len(mrows)), "ts": [(T0 + pd.Timedelta(seconds=r[0])).floor("s") for r in mrows],
            "sender": [r[1] for r in mrows], "receiver": [r[2] for r in mrows], "amount_inr": [round(r[3], 2) for r in mrows],
            "currency": "INR", "payment_format": [r[4] for r in mrows], "is_laundering_base": 0})
        new_tr = pd.DataFrame({
            "trade_id": np.arange(next_tr, next_tr + len(trows)), "ts": [(T0 + pd.Timedelta(seconds=r[0])).floor("s") for r in trows],
            "stock": [r[1] for r in trows], "buyer": [r[2] for r in trows], "seller": [r[3] for r in trows],
            "price": [r[4] for r in trows], "qty": [r[5] for r in trows]})
        tx_ids = [int(x) for x, r in zip(new_tx["tx_id"], mrows) if r[5] == rid]
        fund_ids = [int(x) for x, r in zip(new_tx["tx_id"], mrows) if r[5] == rid + ":fund"]
        tr_ids = [int(x) for x, r in zip(new_tr["trade_id"], trows) if r[6] == rid]
        core_t = ([r[0] for r in trows if r[6] == rid] if ring["layer"] in ("trade", "bridge") else [r[0] for r in mrows if r[5] == rid])
        t_start, t_end = float(min(core_t)), float(max(core_t))
        ring.update(tx_ids=tx_ids, trade_ids=tr_ids, funding_tx_ids=fund_ids, t_start=t_start, t_end=t_end,
                    ts_start=str(T0 + pd.Timedelta(seconds=t_start)), ts_end=str(T0 + pd.Timedelta(seconds=t_end)),
                    split=split_of(t_start, cfg_base), source="live")
        ring.pop("ts_start", None)

        acc_new = pd.DataFrame(w.demat_rows, columns=["account_id", "owner_id", "layer", "account_type"])
        accounts2 = pd.concat([st.accounts, acc_new], ignore_index=True)
        new_tx["ts"] = pd.to_datetime(new_tx["ts"])
        new_tr["ts"] = pd.to_datetime(new_tr["ts"])
        tx2 = pd.concat([st.raw_tx, new_tx], ignore_index=True) if len(new_tx) else st.raw_tx
        tr2 = pd.concat([st.raw_trades, new_tr], ignore_index=True) if len(new_tr) else st.raw_trades
        rings2 = list(st.data.rings) + [ring]
        data2 = data_from_frames(cfg_base, tx2, tr2, accounts2, rings2, st.hards)
        gt2 = GroundTruth(data2)

        # ---- detect (windowed): only the stretch of time around the new ring
        clusters = build_all_clusters(data2, log=lambda *_: None, t_range=(t_start - 2 * DAY, ring["t_end"] + 9 * DAY))
        label_clusters(clusters, gt2)
        X = feature_frame(clusters) if clusters else None
        labels = [label_cluster(c) for c in clusters]
        bundle = st.bundle
        thr = st.thresholds
        best_alert, best_score, caught, closest = None, None, False, None
        if clusters:
            if bundle["scorer"] == "xgb":
                scores = bundle["model"].score(X)
                comps = None
            else:
                comps = hand_components(X)
                scores = bundle["model"].score(comps)
            cands = [_cand(c, s, lab) for c, s, lab in zip(clusters, scores, labels)]
            mine = [a for a in cands if rid in gt2.matches(a["accounts"])]
            if mine:
                top_c = dedupe(mine)[0]
                i = top_c["idx"]
                best_score = float(top_c["score"])
                contrib = (bundle["model"].contributions(X.iloc[[i]]) if comps is None else bundle["model"].contributions(comps.iloc[[i]])).iloc[0]
                amt_by_id = data2.tx.set_index("tx_id")["amount"]
                notional = data2.trades.set_index("trade_id")["notional"]
                alert = build_alert(data2, clusters[i], best_score, contrib, amt_by_id, notional, gt2)
                alert["alert_id"] = f"LIVE-{k:02d}"
                alert["live"] = True
                caught = best_score >= thr[GROUPS[alert["layer"]]]
                alert["above_default"] = bool(caught)
                best_alert = _sanitize(alert)
                closest = dict(layer=alert["layer"], score=best_score, threshold=float(thr[GROUPS[alert["layer"]]]))

        # ---- the rule baseline on the same data
        base = rule_baseline(data2)
        ring_accts = set(ring["accounts"])
        flagged = {a for al in base for a in al["accounts"]} & ring_accts
        base_hit = bool(flagged)

        # ---- commit to live state
        st.raw_tx, st.raw_trades, st.accounts, st.data, st.gt = tx2, tr2, accounts2, data2, gt2
        if best_alert:
            st.alerts.append(best_alert)
        st.injected.append(dict(ring_id=rid, typology=typology, caught=caught))
        st.reindex()

        nodes = sorted(set(ring["accounts"]) | {x for r in mrows for x in (r[1], r[2])} | {x for r in trows for x in (r[2], r[3])})
        events = [[round(r[0] / DAY, 4), r[1], r[2], round(r[3], 2), 0] for r in mrows] + \
                 [[round(r[0] / DAY, 4), r[3], r[2], round(r[4] * r[5], 2), 1] for r in trows]
        owner_links = []
        for a in nodes:
            if a.startswith("D"):
                for b in data2.banks_of_owner.get(data2.owner_of.get(a), []):
                    if b in nodes:
                        owner_links.append([b, a])
        return dict(
            ring_id=rid, typology=typology, params=dict(stealth=stealth, size=size, start_day=round(t_start / DAY, 2)),
            ring=dict(accounts=ring["accounts"], nodes=nodes, events=sorted(events), owners=owner_links,
                      t0=round(t_start / DAY, 3), t1=round(t_end / DAY, 3)),
            caught=caught, alert=best_alert, closest=closest,
            baseline=dict(caught=base_hit, flagged_accounts=len(flagged), ring_accounts=len(ring_accts)),
            seconds=round(time.time() - t_wall, 1))
