"""Shared fixtures. A small dataset is built once per session in a temp folder (TWINTRACE_HOME), so the
tests never touch the real data/processed or artifacts folders."""
import copy
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def small_cfg():
    from src.config import load_config
    cfg = copy.deepcopy(load_config())
    cfg["sample_accounts"] = 3000
    cfg["n_background_tx"] = 16000
    cfg["ring_counts"] = {k: 8 for k in cfg["ring_counts"]}
    cfg["hard_negative_counts"] = {k: 3 for k in cfg["hard_negative_counts"]}
    cfg["data"]["n_background_trades"] = 6000
    cfg["scoring"]["weight_search_iters"] = 60
    cfg["scoring"]["target_fpr"] = 0.01
    return cfg


@pytest.fixture(scope="session")
def home(tmp_path_factory):
    h = tmp_path_factory.mktemp("twintrace_home")
    os.environ["TWINTRACE_HOME"] = str(h)
    yield h
    os.environ.pop("TWINTRACE_HOME", None)


@pytest.fixture(scope="session")
def built(home, small_cfg):
    from src.data_gen.build import build
    stats = build(small_cfg, verbose=False)
    return dict(home=home, cfg=small_cfg, stats=stats)


@pytest.fixture(scope="session")
def tables(built):
    import json

    import pandas as pd
    p = built["home"] / "data" / "processed"
    return dict(tx=pd.read_parquet(p / "transactions.parquet"), trades=pd.read_parquet(p / "trades.parquet"),
                accounts=pd.read_parquet(p / "accounts.parquet"),
                rings=json.loads((p / "rings.json").read_text()), hards=json.loads((p / "hard_negatives.json").read_text()))


@pytest.fixture(scope="session")
def pipeline_out(built):
    from src.pipeline import run_pipeline
    return run_pipeline(built["cfg"], log=lambda *_: None)
