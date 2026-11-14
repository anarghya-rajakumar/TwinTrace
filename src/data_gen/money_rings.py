"""Layer-1 ground truth: planted laundering rings and innocent look-alike hard negatives."""
from __future__ import annotations

import numpy as np

from ..config import DAY
from .world import World, scale_below

H = 3600.0


def _size(w: World, key: str) -> int:
    lo, hi = w.cfg["ring_size"][key]
    return int(w.rng.integers(lo, hi + 1))


def _maybe_stealth(w: World, amounts: np.ndarray) -> np.ndarray:
    if w.rng.random() < w.cfg["stealth"]:
        return scale_below(amounts, w.cfg["threshold_inr"], w.rng)
    return amounts


# ----------------------------------------------------------------- planted rings
def fan_out(w: World, u: float | None = None) -> None:
    """One source disperses a pool of money into many near-equal pieces within a day or two."""
    rng, jit = w.rng, w.cfg["timing_jitter"]
    k = _size(w, "fan_out")
    accts = w.take_banks(k + 1)
    src, rec = accts[0], accts[1:]
    rid = w.next_id("R-FO")
    span_h = rng.uniform(6, 36) * jit
    t0 = w.start_time(span_h / 24 + 0.5, u)
    total = rng.uniform(3e5, 2.5e6)
    pieces = _maybe_stealth(w, np.clip(total / k * (1 + rng.normal(0, 0.08, k)), 1000, None))
    for a, r in zip(pieces, rec):
        w.money.add(rid, t0 + rng.uniform(0, span_h * H), src, r, a)
    w.add_ring(rid, "money", "fan_out", accts, ts_start=t0)


def fan_in_structuring(w: World, u: float | None = None) -> None:
    """Many senders each pay just under the reporting threshold into one hub; hub often forwards on."""
    rng, jit, thr = w.rng, w.cfg["timing_jitter"], w.cfg["threshold_inr"]
    k = _size(w, "fan_in")
    forward = rng.random() < 0.5
    accts = w.take_banks(k + 1 + int(forward))
    hub, senders = accts[0], accts[1:1 + k]
    rid = w.next_id("R-FI")
    span_h = rng.uniform(8, 48) * jit
    t0 = w.start_time(span_h / 24 + 0.5, u)
    amts = rng.uniform(0.9 * thr, 0.998 * thr, k)                 # 45,000 .. 49,900 at the default
    times = t0 + rng.uniform(0, span_h * H, k)
    for a, s, t in zip(amts, senders, times):
        w.money.add(rid, t, s, hub, a)
    if forward:
        w.money.add(rid, times.max() + rng.uniform(1, 6) * H, hub, accts[-1], amts.sum() * rng.uniform(0.9, 0.97))
    w.add_ring(rid, "money", "fan_in_structuring", accts, ts_start=t0)


def round_trip(w: World, u: float | None = None) -> None:
    """A -> B -> C -> ... -> A inside 72h, 90-99% of the money retained per hop."""
    rng = w.rng
    n = _size(w, "round_trip")
    nodes = w.take_banks(n)
    rid = w.next_id("R-RT")
    dur_h = min(72.0, rng.uniform(6, 70) * w.cfg["timing_jitter"])
    t0 = w.start_time(dur_h / 24 + 0.5, u)
    times = t0 + np.sort(rng.uniform(0, dur_h * H, n))
    amt = [rng.uniform(2e5, 2e6)]
    for _ in range(n - 1):
        amt.append(amt[-1] * rng.uniform(0.90, 0.99))
    amt = _maybe_stealth(w, np.array(amt))
    for i in range(n):
        w.money.add(rid, times[i], nodes[i], nodes[(i + 1) % n], amt[i])
    w.add_ring(rid, "money", "round_trip", nodes, ts_start=t0)


def mule_chain(w: World, u: float | None = None) -> None:
    """Money enters a mule and leaves within minutes to hours, hop after hop, 90-98% passed on."""
    rng = w.rng
    hops = _size(w, "mule_chain")
    nodes = w.take_banks(hops + 1)
    rid = w.next_id("R-MC")
    t0 = w.start_time(2.5, u)
    amt = [rng.uniform(1e5, 1.5e6)]
    t = [t0]
    for _ in range(hops):
        amt.append(amt[-1] * rng.uniform(0.90, 0.98))
        dwell = float(np.clip(rng.uniform(300, 6 * H) * w.cfg["timing_jitter"], 300, 6 * H))
        t.append(t[-1] + dwell)
    amt = _maybe_stealth(w, np.array(amt))
    for i in range(hops):
        w.money.add(rid, t[i], nodes[i], nodes[i + 1], amt[i])
    w.add_ring(rid, "money", "mule_chain", nodes, ts_start=t0)


# ----------------------------------------------------------------- hard negatives
def payroll_fanout(w: World) -> None:
    """A company pays 20-60 employees on the same morning, monthly. Looks like dispersion."""
    rng = w.rng
    n = int(rng.integers(20, 61))
    accts = w.take_banks(n + 1)
    corp, emps = accts[0], accts[1:]
    hid = f"H-PAY-{sum(1 for h in w.hard if h['kind'] == 'payroll_fanout') + 1:03d}"
    equal = rng.random() < 0.3
    sal = np.full(n, float(np.round(rng.uniform(20000, 45000), -2))) if equal else \
        np.clip(rng.lognormal(np.log(35000), 0.5, n), 12000, 400000)
    o = rng.uniform(0, 30 * DAY)
    k = 0
    while o + k * 30 * DAY < (w.cfg["n_days"] - 0.5) * DAY:
        base = np.floor((o + k * 30 * DAY) / DAY) * DAY + rng.uniform(8, 11) * H
        for e, s in zip(emps, sal):
            w.money.add(hid, base + rng.uniform(0, 3 * H), corp, e, s * (1 + rng.normal(0, 0.01)))
        k += 1
    w.add_hard(hid, "payroll_fanout", "money", accts)


def rent_fanin(w: World) -> None:
    """Tenants pay a landlord the same amounts in the first days of each month."""
    rng = w.rng
    n = int(rng.integers(8, 26))
    accts = w.take_banks(n + 1)
    land, tenants = accts[0], accts[1:]
    hid = f"H-RENT-{sum(1 for h in w.hard if h['kind'] == 'rent_fanin') + 1:03d}"
    rent = np.round(rng.uniform(8000, 32000, n) / 500) * 500
    o = rng.uniform(0, 30 * DAY)
    k = 0
    while o + k * 30 * DAY < (w.cfg["n_days"] - 5) * DAY:
        for t_, a in zip(tenants, rent):
            w.money.add(hid, o + k * 30 * DAY + rng.uniform(0, 4 * DAY), t_, land, a)
        k += 1
    w.add_hard(hid, "rent_fanin", "money", accts)


def shop_settlement(w: World) -> None:
    """A shop collects many small customer payments and forwards ~95% to its owner every evening."""
    rng = w.rng
    shop, owner = w.take_banks(2)
    hid = f"H-SHOP-{sum(1 for h in w.hard if h['kind'] == 'shop_settlement') + 1:03d}"
    d0 = int(rng.integers(0, 40))
    d1 = min(w.cfg["n_days"] - 1, d0 + int(rng.integers(30, 61)))
    for d in range(d0, d1):
        m = int(rng.integers(10, 26))
        cust = w.random_banks(m)
        amts = np.clip(rng.lognormal(np.log(800), 0.7, m), 50, 8000)
        for c, a in zip(cust, amts):
            w.money.add(hid, d * DAY + rng.uniform(9, 20) * H, c, shop, a)
        w.money.add(hid, d * DAY + rng.uniform(21, 23.5) * H, shop, owner, amts.sum() * rng.uniform(0.94, 0.99))
    w.add_hard(hid, "shop_settlement", "money", [shop, owner])


def family_circular(w: World) -> None:
    """Family members send each other similar pocket-money amounts in a loop every couple of weeks."""
    rng = w.rng
    n = int(rng.integers(3, 6))
    mem = w.take_banks(n)
    hid = f"H-FAM-{sum(1 for h in w.hard if h['kind'] == 'family_circular') + 1:03d}"
    base = np.full(n, np.round(rng.uniform(8000, 25000) / 500) * 500)   # same amount all round: a hard round-trip look-alike
    period = rng.uniform(10, 18) * DAY
    t = rng.uniform(0, 10 * DAY)
    while t < (w.cfg["n_days"] - 2.5) * DAY:
        for i in range(n):
            w.money.add(hid, t + rng.uniform(0, 48 * H), mem[i], mem[(i + 1) % n], base[i] * (1 + rng.normal(0, 0.02)))
        t += period
    w.add_hard(hid, "family_circular", "money", mem)


def inject_money(w: World) -> None:
    for fn, key in [(fan_out, "fan_out"), (fan_in_structuring, "fan_in"), (round_trip, "round_trip"),
                    (mule_chain, "mule_chain")]:
        n = w.cfg["ring_counts"][key]
        for i in range(n):
            fn(w, (i + w.rng.random()) / n)
    hn = w.cfg["hard_negative_counts"]
    for fn, key in [(payroll_fanout, "payroll_fanout"), (rent_fanin, "rent_fanin"),
                    (shop_settlement, "shop_settlement"), (family_circular, "family_circular")]:
        for _ in range(hn[key]):
            fn(w)
