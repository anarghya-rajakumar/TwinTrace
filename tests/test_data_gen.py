"""Stage 1: schema, ring properties from the brief, hard negatives, bridge, determinism, IBM loader."""
import numpy as np
import pandas as pd
import pytest

from src.config import DAY, load_config
from src.data_gen.background import load_ibm_slice
from src.data_gen.build import build
from src.data_gen.patterns import parse_ibm_patterns

H = 3600.0


def rings_of(tables, typ):
    return [r for r in tables["rings"] if r["typology"] == typ]


def test_schemas(tables):
    assert list(tables["tx"].columns) == ["tx_id", "ts", "sender", "receiver", "amount_inr", "currency",
                                          "payment_format", "is_laundering_base"]
    assert list(tables["trades"].columns) == ["trade_id", "ts", "stock", "buyer", "seller", "price", "qty"]
    assert list(tables["accounts"].columns) == ["account_id", "owner_id", "layer", "account_type"]
    assert set(tables["accounts"]["layer"]) == {"bank", "demat"}
    assert tables["tx"]["tx_id"].is_unique and tables["trades"]["trade_id"].is_unique
    assert (tables["tx"]["currency"] == "INR").all()


def test_ninety_day_window_and_order(tables, built):
    tx = tables["tx"]
    t0 = pd.Timestamp(built["cfg"]["start_date"])
    assert tx["ts"].min() >= t0 and (tx["ts"].max() - t0) <= pd.Timedelta(days=built["cfg"]["n_days"])
    assert tx["ts"].is_monotonic_increasing


def test_ring_json_fields_and_all_typologies(tables):
    need = {"ring_id", "layer", "typology", "accounts", "tx_ids", "trade_ids"}
    assert all(need <= set(r) for r in tables["rings"])
    got = {r["typology"] for r in tables["rings"]}
    assert {"fan_out", "fan_in_structuring", "round_trip", "mule_chain", "wash_trading", "loss_booking",
            "market_layering"} <= got
    assert {r["layer"] for r in tables["rings"]} == {"money", "trade", "bridge"}


def test_structuring_amounts_just_under_threshold(tables, built):
    thr = built["cfg"]["threshold_inr"]
    tx = tables["tx"].set_index("tx_id")
    for r in rings_of(tables, "fan_in_structuring"):
        a = tx.loc[r["tx_ids"], "amount_inr"].to_numpy()
        n_band = ((a >= 0.9 * thr) & (a <= 0.998 * thr)).sum()
        assert n_band >= len(a) - 1                      # all but the optional forwarding transfer
        assert 45_000 <= thr * 0.9 and thr * 0.998 <= 49_900 + 1


def test_round_trip_cycles(tables):
    tx = tables["tx"].set_index("tx_id")
    for r in rings_of(tables, "round_trip"):
        d = tx.loc[r["tx_ids"]].sort_values("ts")
        assert 3 <= len(d) <= 6
        assert (d["ts"].max() - d["ts"].min()).total_seconds() <= 72 * H
        assert d["sender"].iloc[0] == d["receiver"].iloc[-1]                     # money returns to its origin
        ratios = d["amount_inr"].to_numpy()[1:] / d["amount_inr"].to_numpy()[:-1]
        assert ((ratios >= 0.899) & (ratios <= 0.991)).all()                     # 90-99% retained per hop


def test_mule_chain_dwell_and_pass_ratio(tables):
    tx = tables["tx"].set_index("tx_id")
    for r in rings_of(tables, "mule_chain"):
        d = tx.loc[r["tx_ids"]].sort_values("ts")
        assert 4 <= len(d) <= 8
        dwell = d["ts"].diff().dropna().dt.total_seconds().to_numpy()
        assert ((dwell >= 299) & (dwell <= 6 * H + 1)).all()
        ratios = d["amount_inr"].to_numpy()[1:] / d["amount_inr"].to_numpy()[:-1]
        assert ((ratios >= 0.899) & (ratios <= 0.981)).all()


def test_wash_rings_internal_volume_and_net_position(tables):
    tr = tables["trades"].set_index("trade_id")
    for r in rings_of(tables, "wash_trading"):
        mem = set(r["accounts"])
        assert 3 <= len(mem) <= 8
        d = tr.loc[r["trade_ids"]]
        internal = d[d["buyer"].isin(mem) & d["seller"].isin(mem)]
        assert 0.6 <= internal["qty"].sum() / d["qty"].sum() <= 0.99
        net = {m: d.loc[d.buyer == m, "qty"].sum() - d.loc[d.seller == m, "qty"].sum() for m in mem}
        gross = d.loc[d.buyer.isin(mem), "qty"].sum() + d.loc[d.seller.isin(mem), "qty"].sum()
        assert sum(abs(v) for v in net.values()) / gross < 0.35                   # net position near zero


def test_loss_booking_pairs_reverse_same_day_off_market(tables):
    tr = tables["trades"]
    ref = tr.assign(day=tr["ts"].dt.floor("D")).groupby(["stock", "day"])["price"].transform("median")
    tr = tr.assign(dev=(tr["price"] / ref - 1).abs()).set_index("trade_id")
    for r in rings_of(tables, "loss_booking"):
        mem = set(r["accounts"])
        d = tr.loc[r["trade_ids"]]
        pair = d[d["buyer"].isin(mem) & d["seller"].isin(mem)]
        assert len(mem) == 2 and len(pair) >= 6
        assert pair["ts"].dt.floor("D").nunique() >= 3                           # repeated on several days
        assert (pair["dev"] > 0.1).sum() >= len(pair) / 2 - 1                   # half of the legs are 20-60% off market


def test_bridge_links_owners_and_funding(tables):
    acc = tables["accounts"].set_index("account_id")
    bank_owners = set(acc[acc.layer == "bank"]["owner_id"])
    for r in tables["rings"]:
        if r["layer"] == "trade":
            owners = {acc.loc[a, "owner_id"] for a in r["accounts"]}
            assert owners <= bank_owners                                         # every trading owner has a bank account
            if r.get("funding_mode") == "shared_funder":
                assert len(r["funding_tx_ids"]) >= len(r["accounts"])
            elif r.get("funding_mode") == "same_owner":
                assert len(owners) < len(r["accounts"]) or len(r["accounts"]) == 1
        if r["layer"] == "bridge":
            assert any(a.startswith("D") for a in r["accounts"]) and any(a.startswith("B") for a in r["accounts"])
            assert r["tx_ids"] and r["trade_ids"]


def test_hard_negatives_exist_for_every_kind(tables):
    kinds = {h["kind"] for h in tables["hards"]}
    assert kinds == {"payroll_fanout", "rent_fanin", "shop_settlement", "family_circular", "market_maker",
                     "legit_repeat_pair"}
    ring_accts = {a for r in tables["rings"] for a in r["accounts"]}
    assert not ring_accts & {a for h in tables["hards"] for a in h["accounts"]}   # innocents are never labelled as rings


def test_hard_negative_shapes(tables):
    tx = tables["tx"].set_index("tx_id")
    pay = [h for h in tables["hards"] if h["kind"] == "payroll_fanout"][0]
    d = tx.loc[pay["tx_ids"]]
    assert d["sender"].nunique() == 1 and d["receiver"].nunique() >= 20          # one payer, many employees, recurring
    assert len(d) >= 2 * d["receiver"].nunique() - 1
    shop = [h for h in tables["hards"] if h["kind"] == "shop_settlement"][0]
    s_acct = shop["accounts"][0]
    d = tx.loc[shop["tx_ids"]]
    assert (d["sender"] == s_acct).sum() >= 20 and (d["receiver"] == s_acct).sum() > 3 * (d["sender"] == s_acct).sum()


def test_deterministic_given_seed(small_cfg, tmp_path, monkeypatch):
    out = []
    for i in range(2):
        monkeypatch.setenv("TWINTRACE_HOME", str(tmp_path / f"run{i}"))
        build(small_cfg, verbose=False)
        out.append(pd.read_parquet(tmp_path / f"run{i}" / "data" / "processed" / "transactions.parquet"))
    pd.testing.assert_frame_equal(out[0], out[1])


def test_seed_changes_data(small_cfg, tmp_path, monkeypatch):
    import copy
    monkeypatch.setenv("TWINTRACE_HOME", str(tmp_path / "a"))
    build(small_cfg, verbose=False)
    c2 = copy.deepcopy(small_cfg)
    c2["seed"] = small_cfg["seed"] + 1
    monkeypatch.setenv("TWINTRACE_HOME", str(tmp_path / "b"))
    build(c2, verbose=False)
    a = pd.read_parquet(tmp_path / "a" / "data" / "processed" / "transactions.parquet")
    b = pd.read_parquet(tmp_path / "b" / "data" / "processed" / "transactions.parquet")
    assert not a["amount_inr"].head(200).equals(b["amount_inr"].head(200))


# ------------------------------------------------------------------ IBM loader on a file in the real format
def _fake_ibm(tmp_path):
    rng = np.random.default_rng(0)
    accts = [("010", f"8000{i:04X}") for i in range(40)]
    rows = []
    base = pd.Timestamp("2022-09-01")
    for i in range(300):
        a, b = rng.choice(len(accts), 2, replace=False)
        ts = (base + pd.Timedelta(minutes=int(rng.integers(0, 9 * 24 * 60)))).strftime("%Y/%m/%d %H:%M")
        amt = round(float(rng.uniform(10, 5000)), 2)
        rows.append(f"{ts},{accts[a][0]},{accts[a][1]},{accts[b][0]},{accts[b][1]},{amt},US Dollar,{amt},US Dollar,Cheque,0")
    laund = []
    for j in range(6):                                          # a fan-out laundering attempt
        ts = (base + pd.Timedelta(days=3, minutes=j * 7)).strftime("%Y/%m/%d %H:%M")
        laund.append(f"{ts},010,{accts[0][1]},010,{accts[1 + j][1]},777.0,US Dollar,777.0,US Dollar,ACH,1")
    csv = tmp_path / "HI-Small_Trans.csv"
    csv.write_text("Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,Amount Paid,"
                   "Payment Currency,Payment Format,Is Laundering\n" + "\n".join(rows + laund) + "\n")
    pat = tmp_path / "HI-Small_Patterns.txt"
    pat.write_text("BEGIN LAUNDERING ATTEMPT - FAN-OUT\n" + "\n".join(laund) + "\nEND LAUNDERING ATTEMPT - FAN-OUT\n")
    return csv, pat


def test_ibm_patterns_parser(tmp_path):
    _, pat = _fake_ibm(tmp_path)
    at = parse_ibm_patterns(pat)
    assert len(at) == 1 and at[0]["typology"] == "FAN-OUT" and len(at[0]["rows"]) == 6
    assert at[0]["rows"][0]["src"].startswith("010|")                           # bank code keeps its leading zero


def test_ibm_loader_maps_schema_window_and_rings(tmp_path, small_cfg):
    import copy
    csv, pat = _fake_ibm(tmp_path)
    cfg = copy.deepcopy(small_cfg)
    cfg["data"]["ibm_trans"], cfg["data"]["ibm_patterns"] = str(csv), str(pat)
    cfg["sample_accounts"], cfg["n_background_tx"] = 40, 400
    df, rings, banks = load_ibm_slice(cfg, np.random.default_rng(0))
    assert len(df) == 306 and df["t"].min() >= 0 and df["t"].max() <= cfg["n_days"] * DAY   # rescaled to the 90-day window
    assert df["label"].sum() == 6                                              # IBM's own laundering flag is kept
    assert len(rings) == 1 and rings[0]["typology"] == "ibm_fan_out" and len(rings[0]["accounts"]) == 7
    assert df["tag"].notna().sum() == 6                                        # all pattern rows matched to transactions
    assert (df["amount"] > 0).all() and df["sender"].str.startswith("B").all()
