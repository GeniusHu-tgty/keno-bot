# 架构（src/keno）

```text
provably_fair/   hmac_rng (HMAC-SHA256 字节流)  →  float_generator (字节→float)  →  verifier (逐局复算)
game/            keno_draw (用上面的随机流抽 10 个号)  hits  paytable (YAML 赔率)  engine (结算)
strategies/      base / random / hot / cold / pattern / selection：怎么选号（不改 RTP）
bot/             money (资金曲线)  phases (阶梯阶段机)  combo_v2 (实盘默认引擎)  regime  ledger (账本与运行目录)
                 bot (纸面主循环)  live (纸面配置)  stake_cdp (Chrome/CDP)  stake_session (真钱执行)  stake_live (实盘调度)
research/        sessions  daily  strategy_grid  strategy_validation  risk_grid  live_lab  shadow (蒙特卡洛与对照)
reporting/       metrics (超几何/卡方/回撤/连败)  report  history_export
webapp/          server (HTTP + API)  static/ (训练台 index.html，实盘台 live.html)
paths.py         唯一决定「文件写在哪、资源从哪读」的模块
```

## 数据流

```text
种子链(server_seed/client_seed/nonce) ──► FloatGenerator ──► draw_keno ──► 开奖 10 个号
                                                                  │
                             选号策略(策略/热号/固定模式) ──────────┤
                                                                  ▼
                     结算 (Paytable) ──► 资金管理 (MoneyManager) ──► 账本 (ledger JSONL)
                                                                  │
                                            页面 /live  ◄── 实盘调度 (stake_live)
                                            真钱下注 ◄── CDP (stake_cdp + stake_session)
```

## 状态写在哪（`src/keno/paths.py`）

| 函数 | 打包成 exe 后 | 源码运行时 |
| --- | --- | --- |
| `app_home()` | `%LOCALAPPDATA%\KenoBOT` | `<repo>/data/webapp` |
| `data_dir()` | `app_home()/data` | `app_home()` |
| `config_file(name)` | exe 内解包的 `configs/` | 仓库 `configs/`，可用 `KENO_CONFIG_DIR` 覆盖 |
| `static_dir()` | exe 内解包的 `keno/webapp/static` | `src/keno/webapp/static` |
| `report_prefix(stem)` | `app_home()/reports` | `app_home()/reports` |
| `official_payouts()` / `sample_rounds()` | 随 exe 打进去的数据 | `data/` 下同名文件 |

`KENO_BOT_HOME` 可以整体改写「状态目录」。PyInstaller 运行时 `sys.frozen` 为真，`sys._MEIPASS` 就是解包根目录，因此所有资源读取都必须走 `paths.resource()` / `paths.bundle_root()`，不要再写 `Path(__file__).parents[n]`。

## 加东西的姿势

* **加选号策略**：在 `strategies/` 实现 `SelectionStrategy.pick(...)`，然后在 `strategies/selection.py` 注册名字。它只能影响选哪 10 个号，不能碰资金；改完记得跑 `strategy-grid` 看它是否只是噪声。
* **加资金管理**：在 `bot/money.py` 实现 `MoneyManager`，`next_bet(bankroll)` 返回下一注金额。默认资金模式的参数在 `configs/bot_phase.yaml`，实盘调度在 `bot/stake_live.py`。
* **加赔率表**：`configs/*.yaml`，字段见 `data/reference/stake_keno_payouts_official.json`（官方 40 档）。`game/paytable.py` 负责解析与查档。
* **加指标**：写在 `reporting/metrics.py`，纯函数、可单测，输入输出都是基本类型。
* **加接口**：`webapp/server.py` 的 `Handler`，`do_GET` / `do_POST` 里注册；新页面放 `webapp/static/`，并用 `paths.static_dir()` 读。

## 打包（`build_exe.ps1`）

```text
keno_bot_app.py  ──PyInstaller──►  dist\KenoBOT.exe
   --paths src                                    （包内源码优先，别解析到别处的 keno）
   --add-data configs;configs                     （YAML 配置）
   --add-data data\reference;data/reference        （官方赔率表）
   --add-data data\samples;data/samples            （自证样本）
   --add-data src\keno\webapp\static;keno/webapp/static
```
