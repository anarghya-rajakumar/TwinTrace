# TwinTrace results (test split only)

Time-based split: first 60% tuning, next 20% validation, last 20% test. Alert threshold chosen on validation for a target false-positive rate of 0.01. Headline scorer per method = best validation F1.

## All rings (money + trade + bridge)

| Method | Scorer | Precision | Recall | F1 | FPR | Alerts | Alerts / 1,000 accts | Rings found |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Rule baseline | rules | 0.095 | 0.711 | 0.167 | 0.0738 | 1638 | 82.5 | 32/45 |
| Single-layer graph (money only) | hand | 0.938 | 0.644 | 0.764 | 0.0008 | 32 | 1.6 | 29/45 |
| Two layers, no bridge | xgb | 0.950 | 0.844 | 0.894 | 0.0001 | 40 | 2.0 | 38/45 |
| TwinTrace (two layers + bridge) | xgb | 0.952 | 0.822 | 0.883 | 0.0013 | 42 | 2.1 | 37/45 |

## Every method and scorer

| Method | Scorer | Precision | Recall | F1 | FPR | Alerts | Alerts / 1,000 accts | Rings found |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Rule baseline | rules | 0.095 | 0.711 | 0.167 | 0.0738 | 1638 | 82.5 | 32/45 |
| Single-layer graph (money only) | hand | 0.938 | 0.644 | 0.764 | 0.0008 | 32 | 1.6 | 29/45 |
| Single-layer graph (money only) | xgb | 0.970 | 0.644 | 0.774 | 0.0010 | 33 | 1.7 | 29/45 |
| Two layers, no bridge | hand | 0.795 | 0.778 | 0.787 | 0.0013 | 44 | 2.2 | 35/45 |
| Two layers, no bridge | xgb | 0.950 | 0.844 | 0.894 | 0.0001 | 40 | 2.0 | 38/45 |
| TwinTrace (two layers + bridge) | hand | 0.792 | 0.822 | 0.807 | 0.0017 | 48 | 2.4 | 37/45 |
| TwinTrace (two layers + bridge) | xgb | 0.952 | 0.822 | 0.883 | 0.0013 | 42 | 2.1 | 37/45 |

## Per-typology recall (headline rows)

| Typology | Rule baseline | Single-layer graph (money only) | Two layers, no bridge | TwinTrace (two layers + bridge) |
|---|---:|---:|---:|---:|
| fan_in_structuring | 1.00 | 1.00 | 1.00 | 1.00 |
| fan_out | 1.00 | 1.00 | 1.00 | 0.86 |
| loss_booking | 0.60 | 0.00 | 0.80 | 0.80 |
| market_layering | 1.00 | 0.00 | 0.50 | 0.50 |
| mule_chain | 0.62 | 1.00 | 1.00 | 1.00 |
| round_trip | 0.29 | 1.00 | 1.00 | 1.00 |
| wash_trading | 0.57 | 0.00 | 0.43 | 0.43 |

## Money-layer rings only (like-for-like for the single-layer method)

| Method | Scorer | Precision | Recall | F1 | FPR | Alerts | Alerts / 1,000 accts | Rings found |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Rule baseline | rules | 0.061 | 0.724 | 0.112 | 0.0713 | 1550 | 78.0 | 21/29 |
| Single-layer graph (money only) | hand | 0.938 | 1.000 | 0.968 | 0.0008 | 32 | 1.6 | 29/29 |
| Two layers, no bridge | xgb | 1.000 | 1.000 | 1.000 | 0.0001 | 29 | 1.5 | 29/29 |
| TwinTrace (two layers + bridge) | xgb | 0.938 | 0.966 | 0.951 | 0.0011 | 32 | 1.6 | 28/29 |
