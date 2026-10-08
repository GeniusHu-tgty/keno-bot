# Strategy Validation（Train / Validation / Test）

- 10/10/10 个随机种子
- 每种子 100 会话 × 176 局
- Train 选择赢家：`block-random/capped-recovery`

## Train Top 10

| 候选 | 平均 ROI | 平均 CI 半宽 | 跨种子正收益率 | 平均绿色率 | 平均爆仓率 |
|---|---:|---:|---:|---:|---:|
| block-random/capped-recovery | -0.599% | +/-2.289% | 30.0% | 43.3% | 0.0% |
| random/probe-window | -0.679% | +/-2.627% | 40.0% | 44.0% | 0.0% |
| block-random/probe-window | -0.727% | +/-2.893% | 20.0% | 43.3% | 0.0% |
| block-random/fractional | -0.754% | +/-2.138% | 30.0% | 42.1% | 0.0% |
| block-random/flat-min | -0.756% | +/-2.151% | 30.0% | 42.1% | 0.0% |
| random/capped-recovery | -0.946% | +/-2.076% | 20.0% | 45.5% | 0.0% |
| random/fractional | -1.087% | +/-1.981% | 0.0% | 43.4% | 0.0% |
| random/flat-min | -1.088% | +/-1.985% | 0.0% | 43.4% | 0.0% |
| random/adaptive | -1.096% | +/-6.266% | 20.0% | 35.8% | 0.0% |
| block-random/adaptive | -1.230% | +/-5.865% | 30.0% | 35.7% | 0.0% |

## Validation

| 候选 | 平均 ROI | 平均 CI 半宽 | 跨种子正收益率 | 平均绿色率 | 平均爆仓率 |
|---|---:|---:|---:|---:|---:|
| capped-recovery | -0.819% | +/-2.150% | 20.0% | 46.5% | 0.0% |

## Test

| 候选 | 平均 ROI | 平均 CI 半宽 | 跨种子正收益率 | 平均绿色率 | 平均爆仓率 |
|---|---:|---:|---:|---:|---:|
| capped-recovery | -0.542% | +/-2.035% | 40.0% | 47.0% | 0.0% |

## 准入结论

- B：没有证明正收益，但可比较最低损耗和风险控制
- `test_roi_positive`: FAIL
- `test_ci_lower_positive`: FAIL
- `test_positive_seed_pct_at_least_70`: FAIL
- `test_max_ruin_at_most_5pct`: PASS
- `validation_test_stable_within_1pct`: PASS
- `not_concentrated_in_top_1pct_sessions`: FAIL
