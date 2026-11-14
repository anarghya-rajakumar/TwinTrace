# Seed sweep (4 seeds: 11, 12, 13, 14); headline rows, test split each time

| Method | Precision | Recall | F1 | FPR | Alerts / 1,000 accts |
|---|---|---|---|---|---|
| Rule baseline | 0.086 ± 0.024 | 0.594 ± 0.085 | 0.150 ± 0.039 | 0.0781 ± 0.0042 | 86.6 ± 4.5 |
| Single-layer graph (money only) | 0.966 ± 0.032 | 0.626 ± 0.041 | 0.758 ± 0.021 | 0.0012 ± 0.0008 | 1.7 ± 0.2 |
| Two layers, no bridge | 0.947 ± 0.020 | 0.893 ± 0.023 | 0.920 ± 0.019 | 0.0007 ± 0.0005 | 2.3 ± 0.1 |
| TwinTrace (two layers + bridge) | 0.983 ± 0.021 | 0.818 ± 0.073 | 0.891 ± 0.035 | 0.0005 ± 0.0006 | 2.1 ± 0.2 |

TwinTrace minus two-layers-without-bridge F1 per seed: -0.010, -0.022, -0.006, -0.075
TwinTrace minus single-layer F1 per seed: +0.170, +0.123, +0.167, +0.071
