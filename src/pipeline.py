"""End-to-end pipeline: clusters -> features -> scoring -> evaluation -> alerts, explanations, artifacts."""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from .config import DAY, artifacts_dir, load_config, split_bounds, split_of
from .detectors.bridge import money_bridge_features, trade_bridge_features
from .detectors.money import compute_pass_events
from .eval.baseline import rule_baseline
from .eval.metrics import GroundTruth, evaluate
from .explain.summary import summarize
from .explain.typology import TYPOLOGY_NAMES, label_cluster
from .graph.clusters import build_money_clusters
from .graph.prep import Data, load_data
from .graph.trade_clusters import build_trade_clusters
from .detectors.bridge import BRIDGE_KEYS as BRIDGE_F
from .scoring.features import FEATURE_SETS, LAYERS, ALL_F, LABELS, MONEY_F, TRADE_F, feature_frame, hand_components
from .scoring.models import HandScorer, XGBScorer, top_contributors
from .scoring.select import choose_threshold, dedupe

METHODS = ["single_layer", "two_layer_no_bridge", "twintrace"]
THRESHOLD_GROUPS = {"money": {"money"}, "trade": {"trade", "bridge"}}
METHOD_TITLES = {"rule_baseline": "Rule baseline", "single_layer": "Single-layer graph (money only)",
                 "two_layer_no_bridge": "Two layers, no bridge", "twintrace": "TwinTrace (two layers + bridge)"}


def build_all_clusters(data: Data, log=print, t_range: tuple | None = None) -> list[dict]:
    t = time.time()
    events = compute_pass_events(data)
    money = build_money_clusters(data, events, t_range)
    log(f"[clusters] money {len(money):,}  ({time.time() - t:.1f}s)")
    t = time.time()
    trade = build_trade_clusters(data, t_range)
    bridge_rows = []
    for c in trade:
        feats, br = trade_bridge_features(data, c)
        c["features"].update(feats)
        if br is not None:
            br["features"].update(feats)
            bridge_rows.append(br)
    for c in money:
        c["features"].update(money_bridge_features(data, c))
    log(f"[clusters] trade {len(trade):,}, bridge {len(bridge_rows):,}  ({time.time() - t:.1f}s)")
    allc = money + trade + bridge_rows
    for i, c in enumerate(allc):
        c["cluster_id"] = i
        c["split"] = split_of(c["t_start"], data.cfg)
    return allc


def label_clusters(clusters: list[dict], gt: GroundTruth) -> None:
    for c in clusters:
        ms = gt.matches(c["accounts"])
        c["matched_rings"] = ms
        c["matched_money_rings"] = [m for m in ms if gt.rings[m]["layer"] == "money"]


def _cand(c: dict, score: float, label: dict) -> dict:
    return dict(accounts=c["accounts"], t_start=c["t_start"], layer=c["layer"], typology=label["primary"],
                score=float(score), idx=c["cluster_id"])


def run_method(method: str, scorer: str, clusters, X: pd.DataFrame, labels: list[dict], gt: GroundTruth, cfg: dict):
    """Train on the tuning split, pick the threshold on validation, return everything needed to evaluate."""
    layers = LAYERS[method]
    idx = [i for i, c in enumerate(clusters) if c["layer"] in layers]
    Xm = X.iloc[idx].copy()
    keep = set(FEATURE_SETS[method])
    for col in Xm.columns:
        if col not in keep:
            Xm[col] = np.nan
    key = "matched_money_rings" if method == "single_layer" else "matched_rings"
    y = np.array([1 if clusters[i][key] else 0 for i in idx])
    tune = np.array([clusters[i]["split"] == "tune" for i in idx])
    seed = cfg["seed"]
    if scorer == "hand":
        comps = hand_components(Xm)
        model = HandScorer(seed, cfg["scoring"]["weight_search_iters"]).fit(comps[tune], y[tune])
        scores = model.score(comps)
        contrib_fn = lambda rows: model.contributions(comps.iloc[rows])  # noqa: E731
    else:
        cols = [c for c in FEATURE_SETS[method]]
        model = XGBScorer(cfg, seed).fit(Xm.loc[tune, cols], y[tune])
        scores = model.score(Xm[cols])
        contrib_fn = lambda rows: model.contributions(Xm[cols].iloc[rows])  # noqa: E731
    cands = [_cand(clusters[i], s, labels[i]) for i, s in zip(idx, scores)]
    # one threshold per layer group (scores from different clusters types are not comparable); the same total
    # false-positive budget is split evenly across the groups present
    present = [g for g, ls in THRESHOLD_GROUPS.items() if any(a["layer"] in ls for a in cands)]
    thr = {g: choose_threshold([a for a in cands if a["layer"] in THRESHOLD_GROUPS[g]], gt,
                               cfg["scoring"]["target_fpr"] / len(present), "val", g,
                               f1_tolerance=cfg["scoring"].get("f1_tolerance", 0.03)) for g in present}
    group_of = {l: g for g, ls in THRESHOLD_GROUPS.items() for l in ls}
    selected = dedupe([a for a in cands if a["score"] >= thr[group_of[a["layer"]]]])
    return dict(model=model, scores=dict(zip(idx, scores)), threshold=thr, selected=selected, contrib_fn=contrib_fn, idx=idx,
                cands=cands, scorer=scorer, method=method)


def _row(name: str, scorer: str, m: dict, scope: str, extra: dict | None = None) -> dict:
    r = dict(method=name, scorer=scorer, scope=scope, precision=m["precision"], recall=m["recall"], f1=m["f1"],
             fpr=m["fpr"], alerts=m["alerts"], alerts_per_1000_accounts=m["alerts_per_1000_accounts"],
             rings=m["rings"], rings_found=m["rings_found"], typology_accuracy=m["typology_accuracy"])
    for k, v in m["per_typology_recall"].items():
        r[f"recall_{k}"] = v
    r.update(extra or {})
    return r


def _num(v, default):
    return default if v is None or (isinstance(v, float) and np.isnan(v)) else v


def _fmt_labels(accts: list, k: int = 3) -> str:
    if not accts:
        return ""
    s = ", ".join(accts[:k])
    return s + (" and others" if len(accts) > k else "")


def build_alert(data: Data, c: dict, score: float, contribs: pd.Series | None, amt_by_id: pd.Series,
                notional_by_id: pd.Series, gt: GroundTruth) -> dict:
    lab = label_cluster(c, score)
    primary, secondary = lab["primary"], lab["secondary"]
    d = c.get("detectors", {})
    ev: dict = {}
    key = {"fan_in_structuring": "structuring", "fan_in": "fan_in", "fan_out": "fan_out", "round_trip": "round_trip",
           "mule_chain": "pass_through", "wash_trading": "wash_trading", "loss_booking": "loss_booking"}
    if primary == "market_layering":
        ev.update(d.get("wash_trading", {}).get("evidence", {}))
        ev.update(c.get("bridge_evidence", {}))
        ev["n_trades"] = int(ev.get("n_trades", len(c["trade_ids"])))
    elif primary in key and key[primary] in d:
        ev.update(d[key[primary]]["evidence"])
    if primary in ("fan_in_structuring", "fan_in") and "pass_through" in d:
        pt = d["pass_through"]["evidence"]
        ev["pass_forward_share"] = pt["ratio_mean"]
        ev["pass_dwell_hours"] = pt["dwell_median_hours"]
    if primary == "wash_trading" and c.get("bridge_evidence", {}).get("funding_source"):
        be = c["bridge_evidence"]
        ev.update({k: be[k] for k in ("funding_source", "n_owners_funded", "n_owners", "funded_inr") if k in be})
    if c["layer"] == "trade" or primary == "market_layering":
        amount = float(notional_by_id.loc[c["trade_ids"]].sum()) if c["trade_ids"] else 0.0
    else:
        amount = float(amt_by_id.loc[c["tx_ids"]].sum()) if c["tx_ids"] else 0.0
    f = c["features"]
    ev.update(n_accounts=len(c["accounts"]), n_tx=_num(f.get("n_tx"), len(c["tx_ids"]) or len(c["trade_ids"])),
              amount_inr=amount, internal_share=float(_num(f.get("internal_share"), _num(f.get("t_internal_share"), 0.0))),
              entry_label=_fmt_labels(c["entry_nodes"]), exit_label=_fmt_labels(c["exit_nodes"]), risk_score=float(score))
    if contribs is not None and set(contribs.index) <= set(ALL_F):      # only features that apply to this layer
        ok = set(TRADE_F + BRIDGE_F) if c["layer"] in ("trade", "bridge") else set(MONEY_F + BRIDGE_F)
        contribs = contribs[[k for k in contribs.index if k in ok]]
    drivers = top_contributors(contribs) if contribs is not None else []
    for i, dr in enumerate(drivers, 1):
        ev[f"driver_{i}_label"] = dr["label"]
        ev[f"driver_{i}_pct"] = float(round(dr["share"] * 100))
    entry_nodes, exit_nodes = c["entry_nodes"], c["exit_nodes"]
    if c["layer"] == "trade":                      # buyer/seller of the first/last trade say nothing; use the funding link
        be = c.get("bridge_evidence", {})
        entry_nodes = [be["funding_source"]] if be.get("funding_source") else []
        exit_nodes = [be["exit_account"]] if be.get("exit_account") else []
        ev["entry_label"], ev["exit_label"] = _fmt_labels(entry_nodes), _fmt_labels(exit_nodes)
    alert = dict(alert_id=None, layer=c["layer"], typology=primary, typology_name=TYPOLOGY_NAMES[primary],
                 secondary_typology=secondary, confidence=lab["confidence"], score=float(score),
                 accounts=c["accounts"], tx_ids=c["tx_ids"], trade_ids=c["trade_ids"], evidence=ev,
                 entry_nodes=entry_nodes, exit_nodes=exit_nodes,
                 window_start=data.iso(c["t_start"]), window_end=data.iso(c["t_end"]), t_start=c["t_start"],
                 t_end=c["t_end"], split=c["split"], cluster_id=c["cluster_id"],
                 contributions=drivers, stock=c.get("stock"),
                 truth=dict(matched_rings=c["matched_rings"],
                            ring_typologies=[gt.rings[m]["typology"] for m in c["matched_rings"]]))
    alert["summary"] = summarize(alert)
    return alert


def run_pipeline(cfg: dict | None = None, log=print) -> dict:
    cfg = cfg or load_config()
    t_all = time.time()
    data = load_data(cfg)
    gt = GroundTruth(data)
    clusters = build_all_clusters(data, log)
    label_clusters(clusters, gt)
    X = feature_frame(clusters)
    labels = [label_cluster(c) for c in clusters]
    log(f"[score] clusters {len(clusters):,}; positives {sum(1 for c in clusters if c['matched_rings']):,}")

    rows, rows_money, runs = [], [], {}
    base = rule_baseline(data)
    for scope, store in (("all", rows), ("money", rows_money)):
        store.append(_row("rule_baseline", "rules", evaluate(base, gt, "test", scope), scope, dict(headline=True, val_f1=np.nan)))
    for method in METHODS:
        best = None
        for scorer in ("hand", "xgb"):
            run = run_method(method, scorer, clusters, X, labels, gt, cfg)
            runs[(method, scorer)] = run
            val_f1 = evaluate(run["selected"], gt, "val")["f1"]
            run["val_f1"] = val_f1
            if best is None or val_f1 > runs[(method, best)]["val_f1"]:
                best = scorer
        for scorer in ("hand", "xgb"):
            run = runs[(method, scorer)]
            for scope, store in (("all", rows), ("money", rows_money)):
                store.append(_row(method, scorer, evaluate(run["selected"], gt, "test", scope), scope,
                                  dict(headline=(scorer == best), val_f1=run["val_f1"], threshold=json.dumps({k: round(v, 2) for k, v in run["threshold"].items()}))))
        log(f"[score] {method}: headline scorer = {best} (chosen on validation F1)")

    # ---- alerts for the dashboards: TwinTrace headline scorer, every split, thresholds fixed on validation
    head = max(("hand", "xgb"), key=lambda s: runs[("twintrace", s)]["val_f1"])
    run = runs[("twintrace", head)]
    final = run["selected"]
    final_idx = {a["idx"] for a in final}
    group_of = {l: g for g, ls in THRESHOLD_GROUPS.items() for l in ls}
    # below-threshold candidates, kept so the web what-if slider can lower the bar and bring them in
    floor = cfg["scoring"].get("web_score_floor", 5.0)
    extras = [a for a in run["cands"] if a["idx"] not in final_idx and floor <= a["score"] < run["threshold"][group_of[a["layer"]]]]
    for a in final:
        a["prio"] = 1
    merged = dedupe(final + extras)
    kept_final = {a["idx"] for a in merged if a.get("prio")}
    assert kept_final == final_idx, "a final alert was merged away"
    sel_rows = [run["idx"].index(a["idx"]) for a in merged]
    contrib = run["contrib_fn"](sel_rows)
    amt_by_id = data.tx.set_index("tx_id")["amount"]
    notional_by_id = data.trades.set_index("trade_id")["notional"]
    all_alerts = []
    for r, a in enumerate(merged):
        al = build_alert(data, clusters[a["idx"]], a["score"], contrib.iloc[r], amt_by_id, notional_by_id, gt)
        al["above_default"] = a["idx"] in final_idx
        all_alerts.append(al)
    all_alerts.sort(key=lambda x: -x["score"])
    for i, a in enumerate(all_alerts, 1):
        a["alert_id"] = f"TT-{i:04d}"
    alerts = [a for a in all_alerts if a["above_default"]]

    out = artifacts_dir()
    res = pd.DataFrame(rows)
    res_m = pd.DataFrame(rows_money)
    res.to_csv(out / "results.csv", index=False)
    res_m.to_csv(out / "results_money_only.csv", index=False)
    _dump = lambda o: o.item() if hasattr(o, "item") else str(o)  # noqa: E731
    (out / "alerts.json").write_text(json.dumps(alerts, default=_dump), encoding="utf-8")
    (out / "alerts_all.json").write_text(json.dumps(all_alerts, default=_dump), encoding="utf-8")
    import joblib
    joblib.dump(dict(scorer=head, model=run["model"], thresholds=run["threshold"], cols=list(FEATURE_SETS["twintrace"])),
                out / "model.joblib")
    meta = dict(seed=cfg["seed"], headline_scorer=head, threshold=run["threshold"], n_alerts=len(alerts), n_alerts_all=len(all_alerts),
                splits={k: [v[0] / DAY, v[1] / DAY] for k, v in split_bounds(cfg).items()},
                n_clusters=len(clusters), elapsed_s=round(time.time() - t_all, 1),
                data=json.loads((data_meta_path()).read_text(encoding="utf-8")) if data_meta_path().exists() else {})
    (out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    write_markdown(res, res_m, out / "results.md", gt, meta)
    log(f"[done] pipeline {meta['elapsed_s']}s")
    return dict(results=res, results_money=res_m, alerts=alerts, all_alerts=all_alerts, meta=meta, clusters=clusters, gt=gt, data=data)


def data_meta_path():
    from .config import processed_dir
    return processed_dir() / "meta.json"


def write_markdown(res: pd.DataFrame, res_m: pd.DataFrame, path, gt: GroundTruth, meta: dict) -> None:
    def table(df: pd.DataFrame, only_head: bool) -> str:
        d = df[df["headline"]] if only_head else df
        cols = ["method", "scorer", "precision", "recall", "f1", "fpr", "alerts", "alerts_per_1000_accounts", "rings_found", "rings"]
        lines = ["| Method | Scorer | Precision | Recall | F1 | FPR | Alerts | Alerts / 1,000 accts | Rings found |",
                 "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        for _, r in d.iterrows():
            lines.append(f"| {METHOD_TITLES.get(r['method'], r['method'])} | {r['scorer']} | {r['precision']:.3f} | {r['recall']:.3f} | "
                         f"{r['f1']:.3f} | {r['fpr']:.4f} | {int(r['alerts'])} | {r['alerts_per_1000_accounts']:.1f} | "
                         f"{int(r['rings_found'])}/{int(r['rings'])} |")
        return "\n".join(lines)

    typ_cols = [c for c in res.columns if c.startswith("recall_")]
    head = res[res["headline"]]
    pt = ["| Typology | " + " | ".join(METHOD_TITLES.get(m, m) for m in head["method"]) + " |",
          "|---|" + "---:|" * len(head)]
    for c in typ_cols:
        pt.append(f"| {c[7:]} | " + " | ".join("n/a" if pd.isna(v) else f"{v:.2f}" for v in head[c]) + " |")
    md = ["# TwinTrace results (test split only)", "",
          f"Time-based split: first 60% tuning, next 20% validation, last 20% test. Alert threshold chosen on validation "
          f"for a target false-positive rate of {gt.cfg['scoring']['target_fpr']}. Headline scorer per method = best validation F1.", "",
          "## All rings (money + trade + bridge)", "", table(res, True), "", "## Every method and scorer", "", table(res, False), "",
          "## Per-typology recall (headline rows)", "", "\n".join(pt), "",
          "## Money-layer rings only (like-for-like for the single-layer method)", "", table(res_m, True), ""]
    path.write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    run_pipeline()
