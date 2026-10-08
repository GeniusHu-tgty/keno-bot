# Strategy Validation（Train / Validation / Test）

- 10/10/10 个随机种子
- 每种子 20 会话 × 176 局
- Train 选择赢家：`hot/martingale`

## Train Top 10

| 候选 | 平均 ROI | 平均 CI 半宽 | 跨种子正收益率 | 平均绿色率 | 平均爆仓率 |
|---|---:|---:|---:|---:|---:|
| hot/martingale | 10.031% | +/-13.363% | 70.0% | 76.0% | 0.0% |
| cold/martingale | 8.644% | +/-15.187% | 80.0% | 75.0% | 0.0% |
| random/martingale | 6.128% | +/-11.006% | 80.0% | 73.0% | 0.0% |
| balanced-random/martingale | 4.908% | +/-10.189% | 90.0% | 80.0% | 0.5% |
| hot/phase | 1.653% | +/-11.698% | 70.0% | 47.0% | 0.0% |
| fixed-pattern/martingale | 1.297% | +/-11.220% | 50.0% | 74.0% | 0.0% |
| fixed-pattern/phase | 1.237% | +/-9.912% | 70.0% | 51.5% | 0.0% |
| avoid-cold-zone/phase | 0.841% | +/-10.535% | 50.0% | 47.5% | 0.0% |
| random/probe-window | 0.069% | +/-6.108% | 50.0% | 45.0% | 0.0% |
| cold/phase | -0.099% | +/-11.668% | 50.0% | 42.5% | 0.0% |

## Validation

| 候选 | 平均 ROI | 平均 CI 半宽 | 跨种子正收益率 | 平均绿色率 | 平均爆仓率 |
|---|---:|---:|---:|---:|---:|
| martingale | 7.129% | +/-8.974% | 90.0% | 76.5% | 0.0% |

## Test

| 候选 | 平均 ROI | 平均 CI 半宽 | 跨种子正收益率 | 平均绿色率 | 平均爆仓率 |
|---|---:|---:|---:|---:|---:|
| martingale | 19.604% | +/-11.872% | 100.0% | 77.0% | 0.0% |

## 准入结论

- B：没有证明正收益，但可比较最低损耗和风险控制
- `test_roi_positive`: PASS
- `test_ci_lower_positive`: PASS
- `test_positive_seed_pct_at_least_70`: PASS
- `test_max_ruin_at_most_5pct`: PASS
- `validation_test_stable_within_1pct`: FAIL
- `not_concentrated_in_top_1pct_sessions`: FAIL
