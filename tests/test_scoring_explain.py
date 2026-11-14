"""Stages 4-5: scoring, de-duplication, threshold selection, typology labels, summaries."""
import copy

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import average_precision_score

from src.config import DAY, load_config
from src.explain.summary import allowed_numbers, numbers_in, summarize, unsupported_numbers
from src.explain.typology import TYPOLOGY_NAMES, label_cluster
from src.scoring.features import HAND_PRIOR, feature_frame, hand_components
from src.scoring.models import HandScorer, XGBScorer, top_contributors
from src.scoring.select import choose_threshold, dedupe

CFG = load_config()


# ---------------------------------------------------------------- scoring
def comps(n=400, seed=0):
    rng = np.random.default_rng(seed)
    y = (rng.random(n) < 0.15).astype(int)
    c = pd.DataFrame({k: rng.random(n) * 0.5 for k in HAND_PRIOR})
    c.loc[y == 1, "shared funding / owner"] += 0.5                       # only this component actually separates
    return c.clip(0, 1), y


def test_hand_scorer_tuning_does_not_hurt_and_finds_the_informative_weight():
    c, y = comps()
    prior = HandScorer(0, 0)
    prior.w = np.array([HAND_PRIOR[n] for n in prior.names], float)
    tuned = HandScorer(0, 150).fit(c, y)
    assert average_precision_score(y, tuned.score(c)) >= average_precision_score(y, prior.score(c))
    assert tuned.names[int(np.argmax(tuned.w / np.array([HAND_PRIOR[n] for n in tuned.names])))] == "shared funding / owner"


def test_hand_score_is_0_to_100_and_contributions_sum_to_score():
    c, y = comps()
    s = HandScorer(0, 10).fit(c, y)
    sc, ct = s.score(c), s.contributions(c)
    assert sc.min() >= 0 and sc.max() <= 100
    np.testing.assert_allclose(ct.sum(axis=1).to_numpy(), sc)


def test_xgb_scorer_ranks_positives_higher_and_shap_contributions_have_right_shape():
    rng = np.random.default_rng(1)
    X = pd.DataFrame(rng.random((500, 5)), columns=list("abcde"))
    y = (X["b"] > 0.7).astype(int).to_numpy()
    m = XGBScorer(CFG, 0).fit(X, y)
    s = m.score(X)
    assert average_precision_score(y, s) > 0.9
    ct = m.contributions(X.iloc[:20])
    assert ct.shape == (20, 5) and ct.abs().mean().idxmax() == "b"
    top = top_contributors(ct.iloc[0], 3)
    assert len(top) <= 3 and all(t["value"] > 0 for t in top)


def test_feature_frame_marks_layer_and_leaves_inapplicable_features_nan():
    cl = [dict(layer="money", features=dict(n_tx=5.0, internal_share=0.9)), dict(layer="trade", features=dict(t_n_trades=9.0))]
    f = feature_frame(cl)
    assert f.loc[0, "is_trade"] == 0 and f.loc[1, "is_trade"] == 1
    assert np.isnan(f.loc[1, "n_tx"]) and np.isnan(f.loc[0, "t_n_trades"])
    assert hand_components(f).notna().all().all()                         # NaN counts as zero in the hand score


# ---------------------------------------------------------------- dedupe and threshold
def al(accts, day, score, layer="money"):
    return dict(accounts=accts, t_start=day * DAY, layer=layer, score=score, typology="fan_out")


def test_dedupe_merges_the_same_ring_seen_in_several_windows_but_not_different_rings():
    out = dedupe([al(["a", "b", "c"], 1, 50), al(["a", "b", "c", "d"], 2, 90), al(["x", "y", "z"], 2, 60)])
    assert [a["score"] for a in out] == [90, 60]
    assert len(dedupe([al(["a", "b", "c"], 1, 50), al(["a", "b", "c"], 40, 55)])) == 2      # far apart in time: separate events


def test_dedupe_prefers_the_cross_layer_chain_on_a_tie():
    out = dedupe([al(["D1", "D2", "D3"], 1, 99.91, "trade"), al(["B0000001", "D1", "D2", "D3", "B2"], 1, 99.93, "bridge")])
    assert len(out) == 1 and out[0]["layer"] == "bridge"


def test_choose_threshold_respects_the_fpr_cap_on_validation(built):
    from src.eval.metrics import GroundTruth, evaluate
    from src.graph.prep import load_data
    data = load_data(built["cfg"])
    gt = GroundTruth(data)
    rng = np.random.default_rng(0)
    ring_sets = [r["accounts"] for r in data.rings if r["split"] == "val"]
    innocents = sorted(gt.innocent_all & gt.active["val"])
    alerts = [dict(accounts=a, t_start=70 * DAY, layer="money", score=float(rng.uniform(60, 100)), typology="fan_out") for a in ring_sets]
    alerts += [dict(accounts=list(rng.choice(innocents, 3, replace=False)), t_start=70 * DAY, layer="money",
                    score=float(rng.uniform(0, 100)), typology="fan_out") for _ in range(300)]
    cap = 0.002
    thr = choose_threshold(alerts, gt, cap, "val")
    assert evaluate(dedupe([a for a in alerts if a["score"] >= thr]), gt, "val")["fpr"] <= cap


# ---------------------------------------------------------------- typology
def cluster(layer="money", **dets):
    return dict(layer=layer, features={"exit_chain_share": 1.0}, detectors={k: dict(score=v, evidence={}) for k, v in dets.items()})


@pytest.mark.parametrize("dets,primary", [
    (dict(fan_out=0.8), "fan_out"), (dict(fan_in=0.6, structuring=0.7), "fan_in_structuring"), (dict(fan_in=0.7), "fan_in"),
    (dict(round_trip=0.9, pass_through=0.5), "round_trip"), (dict(pass_through=0.9), "mule_chain"),
    (dict(wash_trading=0.6, loss_booking=0.4), "loss_booking"), (dict(wash_trading=0.6), "wash_trading"), ({}, "unclassified_anomaly")])
def test_typology_mapping(dets, primary):
    lab = label_cluster(cluster(**dets), 90.0)
    assert lab["primary"] == primary and 0 <= lab["confidence"] <= 1 and primary in TYPOLOGY_NAMES


def test_fan_in_followed_by_pass_through_names_the_secondary_typology():
    assert label_cluster(cluster(structuring=0.7, pass_through=0.6))["secondary"] == "mule_chain"


def test_bridge_layer_is_always_market_layering():
    assert label_cluster(cluster("bridge", wash_trading=0.5))["primary"] == "market_layering"


# ---------------------------------------------------------------- summaries
EVIDENCE = {
    "fan_in_structuring": dict(hub="B0000001", total_inr=482_000.0, n_counterparties=9, span_hours=47.5, n_structured=9, n_tx=10,
                               band_low_inr=45_000.0, band_high_inr=49_800.0, threshold_inr=50_000.0, pass_forward_share=0.94,
                               pass_dwell_hours=2.6),
    "fan_out": dict(hub="B0000001", total_inr=1_200_000.0, n_counterparties=12, span_hours=20.0, amount_cv=0.07, known_share=0.0, new_pair_share=1.0),
    "round_trip": dict(origin="B0000001", n_hops=4, duration_hours=30.5, retention_mean=0.94, amount_start_inr=900_000.0, amount_end_inr=700_000.0),
    "mule_chain": dict(source="B0000001", sink="B0000009", amount_in_inr=450_000.0, n_pass_accounts=4, ratio_mean=0.93, dwell_median_hours=2.7),
    "wash_trading": dict(n_accounts=6, stock="SMLX", n_trades=41, n_days=3, internal_volume_share=0.96, net_position_ratio=0.02,
                         funding_source="B0000007", n_owners_funded=5, n_owners=6, funded_inr=540_000.0),
    "loss_booking": dict(n_accounts=2, stock="SMLY", n_trades=18, reversal_days=5, mean_price_deviation=0.31,
                         max_price_deviation=0.58, pnl_asymmetry=0.2),
    "market_layering": dict(n_owners=5, funding_source="B0000007", funded_inr=540_000.0, stock="SMLX", n_trades=30,
                            internal_volume_share=0.8, withdrawn_inr=480_000.0, exit_account="B0000009"),
    "unclassified_anomaly": dict(n_accounts=5, amount_inr=190_000.0, n_tx=4, internal_share=0.24),
}


@pytest.mark.parametrize("typ", list(EVIDENCE))
def test_every_number_in_a_summary_comes_from_the_alert_evidence(typ):
    ev = dict(EVIDENCE[typ], entry_label="B0000001", exit_label="B0000009, B0000010 and others", risk_score=87.0,
              driver_1_label="shared funding", driver_1_pct=40.0, driver_2_label="timing", driver_2_pct=25.0)
    a = dict(typology=typ, evidence=ev, score=87.0)
    a["summary"] = summarize(a)
    assert unsupported_numbers(a) == set(), a["summary"]
    assert "Risk score: 87." in a["summary"]


def test_summary_matches_the_example_style():
    ev = dict(EVIDENCE["fan_in_structuring"], risk_score=87.0)
    s = summarize(dict(typology="fan_in_structuring", evidence=ev, score=87.0))
    assert "INR 4.8L from 9 accounts" in s and "forwarded 94%" in s and "fan-in followed by pass-through" in s


def test_the_check_catches_an_invented_number():
    a = dict(typology="fan_out", evidence=EVIDENCE["fan_out"], score=87.0)
    a["summary"] = summarize(a) + " It happened within 48 hours."
    assert "48" in unsupported_numbers(a)


def test_number_extraction_ignores_account_ids_and_commas():
    assert numbers_in("Account B0012345 sent INR 45,000 to D0000007 in LRGA, 3 times") == {"45000", "3"}
    assert "5" in allowed_numbers(dict(x=0.05)) and "4.8" in allowed_numbers(dict(x=480_000.0))


def test_real_pipeline_alerts_have_supported_summaries_and_required_fields(pipeline_out):
    alerts = pipeline_out["alerts"]
    assert alerts
    for a in alerts:
        assert unsupported_numbers(a) == set(), (a["alert_id"], a["summary"])
        assert a["typology"] in TYPOLOGY_NAMES and a["summary"].endswith(".")
        assert {"alert_id", "layer", "accounts", "score", "evidence", "entry_nodes", "exit_nodes", "window_start",
                "window_end", "tx_ids", "trade_ids", "contributions"} <= set(a)
        assert "Risk score:" in a["summary"] and len(a["contributions"]) <= 3
    assert [a["score"] for a in alerts] == sorted((a["score"] for a in alerts), reverse=True)
