# Contributing to Keno BOT

Thanks for looking. This is a research/engineering project about Keno, not a money-making product — contributions that make the **measurements** more trustworthy are the most welcome, followed by bug fixes, then UI polish.

## 1. Dev setup

```bash
git clone <your-fork-url> keno-bot && cd keno-bot
python -m pip install -e . pytest

# run the suite from the source tree (Windows PowerShell)
$env:PYTHONPATH='src'; python -m pytest -q

# run the suite from the source tree (bash)
PYTHONPATH=src python -m pytest -q

# start the workbench
python keno_bot_app.py            # http://127.0.0.1:8000, falls back to 8001/8002/...
```

Python 3.11+. Runtime dependency: PyYAML (**paper mode works with the standard library alone**). Optional: `websockets` for the WebSocket data source, `Pillow` only for regenerating the icon, `PyInstaller` only for the exe build.

## 2. Ground rules

1. **Paper mode stays the default.** Nothing may place a real bet without an explicit user action (a flag, or the UI toggle).
2. **No new runtime dependencies** without opening an issue first — the tool should stay easy to audit and easy to package.
3. **No prediction claims.** Heat maps, hot/cold counters and pattern pickers are selection criteria, not predictive models; they do not change RTP. Keep comments and UI text honest about that.
4. **Every number in a report must be reproducible** from a command that a reader can run. If you add a metric, add the way to recompute it.
5. **Never commit** account data: seeds you did not generate, session tokens, exported cookies, browser profiles, or personal paths. Use `data/samples/` for fixtures (`tools/make_sample.py` regenerates them).

## 3. Good first issues

### P0-1 — the per-bet cap is bypassed in combo mode

* Where: `src/keno/bot/stake_live.py:464-477` (`LiveEngine._apply_caps`).
* Problem: the cap branch reads `elif self.kind != "combo" and amount > self.max_bet:` — combo runs never reach it, so the ladder can stake far above `max_bet`.
* Reproduce: start the workbench, open the live page, set `max_bet` to `0.0001` and the custom ladder to `0.0001,0.001,0.011,0.12,1.33`; hit preview repeatedly. All five rungs are proposed, and `cap_note` stays `null`.
* Expected: `elif amount > self.max_bet:` — the cap applies to every engine kind, with the existing note text kept.
* Acceptance: unit test that drives the combo engine to level 4 with `max_bet` below the ladder and asserts every previewed amount `<= max_bet`; `tests/` must stay green.

### P0-2 — `next_bet_blows_stop()` ignores the stop loss

* Where: `src/keno/bot/stake_live.py:121` (used at `:851`).
* Problem: the helper only checks `bankroll`; `session_profit`, `stop_loss`, `level` and `max_level` are accepted but unused, so a session that already hit its stop loss still gets another bet.
* Expected: when the session is at or below `-abs(stop_loss)` and the next bet would need level >= 2 (i.e. the ladder is escalating), report that the bet must be blocked; a level-0 probe may still go out.
* Acceptance: unit test covering (stop loss hit + escalating level -> blocked), (stop loss hit + level 0 -> allowed), (no stop loss -> allowed).

### P0-3 — bet identifiers are random, so a lost response can desync the ledger

* Where: `src/keno/bot/stake_live.py:859` `identifier=str(uuid.uuid4())` (round id at `stake_live.py:558` is random too); confirmation logic in `src/keno/bot/stake_session.py:411-482` raises `Stake 未入账：nonce、余额、注单列表都没变` on timeout.
* Problem: if the mutation response is lost, the money may have moved while the local ladder/ledger never recorded it.
* Expected: derive the identifier deterministically (`f"{run_id}-{index}"`), and on timeout query the account's bet list to reconcile before raising.
* Acceptance: repeated runs produce stable identifiers; a simulated timeout path reconciles instead of raising blindly; a regression test with a stubbed CDP client.

### P1-5 — recovered runs are written with empty summaries

* Where: `src/keno/bot/ledger.py:305` inside `recover_missing_runs()` (`:259`).
* Problem: reconstructed entries always get `{"rounds": n, "profit": "0", "winrate": 0.0}`, so `live_runs.json` shows zeros for every recovered run.
* Expected: summarise the slice that was recovered (rounds, profit, win rate) instead of hard-coding zeros.
* Acceptance: a test that writes records with no run entry, calls `recover_missing_runs()`, and asserts the summary matches the records.

### Smaller, self-contained jobs

* **Cross-platform path audit**: CLI defaults such as `--out reports/...` and `--paytable configs/payout.yaml` are still relative to the current directory even though `keno.paths` resolves packaged assets. Sweep the CLI and the `research/` modules onto `paths.report_prefix()` / `paths.config_file()`.
* **English UI**: `src/keno/webapp/static/*.html|js` are mostly Chinese; add a language switch (keep Chinese as the default) instead of rewriting strings in place.
* **Schema validation**: validate ledger rows and `live_runs.json` against small JSON Schemas; report clear errors instead of `KeyError`.
* **Property tests**: use Hypothesis for the float generator (`0 <= x < 1`, cursor advancement, byte-consumption boundaries) and for `draw_keno` (10 unique numbers in 1..40).
* **Exe smoke job**: a Windows CI job that runs `build_exe.ps1`, starts `dist\KenoBOT.exe` with `KENO_BOT_HOME=<temp>`, and curls `/live` until the title contains `Keno BOT`.

## 4. Pull requests

* Keep a PR to one idea; include the command you ran and its output for anything numeric.
* Run `PYTHONPATH=src python -m pytest -q` before pushing.
* If you change a report's conclusions, update the matching file under `reports/` in the same PR.
* Do not reformat unrelated files; the repository is intentionally flat and readable.

## 5. Where things live

See `docs/ARCHITECTURE.md` (module map and data flow) and `docs/VERIFICATION.md` (how to re-derive draws and audit the paytable).

## 6. Licensing of contributions

Keno BOT is released under the **GNU General Public License v2.0** (see `LICENSE`). By submitting a pull request you agree that your contribution is licensed under the same terms. Copyright (C) 2026 GeniusHu-tgty and contributors.

Keep the two-line header at the top of every Python file:

```python
# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
```

Do not add code you cannot license this way — no copied code from GPL-incompatible sources, no vendored binaries, no scraped data dumps.

## 中文摘要

这个仓库欢迎三类贡献，按优先级：① 让**测量**更可信（校验、审计、复现脚本）；② 修 bug；③ 界面与文档。

规矩：纸面（paper）永远是默认模式，真钱必须显式开启；不引入新的运行时依赖；不写「能预测」的话；每个报告里的数字都要有能重跑的命令；不要把别人的种子、令牌、cookie、浏览器 profile 或本机私有路径提交进仓库。

上手最快的四个任务（P0-1 单注上限在 combo 模式失效、P0-2 止损判断没看止损、P0-3 下注标识随机导致账本漂移、P1-5 恢复出来的运行摘要恒为 0）都在上面写了复现步骤与验收标准。
