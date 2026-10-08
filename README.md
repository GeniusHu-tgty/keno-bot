# Keno BOT

**Keno BOT** 是一个只针对 Keno 的本地研究台 + 自动投注机器人：把平台的**可验证公平性（provably fair）种子链在本地完整复算**，审计**官方 40 档赔率表**，用**零模型（null model）**回测各种下注策略，并且——在你自己明确打开开关的前提下——**通过本地 Chrome 的 CDP 通道操作真实账户自动下注**。

> Keno BOT is a local Keno workbench and betting bot. It re-derives every draw from the published provably-fair seed chain, audits the payout table, back-tests staking policies against a null model, and can drive a real account through your own Chrome over CDP. **Paper mode is the default; live bets need an explicit flag.**

只做 Keno。不做预测、不接 AI 选号、不承诺盈利。

---

## 1. 它和常见的 Keno 脚本不一样在哪

| 常见脚本 | Keno BOT |
| --- | --- |
| 一把锤子：猜热号、追冷号、倍投 | 先给一把尺子：每局理论 RTP、单注方差、期望值能本地算出来 |
| 只截图晒盈利 | 真钱账本全量落地：流水、回收、回撤、连败、分位数都摆出来（包括亏的那些） |
| 赔率靠口口相传 | 官方 40 档赔率逐档复核，自建表与官方表的差异列成对照 |
| RNG 只能「相信平台」 | HMAC-SHA256 种子链本地复算，逐字节对齐官方计算器 |
| 只能手动点 | 阶梯资金 + 会话纪律 + 分片冷却 + 止损/收绿，全程自动，可无人值守 |

## 2. 快速开始

### 路线 A：直接跑 exe（推荐给不装 Python 的人）

1. 下载 `KenoBOT.exe`（或自己构建，见路线 C）。
2. 双击。程序在本机 `127.0.0.1` 上起一个页面并自动打开浏览器。
3. 页面分两个台：`/` 训练台（纯模拟）、`/live` 实盘台（需要连真实账户才会动真钱）。

第一次运行会在 `%LOCALAPPDATA%\KenoBOT` 建目录存放状态、日志和报表；不写注册表，不装服务，删掉目录就等于清空。

### 路线 B：源码运行（开发者）

```bash
git clone <your-fork-url> keno-bot && cd keno-bot
python -m pip install -e .
python keno_bot_app.py          # 起页面（等价于 python -m keno.cli serve）
```

Windows 上也可以直接双击根目录的 `启动.bat`（有 `dist\KenoBOT.exe` 就启 exe，否则用本机 Python 起页面）。

### 路线 C：自己打包 exe

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1            # 单文件 dist\KenoBOT.exe
powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Onedir   # 目录版，启动更快
```

脚本会在需要时自动生成图标（`tools/make_icon.py`）、示例数据（`tools/make_sample.py`）并安装 PyInstaller。

## 3. 实盘台怎么连（真钱，默认关）

Keno BOT 不保存你的账号密码，也没有自己的登录接口。它只做一件事：连到你**已经登录**的 Chrome 上（Chrome DevTools Protocol），从页面自己的请求里取会话令牌（只存在内存里，从不落盘），然后像人一样点下注按钮。

```bash
# 1) 先用调试端口启动 Chrome（用你自己的用户目录，不要用陌生脚本的 profile）
chrome.exe --remote-debugging-port=9222 --user-data-dir=%USERPROFILE%\keno-chrome-profile

# 2) 在这个 Chrome 里手动登录，打开 Keno 页面

# 3) 只读体检：连上、看状态，不下注
python -m keno.cli live connect --cdp http://127.0.0.1:9222

# 4) 真的要下注时，才加 --live-bets；并且先跑最小注
python -m keno.cli live run --cdp http://127.0.0.1:9222 --live-bets --risk low --pick-count 10 --rounds 20
```

`KENO_CHROME_PROFILE` / `KENO_CHROME_PS1` 两个环境变量可以指定 Chrome 用户目录与启动脚本；不设就用 `~/.keno-bot/` 下的默认值。

纪律（写在代码里，不是写在文档里就算）：单注上限、阶梯档位、二连败降档、四档赢了强制休息、止损/收绿、分片冷却、日上限。先在训练台把参数跑熟再连真钱。

## 4. 可验证公平性（这个仓库最值钱的部分）

Keno 每一局的结果都能从三个公开量重算：`server_seed`（平台先给哈希、后揭晓）、`client_seed`（你可以改）、`nonce`（局号）。Keno BOT 把这条链写到字节级：

```bash
# 仓库自带的自证样本（240 局，种子只存在于本仓库）
python -m keno.cli verify-rounds \
  --replay-file data/samples/rounds_sample.jsonl \
  --seeds-file  data/samples/seeds_sample.json
```

输出为逐局 PASS/FAIL 与总命中率对照；改一位种子就立刻 FAIL，说明它真的在校验而不是走过场。

实盘采集的对局同样一条命令复算（真实采集里 4/4 局 PASS，且开奖串与官方计算器逐字节一致）。

## 5. 实测结果（把这几个数字看完再决定要不要用）

### 5.1 真钱账本（自动下注，2026-09-12 → 2026-09-18）

| 指标 | 数值 |
| --- | --- |
| 局数 | 9,331 |
| 投入 | 121.2212 U |
| 回收 | 112.3248 U |
| 净 | **-8.8964 U** |
| 实测 RTP | 92.66%（理论 98.76%） |
| 单局「收回 ≥ 投下」比例 | 70.24% |
| 最大单次回撤 | 10.73 U |
| 最长连败 | 13 局 |

把同样 9,331 局、同样的注额阶梯丢进 20,000 次蒙特卡洛（公平超几何 + 官方赔率），期望是 -1.58 U、标准差 7.78 U；实测 -8.90 U 落在 **9.8 ~ 14.0 分位**。也就是说：**账面难看属于正常方差范围，没有证据表明盘口被动了手脚。** 唯一的硬结论是流水放大——同样的局数平注最小注只要 0.93 U 流水，这套阶梯跑出了 133.9 倍。

命中分布同样对得上：low/10 子集 7,029 局的卡方值 5.58（df 6，p≈0.47）。

### 5.2 纸面回测（零模型，不是「策略有效」的证据）

| 实验 | 结果 |
| --- | --- |
| 1,000 会话 × 176 局（阶梯资金） | 盈利会话 38.2%，中位 -0.416 U |
| 同上，平注对照臂 | 盈利会话 37.5%（更差） |
| 30 天 × 24h 无人值守 | 盈利天数 6.7%，单日中位 -9.56 U，30 天里 25 天爆仓 |
| 社区常见打法（low/9、low/10、classic/10 等） | ROI 全为负，-0.5% ~ -2.5% |

结论写在这里：**Keno 的每次下注期望为负，任何资金管理只能改变结果的分布形状（回撤、爆仓速度、波动），不能把负期望改成正期望。** 这个仓库的价值在于把这句话量化，而不是绕过它。

### 5.3 赔率表审计

`data/reference/stake_keno_payouts_official.json` 收录官方 40 档赔率，脚本逐档算 RTP：**98.65% ~ 99.07%**（low 10 选 = 98.76%）。自建表（`configs/payout.yaml`，来源是方案截图里的档位比例）与官方表在 5/6/7/8/9 中档上存在差异，差异清单见 `reports/payout_audit.md`。

## 6. 目录结构

```text
keno_bot_app.py           启动器 / PyInstaller 入口
build_exe.ps1             打包 exe
configs/                  game.yaml（棋盘、RNG 协议） payout.yaml（自建赔率） bot_phase.yaml（阶梯参数）
data/reference/           官方赔率表
data/samples/             自证样本（仓库自己生成的种子与开奖）
src/keno/provably_fair/   HMAC-SHA256 与浮点生成、逐局校验
src/keno/game/            开奖、命中、赔率、结算
src/keno/bot/             下注机器人：资金、阶段机、组合策略、账本、CDP/实盘执行
src/keno/research/        蒙特卡洛、参数冻结验证、风险网格
src/keno/reporting/       指标（超几何、卡方、回撤、连败）与报告导出
src/keno/webapp/          本地工作台（HTTP 服务 + 页面）
tools/                    生成示例数据、生成图标
docs/                     架构、验证方法与选号逻辑说明
tests/                    pytest（109+ 项）
```

状态写在哪里：exe 版写 `%LOCALAPPDATA%\KenoBOT`，源码版写 `data/webapp/`，可用 `KENO_BOT_HOME` 覆盖。

## 7. 已知问题（欢迎 PR，标了难度）

| 编号 | 内容 | 位置 |
| --- | --- | --- |
| P0-1 | 组合模式下单注上限失效（`elif self.kind != "combo" and amount > self.max_bet` 让 combo 走不进来） | `src/keno/bot/stake_live.py` |
| P0-2 | `next_bet_blows_stop()` 只看余额，不看止损/档位 | `src/keno/bot/stake_live.py` |
| P0-3 | 下注确认丢失时用随机 `identifier`，超时后可能「钱动了、账没记」 | `src/keno/bot/stake_session.py` |
| P1-5 | 恢复出来的运行记录 summary 恒为 0 | `src/keno/bot/ledger.py` |

更细的复现步骤、期望行为、验收标准写在 `CONTRIBUTING.md` 的 good first issues 里。

## 8. 与其它开源 Keno 项目的关系

* **evilbot**（`poky1084/evilbot`）：浏览器里跑的 JS/Lua 策略框架，生态最活跃，适合学「脚本怎么挂进页面」；Keno 只是它支持的十几个游戏之一，没有本地 RNG 复算与赔率审计。
* **stake-bet-analyzer / Keno-Predictor 一类扩展**：做热号与模式统计，不自动下注，也不验证结果来源。
* **本仓库**：默认只读、可验证、可回放；自带真钱执行器，但真钱路径必须显式打开。

## 9. 路线图（Roadmap，欢迎 PR）

* **脚本式策略插件**：给外部策略一个稳定的钩子（每局拿到历史与余额、返回 picks 与金额），让人不用改核心就能贡献选号逻辑——这是 **evilbot** 最值得学的一点（它的 `dobet()` 接口）。
* **BET_LIST 对账**：下注失败/超时后用平台的注单列表反查补账，替掉现在「uuid identifier + 只看 nonce/余额」的做法（对应已知问题 P0-3）。
* **英文界面**：静态页面文案目前以中文为主，i18n 化后对海外贡献者更友好。
* **数据校验**：给 `data/**/*.jsonl` 加 JSON Schema 与 `collect` 侧的字段断言，坏行直接拒绝。
* **跨平台路径清扫**：把所有个人路径收敛到 `keno/paths.py` + 环境变量（`KENO_CHROME_PROFILE` / `KENO_CHROME_PS1` / `KENO_BOT_HOME`），支持 macOS/Linux 的 Chrome 启动。
* **WebSocket 数据源实装**：`src/keno/bot/ws.py` 目前是骨架，做实后可以不依赖轮询就看盘与对账。

## 10. 免责声明

Keno 是负期望的赌博游戏。作者实测结果是**亏损**（见 5.1）。这个仓库是研究与工程实践项目，不构成投资建议、不承诺任何收益。请只使用你输得起的钱，并遵守你所在地区的法律与平台条款。

## 11. 许可

MIT，见 `LICENSE`。

---
---

# Keno BOT (English)

A local **Keno** workbench and betting bot. Three things make it different from the usual Keno scripts:

1. **Everything is re-derived locally.** Draws are reconstructed from the published `server_seed` / `client_seed` / `nonce` chain (HMAC-SHA256) byte for byte; the shipped sample can be verified with one command; captured live rounds verified 4/4 against the official calculator.
2. **The payout table is audited, not trusted.** All 40 tiers of the official table are recomputed: RTP 98.65%–99.07% (low, 10 picks: 98.76%).
3. **The results are published including the losses.** 9,331 real-money rounds: wagered 121.2212 U, returned 112.3248 U, net **−8.8964 U**, realized RTP 92.66%. A 20,000-run Monte-Carlo on the same stake ladder puts that at the 9.8–14.0 percentile — i.e. *normal variance*, not a rigged game; the real cost of the ladder was turnover (133.9× a flat minimum bet).

### Quickstart

```bash
python -m pip install -e .
python keno_bot_app.py     # workbench on http://127.0.0.1:8000 (falls back to 8001, 8002, ...)
```

* Paper mode is the default; it never touches a real account.
* Live mode talks to **your already-logged-in Chrome** over CDP (`chrome --remote-debugging-port=9222`), reads the session token from the page's own requests, keeps it in memory only, and requires the explicit `--live-bets` / UI toggle.
* Prebuilt Windows binary: `build_exe.ps1` (or download `KenoBOT.exe`).

### Verify the sample yourself

```bash
python -m keno.cli verify-rounds --replay-file data/samples/rounds_sample.jsonl --seeds-file data/samples/seeds_sample.json
```

### Honest expectation setting

Keno has negative expectation per bet. Money management changes the *shape* of the outcome distribution (drawdown, ruin speed, variance), never its sign. This repo exists to make that measurable: the null-model runs above show 38.2% profitable sessions in an 1,000-session Monte-Carlo (median −0.416 U) and 6.7% profitable days over a 30-day unattended simulation.

### Roadmap (PRs welcome)

* **Script-style strategy plugins** — a stable per-round hook (history + bankroll in, picks + stake out) so people can contribute selection logic without touching the core. This is the one lesson worth taking from **evilbot** (`dobet()`).
* **Bet-list reconciliation** — after a failed/timed-out bet, look the wager up in the platform's own bet list instead of trusting nonce/balance deltas (see known issue P0-3).
* **English UI** — the static pages are still mostly Chinese; i18n them.
* **Data contracts** — JSON Schema for `data/**/*.jsonl` plus field assertions in `collect`.
* **Cross-platform paths** — funnel everything through `keno/paths.py` + env vars (`KENO_CHROME_PROFILE`, `KENO_CHROME_PS1`, `KENO_BOT_HOME`); support Chrome on macOS/Linux.
* **Real WebSocket source** — `src/keno/bot/ws.py` is a skeleton; make it the primary feed.

### License

MIT. Gambling is negative EV — this is a research/engineering project, not a money printer.

