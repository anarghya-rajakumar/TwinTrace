"""Stage 2: matching rule, metrics, time-based splits, baseline, registry outputs."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.config import DAY, load_config, split_bounds, split_of
from src.eval.baseline import rule_baseline
from src.eval.metrics import GroundTruth, evaluate, match_alert

CFG = load_config()


def test_match_rule_both_directions():
    ring = {"a", "b", "c", "d"}
    assert match_alert({"a", "b", "x"}, ring, 0.5)             # 2/3 of the alert is in the ring
    assert match_alert({"a", "b", "x", "y", "z", "w"}, ring, 0.5)   # alert covers 2/4 of the ring
    assert not match_alert({"a", "x", "y", "z", "w"}, ring, 0.5)    # neither clause
    assert not match_alert({"x", "y"}, ring, 0.5)


def test_splits_are_contiguous_in_time_and_60_20_20():
    b = split_bounds(CFG)
    assert b["tune"][0] == 0 and b["tune"][1] == b["val"][0] and b["val"][1] == b["test"][0]
    total = CFG["n_days"] * DAY
    assert abs(b["tune"][1] / total - 0.6) < 1e-9 and abs(b["val"][1] / total - 0.8) < 1e-9
    assert split_of(1.0, CFG) == "tune" and split_of(0.7 * total, CFG) == "val" and split_of(0.9 * total, CFG) == "test"


def toy():
    day = DAY
    accounts = pd.DataFrame({"account_id": [f"B{i}" for i in range(100)], "owner_id": "o", "layer": "bank", "account_type": "x"})
    tx = pd.DataFrame({"t": np.linspace(0, 89 * day, 400), "sender": [f"B{i % 100}" for i in range(400)],
                       "receiver": [f"B{(i + 1) % 100}" for i in range(400)]})
    trades = pd.DataFrame({"t": [], "buyer": [], "seller": []})
    rings = [dict(ring_id="R1", layer="money", typology="fan_out", accounts=["B1", "B2", "B3", "B4"], split="test"),
             dict(ring_id="R2", layer="money", typology="mule_chain", accounts=["B10", "B11", "B12"], split="test"),
             dict(ring_id="R3", layer="money", typology="fan_out", accounts=["B20", "B21", "B22"], split="val")]
    return SimpleNamespace(cfg=CFG, rings=rings, tx=tx, trades=trades, accounts=accounts)


def alert(accts, day, layer="money", typ="fan_out"):
    return dict(accounts=accts, t_start=day * DAY, layer=layer, typology=typ)


def test_perfect_alerts_give_precision_recall_one_and_zero_fpr():
    gt = GroundTruth(toy())
    m = evaluate([alert(["B1", "B2", "B3", "B4"], 80), alert(["B10", "B11", "B12"], 85, typ="mule_chain")], gt, "test")
    assert m["precision"] == 1 and m["recall"] == 1 and m["f1"] == 1 and m["fpr"] == 0
    assert m["per_typology_recall"] == {"fan_out": 1.0, "mule_chain": 1.0} and m["typology_accuracy"] == 1


def test_false_alarm_hits_precision_and_fpr_not_recall():
    gt = GroundTruth(toy())
    m = evaluate([alert(["B1", "B2", "B3", "B4"], 80), alert(["B50", "B51", "B52"], 80)], gt, "test")
    assert m["precision"] == 0.5 and m["recall"] == 0.5
    assert m["fpr"] == pytest.approx(3 / gt.n_innocent_active["test"])
    assert m["alerts_per_1000_accounts"] == pytest.approx(2000 / gt.n_active["test"])


def test_alerts_outside_the_split_are_ignored():
    gt = GroundTruth(toy())
    m = evaluate([alert(["B1", "B2", "B3", "B4"], 10), alert(["B20", "B21", "B22"], 60)], gt, "test")
    assert m["alerts"] == 0 and m["recall"] == 0                          # tune/val alerts never leak into test
    assert evaluate([alert(["B20", "B21", "B22"], 60)], gt, "val")["recall"] == 1


def test_wrong_typology_label_lowers_typology_accuracy_only():
    gt = GroundTruth(toy())
    m = evaluate([alert(["B10", "B11", "B12"], 85, typ="fan_out")], gt, "test")
    assert m["precision"] == 1 and m["typology_accuracy"] == 0


def test_baseline_flags_large_transfers_and_structuring_and_reports_alerts(tables, built):
    from src.graph.prep import load_data
    data = load_data(built["cfg"])
    al = rule_baseline(data)
    assert {a["typology"] for a in al} >= {"rule_large_transaction", "rule_structuring"}
    assert all(a["alert_id"] is None and len(a["accounts"]) == 1 for a in al)
    thr = built["cfg"]["threshold_inr"]
    big = data.tx[data.tx["amount"] >= thr]
    flagged = {x for a in al if a["typology"] == "rule_large_transaction" for x in a["accounts"]}
    assert set(big["sender"]) <= flagged and set(big["receiver"]) <= flagged
    gt = GroundTruth(data)
    m = evaluate(al, gt, "test")
    assert 0 < m["fpr"] and m["precision"] < 0.5                          # the point of the baseline: many false alarms
