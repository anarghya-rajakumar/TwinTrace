"""Stage 1 orchestration: background + planted rings + hard negatives + bridge -> data/processed/*."""
from __future__ import annotations

import json
import time
from collections import Counter

import numpy as np
import pandas as pd

from ..config import DAY, load_config, processed_dir, split_of, t0 as cfg_t0
from .background import load_ibm_slice, synth_background
from .money_rings import inject_money
from .trades import Market, background_trades, inject_trades, weekday_list
from .world import World


def _jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def build(cfg: dict | None = None, verbose: bool = True) -> dict:
    cfg = cfg or load_config()
    t_start = time.time()
    rng = np.random.default_rng(cfg["seed"])
    T0 = cfg_t0(cfg)

    loaded = load_ibm_slice(cfg, rng)
    if loaded is not None:
        bg, ibm_rings, bank_ids = loaded
        source = "IBM AML HI-Small slice"
    else:
        bg, bank_ids = synth_background(cfg, rng)
        ibm_rings = []
        source = "IBM-format synthetic background (HI-Small_Trans.csv not found in data/raw/)"
    bank_ids = np.array(bank_ids, dtype=object)
    idx = {b: i for i, b in enumerate(bank_ids)}
    activity = np.zeros(len(bank_ids))
    for col in ("sender", "receiver"):
        vc = bg[col].value_counts()
        activity[[idx[a] for a in vc.index]] += vc.to_numpy()

    # owners: one owner per bank account, with ~3% of owners holding two accounts
    owners = np.array([f"O{i:07d}" for i in range(len(bank_ids))], dtype=object)
    dup = rng.random(len(bank_ids)) < 0.03
    owners[dup] = owners[rng.integers(0, len(bank_ids), dup.sum())]
    owner_of = dict(zip(bank_ids, owners))
    bank_of_owner: dict = {}
    for b, o in owner_of.items():
        bank_of_owner.setdefault(o, b)

    w = World(cfg, rng, bank_ids, activity, owner_of)
    w.bank_of_owner = bank_of_owner
    w.weekdays = weekday_list(cfg)
    w.demat_owner = {}

    # background demat accounts
    uniq_owners = np.array(sorted(set(owners)), dtype=object)
    n_dm = int(cfg["data"]["demat_share"] * len(uniq_owners))
    for o in rng.choice(uniq_owners, size=n_dm, replace=False):
        did = w.new_demat(str(o), "institutional" if rng.random() < 0.03 else "retail")
        w.background_demat.append(did)
    w.demat_owner = {r[0]: r[1] for r in w.demat_rows}

    mkt = Market(cfg, rng)
    bg_trades = background_trades(w, mkt, w.background_demat)

    inject_money(w)
    inject_trades(w, mkt)
    w.demat_owner.update({r[0]: r[1] for r in w.demat_rows})
    for r in ibm_rings:
        w.rings.append(r)

    # ---------------- assemble transactions
    inj = pd.DataFrame(w.money.rows, columns=["t", "sender", "receiver", "amount", "fmt", "tag"])
    inj["label"] = 0
    cols = ["t", "sender", "receiver", "amount", "fmt", "tag", "label"]
    allm = pd.concat([bg[cols], inj[cols]], ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)
    allm["tx_id"] = np.arange(len(allm), dtype=np.int64)
    ts = (T0 + pd.to_timedelta(allm["t"], unit="s")).dt.floor("s")
    tx = pd.DataFrame(dict(tx_id=allm["tx_id"], ts=ts, sender=allm["sender"], receiver=allm["receiver"],
                           amount_inr=allm["amount"].round(2), currency="INR", payment_format=allm["fmt"],
                           is_laundering_base=allm["label"].astype(int)))

    # ---------------- assemble trades
    tinj = pd.DataFrame(w.trades.rows, columns=["t", "stock", "buyer", "seller", "price", "qty", "tag"])
    allt = pd.concat([bg_trades, tinj], ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)
    allt["trade_id"] = np.arange(len(allt), dtype=np.int64)
    trades = pd.DataFrame(dict(trade_id=allt["trade_id"], ts=(T0 + pd.to_timedelta(allt["t"], unit="s")).dt.floor("s"),
                               stock=allt["stock"], buyer=allt["buyer"], seller=allt["seller"],
                               price=allt["price"], qty=allt["qty"]))

    tx_by_tag = allm[allm["tag"].notna()].groupby("tag")["tx_id"].apply(list).to_dict()
    tr_by_tag = allt[allt["tag"].notna()].groupby("tag")["trade_id"].apply(list).to_dict()
    t_of_tx, t_of_tr = allm.set_index("tx_id")["t"], allt.set_index("trade_id")["t"]

    rings = []
    for r in w.rings:
        rid = r["ring_id"]
        r = dict(r)
        r["tx_ids"] = tx_by_tag.get(rid, [])
        r["trade_ids"] = tr_by_tag.get(rid, [])
        r["funding_tx_ids"] = tx_by_tag.get(rid + ":fund", [])
        # core activity defines the ring's time: trades for trade/bridge rings, transfers for money rings
        tr_times = [t_of_tr[i] for i in r["trade_ids"]]
        tx_times = [t_of_tx[i] for i in r["tx_ids"]]
        times = tr_times if (r["layer"] in ("trade", "bridge") and tr_times) else (tx_times or tr_times)
        if not times:
            continue
        r["t_first_any"] = float(min(tx_times + tr_times))
        r["t_start"], r["t_end"] = float(min(times)), float(max(times))
        r["ts_start"], r["ts_end"] = str(T0 + pd.Timedelta(seconds=r["t_start"])), str(T0 + pd.Timedelta(seconds=r["t_end"]))
        r["split"] = split_of(r["t_start"], cfg)
        rings.append(r)
    hards = []
    for h in w.hard:
        h = dict(h)
        h["tx_ids"] = tx_by_tag.get(h["hn_id"], [])
        h["trade_ids"] = tr_by_tag.get(h["hn_id"], [])
        hards.append(h)

    # ---------------- accounts (bridge: owner links bank accounts to demat accounts)
    atype = rng.choice(["savings", "current"], size=len(bank_ids), p=[0.85, 0.15])
    bank_rows = [(b, owner_of[b], "bank", t) for b, t in zip(bank_ids, atype)]
    accounts = pd.DataFrame(bank_rows + w.demat_rows, columns=["account_id", "owner_id", "layer", "account_type"])

    out = processed_dir()
    tx.to_parquet(out / "transactions.parquet", index=False)
    trades.to_parquet(out / "trades.parquet", index=False)
    accounts.to_parquet(out / "accounts.parquet", index=False)
    mkt.daily_frame(T0).to_parquet(out / "prices.parquet", index=False)
    (out / "rings.json").write_text(json.dumps(rings, default=_jsonable), encoding="utf-8")
    (out / "hard_negatives.json").write_text(json.dumps(hards, default=_jsonable), encoding="utf-8")
    meta = dict(source=source, price_source=mkt.source, seed=cfg["seed"], elapsed_s=round(time.time() - t_start, 1))
    (out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    stats = dict(
        transactions=len(tx), trades=len(trades), accounts=len(accounts),
        bank_accounts=int((accounts.layer == "bank").sum()), demat_accounts=int((accounts.layer == "demat").sum()),
        rings=dict(Counter(r["typology"] for r in rings)),
        hard_negatives=dict(Counter(h["kind"] for h in hards)), meta=meta)
    if verbose:
        print(f"[data] background source : {source}")
        print(f"[data] price source      : {mkt.source}")
        print(f"[data] transactions      : {len(tx):,}   trades: {len(trades):,}")
        print(f"[data] accounts          : {stats['bank_accounts']:,} bank + {stats['demat_accounts']:,} demat")
        print("[data] planted rings by typology:")
        for k, v in sorted(stats["rings"].items()):
            print(f"         {k:<22}{v:>4}")
        print("[data] hard negatives by kind:")
        for k, v in sorted(stats["hard_negatives"].items()):
            print(f"         {k:<22}{v:>4}")
        print(f"[data] wrote {out} in {meta['elapsed_s']}s")
    return stats


if __name__ == "__main__":
    build()
