"""Shared mutable state used while planting rings: account pools, collectors, ground truth."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import DAY

PAY_FORMATS_SMALL = ["UPI", "IMPS", "NEFT", "Cash", "Cheque"]
PAY_FORMATS_LARGE = ["RTGS", "NEFT", "Cheque"]


def pick_format(amount: float, rng: np.random.Generator) -> str:
    if amount < 200_000:
        return str(rng.choice(PAY_FORMATS_SMALL, p=[0.45, 0.25, 0.2, 0.05, 0.05]))
    return str(rng.choice(PAY_FORMATS_LARGE, p=[0.5, 0.3, 0.2]))


class MoneyCollector:
    """Accumulates injected bank transfers as (t_seconds, sender, receiver, amount, fmt, tag)."""

    def __init__(self, rng: np.random.Generator):
        self.rows: list[tuple] = []
        self.rng = rng

    def add(self, tag: str, t: float, s: str, r: str, amt: float, fmt: str | None = None) -> None:
        amt = float(round(max(amt, 1.0), 2))
        self.rows.append((float(t), s, r, amt, fmt or pick_format(amt, self.rng), tag))


class TradeCollector:
    """Accumulates trades as (t_seconds, stock, buyer, seller, price, qty, tag)."""

    def __init__(self):
        self.rows: list[tuple] = []

    def add(self, tag: str, t: float, stock: str, buyer: str, seller: str, price: float, qty: float) -> None:
        self.rows.append((float(t), stock, buyer, seller, float(round(price, 2)), int(max(qty, 1)), tag))


@dataclass
class World:
    cfg: dict
    rng: np.random.Generator
    bank_ids: np.ndarray
    activity: np.ndarray
    owner_of: dict
    money: MoneyCollector = None
    trades: TradeCollector = None
    rings: list = field(default_factory=list)
    hard: list = field(default_factory=list)
    demat_rows: list = field(default_factory=list)       # (account_id, owner_id, 'demat', type)
    background_demat: list = field(default_factory=list)
    used: set = field(default_factory=set)
    _pool: list = field(default_factory=list)
    _ptr: int = 0
    _demat_n: int = 0

    def __post_init__(self):
        self.money = MoneyCollector(self.rng)
        self.trades = TradeCollector()
        order = np.argsort(self.activity, kind="stable")
        pool = order[: max(10, len(order) * 3 // 5)].copy()      # quiet accounts host rings
        self.rng.shuffle(pool)
        self._pool = [self.bank_ids[i] for i in pool]

    # -- accounts -------------------------------------------------------
    def take_banks(self, k: int) -> list[str]:
        out = self._pool[self._ptr:self._ptr + k]
        if len(out) < k:
            raise RuntimeError("account pool exhausted; raise sample_accounts")
        self._ptr += k
        self.used.update(out)
        return out

    def random_banks(self, k: int) -> list[str]:
        return list(self.rng.choice(self.bank_ids, size=k, replace=False))

    def new_demat(self, owner_id: str, atype: str = "retail") -> str:
        did = f"D{self._demat_n:07d}"
        self._demat_n += 1
        self.demat_rows.append((did, owner_id, "demat", atype))
        return did

    # -- ground truth ---------------------------------------------------
    def next_id(self, prefix: str) -> str:
        n = sum(1 for r in self.rings if r["ring_id"].startswith(prefix)) + 1
        return f"{prefix}-{n:03d}"

    def start_time(self, span_days: float, u: float | None = None) -> float:
        """Ring start in seconds. `u` in [0,1) stratifies starts evenly across the horizon."""
        hi = max(1.0, self.cfg["n_days"] - span_days - 0.2) * DAY
        if u is None:
            return float(self.rng.uniform(0.3 * DAY, hi))
        return float(0.3 * DAY + u * (hi - 0.3 * DAY))

    def add_ring(self, ring_id: str, layer: str, typology: str, accounts: list, **extra) -> None:
        self.rings.append(dict(ring_id=ring_id, layer=layer, typology=typology,
                               accounts=list(accounts), source="injected", **extra))

    def add_hard(self, hn_id: str, kind: str, layer: str, accounts: list) -> None:
        self.hard.append(dict(hn_id=hn_id, kind=kind, layer=layer, accounts=list(accounts)))


def scale_below(amounts: np.ndarray, thr: float, rng: np.random.Generator) -> np.ndarray:
    """Rescale so the largest piece stays under the reporting threshold."""
    m = amounts.max()
    cap = thr * rng.uniform(0.6, 0.99)
    return amounts if m <= cap else amounts / m * cap
