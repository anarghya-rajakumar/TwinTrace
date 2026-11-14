"""Process-wide state for the web app: data, alerts, the trained model. Reloadable (reset after live ring injection)."""
from __future__ import annotations

import json
import threading

import joblib
import pandas as pd

from ..config import artifacts_dir, load_config, processed_dir
from ..eval.metrics import GroundTruth
from ..graph.prep import data_from_frames

GROUPS = {"money": "money", "trade": "trade", "bridge": "trade"}   # alert layer -> threshold group


class State:
    def __init__(self):
        self.lock = threading.RLock()
        self.load()

    def load(self) -> None:
        cfg = load_config()
        p, a = processed_dir(), artifacts_dir()
        self.cfg = cfg
        self.raw_tx = pd.read_parquet(p / "transactions.parquet")
        self.raw_trades = pd.read_parquet(p / "trades.parquet")
        self.accounts = pd.read_parquet(p / "accounts.parquet")
        rings = json.loads((p / "rings.json").read_text(encoding="utf-8"))
        self.hards = json.loads((p / "hard_negatives.json").read_text(encoding="utf-8"))
        self.data = data_from_frames(cfg, self.raw_tx, self.raw_trades, self.accounts, rings, self.hards)
        self.gt = GroundTruth(self.data)
        self.alerts = json.loads((a / "alerts_all.json").read_text(encoding="utf-8"))
        self.results = pd.read_csv(a / "results.csv")
        self.meta = json.loads((a / "meta.json").read_text(encoding="utf-8"))
        self.bundle = joblib.load(a / "model.joblib")
        self.thresholds = dict(self.bundle["thresholds"])
        self.injected: list[dict] = []
        self.reindex()

    def reindex(self) -> None:
        self.alert_by_id = {x["alert_id"]: x for x in self.alerts}
        self.acct_alerts: dict[str, list[str]] = {}
        for x in self.alerts:
            for acc in x["accounts"]:
                self.acct_alerts.setdefault(acc, []).append(x["alert_id"])

    def reset(self) -> None:
        with self.lock:
            self.load()


_STATE: State | None = None


def get_state() -> State:
    global _STATE
    if _STATE is None:
        _STATE = State()
    return _STATE


def set_state(s: State | None) -> None:
    global _STATE
    _STATE = s
