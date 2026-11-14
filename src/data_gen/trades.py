"""Layer-2 ground truth: market model, organic trades, wash/loss-booking rings, bridge rings, hard negatives."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..config import DAY, ROOT
from .world import World, scale_below

H = 3600.0


class Market:
    """Daily close paths per (anonymised) ticker. Real price *shape* from yfinance if enabled and online,
    otherwise a seeded random walk. Prices are always rescaled to the configured start price."""

    def __init__(self, cfg: dict, rng: np.random.Generator):
        self.cfg = cfg
        self.tickers = cfg["data"]["tickers"]
        self.kind = {k: v["kind"] for k, v in self.tickers.items()}
        n = cfg["n_days"] + 4
        self.close: dict[str, np.ndarray] = {}
        self.source = "synthetic random walk"
        cache = {}
        if cfg["data"].get("use_yfinance"):
            cache = self._try_yfinance(n)
            if cache:
                self.source = "yfinance shapes (proxies, rescaled)"
        for sym, spec in self.tickers.items():
            ret = cache.get(spec["proxy"])
            if ret is None:
                vol = 0.011 if spec["kind"] == "liquid" else 0.027
                ret = rng.normal(0.0002, vol, n)
            self.close[sym] = spec["start_price"] * np.exp(np.cumsum(ret) - ret[0])   # day 0 = start price

    def _try_yfinance(self, n: int) -> dict:
        try:  # best effort; any failure -> offline fallback
            import yfinance as yf
            out = {}
            for proxy in {v["proxy"] for v in self.tickers.values()}:
                d = yf.download(proxy, period="1y", progress=False, auto_adjust=True)["Close"].squeeze().dropna()
                r = np.log(d).diff().dropna().to_numpy()
                if len(r) >= n:
                    out[proxy] = r[-n:]
            return out
        except Exception:
            return {}

    def price_at(self, sym: str, t) -> np.ndarray | float:
        c = self.close[sym]
        t = np.asarray(t, dtype=float)
        d = np.floor(t / DAY).astype(int)
        f = t / DAY - d
        return c[d] * (1 - f) + c[d + 1] * f

    def daily_frame(self, t0: pd.Timestamp) -> pd.DataFrame:
        rows = []
        for s, c in self.close.items():
            for d in range(self.cfg["n_days"]):
                rows.append((s, (t0 + pd.Timedelta(days=d)).normalize(), float(c[d])))
        return pd.DataFrame(rows, columns=["stock", "date", "close"])


def weekday_list(cfg: dict) -> np.ndarray:
    dow0 = pd.Timestamp(cfg["start_date"]).day_of_week
    return np.array([d for d in range(cfg["n_days"]) if (dow0 + d) % 7 < 5])


def _tt(w: World, days) -> np.ndarray:
    days = np.atleast_1d(days)
    return days * DAY + (9.25 + w.rng.uniform(0, 6.25, len(days))) * H


def background_trades(w: World, mkt: Market, demat_ids: list[str]) -> pd.DataFrame:
    rng, cfg = w.rng, w.cfg
    n = cfg["data"]["n_background_trades"]
    stocks = list(mkt.tickers)
    p = np.array([0.28, 0.26, 0.24, 0.12, 0.10])[: len(stocks)]
    p = p / p.sum()
    si = rng.choice(len(stocks), n, p=p)
    day = rng.choice(w.weekdays, n)
    t = _tt(w, day)
    act = rng.lognormal(0, 0.9, len(demat_ids))
    act /= act.sum()
    ids = np.array(demat_ids, dtype=object)
    b = rng.choice(len(ids), n, p=act)
    s = rng.choice(len(ids), n, p=act)
    s = np.where(s == b, (s + 1) % len(ids), s)
    price = np.empty(n)
    qty = np.empty(n)
    for k, sym in enumerate(stocks):
        m = si == k
        price[m] = mkt.price_at(sym, t[m]) * (1 + rng.normal(0, 0.0015, m.sum()))
        med = 40 if mkt.kind[sym] == "liquid" else 15
        qty[m] = rng.lognormal(np.log(med), 0.9, m.sum())
    return pd.DataFrame(dict(t=t, stock=np.array(stocks, dtype=object)[si], buyer=ids[b], seller=ids[s],
                             price=np.round(price, 2), qty=np.maximum(1, qty.round()).astype(int), tag=None))


# ------------------------------------------------------------------ helpers
def _pick_stock(w: World, mkt: Market, p_illiquid: float) -> str:
    kinds = mkt.kind
    pool = [s for s, k in kinds.items() if (k == "illiquid") == (w.rng.random() < p_illiquid)]
    pool = pool or list(kinds)
    return str(w.rng.choice(pool))


def _schedule_days(w: World, start_day: int, span_days: int, n: int) -> np.ndarray:
    avail = [d for d in w.weekdays if start_day <= d <= start_day + span_days + 2]
    if not avail:
        avail = [int(w.weekdays[-1])]
    return np.sort(_tt(w, w.rng.choice(avail, n)))


def _start_day(w: World, span_days: int, u: float | None = None) -> int:
    cands = w.weekdays[(w.weekdays >= 1) & (w.weekdays <= w.cfg["n_days"] - span_days - 3)]
    if u is None:
        return int(w.rng.choice(cands))
    return int(cands[min(len(cands) - 1, int(u * len(cands)))])


def drip_fund(w: World, tag: str, funder: str, banks: list[str], t_first: float) -> None:
    """A single funder drips money into the owners' bank accounts in the days before trading."""
    rng, thr = w.rng, w.cfg["threshold_inr"]
    for b in banks:
        for _ in range(int(rng.integers(1, 3))):
            a = rng.uniform(15000, 90000)
            if rng.random() < w.cfg["stealth"]:
                a = min(a, thr * rng.uniform(0.6, 0.98))
            w.money.add(tag, max(0.1 * DAY, t_first - rng.uniform(1, 10) * DAY), funder, b, a)


def _owner_banks(w: World, k: int) -> tuple[list[str], list[str]]:
    banks = w.take_banks(k)
    return banks, [w.owner_of[b] for b in banks]


def _wash_core(w: World, mkt: Market, tag: str, members: list[str], stock: str, d0: int, span_days: int):
    rng, cfg = w.rng, w.cfg
    k = len(members)
    rounds = int(rng.integers(4, 9))
    times = _schedule_days(w, d0, span_days, rounds * k)
    order = rng.permutation(k)
    illiq = mkt.kind[stock] == "illiquid"
    qbase = rng.uniform(200, 800) if illiq else rng.uniform(100, 400)
    pump = rng.uniform(0.0, 0.02)
    total_n = rounds * k
    vol_int, idx = 0, 0
    for r in range(rounds):
        q = qbase * rng.uniform(0.8, 1.2)
        for i in range(k):
            seller, buyer = members[order[i]], members[order[(i + 1) % k]]
            t = times[idx]
            qty = max(1, round(q * (1 + rng.normal(0, 0.03))))
            px = float(mkt.price_at(stock, t)) * (1 + pump * idx / total_n + rng.normal(0, 0.002))
            w.trades.add(tag, t, stock, buyer, seller, px, qty)
            vol_int += qty
            idx += 1
    share = rng.uniform(0.70, 0.95 - 0.10 * cfg["stealth"])
    v_ext = vol_int * (1 - share) / share
    m_ext = max(2, int(k * (1 - share) * 10))
    for j in range(m_ext):
        t = float(rng.uniform(times.min(), times.max()))
        m = members[j % k]
        other = str(rng.choice(w.background_demat))
        qty = max(1, round(v_ext / m_ext))
        px = float(mkt.price_at(stock, t)) * (1 + rng.normal(0, 0.002))
        if j % 2 == 0:
            w.trades.add(tag, t, stock, m, other, px, qty)
        else:
            w.trades.add(tag, t, stock, other, m, px, qty)
    return float(times.min()), float(times.max())


def wash_ring(w: World, mkt: Market, u: float | None = None) -> None:
    rng, cfg = w.rng, w.cfg
    lo, hi = cfg["ring_size"]["wash_trading"]
    k = int(rng.integers(lo, hi + 1))
    banks, owners = _owner_banks(w, k)
    mode = "shared_funder" if rng.random() < 0.6 else "same_owner"
    if mode == "same_owner":
        m = int(rng.integers(1, 3))
        owners = [owners[i % m] for i in range(k)]
    members = [w.new_demat(o) for o in owners]
    rid = w.next_id("R-WT")
    stock = _pick_stock(w, mkt, 0.7 - 0.4 * cfg["stealth"])
    span = int(rng.integers(1, 4) * max(1.0, cfg["timing_jitter"]))
    d0 = _start_day(w, span, u)
    tmin, tmax = _wash_core(w, mkt, rid, members, stock, d0, span)
    if mode == "shared_funder":
        drip_fund(w, rid + ":fund", w.take_banks(1)[0], banks, tmin)
    w.add_ring(rid, "trade", "wash_trading", members, stock=stock, funding_mode=mode, ts_start=tmin, ts_end=tmax)


def loss_booking_pair(w: World, mkt: Market, u: float | None = None) -> None:
    """Repeated same-day reversals at 20-60% off market: one account books losses, the other gains."""
    rng, cfg = w.rng, w.cfg
    banks, owners = _owner_banks(w, 2)
    mode = "shared_funder" if rng.random() < 0.5 else "same_owner"
    if mode == "same_owner":
        owners = [owners[0], owners[0]]
    loser, gainer = (w.new_demat(o) for o in owners)
    rid = w.next_id("R-LB")
    stock = _pick_stock(w, mkt, 0.6)
    k = int(rng.integers(3, 9))
    d0 = _start_day(w, 5, u)
    days = np.sort(rng.choice([d for d in w.weekdays if d0 <= d <= d0 + 14] or [d0], size=k))
    sign = 1 if rng.random() < 0.5 else -1                       # sell cheap (-) or buy dear (+) at the pair
    illiq = mkt.kind[stock] == "illiquid"
    tmin = None
    for d in days:
        t1 = d * DAY + (9.25 + rng.uniform(0, 2)) * H
        t2 = t1 + rng.uniform(1, 4) * H
        q = rng.uniform(50, 400) if illiq else rng.uniform(100, 600)
        dev = rng.uniform(0.2, 0.6)
        m1, m2 = float(mkt.price_at(stock, t1)), float(mkt.price_at(stock, t2))
        if sign < 0:   # loser sells cheap to gainer, gainer returns the shares at market
            w.trades.add(rid, t1, stock, gainer, loser, m1 * (1 - dev), q)
            w.trades.add(rid, t2, stock, loser, gainer, m2, q)
        else:          # loser buys dear from gainer, then sells back at market
            w.trades.add(rid, t1, stock, loser, gainer, m1 * (1 + dev), q)
            w.trades.add(rid, t2, stock, gainer, loser, m2, q)
        tmin = t1 if tmin is None else min(tmin, t1)
    for m in (loser, gainer):                                    # a few ordinary trades each
        for _ in range(int(rng.integers(1, 4))):
            t = float(_tt(w, rng.choice(days))[0])
            px = float(mkt.price_at(stock, t))
            other = str(rng.choice(w.background_demat))
            w.trades.add(rid, t, stock, m, other, px, rng.uniform(10, 60))
    if mode == "shared_funder":
        drip_fund(w, rid + ":fund", w.take_banks(1)[0], banks, tmin)
    w.add_ring(rid, "trade", "loss_booking", [loser, gainer], stock=stock, funding_mode=mode,
               ts_start=float(tmin), ts_end=float(days[-1] * DAY + 15 * H))


def bridge_ring(w: World, mkt: Market, u: float | None = None) -> None:
    """Bank -> trading accounts -> wash trades -> withdrawal. The funding looks like harmless drip payments."""
    rng, cfg, thr = w.rng, w.cfg, w.cfg["threshold_inr"]
    lo, hi = cfg["ring_size"]["bridge"]
    k = int(rng.integers(lo, hi + 1))
    banks, owners = _owner_banks(w, k)
    src, exit_acct = w.take_banks(2)
    members = [w.new_demat(o) for o in owners]
    rid = w.next_id("R-BR")
    stock = _pick_stock(w, mkt, 0.5)
    span = int(rng.integers(1, 4))
    d0 = _start_day(w, span + 6, u)
    tmin, tmax = _wash_core(w, mkt, rid, members, stock, d0, span)
    funded = {b: 0.0 for b in banks}
    for b in banks:                                              # stealth drip over the preceding days
        for _ in range(int(rng.integers(1, 4))):
            a = rng.uniform(20000, 80000)
            if rng.random() < cfg["stealth"]:
                a = min(a, thr * rng.uniform(0.6, 0.98))
            funded[b] += a
            w.money.add(rid, max(0.1 * DAY, tmin - rng.uniform(1, 10) * DAY), src, b, a)
    for b in banks:                                              # cash-out after the trades
        w.money.add(rid, tmax + rng.uniform(0.5, 3) * DAY, b, exit_acct, funded[b] * rng.uniform(0.85, 0.95))
    w.add_ring(rid, "bridge", "market_layering", [src] + banks + members + [exit_acct], stock=stock,
               ts_start=max(0.1 * DAY, tmin - 10 * DAY), ts_end=tmax + 3.5 * DAY)


# ------------------------------------------------------------------ hard negatives
def market_maker(w: World, mkt: Market) -> None:
    rng = w.rng
    mm = str(rng.choice(w.background_demat))
    hid = f"H-MM-{sum(1 for h in w.hard if h['kind'] == 'market_maker') + 1:03d}"
    for stock in rng.choice(list(mkt.tickers), size=2, replace=False):
        n = int(rng.integers(150, 251))
        times = _tt(w, rng.choice(w.weekdays, n))
        for j in range(n):
            other = str(rng.choice(w.background_demat))
            qty = max(1, round(rng.lognormal(np.log(60), 0.5)))
            px = float(mkt.price_at(stock, times[j])) * (1 + rng.normal(0, 0.001))
            if j % 2 == 0:
                w.trades.add(hid, times[j], stock, mm, other, px, qty)
            else:
                w.trades.add(hid, times[j], stock, other, mm, px, qty)
    w.add_hard(hid, "market_maker", "trade", [mm])


def legit_pair(w: World, mkt: Market) -> None:
    """Legitimate repeated counterparties: 2 accounts trading both ways, or a small active group
    (e.g. a trading desk) cycling a stock at market prices. In the trade graph alone the group looks
    like a wash ring; what differs is where the money behind the accounts came from."""
    rng = w.rng
    k = int(rng.choice([2, 2, 3, 4]))
    members = [str(x) for x in rng.choice(w.background_demat, size=k, replace=False)]
    hid = f"H-PAIR-{sum(1 for h in w.hard if h['kind'] == 'legit_repeat_pair') + 1:03d}"
    stock = str(rng.choice(list(mkt.tickers)))
    if k == 2:
        n = int(rng.integers(3, 11))
        times = np.sort(_tt(w, rng.choice(w.weekdays, n)))
        for t in times:
            px = float(mkt.price_at(stock, t)) * (1 + rng.normal(0, 0.002))
            buyer, seller = (members[0], members[1]) if rng.random() < 0.5 else (members[1], members[0])
            w.trades.add(hid, t, stock, buyer, seller, px, rng.uniform(20, 200))
        tmin = float(times.min())
    else:
        d0 = _start_day(w, 3)
        rounds = int(rng.integers(3, 7))
        times = _schedule_days(w, d0, 2, rounds * k)
        order = rng.permutation(k)
        idx = 0
        illiq = mkt.kind[stock] == "illiquid"
        q0 = rng.uniform(100, 500) if illiq else rng.uniform(60, 250)
        for _ in range(rounds):
            q = q0 * rng.uniform(0.8, 1.2)
            for i in range(k):
                t = times[idx]
                idx += 1
                px = float(mkt.price_at(stock, t)) * (1 + rng.normal(0, 0.002))
                w.trades.add(hid, t, stock, members[order[(i + 1) % k]], members[order[i]], px, q * (1 + rng.normal(0, 0.03)))
        tmin = float(times.min())
        for j in range(max(2, k)):                               # ordinary outside trades, like the rings have
            t = float(rng.uniform(times.min(), times.max()))
            px = float(mkt.price_at(stock, t)) * (1 + rng.normal(0, 0.002))
            other = str(rng.choice(w.background_demat))
            if j % 2 == 0:
                w.trades.add(hid, t, stock, members[j % k], other, px, q0 * 0.3)
            else:
                w.trades.add(hid, t, stock, other, members[j % k], px, q0 * 0.3)
    if rng.random() < 0.15:                                      # relatives funded by the same person
        banks = [w.bank_of_owner[w.demat_owner[x]] for x in members]
        drip_fund(w, hid + ":fund", w.take_banks(1)[0], banks, tmin)
    w.add_hard(hid, "legit_repeat_pair", "trade", members)


def inject_trades(w: World, mkt: Market) -> None:
    n = w.cfg["ring_counts"]["wash_trading"]
    for i in range(n):
        wash_ring(w, mkt, (i + w.rng.random()) / n)
    n = w.cfg["ring_counts"]["loss_booking"]
    for i in range(n):
        loss_booking_pair(w, mkt, (i + w.rng.random()) / n)
    n = w.cfg["ring_counts"]["bridge"]
    for i in range(n):
        bridge_ring(w, mkt, (i + w.rng.random()) / n)
    hn = w.cfg["hard_negative_counts"]
    for _ in range(hn["market_maker"]):
        market_maker(w, mkt)
    for _ in range(hn["legit_repeat_pair"]):
        legit_pair(w, mkt)
