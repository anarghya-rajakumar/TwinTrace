"""Template case summaries. Every number comes from `alert["evidence"]`; nothing is invented."""
from __future__ import annotations

import re

from .typology import TYPOLOGY_NAMES


def inr(x: float) -> str:
    x = float(x)
    if x >= 1e7:
        return f"INR {x / 1e7:.1f}Cr"
    if x >= 1e5:
        return f"INR {x / 1e5:.1f}L"
    return f"INR {x:,.0f}"


def pct(x: float) -> str:
    return f"{float(x) * 100:.0f}%"


def hrs(x: float) -> str:
    x = float(x)
    return f"{x:.0f} hours" if x >= 10 else f"{x:.1f} hours"


def num(x: float) -> str:
    return f"{int(round(float(x))):,}"


def _g(ev: dict, k: str, default=0.0):
    v = ev.get(k, default)
    return default if v is None else v


def _drivers(ev: dict) -> str:
    parts = []
    for i in (1, 2, 3):
        if f"driver_{i}_pct" in ev:
            parts.append(f"{ev[f'driver_{i}_label']} ({num(ev[f'driver_{i}_pct'])}%)")
    return ("Top score drivers: " + ", ".join(parts) + ".") if parts else ""


def _flow(ev: dict) -> str:
    s = []
    if ev.get("entry_label"):
        s.append(f"Entry point: {ev['entry_label']}.")
    if ev.get("exit_label"):
        s.append(f"Exit point: {ev['exit_label']}.")
    return " ".join(s)


def summarize(alert: dict) -> str:
    ev, typ = alert["evidence"], alert["typology"]
    risk = f"Risk score: {num(alert['score'])}."
    if typ in ("fan_in_structuring", "fan_in"):
        body = (f"Account {ev['hub']} received {inr(_g(ev, 'total_inr'))} from {num(_g(ev, 'n_counterparties'))} accounts "
                f"within {hrs(_g(ev, 'span_hours'))}.")
        if typ == "fan_in_structuring" and "n_structured" in ev:
            body += (f" {num(ev['n_structured'])} of {num(ev['n_tx'])} transfers were between {inr(ev['band_low_inr'])} and "
                     f"{inr(ev['band_high_inr'])}, just under the {inr(ev['threshold_inr'])} reporting threshold.")
        if "pass_forward_share" in ev:
            body += (f" It then forwarded {pct(ev['pass_forward_share'])} of the inflow within {hrs(ev['pass_dwell_hours'])}."
                     " This matches fan-in followed by pass-through.")
        else:
            body += " This matches aggregation" + (" with structuring." if typ == "fan_in_structuring" else " (fan-in).")
    elif typ == "fan_out":
        body = (f"Account {ev['hub']} sent {inr(_g(ev, 'total_inr'))} to {num(_g(ev, 'n_counterparties'))} accounts within "
                f"{hrs(_g(ev, 'span_hours'))} in near-equal pieces (variation {pct(_g(ev, 'amount_cv'))}); "
                f"{pct(_g(ev, 'new_pair_share'))} of these account pairs had never transacted before. "
                "This matches dispersion (fan-out).")
    elif typ == "round_trip":
        body = (f"Money left account {ev['origin']} and returned to it after {num(ev['n_hops'])} hops within "
                f"{hrs(ev['duration_hours'])}, keeping {pct(ev['retention_mean'])} of the amount at each hop "
                f"({inr(ev['amount_start_inr'])} out, {inr(ev['amount_end_inr'])} back). This matches round-tripping.")
    elif typ == "mule_chain":
        body = (f"Account {ev.get('source') or 'unknown'} sent {inr(_g(ev, 'amount_in_inr'))} through {num(_g(ev, 'n_pass_accounts'))} "
                f"intermediary accounts, each forwarding {pct(_g(ev, 'ratio_mean'))} of what it received within a median of "
                f"{hrs(_g(ev, 'dwell_median_hours'))}, ending at {ev.get('sink') or 'unknown'}. "
                "This matches a mule / pass-through chain.")
    elif typ == "wash_trading":
        body = (f"{num(ev['n_accounts'])} accounts traded {ev['stock']} among themselves {num(ev['n_trades'])} times over "
                f"{num(ev['n_days'])} days. {pct(ev['internal_volume_share'])} of their volume stayed inside the group and "
                f"net position is {pct(ev['net_position_ratio'])} of gross volume.")
        if "funding_source" in ev:
            body += (f" {num(ev['n_owners_funded'])} of {num(ev['n_owners'])} owners were funded by the same source "
                     f"({inr(ev['funded_inr'])}).")
        body += " This matches wash trading."
    elif typ == "loss_booking":
        body = (f"{num(ev['n_accounts'])} accounts traded {ev['stock']} back and forth on {num(ev['reversal_days'])} days, "
                f"{num(ev['n_trades'])} trades in all, at prices {pct(ev['mean_price_deviation'])} away from the day's "
                f"market price on average (up to {pct(ev['max_price_deviation'])}); one side's profit/loss imbalance was "
                f"{pct(ev['pnl_asymmetry'])} of traded value. This matches loss-booking.")
    elif typ == "market_layering":
        body = (f"{num(ev['n_owners'])} owners were funded by {ev['funding_source']} ({inr(ev['funded_inr'])}), traded "
                f"{ev.get('stock', 'a stock')} almost only with each other ({num(ev['n_trades'])} trades, "
                f"{pct(ev['internal_volume_share'])} of volume internal), then {inr(ev['withdrawn_inr'])} left to "
                f"{ev['exit_account']}. This matches layering through the market (bank to trading account to withdrawal).")
    else:
        body = (f"A cluster of {num(_g(ev, 'n_accounts'))} accounts moved {inr(_g(ev, 'amount_inr'))} in "
                f"{num(_g(ev, 'n_tx'))} transfers, {pct(_g(ev, 'internal_share'))} of it staying inside the group. "
                "No single typology matched; flagged for human review.")
    parts = [body, _flow(ev), _drivers(ev), risk]
    return " ".join(p for p in parts if p)


# ------------------------------------------------------------------ used by tests
_ID = re.compile(r"\b[A-Z]{1,2}-?\d{3,}\b|\b[BDO]\d{5,}\b|\bSML[XY]\b|\bLRG[ABC]\b")


def numbers_in(text: str) -> set[str]:
    clean = _ID.sub(" ", text).replace(",", "")
    return set(re.findall(r"\d+(?:\.\d+)?", clean))


def allowed_numbers(evidence: dict) -> set[str]:
    """Every rendering of every numeric evidence value that the templates can produce."""
    out: set[str] = set()
    for v in evidence.values():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        for scale, fmts in ((1, ("{:.0f}", "{:.1f}", "{:.2f}")), (100, ("{:.0f}",)), (1e-5, ("{:.1f}",)), (1e-7, ("{:.1f}",))):
            for f in fmts:
                out.add(f.format(float(v) * scale))
    return out


def unsupported_numbers(alert: dict) -> set[str]:
    return numbers_in(alert["summary"]) - allowed_numbers(alert["evidence"])
