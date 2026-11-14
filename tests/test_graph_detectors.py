"""Stage 3: graph construction, sliding windows, clustering, and the Layer-1 detectors on hand-made data."""
from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.config import load_config
from src.detectors.money import (add_known, compute_pass_events, fan_alerts, passthrough_alerts, roundtrip_alerts)
from src.graph.builders import aggregate, build_multidigraph, candidate_clusters, sliding_windows
from src.graph.prep import _group_index

CFG = load_config()
H = 3600.0


def frame(rows, known_before=None):
    """rows: (t_hours, sender, receiver, amount). known_before: hours before t=0 the pair was first seen."""
    df = pd.DataFrame(rows, columns=["t", "sender", "receiver", "amount"])
    df["t"] = df["t"] * H
    df["tx_id"] = np.arange(len(df))
    df["pair_first_t"] = df["t"] if known_before is None else -known_before * H
    return add_known(df, 0.0, CFG["detectors"]["recurrence_gap_hours"])


# ---------------------------------------------------------------- graph
def test_multidigraph_keeps_every_transfer_aggregate_collapses_pairs():
    df = frame([(0, "A", "B", 100), (1, "A", "B", 50), (2, "B", "C", 70)])
    mg, ag = build_multidigraph(df), aggregate(df)
    assert mg.number_of_edges() == 3 and ag.number_of_edges() == 2
    assert ag["A"]["B"]["amount"] == 150 and ag["A"]["B"]["count"] == 2


def test_sliding_windows_cover_horizon():
    t = np.arange(0, 10 * 86400, 3600.0)
    w = list(sliding_windows(t, 72, 24, 10 * 86400))
    assert w[0][:2] == (0.0, 72 * H) and len(w) == 10
    ws, we, lo, hi = w[2]
    assert t[lo] >= ws and t[hi - 1] < we and hi - lo == 72


def test_small_components_stay_whole_large_ones_are_split_by_louvain():
    cycle = [(i, f"c{i}", f"c{(i + 1) % 6}", 100) for i in range(6)]       # an isolated 6-cycle
    chain = [(i, f"m{i}", f"m{i + 1}", 100) for i in range(4)]
    cliques = []                                                           # two dense blobs joined by one edge
    for g in "xy":
        for i in range(25):
            for j in range(i + 1, 25):
                cliques.append((0, f"{g}{i}", f"{g}{j}", 10))
    cliques.append((0, "x0", "y0", 10))
    df = frame(cycle + chain + cliques)
    out = candidate_clusters(df, 3, 40, seed=1)
    sets = [set(c) for c in out]
    assert {f"c{i}" for i in range(6)} in sets                             # ring not cut in two
    assert {f"m{i}" for i in range(5)} in sets
    big = [s for s in sets if s & {"x1", "y1"}]
    assert len(big) == 2 and all(len(s) == 25 for s in big)               # the 50-node component split into its blobs


# ---------------------------------------------------------------- fan-in / fan-out / structuring
def test_fan_out_detected_and_recurrence_suppresses_it():
    rows = [(i * 0.5, "S", f"R{i}", 40_000 + i * 100) for i in range(10)]
    (a,) = [x for x in fan_alerts(frame(rows), CFG) if x["typology"] == "fan_out"]
    assert a["evidence"]["n_counterparties"] == 10 and a["entry_nodes"] == ["S"] and a["score"] > 0.5
    known = [x for x in fan_alerts(frame(rows, known_before=24 * 20), CFG) if x["typology"] == "fan_out"]
    assert known[0]["score"] == 0.0                                        # same payees paid for weeks: payroll-like


def test_structuring_needs_amounts_just_under_threshold():
    thr = CFG["threshold_inr"]
    near = [(i, f"S{i}", "H", 0.93 * thr + i * 50) for i in range(8)]
    al = fan_alerts(frame(near), CFG)
    st = [a for a in al if a["typology"] == "structuring"]
    assert len(st) == 1 and st[0]["evidence"]["n_structured"] == 8 and st[0]["entry_nodes"] == sorted(f"S{i}" for i in range(8))
    far = [(i, f"S{i}", "H", 12_000 + i * 50) for i in range(8)]
    assert not [a for a in fan_alerts(frame(far), CFG) if a["typology"] == "structuring"]


def test_merchant_like_fan_in_scores_below_a_ring_like_fan_in():
    rng = np.random.default_rng(0)
    ring = [(i, f"S{i}", "H", 47_000 + i) for i in range(10)]
    shop = [(i * 5, f"C{i}", "M", float(rng.lognormal(6.5, 1.0))) for i in range(10)]
    s_ring = max(a["score"] for a in fan_alerts(frame(ring), CFG) if a["typology"] == "structuring")
    s_shop = max(a["score"] for a in fan_alerts(frame(shop), CFG) if a["typology"] == "fan_in")
    assert s_ring > s_shop


# ---------------------------------------------------------------- round tripping
def test_round_trip_requires_time_order_retention_and_duration():
    ok = frame([(0, "A", "B", 100_000), (10, "B", "C", 95_000), (20, "C", "A", 90_000)])
    (a,) = roundtrip_alerts(ok, CFG)
    assert a["evidence"]["n_hops"] == 3 and 0.93 < a["evidence"]["retention_mean"] < 0.96
    wrong_order = frame([(20, "A", "B", 100_000), (10, "B", "C", 95_000), (0, "C", "A", 90_000)])
    assert roundtrip_alerts(wrong_order, CFG) == []                       # not a time-ordered path
    growing = frame([(0, "A", "B", 100_000), (10, "B", "C", 150_000), (20, "C", "A", 220_000)])
    assert roundtrip_alerts(growing, CFG) == []                           # money should not grow around a loop
    slow = frame([(0, "A", "B", 100_000), (60, "B", "C", 95_000), (120, "C", "A", 90_000)])
    assert roundtrip_alerts(slow, CFG) == []                              # over 72 hours


def test_round_trip_known_pairs_score_lower():
    rows = [(0, "A", "B", 100_000), (10, "B", "C", 95_000), (20, "C", "A", 90_000)]
    new, old = roundtrip_alerts(frame(rows), CFG)[0], roundtrip_alerts(frame(rows, known_before=24 * 30), CFG)[0]
    assert old["score"] < new["score"]


# ---------------------------------------------------------------- pass-through chains
def _data(rows):
    df = frame(rows)
    df["tx_id"] = np.arange(len(df))
    s, r = df["sender"].to_numpy(dtype=object), df["receiver"].to_numpy(dtype=object)
    return SimpleNamespace(cfg=CFG, tx=df, send_rows=_group_index(s, np.arange(len(df))), recv_rows=_group_index(r, np.arange(len(df))))


def test_mule_chain_found_as_one_chain_with_dwell_and_ratio():
    d = _data([(0, "A", "B", 500_000), (1, "B", "C", 470_000), (3, "C", "D", 440_000), (4, "D", "E", 415_000)])
    ev = compute_pass_events(d)
    assert set(ev["account"]) == {"B", "C", "D"} and (ev["ratio"] > 0.9).all()
    (a,) = passthrough_alerts(d, ev, 0.0, 10 * H)
    assert set(a["accounts"]) == set("ABCDE") and a["evidence"]["n_pass_accounts"] == 3
    assert a["entry_nodes"] == ["A"] and a["exit_nodes"] == ["E"]


def test_daily_settlement_shop_scores_below_a_mule():
    mule = _data([(0, "A", "B", 500_000), (1, "B", "C", 470_000), (3, "C", "D", 440_000)])
    rows = [(h, f"cust{h}", "SHOP", 3000) for h in range(0, 8)] + [(8, "SHOP", "OWNER", 22_800)]
    rows += [(24 * 3 + h, f"cust{h}x", "SHOP", 3000) for h in range(0, 8)] + [(24 * 3 + 8, "SHOP", "OWNER", 22_800)]
    shop = _data(rows)
    ev_m, ev_s = compute_pass_events(mule), compute_pass_events(shop)
    s_m = passthrough_alerts(mule, ev_m, 0.0, 10 * H)[0]["score"]
    s_shop = passthrough_alerts(shop, ev_s, 3 * 24 * H, 5 * 24 * H)[0]["score"]
    assert s_shop < s_m                                                   # many inflows + repeated daily
