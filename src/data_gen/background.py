"""Layer-1 organic background: IBM AML slice if present, otherwise an IBM-format synthetic stand-in."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import DAY, ROOT
from .patterns import parse_ibm_patterns
from .world import PAY_FORMATS_LARGE, PAY_FORMATS_SMALL

IBM_COLS = ["Timestamp", "From Bank", "Account", "To Bank", "Account.1", "Amount Received",
            "Receiving Currency", "Amount Paid", "Payment Currency", "Payment Format", "Is Laundering"]
HOURLY = np.array([1, 1, 1, 1, 1, 2, 3, 5, 7, 9, 10, 10, 9, 9, 10, 10, 9, 8, 6, 5, 4, 3, 2, 1], float)


def _fmt_array(amount: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    small = rng.choice(PAY_FORMATS_SMALL, size=len(amount), p=[0.45, 0.25, 0.2, 0.05, 0.05])
    large = rng.choice(PAY_FORMATS_LARGE, size=len(amount), p=[0.5, 0.3, 0.2])
    return np.where(amount < 200_000, small, large)


def synth_background(cfg: dict, rng: np.random.Generator):
    """IBM-style organic traffic: neighbourhood structure, heavy-tailed activity, recurring bills,
    honest bursts and honest near-threshold payments.
    Returns (df[t, sender, receiver, amount, fmt, tag, label], bank_ids)."""
    n = cfg["sample_accounts"]
    total = cfg["n_background_tx"]
    nd = cfg["n_days"]
    thr = cfg["threshold_inr"]
    noise = cfg["noise_level"]
    ids = np.array([f"B{i:07d}" for i in range(n)], dtype=object)

    nb = rng.integers(0, max(2, n // 70), size=n)                 # neighbourhood id
    w = rng.lognormal(0.0, 1.0, size=n)
    p = w / w.sum()
    members = {int(g): np.where(nb == g)[0] for g in np.unique(nb)}

    n_rec = int(0.02 * n)
    n_burst = int(30 * noise)
    n_main = max(1000, total - n_rec * 4 - n_burst * 10)
    s = rng.choice(n, size=n_main, p=p)
    r = rng.choice(n, size=n_main, p=p)                           # global receivers (25%)
    local = rng.random(n_main) < 0.75
    for g, mem in members.items():
        sel = np.where(local & (nb[s] == g))[0]
        if len(sel):
            r[sel] = rng.choice(mem, size=len(sel))
    r = np.where(r == s, (r + 1) % n, r)
    amt = np.clip(rng.lognormal(np.log(6000), 1.25, n_main), 50, 5e6)
    # merchants: popular receivers of many small payments (innocent high in-degree)
    merch = rng.choice(n, size=max(10, int(0.004 * n)), replace=False)
    is_m = rng.random(n_main) < 0.15
    r = np.where(is_m, rng.choice(merch, size=n_main), r)
    r = np.where(r == s, (r + 1) % n, r)
    amt = np.where(is_m, np.clip(rng.lognormal(np.log(700), 0.9, n_main), 20, 15000), amt)
    near = rng.random(n_main) < 0.015 * noise                    # honest payments just under the threshold
    amt = np.where(near, rng.uniform(0.9 * thr, 0.998 * thr, n_main), amt)
    day = rng.integers(0, nd, n_main)
    hour = rng.choice(24, size=n_main, p=HOURLY / HOURLY.sum())
    t = day * DAY + hour * 3600 + rng.uniform(0, 3600, n_main)
    rows = [pd.DataFrame(dict(t=t, sender=ids[s], receiver=ids[r], amount=amt))]

    # recurring bills / subscriptions: fixed pair, fixed amount, period 7/14/30 days
    rs = rng.choice(n, size=n_rec, p=p)
    rec = []
    for i in range(n_rec):
        g = int(nb[rs[i]])
        rcv = int(rng.choice(members[g]))
        if rcv == rs[i]:
            rcv = (rcv + 1) % n
        period = int(rng.choice([7, 14, 30]))
        a = float(np.clip(rng.lognormal(np.log(3000), 0.8), 100, 40_000))
        off = rng.uniform(0, period * DAY)
        for k in range(4):
            tt = off + k * period * DAY + rng.uniform(-3600, 3600)
            if 0 <= tt < nd * DAY:
                rec.append((tt, ids[rs[i]], ids[rcv], a))
    rows.append(pd.DataFrame(rec, columns=["t", "sender", "receiver", "amount"]))

    # honest bursts: event collections (fan-in) and vendor payment runs (fan-out), amounts not near-threshold
    bur = []
    glist = [g for g, m in members.items() if len(m) >= 8]
    for _ in range(n_burst):
        mem = members[int(rng.choice(glist))]
        hub = int(rng.choice(mem))
        k = int(rng.integers(6, 15))
        pool = mem[mem != hub]
        others = rng.choice(pool, size=min(k, len(pool)), replace=False)
        t0 = rng.uniform(0, (nd - 2) * DAY)
        base = float(rng.lognormal(np.log(2500), 0.6))
        fan_in = rng.random() < 0.5
        for o in others:
            a = float(np.clip(base * rng.uniform(0.5, 1.5), 100, 30_000))
            tt = t0 + rng.uniform(0, DAY)
            bur.append((tt, ids[o], ids[hub], a) if fan_in else (tt, ids[hub], ids[o], a))
    rows.append(pd.DataFrame(bur, columns=["t", "sender", "receiver", "amount"]))

    df = pd.concat(rows, ignore_index=True)
    df["fmt"] = _fmt_array(df["amount"].to_numpy(), rng)
    df["tag"] = None
    df["label"] = 0
    return df, list(ids)


def load_ibm_slice(cfg: dict, rng: np.random.Generator):
    """Load a chronological ~20k-account / ~100k-tx slice of IBM HI-Small, rescale time to the 90-day
    window and amounts to INR. Returns (df, ibm_rings, bank_ids) or None if the file is missing."""
    path = ROOT / cfg["data"]["ibm_trans"]
    if not Path(path).exists():
        return None
    # bank / account codes must stay strings: the patterns file writes banks as "010", pandas would read 10
    raw = pd.read_csv(path, nrows=2_500_000, header=0, names=IBM_COLS,
                      dtype={c: str for c in ("From Bank", "Account", "To Bank", "Account.1")})
    raw["src"] = raw["From Bank"].astype(str) + "|" + raw["Account"].astype(str)
    raw["dst"] = raw["To Bank"].astype(str) + "|" + raw["Account.1"].astype(str)
    raw["ts_raw"] = pd.to_datetime(raw["Timestamp"], format="%Y/%m/%d %H:%M")

    pat_path = ROOT / cfg["data"]["ibm_patterns"]
    attempts = parse_ibm_patterns(pat_path) if Path(pat_path).exists() else []
    ring_accts = {a for at in attempts for row in at["rows"] for a in (row["src"], row["dst"])}

    cnt = pd.concat([raw["src"], raw["dst"]]).value_counts()
    keep = set(cnt.index[: cfg["sample_accounts"]]) | ring_accts
    sel = raw[raw["src"].isin(keep) & raw["dst"].isin(keep)].sort_values("ts_raw", kind="stable")
    sel = sel.head(cfg["n_background_tx"]).reset_index(drop=True)
    return finalise_ibm(sel, attempts, cfg)


def finalise_ibm(sel: pd.DataFrame, attempts: list, cfg: dict):
    """Map an IBM-format frame (with src/dst/ts_raw columns) to the unified background schema."""
    uniq = pd.unique(pd.concat([sel["src"], sel["dst"]]))
    idmap = {a: f"B{i:07d}" for i, a in enumerate(uniq)}
    span = (sel["ts_raw"].max() - sel["ts_raw"].min()).total_seconds() or 1.0
    t = (sel["ts_raw"] - sel["ts_raw"].min()).dt.total_seconds() / span * (cfg["n_days"] - 1) * DAY
    fx = cfg["data"]["usd_to_inr"]
    df = pd.DataFrame(dict(
        t=t.to_numpy(), sender=sel["src"].map(idmap).to_numpy(), receiver=sel["dst"].map(idmap).to_numpy(),
        amount=(sel["Amount Paid"].astype(float) * fx).clip(lower=1.0).to_numpy(),
        fmt=sel["Payment Format"].astype(str).to_numpy(), tag=None,
        label=sel["Is Laundering"].astype(int).to_numpy()))
    key = {}
    for i, (ts, a, b, amt) in enumerate(zip(sel["ts_raw"], sel["src"], sel["dst"], sel["Amount Paid"])):
        key[(ts, a, b, round(float(amt), 4))] = i
    rings = []
    for k, at in enumerate(attempts, 1):
        rows = [key.get((pd.Timestamp(rw["ts"]), rw["src"], rw["dst"], round(float(rw["amt"]), 4))) for rw in at["rows"]]
        rows = [x for x in rows if x is not None]
        if len(rows) < 3:
            continue
        tag = f"IBM-{k:04d}"
        df.loc[rows, "tag"] = tag
        accts = sorted({idmap[a] for rw in at["rows"] for a in (rw["src"], rw["dst"]) if a in idmap})
        rings.append(dict(ring_id=tag, layer="money", typology="ibm_" + at["typology"].lower().replace("-", "_"),
                          accounts=accts, source="ibm"))
    return df, rings, list(idmap.values())
