"""Robustness: regenerate the whole dataset with several seeds and report the spread of the headline metrics.
Each run uses its own temporary TWINTRACE_HOME, so the real data/ and artifacts/ folders are untouched.
Usage: python -m src.eval.seed_sweep 1 2 3 4"""
from __future__ import annotations

import copy
import os
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd


def main(seeds: list[int]) -> pd.DataFrame:
    from ..config import artifacts_dir, load_config
    from ..data_gen.build import build
    from ..pipeline import METHOD_TITLES, run_pipeline
    out_dir = artifacts_dir()
    base = load_config()
    rows = []
    for sd in seeds:
        t = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TWINTRACE_HOME"] = tmp
            cfg = copy.deepcopy(base)
            cfg["seed"] = sd
            build(cfg, verbose=False)
            res = run_pipeline(cfg, log=lambda *_: None)["results"]
        os.environ.pop("TWINTRACE_HOME", None)
        for _, r in res[res["headline"]].iterrows():
            rows.append(dict(seed=sd, method=r["method"], scorer=r["scorer"], precision=r["precision"], recall=r["recall"],
                             f1=r["f1"], fpr=r["fpr"], alerts_per_1000=r["alerts_per_1000_accounts"],
                             rings=r["rings"], rings_found=r["rings_found"]))
        print(f"[seed {sd}] done in {time.time() - t:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "seed_sweep.csv", index=False)
    agg = df.groupby("method")[["precision", "recall", "f1", "fpr", "alerts_per_1000"]].agg(["mean", "std"])
    lines = [f"# Seed sweep ({len(seeds)} seeds: {', '.join(map(str, seeds))}); headline rows, test split each time", "",
             "| Method | Precision | Recall | F1 | FPR | Alerts / 1,000 accts |", "|---|---|---|---|---|---|"]
    for m in ["rule_baseline", "single_layer", "two_layer_no_bridge", "twintrace"]:
        a = agg.loc[m]
        cell = lambda c, f="{:.3f}": f"{f.format(a[(c, 'mean')])} ± {f.format(a[(c, 'std')])}"  # noqa: E731
        lines.append(f"| {METHOD_TITLES[m]} | {cell('precision')} | {cell('recall')} | {cell('f1')} | {cell('fpr', '{:.4f}')} | "
                     f"{cell('alerts_per_1000', '{:.1f}')} |")
    piv = df.pivot(index="seed", columns="method", values="f1")
    lines += ["", f"TwinTrace minus two-layers-without-bridge F1 per seed: {', '.join(f'{v:+.3f}' for v in (piv['twintrace'] - piv['two_layer_no_bridge']))}",
              f"TwinTrace minus single-layer F1 per seed: {', '.join(f'{v:+.3f}' for v in (piv['twintrace'] - piv['single_layer']))}"]
    (out_dir / "seed_sweep.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return df


if __name__ == "__main__":
    main([int(a) for a in sys.argv[1:]] or [1, 2, 3, 4])
