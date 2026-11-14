"""Load processed artifacts and derive the numeric columns / indexes every detector uses."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import load_config, processed_dir, t0 as cfg_t0


def _group_index(keys: np.ndarray, rows: np.ndarray) -> dict:
    order = np.argsort(keys, kind="stable")
    ks, rs = keys[order], rows[order]
    if len(ks) == 0:
        return {}
    bounds = np.flatnonzero(ks[1:] != ks[:-1]) + 1
    starts = np.r_[0, bounds]
    return {ks[s]: np.sort(g) for s, g in zip(starts, np.split(rs, bounds))}


@dataclass
class Data:
    cfg: dict
    tx: pd.DataFrame
    trades: pd.DataFrame
    accounts: pd.DataFrame
    rings: list
    hards: list
    t0: pd.Timestamp
    horizon: float
    acct_rows: dict = field(default_factory=dict)      # bank account -> sorted row positions in tx
    demat_rows: dict = field(default_factory=dict)     # demat account -> sorted row positions in trades
    owner_of: dict = field(default_factory=dict)       # any account -> owner
    banks_of_owner: dict = field(default_factory=dict)
    demat_of_owner: dict = field(default_factory=dict)
    recv_rows: dict = field(default_factory=dict)      # bank account -> rows where it is the receiver
    send_rows: dict = field(default_factory=dict)      # bank account -> rows where it is the sender
    code_of: dict = field(default_factory=dict)        # bank account -> int code
    s_code: np.ndarray = None
    r_code: np.ndarray = None

    def iso(self, t: float) -> str:
        return str(self.t0 + pd.Timedelta(seconds=float(t)))


def prepare_tx(tx: pd.DataFrame, t0: pd.Timestamp) -> pd.DataFrame:
    df = tx.rename(columns={"amount_inr": "amount", "payment_format": "fmt"}).copy()
    df["t"] = (df["ts"] - t0).dt.total_seconds()
    df = df.sort_values(["t", "tx_id"], kind="stable").reset_index(drop=True)
    for c in ("sender", "receiver"):
        df[c] = df[c].astype(object)
    # earliest time each ordered pair ever transacted: lets detectors ask "was this pair known BEFORE the window?"
    df["pair_first_t"] = df.groupby(["sender", "receiver"])["t"].transform("min")
    return df


def prepare_trades(tr: pd.DataFrame, t0: pd.Timestamp) -> pd.DataFrame:
    df = tr.copy()
    df["t"] = (df["ts"] - t0).dt.total_seconds()
    df = df.sort_values(["t", "trade_id"], kind="stable").reset_index(drop=True)
    for c in ("stock", "buyer", "seller"):
        df[c] = df[c].astype(object)
    df["day"] = np.floor(df["t"] / 86400.0).astype(int)
    df["ref_price"] = df.groupby(["stock", "day"])["price"].transform("median")   # observable day reference price
    df["dev"] = df["price"] / df["ref_price"] - 1.0
    df["notional"] = df["price"] * df["qty"]
    return df


def load_data(cfg: dict | None = None) -> Data:
    cfg = cfg or load_config()
    p = processed_dir()
    rings = json.loads((p / "rings.json").read_text(encoding="utf-8"))
    hards = json.loads((p / "hard_negatives.json").read_text(encoding="utf-8"))
    return data_from_frames(cfg, pd.read_parquet(p / "transactions.parquet"), pd.read_parquet(p / "trades.parquet"),
                            pd.read_parquet(p / "accounts.parquet"), rings, hards)


def data_from_frames(cfg: dict, tx_raw: pd.DataFrame, trades_raw: pd.DataFrame, accounts: pd.DataFrame, rings: list,
                     hards: list) -> Data:
    """Build the analysis object from raw frames (used by load_data and by live ring injection)."""
    T0 = cfg_t0(cfg)
    tx = prepare_tx(tx_raw, T0)
    trades = prepare_trades(trades_raw, T0)
    d = Data(cfg, tx, trades, accounts, rings, hards, T0, cfg["n_days"] * 86400.0)

    s = tx["sender"].to_numpy(dtype=object)
    r = tx["receiver"].to_numpy(dtype=object)
    n = len(tx)
    d.acct_rows = _group_index(np.concatenate([s, r]), np.concatenate([np.arange(n), np.arange(n)]))
    d.send_rows = _group_index(s, np.arange(n))
    d.recv_rows = _group_index(r, np.arange(n))
    codes, uniq = pd.factorize(np.concatenate([s, r]))
    d.s_code, d.r_code = codes[:n], codes[n:]
    d.code_of = {a: i for i, a in enumerate(uniq)}
    nt = len(trades)
    b = trades["buyer"].to_numpy(dtype=object)
    sl = trades["seller"].to_numpy(dtype=object)
    d.demat_rows = _group_index(np.concatenate([b, sl]), np.concatenate([np.arange(nt), np.arange(nt)]))
    d.owner_of = dict(zip(accounts["account_id"], accounts["owner_id"]))
    for acc, own, layer in zip(accounts["account_id"], accounts["owner_id"], accounts["layer"]):
        (d.banks_of_owner if layer == "bank" else d.demat_of_owner).setdefault(own, []).append(acc)
    return d
