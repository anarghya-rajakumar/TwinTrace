"""Score A (hand-weighted, tuned on the tuning split) and Score B (XGBoost + SHAP)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score
from xgboost import XGBClassifier

from .features import HAND_PRIOR, LABELS


class HandScorer:
    """0..100 weighted sum of explainable components. Weights start from a hand-set prior and are tuned by
    seeded random search on the tuning split (objective: average precision)."""

    def __init__(self, seed: int = 0, iters: int = 400):
        self.seed, self.iters = seed, iters
        self.names = list(HAND_PRIOR)
        self.w = np.array([HAND_PRIOR[n] for n in self.names], float)

    def fit(self, comps: pd.DataFrame, y: np.ndarray) -> "HandScorer":
        X = comps[self.names].to_numpy()
        rng = np.random.default_rng(self.seed)
        best_w, best = self.w.copy(), average_precision_score(y, X @ self.w) if y.sum() else 0.0
        for _ in range(self.iters):
            cand = best_w * np.exp(rng.normal(0, 0.5, len(self.w)))
            ap = average_precision_score(y, X @ cand) if y.sum() else 0.0
            if ap > best:
                best, best_w = ap, cand
        self.w, self.tuned_ap = best_w, best
        return self

    def score(self, comps: pd.DataFrame) -> np.ndarray:
        return 100.0 * (comps[self.names].to_numpy() @ self.w) / self.w.sum()

    def contributions(self, comps: pd.DataFrame) -> pd.DataFrame:
        c = 100.0 * comps[self.names].to_numpy() * self.w / self.w.sum()
        return pd.DataFrame(c, columns=self.names, index=comps.index)


class XGBScorer:
    def __init__(self, cfg: dict, seed: int = 0):
        p = cfg["scoring"]["xgb"]
        self.params = dict(n_estimators=p["n_estimators"], max_depth=p["max_depth"], learning_rate=p["learning_rate"],
                           subsample=0.9, colsample_bytree=0.9, min_child_weight=2, reg_lambda=5.0, tree_method="hist", random_state=seed, n_jobs=4,
                           eval_metric="aucpr")
        self.max_spw = float(p.get("max_scale_pos_weight", 1.0))
        self.model = None
        self.cols: list[str] = []

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "XGBScorer":
        self.cols = list(X.columns)
        pos = max(1, int(y.sum()))
        spw = float(min(self.max_spw, (len(y) - pos) / pos))
        self.model = XGBClassifier(scale_pos_weight=spw, **self.params)
        self.model.fit(X[self.cols], y)
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        return 100.0 * self.model.predict_proba(X[self.cols])[:, 1]

    def contributions(self, X: pd.DataFrame) -> pd.DataFrame:
        """TreeSHAP values (log-odds). Uses the shap library; falls back to XGBoost's native pred_contribs."""
        try:
            import shap
            vals = shap.TreeExplainer(self.model).shap_values(X[self.cols])
            vals = np.asarray(vals)
        except Exception:
            import xgboost as xgb
            vals = self.model.get_booster().predict(xgb.DMatrix(X[self.cols]), pred_contribs=True)[:, :-1]
        return pd.DataFrame(vals, columns=self.cols, index=X.index)


def top_contributors(contrib_row: pd.Series, k: int = 3) -> list[dict]:
    pos = contrib_row[contrib_row > 0].sort_values(ascending=False).head(k)
    tot = float(contrib_row[contrib_row > 0].sum()) or 1.0
    return [dict(feature=n, label=LABELS.get(n, n), value=float(v), share=float(v / tot)) for n, v in pos.items()]
