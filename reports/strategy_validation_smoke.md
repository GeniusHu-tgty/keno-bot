# Strategy Validation（Train / Validation / Test）

- 1/1/1 个随机种子
- 每种子 10 会话 × 20 局
- Train 选择赢家：`block-random/flat-min`

## Train Top 10

| 候选 | 平均 ROI | 平均 CI 半宽 | 平均绿色率 | 平均爆仓率 |
|---|---:|---:|---:|---:|
| block-random/flat-min | 5.200% | +/-16.398% | 60.0% | 0.0% |
| block-random/probe-window | 5.200% | +/-16.398% | 60.0% | 0.0% |
| random/flat-min | -1.900% | +/-16.052% | 60.0% | 0.0% |
| random/probe-window | -1.900% | +/-16.052% | 60.0% | 0.0% |

## Validation

| 候选 | 平均 ROI | 平均 CI 半宽 | 平均绿色率 | 平均爆仓率 |
|---|---:|---:|---:|---:|
| flat-min | -15.800% | +/-14.462% | 20.0% | 0.0% |

## Test

| 候选 | 平均 ROI | 平均 CI 半宽 | 平均绿色率 | 平均爆仓率 |
|---|---:|---:|---:|---:|
| flat-min | 3.300% | +/-14.527% | 70.0% | 0.0% |
