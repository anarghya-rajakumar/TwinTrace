"""The web app backend: board payload, case file, trace, what-if (must reproduce the benchmark), live ring planting."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client(pipeline_out):
    from src.server import create_app
    from src.web.state import set_state
    set_state(None)
    with TestClient(create_app()) as c:
        yield c
    set_state(None)


@pytest.fixture(scope="module")
def board(client):
    return client.get("/api/board").json()


def test_board_payload_is_self_consistent(board):
    n = len(board["nodes"])
    assert board["days"] == 90 and set(board["splits"]) == {"tune", "val", "test"}
    assert all(0 <= e[1] < n and 0 <= e[2] < n and e[4] in (0, 1) for e in board["events"])
    assert all(a["acc"] and max(a["acc"]) < n and a["grp"] in ("money", "trade") for a in board["alerts"])
    assert all(max(r["acc"], default=0) < n for r in board["rings"])
    assert all(0 <= b < n and 0 <= d < n for b, d in board["owners"])
    kinds = {x["k"] for x in board["nodes"]}
    assert kinds == {"b", "d"}                                           # both layers are on the board
    assert {"rule_baseline", "single_layer", "twintrace"} <= set(board["methods"])
    assert min(a["score"] for a in board["alerts"]) >= board["min_score"]


def test_board_events_are_timed_and_alerts_fire_after_their_pattern_starts(board):
    assert all(0 <= e[0] <= 90 for e in board["events"])
    assert all(a["t1"] >= a["t0"] for a in board["alerts"])


def test_default_alerts_are_flagged_and_truth_overlay_is_available(board):
    dflt = [a for a in board["alerts"] if a["dflt"]]
    assert dflt and all(a["score"] >= board["thresholds"][a["grp"]] for a in dflt)
    assert any(a["hit"] for a in board["alerts"])
    assert len(board["rings"]) > 0 and all("det" in r for r in board["rings"])


def test_case_file_endpoint(client, board):
    a = board["alerts"][0]
    d = client.get(f"/api/alert/{a['id']}").json()
    assert d["alert"]["alert_id"] == a["id"] and d["alert"]["summary"]
    assert d["flow"]["pos"] and d["events"] and all(e["t"] >= 0 for e in d["events"])
    assert client.get("/api/alert/NOPE").status_code == 404


def test_trace_follows_money_both_ways_and_flags_known_alerts(client, board):
    a = next(x for x in board["alerts"] if x["layer"] == "money" and x["dflt"])
    acc = board["nodes"][a["acc"][0]]["id"]
    d = client.get("/api/trace", params=dict(account=acc, depth=2)).json()
    ids = {n["id"] for n in d["nodes"]}
    assert d["origin"] == acc and acc in ids and len(ids) > 1
    assert all(e["src"] in ids and e["dst"] in ids for e in d["edges"])
    origin = next(n for n in d["nodes"] if n["id"] == acc)
    assert origin["alerts"] and d["reach"]["flagged"] >= 1
    up = client.get("/api/trace", params=dict(account=acc, direction="up")).json()
    assert all(n["side"] in ("origin", "up", "both") for n in up["nodes"])
    assert client.get("/api/trace", params=dict(account="B_NOPE")).status_code == 404


def test_trace_crosses_from_bank_to_trading_through_the_owner(client, board):
    a = next((x for x in board["alerts"] if x["layer"] == "bridge"), None)
    if a is None:
        pytest.skip("no bridge alert in the small dataset")
    bank = next(board["nodes"][i]["id"] for i in a["acc"] if board["nodes"][i]["k"] == "b")
    d = client.get("/api/trace", params=dict(account=bank, depth=2)).json()
    assert any(e["kind"] == "owner" for e in d["edges"]) and any(n["k"] == "d" for n in d["nodes"])


def test_whatif_at_default_thresholds_reproduces_the_benchmark_table(client, pipeline_out):
    m = client.get("/api/whatif").json()
    row = pipeline_out["results"].query("method == 'twintrace' and headline").iloc[0]
    assert m["precision"] == pytest.approx(row["precision"]) and m["recall"] == pytest.approx(row["recall"])
    assert m["fpr"] == pytest.approx(row["fpr"]) and m["alerts"] == int(row["alerts"])


def test_whatif_raising_the_bar_trades_recall_for_fewer_alerts(client, board):
    d = board["thresholds"]
    lo = client.get("/api/whatif", params=dict(money=board["min_score"], trade=board["min_score"])).json()
    hi = client.get("/api/whatif", params=dict(money=100.5, trade=100.5)).json()
    assert hi["alerts"] == 0 and hi["recall"] == 0
    assert lo["alerts"] >= client.get("/api/whatif").json()["alerts"] and lo["recall"] >= hi["recall"]
    off = client.get("/api/whatif", params=dict(money=d["money"], trade=101)).json()
    assert off["per_typology"].get("wash_trading", 0) == 0               # trade layer switched off: wash trading unseen


def test_search_finds_alerts_and_accounts(client, board):
    aid = board["alerts"][0]["id"]
    assert any(r["id"] == aid for r in client.get("/api/search", params=dict(q=aid)).json())
    assert any(r["type"] == "account" for r in client.get("/api/search", params=dict(q="B000")).json())


def test_planting_a_money_ring_returns_geometry_a_verdict_and_changes_live_state(pipeline_out):
    from src.web.inject import plant
    from src.web.state import get_state
    st = get_state()
    n_rings, n_inj = len(st.data.rings), len(st.injected)
    r = plant(st, "round_trip", stealth=0.0, start_day=70, seed=5)
    assert r["ring_id"].startswith("LIVE-RT") and r["ring"]["events"] and r["ring"]["nodes"]
    assert all(0 <= e[0] <= 90 for e in r["ring"]["events"]) and 69 <= r["ring"]["t0"] <= 75
    assert set(r["baseline"]) == {"caught", "flagged_accounts", "ring_accounts"} and isinstance(r["caught"], bool)
    assert len(st.data.rings) == n_rings + 1 and len(st.injected) == n_inj + 1
    assert r["ring_id"] in st.gt.rings                                  # ground truth knows about it
    if r["alert"]:
        assert r["alert"]["alert_id"].startswith("LIVE-") and r["alert"]["truth"]["matched_rings"] == [r["ring_id"]]
        assert r["closest"]["score"] == pytest.approx(r["alert"]["score"])


def test_planted_trade_and_bridge_rings_produce_trades_and_owner_links(pipeline_out):
    from src.web.inject import plant
    from src.web.state import get_state
    st = get_state()
    w = plant(st, "wash_trading", stealth=0.3, start_day=65, seed=7)
    assert any(e[4] == 1 for e in w["ring"]["events"]) and all(a.startswith("D") for a in w["ring"]["accounts"])
    b = plant(st, "market_layering", stealth=0.3, start_day=60, seed=9)
    assert any(e[4] == 1 for e in b["ring"]["events"]) and any(e[4] == 0 for e in b["ring"]["events"])
    assert b["ring"]["owners"]                                           # bank <-> trading links drawn


def test_planting_through_the_api_and_reset_restores_the_original(client):
    r = client.post("/api/plant", json=dict(typology="mule_chain", stealth=0.2, start_day=66))
    assert r.status_code == 200 and r.json()["ring_id"].startswith("LIVE-MC")
    assert client.post("/api/plant", json=dict(typology="nope")).status_code == 400
    n = client.get("/api/health").json()
    assert n["injected"] >= 1
    assert client.post("/api/reset").json()["ok"]
    h = client.get("/api/health").json()
    assert h["injected"] == 0 and h["alerts"] < n["alerts"] + 1


def test_the_built_front_end_is_served():
    from src.config import ROOT
    if not (ROOT / "web" / "dist" / "index.html").exists():
        pytest.skip("web/dist not built")
    from src.server import create_app
    with TestClient(create_app()) as c:
        r = c.get("/")
        assert r.status_code == 200 and "TwinTrace" in r.text
