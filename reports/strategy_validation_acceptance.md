# Strategy Validation（Train / Validation / Test）

- 2/1/1 个随机种子
- 每种子 50 会话 × 40 局
- Train 选择赢家：`hot/probe-window`

## Train Top 10

| 候选 | 平均 ROI | 平均 CI 半宽 | 平均绿色率 | 平均爆仓率 |
|---|---:|---:|---:|---:|
| hot/probe-window | 1.442% | +/-9.097% | 47.0% | 0.0% |
| hot/flat-min | 0.590% | +/-6.315% | 48.0% | 0.0% |
| random/flat-min | 0.320% | +/-5.851% | 43.0% | 0.0% |
| hot/capped-recovery | -0.390% | +/-6.074% | 49.0% | 0.0% |
| random/capped-recovery | -0.437% | +/-6.337% | 41.0% | 0.0% |
| cold/flat-min | -1.120% | +/-6.436% | 43.0% | 0.0% |
| cold/capped-recovery | -1.213% | +/-7.111% | 43.0% | 0.0% |
| random/probe-window | -1.743% | +/-9.764% | 39.0% | 0.0% |
| cold/probe-window | -2.643% | +/-10.506% | 45.0% | 0.0% |
| block-random/probe-window | -3.789% | +/-8.174% | 39.0% | 0.0% |

## Validation

| 候选 | 平均 ROI | 平均 CI 半宽 | 平均绿色率 | 平均爆仓率 |
|---|---:|---:|---:|---:|
| probe-window | -2.483% | +/-7.446% | 44.0% | 0.0% |

## Test

| 候选 | 平均 ROI | 平均 CI 半宽 | 平均绿色率 | 平均爆仓率 |
|---|---:|---:|---:|---:|
| probe-window | -1.194% | +/-8.452% | 44.0% | 0.0% |
