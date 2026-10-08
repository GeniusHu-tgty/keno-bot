# Keno BOT

[![License: GPL v2](https://img.shields.io/badge/license-GPLv2-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#quickstart)
[![Tests](https://img.shields.io/badge/tests-110%20passing-brightgreen.svg)](CONTRIBUTING.md)
[![中文文档](https://img.shields.io/badge/docs-%E4%B8%AD%E6%96%87%20README-red.svg)](README.zh-CN.md)

**Keno BOT** is a local, replayable **Keno** workbench and betting bot.

* It re-derives every draw from the published provably-fair chain (`server_seed` / `client_seed` / `nonce`, HMAC-SHA256) — byte for byte, with a verifier you can run in one command.
* It audits the platform's 40-tier payout table instead of trusting it (measured RTP 98.65% – 99.07%).
* It back-tests staking policies against a **null model** (fair hypergeometric draws), so you see the *shape* of the outcome distribution instead of a sales pitch.
* It can drive **your own** account through **your own Chrome** over CDP — paper mode is the default, live betting sits behind an explicit flag.

Keno only. No prediction models, no AI number picking, no profit promises.

![Keno BOT workbench](docs/images/lab.png)

---

## Why not just another Keno script

| The usual script | Keno BOT |
| --- | --- |
| A hammer: hot numbers, cold numbers, martingale | A ruler first: per-bet RTP, variance and expected value are computed locally |
| Screenshots of the wins | A full real-money ledger: turnover, returns, drawdown, losing streaks and percentiles — losses included |
| Payout odds from hearsay | All 40 official tiers recomputed, differences against the built-in table listed one by one |
| The RNG is taken on faith | The HMAC-SHA256 chain is replayed locally and matches the official calculator byte for byte |
| Manual clicking | Staking ladder + session discipline + slice cooldown + stop-loss / take-profit, unattended if you want |

## Quickstart

### A. Run the Windows binary (no Python needed)

1. Download `KenoBOT.exe` from [Releases](../../releases).
2. Double-click it. It serves a page on `127.0.0.1` and opens your browser.
3. Two workbenches: `/` = the simulator (paper only) and `/live` = the live desk (it only touches real money after you connect an account and tick *allow real money*).

The first run creates `%LOCALAPPDATA%\KenoBOT` for state, logs and reports. No registry writes, no service, no installer — delete the folder to wipe it.

### B. Run from source (developers)

```bash
git clone <your-fork-url> keno-bot && cd keno-bot
python -m pip install -e .
python keno_bot_app.py        # same as: python -m keno.cli serve
```

On Windows you can also double-click `启动.bat`: it launches `dist\KenoBOT.exe` when present, otherwise the local Python app.

### C. Build your own exe

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1            # single file: dist\KenoBOT.exe
powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Onedir   # folder build, faster start
powershell -ExecutionPolicy Bypass -File tools\make_release.ps1  # exe + docs -> dist\KenoBOT-<version>-win64.zip
```

The build script generates the icon (`tools/make_icon.py`) and the self-test sample (`tools/make_sample.py`) when needed, and installs PyInstaller if it is missing.

## Live desk (real money, off by default)

Keno BOT never stores your password and ships no login endpoint. It attaches to a Chrome instance **you** are already logged into (Chrome DevTools Protocol), reads the session token out of the page's own requests (in memory only, never written to disk) and then clicks the bet button like a human.

```bash
# 1) start Chrome with a debugging port, using a profile you own
chrome.exe --remote-debugging-port=9222 --user-data-dir=%USERPROFILE%\keno-chrome-profile

# 2) log in inside that Chrome and open the Keno page

# 3) read-only check: connect and report state, no bets
python -m keno.cli live connect --cdp http://127.0.0.1:9222

# 4) only when you mean it: add --live-bets, and start with the minimum stake
python -m keno.cli live run --cdp http://127.0.0.1:9222 --live-bets --risk low --pick-count 10 --rounds 20
```

`KENO_CHROME_PROFILE` and `KENO_CHROME_PS1` point at your Chrome profile and launcher script; without them a default under `~/.keno-bot/` is used.

Discipline lives in the code, not in this document: per-bet cap, ladder levels, two-loss step-down, forced break after a level-4 win, stop-loss / take-profit, slice cooldown and a daily cap. Tune it on the simulator before you connect anything real.

![Keno BOT live desk](docs/images/live.png)

## Provably fair, verified locally

Every round is reproducible from three public values: `server_seed` (hashed up front, revealed later), `client_seed` (yours) and `nonce` (round index). Keno BOT implements that chain down to the byte:

```bash
# self-contained sample shipped with the repo (240 rounds)
python -m keno.cli verify-rounds \
  --replay-file data/samples/rounds_sample.jsonl \
  --seeds-file  data/samples/seeds_sample.json
```

Expect `240/240 rounds PASS` plus a hit-rate comparison. Flip one bit in a seed and it fails immediately — that is how you know the check is real. Captured live rounds replayed the same way and matched the official calculator byte for byte.

## Results so far (read these before deciding anything)

### Real-money ledger (automated betting, 2026-09-12 → 2026-09-18)

| Metric | Value |
| --- | --- |
| Rounds | 9,331 |
| Wagered | 121.2212 U |
| Returned | 112.3248 U |
| Net | **−8.8964 U** |
| Realized RTP | 92.66% (theoretical: 98.76%) |
| Rounds returning at least the stake | 70.24% |
| Worst drawdown | 10.73 U |
| Longest losing streak | 13 rounds |

Feeding the same 9,331 rounds and the same stake ladder into 20,000 Monte-Carlo runs (fair hypergeometric draws, official payouts) gives an expectation of −1.58 U with σ = 7.78 U. The observed −8.90 U sits at the **9.8th–14th percentile**: ugly, but inside normal variance — there is no evidence the game was tampered with. The one hard finding is turnover: at a flat minimum stake those rounds would have moved 0.93 U, while the ladder moved **133.9×** that.

The hit distribution agrees as well: the low/10 subset (7,029 rounds) has χ² = 5.58 with df = 6, p ≈ 0.47.

### Paper back-tests (null model — this is not evidence that a strategy works)

| Experiment | Result |
| --- | --- |
| 1,000 sessions × 176 rounds (ladder staking) | 38.2% profitable sessions, median −0.416 U |
| Same, flat-stake control arm | 37.5% profitable sessions (worse) |
| 30 days × 24 h unattended | 6.7% profitable days, median day −9.56 U, 25 of 30 days ruined |
| Popular community strategies (low/9, low/10, classic/10, …) | all negative ROI, −0.5% to −2.5% |

**Every Keno bet has negative expectation. Money management changes the shape of the outcome distribution (drawdown, ruin speed, variance) — never its sign.** The point of this repo is to make that measurable instead of rhetorical.

### Payout-table audit

`data/reference/stake_keno_payouts_official.json` holds the 40 official tiers; the audit script recomputes each one: **98.65% – 99.07%** (low, 10 picks = 98.76%). The built-in table in `configs/payout.yaml` differs from the official one on the 5/6/7/8/9-hit tiers; the list is in `reports/payout_audit.md`.

## Project layout

```text
keno_bot_app.py            launcher / PyInstaller entry point
build_exe.ps1              build the Windows binary
configs/                   game.yaml (board, RNG protocol), payout.yaml (built-in table), bot_phase.yaml (ladder)
data/reference/            official payout table
data/samples/              self-contained verification sample
src/keno/provably_fair/    HMAC-SHA256 stream, float generator, per-round verifier
src/keno/game/             draws, hits, payouts, settlement
src/keno/bot/              the bot: money management, phase machine, combo strategy, ledger, CDP / live execution
src/keno/research/         Monte-Carlo, parameter-freezing validation, risk grid
src/keno/reporting/        metrics (hypergeometric, χ², drawdown, streaks) and report export
src/keno/webapp/           local workbench (HTTP server + static pages)
tools/                     sample/icon generation, release packaging
docs/                      architecture, verification method, quick start (zh)
tests/                     pytest suite (110 tests)
```

Where state lives: the exe writes to `%LOCALAPPDATA%\KenoBOT`, a source checkout writes to `data/webapp/`, and `KENO_BOT_HOME` overrides both.

## How it relates to other open-source Keno projects

* **evilbot** (`poky1084/evilbot`) — the most active browser-side strategy framework; great to learn how a script hooks into a page. Keno is one of a dozen games it supports, and it does not verify the RNG or audit payouts.
* **stake-bet-analyzer** and similar extensions — hot/cold and pattern statistics, no automated betting, no result verification.
* **This repo** — read-only by default, verifiable, replayable; it does ship a real-money executor, but live betting must be switched on explicitly.

## Roadmap (PRs welcome)

* **Script-style strategy plugins** — a stable per-round hook (history + bankroll in, picks + stake out) so selection logic can be contributed without touching the core. It is the one lesson worth taking from **evilbot** (its `dobet()` interface).
* **Bet-list reconciliation** — after a failed or timed-out bet, look the wager up in the platform's own bet list instead of trusting nonce/balance deltas.
* **English UI** — the static pages are still mostly Chinese; i18n them.
* **Data contracts** — JSON Schema for `data/**/*.jsonl` plus field assertions in `collect`, so malformed rows are rejected at the source.
* **Cross-platform paths** — funnel every path through `keno/paths.py` + env vars (`KENO_CHROME_PROFILE`, `KENO_CHROME_PS1`, `KENO_BOT_HOME`) and support launching Chrome on macOS/Linux.
* **A real WebSocket feed** — `src/keno/bot/ws.py` is a skeleton; make it the primary data source instead of polling.

See `CONTRIBUTING.md` for good first issues with reproduction steps and acceptance criteria.

## Disclaimer

Keno is a negative-expectation gambling game. The author's own measured result is a **loss** (see above). This is a research and engineering project, not investment advice, and it promises nothing. Only play with money you can afford to lose, and follow the law and the platform terms that apply to you.

## License

**GNU General Public License v2.0** — see [`LICENSE`](LICENSE). Copyright (C) 2026 GeniusHu-tgty. There is no warranty, as stated in the license. You may use, study, share and modify this software, including commercially; if you distribute a modified version it must stay under the GPL and ship its source.

---

[中文说明 / Chinese README →](README.zh-CN.md)
