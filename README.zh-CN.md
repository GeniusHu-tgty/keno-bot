# Keno BOT　中文说明

[![License: GPL v2](https://img.shields.io/badge/license-GPLv2-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#快速开始)
[![Tests](https://img.shields.io/badge/tests-110%20passing-brightgreen.svg)](CONTRIBUTING.md)
[![English](https://img.shields.io/badge/README-English-blue.svg)](README.md)

**Keno BOT** 是一个只针对 **Keno** 的本地研究台 + 自动投注机器人。

* 把平台的**可验证公平性**种子链在本地完整复算（`server_seed` / `client_seed` / `nonce`，HMAC-SHA256），逐字节与官方计算器一致，一条命令就能自证。
* 把平台的 **40 档官方赔率**逐档审计，而不是照抄（实测 RTP 98.65% – 99.07%）。
* 用**零模型**（公平超几何分布）回测各种下注策略，让你看到结果分布的形状，而不是一张盈利截图。
* 在你自己明确打开开关之后，可以通过**你自己的 Chrome**（CDP）操作**你自己的**真实账户自动下注——默认是纯模拟，真钱必须显式开启。

只做 Keno。不做预测、不接 AI 选号、不承诺任何收益。

![Keno BOT 全自动台](docs/images/lab.png)

---

## 它和常见的 Keno 脚本不一样在哪

| 常见脚本 | Keno BOT |
| --- | --- |
| 一把锤子：猜热号、追冷号、倍投 | 先给一把尺子：单注 RTP、方差、期望值在本地就能算出来 |
| 只晒盈利截图 | 真钱账本全量落地：流水、回收、回撤、连败、分位数，包括亏的那些 |
| 赔率靠口口相传 | 官方 40 档赔率逐档复核，自建表与官方表的差异列成对照 |
| RNG 只能「相信平台」 | HMAC-SHA256 种子链本地复算，逐字节对齐官方计算器 |
| 只能手动点 | 阶梯资金 + 会话纪律 + 分片冷却 + 止损/止盈，全程自动，可无人值守 |

## 快速开始

### A. 直接跑 exe（不装 Python）

1. 在 [Releases](../../releases) 里下载 `KenoBOT.exe`。
2. 双击运行，程序在本机 `127.0.0.1` 起一个页面并自动打开浏览器。
3. 两个台：`/` 训练台（纯模拟）、`/live` 实盘台（连接账号并勾选「允许真钱」之后才会动真钱）。

第一次运行会在 `%LOCALAPPDATA%\KenoBOT` 建目录存放状态、日志与报表；不写注册表、不装服务，删掉目录就等于清空。

### B. 源码运行（开发者）

```bash
git clone <your-fork-url> keno-bot && cd keno-bot
python -m pip install -e .
python keno_bot_app.py        # 等价于 python -m keno.cli serve
```

Windows 上也可以直接双击根目录的 `启动.bat`：有 `dist\KenoBOT.exe` 就启 exe，否则用本机 Python 起页面。

### C. 自己打包 exe

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1            # 单文件 dist\KenoBOT.exe
powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Onedir   # 目录版，启动更快
powershell -ExecutionPolicy Bypass -File tools\make_release.ps1  # exe + 文档 -> dist\KenoBOT-<version>-win64.zip
```

打包脚本会在需要时自动生成图标（`tools/make_icon.py`）与自证样本（`tools/make_sample.py`），缺 PyInstaller 时自动安装。

## 实盘台怎么连（真钱，默认关）

Keno BOT 不保存你的账号密码，也没有自己的登录接口。它只做一件事：连到你**已经登录**的 Chrome（Chrome DevTools Protocol），从页面自己的请求里取会话令牌（只存在内存里，从不落盘），然后像人一样点下注按钮。

```bash
# 1) 先用调试端口启动 Chrome（用你自己的用户目录）
chrome.exe --remote-debugging-port=9222 --user-data-dir=%USERPROFILE%\keno-chrome-profile

# 2) 在这个 Chrome 里手动登录，打开 Keno 页面

# 3) 只读体检：连上、看状态，不下注
python -m keno.cli live connect --cdp http://127.0.0.1:9222

# 4) 真的要下注时才加 --live-bets，并且先跑最小注
python -m keno.cli live run --cdp http://127.0.0.1:9222 --live-bets --risk low --pick-count 10 --rounds 20
```

`KENO_CHROME_PROFILE` / `KENO_CHROME_PS1` 可以指定 Chrome 用户目录与启动脚本；不设就用 `~/.keno-bot/` 下的默认值。

纪律写在代码里，不是写在文档里就算：单注上限、阶梯档位、二连败降档、四档赢了强制休息、止损/止盈、分片冷却、日上限。先在训练台把参数跑熟，再考虑连真钱。

![Keno BOT 实盘台](docs/images/live.png)

## 可验证公平性（这个仓库最值钱的部分）

每一局都能从三个公开量重算：`server_seed`（平台先给哈希、后揭晓）、`client_seed`（你可以改）、`nonce`（局号）。Keno BOT 把这条链做到字节级：

```bash
# 仓库自带的自证样本（240 局，种子只存在于本仓库）
python -m keno.cli verify-rounds \
  --replay-file data/samples/rounds_sample.jsonl \
  --seeds-file  data/samples/seeds_sample.json
```

输出是逐局 PASS/FAIL 与命中率对照，期望看到 `240/240 rounds PASS`。改一位种子就立刻 FAIL——这就说明它真的在校验，而不是走过场。实盘采集的对局用同一条命令复算，结果与官方计算器逐字节一致。

## 实测结果（把这几个数字看完再决定要不要用）

### 真钱账本（自动下注，2026-09-12 → 2026-09-18）

| 指标 | 数值 |
| --- | --- |
| 局数 | 9,331 |
| 投入 | 121.2212 U |
| 回收 | 112.3248 U |
| 净 | **−8.8964 U** |
| 实测 RTP | 92.66%（理论 98.76%） |
| 单局「收回 ≥ 投下」比例 | 70.24% |
| 最大单次回撤 | 10.73 U |
| 最长连败 | 13 局 |

把同样 9,331 局、同样的注额阶梯丢进 20,000 次蒙特卡洛（公平超几何 + 官方赔率），期望是 −1.58 U、标准差 7.78 U；实测 −8.90 U 落在 **9.8 ~ 14 分位**。也就是说：**账面难看属于正常方差范围，没有证据表明盘口被动了手脚。** 唯一的硬结论是流水放大——同样局数平注最小注只要 0.93 U 流水，这套阶梯跑出了 **133.9 倍**。

命中分布同样对得上：low/10 子集 7,029 局的卡方值 5.58（df = 6，p ≈ 0.47）。

### 纸面回测（零模型，不是「策略有效」的证据）

| 实验 | 结果 |
| --- | --- |
| 1,000 会话 × 176 局（阶梯资金） | 盈利会话 38.2%，中位 −0.416 U |
| 同上，平注对照臂 | 盈利会话 37.5%（更差） |
| 30 天 × 24h 无人值守 | 盈利天数 6.7%，单日中位 −9.56 U，30 天里 25 天爆仓 |
| 社区常见打法（low/9、low/10、classic/10 等） | ROI 全为负，−0.5% ~ −2.5% |

**Keno 每次下注的期望都是负的。任何资金管理只能改变结果分布的形状（回撤、爆仓速度、波动），不能把负期望改成正期望。** 这个仓库的价值在于把这句话量化，而不是绕过它。

### 赔率表审计

`data/reference/stake_keno_payouts_official.json` 收录官方 40 档赔率，审计脚本逐档重算：**98.65% ~ 99.07%**（low 10 选 = 98.76%）。自建表 `configs/payout.yaml` 与官方表在 5/6/7/8/9 中档上存在差异，差异清单见 `reports/payout_audit.md`。

## 目录结构

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
tools/                    生成样本、生成图标、打包发布
docs/                     架构、验证方法、中文快速开始
tests/                    pytest（110 项）
```

状态写在哪里：exe 版写 `%LOCALAPPDATA%\KenoBOT`，源码版写 `data/webapp/`，可用 `KENO_BOT_HOME` 覆盖。

## 与其它开源 Keno 项目的关系

* **evilbot**（`poky1084/evilbot`）：浏览器里跑的 JS/Lua 策略框架，生态最活跃，适合学「脚本怎么挂进页面」；Keno 只是它支持的十几个游戏之一，没有本地 RNG 复算与赔率审计。
* **stake-bet-analyzer** 一类扩展：做热号与模式统计，不自动下注，也不验证结果来源。
* **本仓库**：默认只读、可验证、可回放；自带真钱执行器，但真钱路径必须显式打开。

## 路线图（Roadmap，欢迎 PR）

* **脚本式策略插件**：给外部策略一个稳定的钩子（每局拿到历史与余额、返回 picks 与金额），让人不用改核心就能贡献选号逻辑——这是 **evilbot** 最值得学的一点（它的 `dobet()` 接口）。
* **BET_LIST 对账**：下注失败/超时后用平台的注单列表反查补账，替掉现在「uuid identifier + 只看 nonce/余额」的做法。
* **英文界面**：静态页面文案目前以中文为主，i18n 化后对海外贡献者更友好。
* **数据校验**：给 `data/**/*.jsonl` 加 JSON Schema 与 `collect` 侧的字段断言，坏行直接拒绝。
* **跨平台路径清扫**：把所有个人路径收敛到 `keno/paths.py` + 环境变量（`KENO_CHROME_PROFILE` / `KENO_CHROME_PS1` / `KENO_BOT_HOME`），支持 macOS/Linux 的 Chrome 启动。
* **WebSocket 数据源实装**：`src/keno/bot/ws.py` 目前是骨架，做实后可以不依赖轮询就看盘与对账。

更细的复现步骤与验收标准写在 `CONTRIBUTING.md` 的 good first issues 里。

## 免责声明

Keno 是负期望的赌博游戏。作者实测结果是**亏损**（见上）。这个仓库是研究与工程实践项目，不构成投资建议、不承诺任何收益。请只使用你输得起的钱，并遵守你所在地区的法律与平台条款。

## 许可

**GNU General Public License v2.0**，见 [`LICENSE`](LICENSE)。Copyright (C) 2026 GeniusHu-tgty。按许可证原文，本软件不提供任何担保。你可以使用、研究、分享、修改，包括商用；如果你分发修改后的版本，它必须仍然保持 GPL 并附带源码。

---

[English README →](README.md)
