# 验证方法（每个数字都能自己重算）

## 1. 重算开奖：这条链到底是不是 determine 的

平台公开三个量：`server_seed`（先给哈希、结算后揭晓）、`client_seed`、`nonce`。Keno BOT 只做一件事——按它们的定义重新算一遍：

```text
bytes  = HMAC_SHA256(key = server_seed, message = "{client_seed}:{nonce}:{cursor}")
float  = 前 4 字节按大端解释为整数 / 2^32            （digest 用满则 cursor += 1）
draw   = 用同一串 float 依次做部分 Fisher–Yates，取前 10 个号
```

```bash
# 仓库自带样本（240 局，种子由本仓库生成，不含任何第三方账号数据）
python -m keno.cli verify-rounds \
  --replay-file data/samples/rounds_sample.jsonl \
  --seeds-file  data/samples/seeds_sample.json
```

输出逐局 PASS/FAIL。把 `data/samples/seeds_sample.json` 里任何一位十六进制字符改掉，对应那局立刻 FAIL——这说明这是真的校验，而不是打印 PASS 的仪式。

## 2. 采集与复算自己的对局（只读）

```bash
# 连已经登录的 Chrome（只读，不下注），采集开奖与种子
python -m keno.cli collect --cdp http://127.0.0.1:9222 --out data/raw/my_session.jsonl

# 复算
python -m keno.cli verify-rounds --replay-file data/raw/my_session.jsonl \
  --seeds-file data/raw/my_session.seeds.json
```

`collect` 只读页面已经存在的数据；真钱执行器在 `live run --live-bets`，与采集路径分开。

## 3. 审计赔率表

```bash
python -m keno.cli paper-trade --rounds 200000 --pick-count 10 --bet 0.0001 \
  --paytable configs/payout.yaml --out reports/paper_trade.json
```

`data/reference/stake_keno_payouts_official.json` 是官方 40 档表；`reports/payout_audit.md` 给出逐档 RTP（98.65% ~ 99.07%）以及自建表与官方表的逐档差异。任何一档赔率的改动都会直接在 RTP 上体现出来。

## 4. 「策略是不是幻觉」的判据

```bash
# 零模型：同一条资金曲线跑 1000 个会话，看它落在什么分布里
python -m keno.cli sessions --sessions 1000 --rounds 176 --pick-count 10 \
  --paytable configs/payout.yaml --phase-config configs/bot_phase.yaml --out reports/sessions

# 参数冻结：训练集挑参数，验证集/测试集只用来否决
python -m keno.cli strategy-validate --train-seeds 0,1,2 --validation-seeds 3,4,5 --test-seeds 6,7,8 \
  --sessions-per-seed 1000 --rounds 176 --out reports/strategy_validation
```

判据只有一条：**在没见过的种子上，结果是否还落在零模型分布的上尾**。同一批种子上反复挑参数、挑出「最好」的那条曲线，属于过拟合，不算结果——`reports/strategy_grid_acceptance.md` 里记录了这条纪律被执行的例子。

## 5. 这个仓库不能证明什么

* 它不能证明「某条策略长期盈利」。Keno 每注期望为负，资金管理只改变分布形状。
* 它不能证明平台没有别的操纵手段——它只证明：**在你采样到的那批局里，开奖串与公开种子链一致**（实盘样本 4/4 PASS，命中分布卡方 5.58，df 6，p≈0.47）。
* 它不构成任何形式的收益承诺。作者的实测结果是亏损（`reports/live_lab_all.md` 与 README 第 5 节）。
