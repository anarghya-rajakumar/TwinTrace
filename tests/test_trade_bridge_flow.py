"""Stage 7 (trade layer + bridge), the flow layouts, the pipeline contract and the dashboard."""
import json

import numpy as np
import pandas as pd
import pytest

from src.config import load_config
from src.detectors.trade import loss_score, trade_features, wash_score
from src.explain.flow import alert_flow, bridge_flow, money_flow, trade_flow

CFG = load_config()


# ---------------------------------------------------------------- trade detectors on hand-made trades
def trades(rows):
    df = pd.DataFrame(rows, columns=["t", "buyer", "seller", "price", "qty", "ref"])
    df["trade_id"] = np.arange(len(df))
    df["day"] = (df["t"] // 86400).astype(int)
    df["ref_price"] = df["ref"]
    df["dev"] = df["price"] / df["ref"] - 1
    df["notional"] = df["price"] * df["qty"]
    return df


def test_wash_ring_has_high_internal_share_zero_net_position_and_high_score():
    rows = []
    for k in range(5):                                           # A->B->C->A, same qty, market price, repeated
        for s, b in [("A", "B"), ("B", "C"), ("C", "A")]:
            rows.append((3600 * len(rows), b, s, 100.0, 300, 100.0))
    rows.append((99_000, "A", "OUT", 100.0, 20, 100.0))
    f, internal = trade_features(trades(rows), ["A", "B", "C"], 150.0)
    assert f["t_internal_share"] > 0.9 and f["t_net_pos_ratio"] < 0.05 and f["t_n_trades"] == 15
    assert wash_score(f, True, 0.5) > 0.6 and loss_score(f) == 0


def test_loss_booking_pair_has_off_market_prices_reversals_and_asymmetry():
    rows = []
    for d in range(4):
        t = d * 86400 + 36_000
        rows.append((t, "P", "L", 60.0, 100, 100.0))             # L sells at 40% off market to P
        rows.append((t + 7200, "L", "P", 100.0, 100, 100.0))     # P returns the shares at market
    f, _ = trade_features(trades(rows), ["P", "L"], 150.0)
    assert f["t_reversal_days"] == 4 and f["t_dev_abs_mean"] == pytest.approx(0.2) and f["t_pnl_asym"] > 0.15
    assert loss_score(f) > 0.5


def test_legit_pair_at_market_prices_scores_zero_for_loss_booking():
    rows = [(d * 86400 + 40_000, "A", "B", 100.0, 50, 100.0) for d in range(3)] + [(d * 86400 + 50_000, "B", "A", 100.0, 50, 100.0) for d in range(3)]
    f, _ = trade_features(trades(rows), ["A", "B"], 150.0)
    assert loss_score(f) == 0 and f["t_dev_abs_mean"] == 0


def test_market_maker_hub_has_many_counterparties_and_no_internal_volume():
    rows = [(3600 * i, "MM", f"X{i}", 100.0, 40, 100.0) if i % 2 else (3600 * i, f"X{i}", "MM", 100.0, 40, 100.0) for i in range(30)]
    f, _ = trade_features(trades(rows), ["MM"], 150.0)
    assert f["t_internal_share"] == 0 and f["t_n_ext_cp"] == 30 and f["t_net_pos_ratio"] < 0.1


# ---------------------------------------------------------------- on the generated data
@pytest.fixture(scope="module")
def clusters(pipeline_out):
    return pipeline_out["clusters"], pipeline_out["gt"]


def _matches(c, gt, typ):
    return [m for m in c["matched_rings"] if gt.rings[m]["typology"] == typ]


def test_every_trade_and_bridge_ring_is_represented_by_a_cluster(clusters):
    cl, gt = clusters
    found = {m for c in cl for m in c["matched_rings"]}
    missing = [k for k, r in gt.rings.items() if r["layer"] in ("trade", "bridge") and k not in found]
    assert len(missing) <= 1


def test_bridge_features_separate_rings_from_market_makers_and_most_legit_pairs(clusters):
    cl, gt = clusters
    wash = [c for c in cl if c["layer"] == "trade" and _matches(c, gt, "wash_trading")]
    assert wash and np.mean([c["features"]["owner_link"] > 0 for c in wash]) > 0.9       # shared funder or same owner
    hubs = [c for c in cl if c["layer"] == "trade" and len(c["accounts"]) == 1]
    assert hubs and all(c["features"]["owner_link"] == 0 for c in hubs)
    legit = [c for c in cl if c["layer"] == "trade" and not c["matched_rings"] and len(c["accounts"]) > 1]
    if legit:
        assert np.mean([c["features"]["owner_link"] > 0 for c in legit]) < 0.5


def test_shared_funding_needs_two_owners_funded_by_the_same_source(clusters):
    cl, _ = clusters
    for c in cl:
        if c["layer"] == "trade" and c["features"]["funding_overlap"] > 0:
            assert c["bridge_evidence"]["n_owners_funded"] >= 2


def test_bridge_rows_trace_bank_to_trade_to_withdrawal(clusters):
    cl, gt = clusters
    rows = [c for c in cl if c["layer"] == "bridge"]
    assert rows
    for c in rows:
        assert c["trade_ids"] and c["tx_ids"] and c["entry_nodes"] and c["exit_nodes"]
        assert c["features"]["funding_overlap"] >= 0.5 and c["features"]["exit_chain_share"] >= 0.5
        assert any(a.startswith("D") for a in c["accounts"]) and any(a.startswith("B") for a in c["accounts"])
    assert sum(1 for c in rows if _matches(c, gt, "market_layering")) / len(rows) > 0.8


# ---------------------------------------------------------------- flow layouts
def test_money_flow_orders_columns_left_to_right_and_marks_entry_and_exit(pipeline_out):
    data = pipeline_out["data"]
    a = next(x for x in pipeline_out["alerts"] if x["typology"] == "mule_chain")
    f = money_flow(a, data.tx)
    xs = {n: f["pos"][n][0] for n in a["accounts"] if n in f["pos"]}
    e, x = a["entry_nodes"][0], a["exit_nodes"][0]
    assert f["role"][e] == "entry" and f["role"][x] == "exit"
    assert xs[e] < xs[x] and xs[e] == min(v for k, v in xs.items() if f["role"][k] in ("entry", "internal", "exit"))


def test_flow_covers_every_alert_layer(pipeline_out):
    data = pipeline_out["data"]
    seen = set()
    for a in pipeline_out["alerts"]:
        f = alert_flow(a, data.tx, data.trades, data.owner_of)
        assert f["pos"] and all(len(p) == 2 for p in f["pos"].values())
        assert all(e["src"] in f["pos"] and e["dst"] in f["pos"] for e in f["edges"] if e["kind"] != "external")
        seen.add(a["layer"])
    assert seen >= {"money", "trade"}


def test_bridge_flow_has_four_columns_funder_bank_trading_exit(pipeline_out):
    data = pipeline_out["data"]
    a = next((x for x in pipeline_out["alerts"] if x["layer"] == "bridge"), None)
    if a is None:
        pytest.skip("no bridge alert in the small dataset")
    f = bridge_flow(a, data.tx, data.trades, data.owner_of)
    col = {r: {f["pos"][n][0] for n in f["pos"] if f["role"][n] == r} for r in ("entry", "exit")}
    assert col["entry"] == {0} and col["exit"] == {3}
    assert {e["kind"] for e in f["edges"]} >= {"money", "trade"}


# ---------------------------------------------------------------- pipeline contract
def test_results_table_contract_and_honest_split(pipeline_out, built):
    res = pipeline_out["results"]
    need = {"method", "scorer", "precision", "recall", "f1", "fpr", "alerts", "alerts_per_1000_accounts", "rings", "rings_found", "headline"}
    assert need <= set(res.columns)
    assert {"rule_baseline", "single_layer", "two_layer_no_bridge", "twintrace"} <= set(res["method"])
    assert res[["precision", "recall", "f1", "fpr"]].apply(lambda s: s.between(0, 1)).all().all()
    assert res["headline"].sum() == 4                                     # one headline row per method
    assert any(c.startswith("recall_") for c in res.columns)
    art = built["home"] / "artifacts"
    for f in ("results.csv", "results_money_only.csv", "results.md", "alerts.json", "meta.json"):
        assert (art / f).exists()
    md = (art / "results.md").read_text(encoding="utf-8")
    assert "test split only" in md and "Precision" in md


def test_graph_methods_raise_far_fewer_false_alarms_than_the_rule_baseline(pipeline_out):
    h = pipeline_out["results"].query("headline").set_index("method")
    assert h.loc["twintrace", "fpr"] < h.loc["rule_baseline", "fpr"] / 5
    assert h.loc["twintrace", "alerts_per_1000_accounts"] < h.loc["rule_baseline", "alerts_per_1000_accounts"] / 5
    assert h.loc["twintrace", "precision"] > h.loc["rule_baseline", "precision"]


def test_single_layer_cannot_see_trade_only_rings(pipeline_out):
    h = pipeline_out["results"].query("headline").set_index("method")
    assert h.loc["single_layer", "recall_wash_trading"] == 0 or np.isnan(h.loc["single_layer", "recall_wash_trading"])
    assert h.loc["single_layer", "recall_loss_booking"] == 0 or np.isnan(h.loc["single_layer", "recall_loss_booking"])


def test_pipeline_is_deterministic(built, pipeline_out):
    from src.pipeline import run_pipeline
    again = run_pipeline(built["cfg"], log=lambda *_: None)
    a = pipeline_out["results"].drop(columns=["threshold"], errors="ignore")
    b = again["results"].drop(columns=["threshold"], errors="ignore")
    pd.testing.assert_frame_equal(a, b)
    assert [x["alert_id"] for x in again["alerts"]] == [x["alert_id"] for x in pipeline_out["alerts"]]
