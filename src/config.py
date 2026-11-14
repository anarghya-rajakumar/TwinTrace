"""Config loading and shared path / time-split helpers."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
DAY = 86400.0


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path) if path else ROOT / "config.yaml"
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def home() -> Path:
    """Base folder for generated data and artifacts. Override with TWINTRACE_HOME (the tests do)."""
    return Path(os.environ["TWINTRACE_HOME"]) if os.environ.get("TWINTRACE_HOME") else ROOT


def processed_dir() -> Path:
    d = home() / "data" / "processed"
    d.mkdir(parents=True, exist_ok=True)
    return d


def artifacts_dir() -> Path:
    d = home() / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def t0(cfg: dict) -> pd.Timestamp:
    return pd.Timestamp(cfg["start_date"])


def split_bounds(cfg: dict) -> dict[str, tuple[float, float]]:
    """Return {split: (start_s, end_s)} in seconds since t0. Time-based only."""
    total = cfg["n_days"] * DAY
    a = cfg["splits"]["tune"] * total
    b = a + cfg["splits"]["val"] * total
    return {"tune": (0.0, a), "val": (a, b), "test": (b, total + 1.0)}


def split_of(t_seconds: float, cfg: dict) -> str:
    for name, (lo, hi) in split_bounds(cfg).items():
        if lo <= t_seconds < hi:
            return name
    return "test"
