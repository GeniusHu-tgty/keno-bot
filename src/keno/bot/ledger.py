from __future__ import annotations

"""Paper vs live bet ledger.

Two files, two session counters. Tokens never stored. Each row must carry
`book` so virtual and real money cannot be mixed in reports.
"""

import json
import threading
import time
import uuid
from decimal import Decimal
from math import comb
from pathlib import Path

from .. import paths

ROOT = paths.bundle_root()
DATA_DIR = paths.data_dir()
PAPER_PATH = DATA_DIR / "records.jsonl"
LIVE_PATH = DATA_DIR / "live_records.jsonl"
LIVE_STATE_PATH = DATA_DIR / "live_state.json"
LIVE_RUNS_PATH = DATA_DIR / "live_runs.json"

_LOCK = threading.RLock()
_LIVE_META = {
    "batch": 1,
    "run": 1,
    "start_index": 0,
    "started_at": time.time(),
    "conversation_id": 1,
}


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"))


def _load_live_meta() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not LIVE_STATE_PATH.exists():
        return
    try:
        data = json.loads(LIVE_STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    _LIVE_META.update({k: data[k] for k in _LIVE_META if k in data})


def _save_live_meta() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LIVE_STATE_PATH.write_text(json.dumps(_LIVE_META, ensure_ascii=False, indent=2), encoding="utf-8")


_load_live_meta()


def live_level() -> str:
    return f"L{_LIVE_META['conversation_id']}B{_LIVE_META['batch']}R{_LIVE_META['run']}"


def live_session_info() -> dict:
    run = current_run()
    play_started = float((run or {}).get("play_started_at") or 0)
    play_ended = float((run or {}).get("play_ended_at") or 0)
    if play_started <= 0:
        duration = 0.0
    elif play_ended > play_started:
        duration = play_ended - play_started
    else:
        duration = max(0.0, time.time() - play_started)
    return {
        "level": live_level(),
        "duration_sec": duration,
        "playing": play_started > 0 and play_ended <= 0,
        "conversation_id": int(_LIVE_META.get("conversation_id") or 1),
        "batch": int(_LIVE_META.get("batch") or 1),
        "run": int(_LIVE_META.get("run") or 1),
    }


def new_live_session(
    new_batch: bool = False,
    new_conversation: bool = False,
    name: str | None = None,
    settings: dict | None = None,
) -> str:
    with _LOCK:
        records = read_records("live")
        _catalog_close_open(records)
        if new_conversation:
            _LIVE_META["conversation_id"] = int(_LIVE_META.get("conversation_id") or 1) + 1
            _LIVE_META["batch"] = 1
            _LIVE_META["run"] = 1
        elif new_batch:
            _LIVE_META["batch"] = int(_LIVE_META.get("batch") or 1) + 1
            _LIVE_META["run"] = 1
        else:
            _LIVE_META["run"] = int(_LIVE_META.get("run") or 1) + 1
        _LIVE_META["start_index"] = len(records)
        _LIVE_META["started_at"] = time.time()
        _save_live_meta()
        _catalog_open(len(records), name=name, settings=settings)
        return live_level()


def _runs_empty() -> dict:
    return {"runs": [], "current_id": None}


def _load_runs() -> dict:
    for path in (LIVE_RUNS_PATH, LIVE_RUNS_PATH.with_name("live_runs.json.bak")):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or "runs" not in data:
            continue
        data.setdefault("runs", [])
        data.setdefault("current_id", None)
        return data
    return _runs_empty()


def _save_runs(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = LIVE_RUNS_PATH.with_name("live_runs.json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    if LIVE_RUNS_PATH.exists():
        bak = LIVE_RUNS_PATH.with_name("live_runs.json.bak")
        try:
            LIVE_RUNS_PATH.replace(bak)
        except OSError:
            pass
    tmp.replace(LIVE_RUNS_PATH)


def _fmt_when(ts: float) -> str:
    local = time.localtime(float(ts or time.time()))
    return f"{local.tm_mon}月{local.tm_mday}日 {local.tm_hour:02d}:{local.tm_min:02d}"


def mode_brief(settings: dict | None) -> str:
    s = settings or {}
    risk = {"low": "低等", "medium": "中等", "classic": "典型", "high": "高等"}.get(str(s.get("risk") or "low"), "低等")
    n = int(s.get("pick_count") or 10)
    amounts = str(s.get("custom_amounts") or "0.0001")
    keep = "赢了留号" if s.get("keep_on_win", True) not in (False, "false", "0", 0) else "每局换号"
    recon = "侦察开" if s.get("recon_on") else "侦察关"
    return f"{risk}{n}选 · Combo V2 · {amounts} · {keep} · {recon}"


def _catalog_close_open(records: list[dict]) -> None:
    data = _load_runs()
    now = time.time()
    changed = False
    for run in data["runs"]:
        if not run.get("open"):
            continue
        start = int(run.get("start_index") or 0)
        rows = records[start:]
        stats = summarize(rows)
        run["open"] = False
        run["ended_at"] = now
        run["end_index"] = len(records)
        if run.get("play_started_at") and not run.get("play_ended_at"):
            run["play_ended_at"] = now
        run["summary"] = {
            "rounds": len(rows),
            "profit": str(stats.get("profit") or "0"),
            "winrate": stats.get("success_rate") or 0.0,
        }
        changed = True
    if changed:
        data["current_id"] = None
        _save_runs(data)


def _catalog_open(start_index: int, name: str | None = None, settings: dict | None = None) -> dict:
    data = _load_runs()
    started = float(_LIVE_META.get("started_at") or time.time())
    run = {
        "id": time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4],
        "name": (name or "").strip(),
        "started_at": started,
        "ended_at": None,
        "start_index": int(start_index),
        "end_index": None,
        "open": True,
        "settings": dict(settings or {}),
        "summary": {"rounds": 0, "profit": "0", "winrate": 0.0},
    }
    data["runs"].append(run)
    data["current_id"] = run["id"]
    _save_runs(data)
    return run


def _parse_ts(value) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return time.mktime(time.strptime(str(value), "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return 0.0


def _infer_amounts(rows: list[dict]) -> str:
    seen: list[Decimal] = []
    got: set[str] = set()
    for row in rows:
        raw = str(row.get("bet") or "").strip()
        if not raw or raw in got:
            continue
        try:
            amt = Decimal(raw)
        except Exception:
            continue
        got.add(raw)
        seen.append(amt)
    seen.sort()
    return ",".join(format(a, "f") for a in seen) if seen else "0.0001"


def _group_record_ranges(records: list[dict]) -> list[tuple[str, int, int]]:
    groups: list[tuple[str, int, int]] = []
    if not records:
        return groups
    start = 0
    key = str(records[0].get("run_id") or "") or ("session:" + str(records[0].get("session") or "x"))
    for i, row in enumerate(records[1:], 1):
        nxt = str(row.get("run_id") or "") or ("session:" + str(row.get("session") or "x"))
        if nxt != key:
            groups.append((key, start, i))
            start = i
            key = nxt
    groups.append((key, start, len(records)))
    return groups


def _range_covered(runs: list[dict], start: int, end: int) -> bool:
    for run in runs:
        rs = int(run.get("start_index") or 0)
        if run.get("open") or run.get("end_index") in (None, ""):
            re = 10**12
        else:
            re = int(run.get("end_index") or rs)
        if rs <= start and end <= re:
            return True
    return False


def recover_missing_runs() -> int:
    """Rebuild catalog entries from live_records.jsonl. Bets are permanent; the list is not allowed to stay empty."""
    with _LOCK:
        records = read_records("live")
        data = _load_runs()
        by_id = {str(r.get("id")): r for r in data["runs"]}
        added = 0
        for key, start, end in _group_record_ranges(records):
            if start >= end:
                continue
            rid = key if key and not key.startswith("session:") else ""
            if rid and rid in by_id:
                run = by_id[rid]
                if run.get("start_index") in (None, ""):
                    run["start_index"] = start
                if not run.get("open") and run.get("end_index") in (None, ""):
                    run["end_index"] = end
                continue
            if _range_covered(data["runs"], start, end):
                continue
            first = records[start]
            last = records[end - 1]
            if not rid:
                stamp = str(first.get("ts") or start).replace(" ", "-").replace(":", "")
                rid = "recov-" + stamp
            if rid in by_id:
                continue
            settings = {
                "risk": first.get("risk") or "low",
                "pick_count": int(first.get("pick_count") or 10),
                "custom_amounts": _infer_amounts(records[start:end]),
                "keep_on_win": True,
                "recon_on": False,
            }
            started = _parse_ts(first.get("ts")) or time.time()
            ended = _parse_ts(last.get("ts")) or started
            run = {
                "id": rid,
                "name": "",
                "started_at": started,
                "ended_at": ended,
                "start_index": start,
                "end_index": end,
                "open": False,
                "settings": settings,
                "recovered": True,
                "summary": {"rounds": end - start, "profit": "0", "winrate": 0.0},
            }
            data["runs"].append(run)
            by_id[rid] = run
            added += 1
        if added:
            data["runs"].sort(key=lambda r: float(r.get("started_at") or 0))
            _save_runs(data)
        return added


def _amounts_key(text: str) -> str:
    parts: list[str] = []
    for p in str(text or "").replace("，", ",").split(","):
        p = p.strip()
        if not p:
            continue
        try:
            parts.append(format(Decimal(p).normalize(), "f"))
        except Exception:
            parts.append(p)
    return ",".join(parts)


def fix_mismatched_run_names() -> int:
    """Don't keep a strategy nickname if the ladder/risk no longer match."""
    with _LOCK:
        data = _load_runs()
        changed = 0
        video_low4 = _amounts_key("0.001,0.011,0.12,1.33")
        for run in data["runs"]:
            name = str(run.get("name") or "").strip()
            if name != "录像低等四档":
                continue
            s = run.get("settings") or {}
            amt = _amounts_key(s.get("custom_amounts"))
            risk = str(s.get("risk") or "low").lower()
            if risk == "low" and amt == video_low4:
                continue
            risk_name = {"low": "低等", "medium": "中等", "classic": "典型", "high": "高等"}.get(risk, risk)
            raw = str(s.get("custom_amounts") or "").strip()
            run["name"] = f"{risk_name} {raw}".strip() if raw else risk_name
            changed += 1
        if changed:
            _save_runs(data)
        return changed


def _ensure_catalog() -> dict:
    data = _load_runs()
    records = read_records("live")
    if records:
        recover_missing_runs()
        fix_mismatched_run_names()
        data = _load_runs()
    if data["runs"]:
        return data
    start = int(_LIVE_META.get("start_index") or 0)
    _catalog_open(start, name="", settings={})
    return _load_runs()


def current_run() -> dict | None:
    data = _ensure_catalog()
    cid = data.get("current_id")
    for run in data["runs"]:
        if run.get("id") == cid:
            return run
    for run in reversed(data["runs"]):
        if run.get("open"):
            return run
    return None


def update_current_run_settings(settings: dict | None = None, name: str | None = None) -> dict | None:
    with _LOCK:
        data = _ensure_catalog()
        cid = data.get("current_id")
        for run in data["runs"]:
            if run.get("id") != cid and not (cid is None and run.get("open")):
                continue
            if settings:
                run["settings"] = dict(settings)
            if name is not None:
                run["name"] = str(name).strip()
            _save_runs(data)
            return run
        return None


def mark_play_start() -> None:
    with _LOCK:
        data = _ensure_catalog()
        cid = data.get("current_id")
        now = time.time()
        for run in data["runs"]:
            if run.get("id") == cid or (cid is None and run.get("open")):
                if not run.get("play_started_at"):
                    run["play_started_at"] = now
                run["play_ended_at"] = None
                _save_runs(data)
                return


def mark_play_end() -> None:
    with _LOCK:
        data = _ensure_catalog()
        cid = data.get("current_id")
        now = time.time()
        for run in data["runs"]:
            if run.get("id") == cid or run.get("open"):
                if run.get("play_started_at") and not run.get("play_ended_at"):
                    run["play_ended_at"] = now
                _save_runs(data)
                return


def delete_live_run(run_id: str) -> bool:
    with _LOCK:
        data = _ensure_catalog()
        was_current = data.get("current_id") == run_id
        kept = [r for r in data["runs"] if r.get("id") != run_id]
        if len(kept) == len(data["runs"]):
            return False
        data["runs"] = kept
        if was_current:
            data["current_id"] = None
        _save_runs(data)
        if was_current:
            records = read_records("live")
            _LIVE_META["start_index"] = len(records)
            _LIVE_META["started_at"] = time.time()
            _save_live_meta()
            _catalog_open(len(records), name="", settings={})
        return True


def rename_live_run(run_id: str, name: str) -> dict | None:
    with _LOCK:
        data = _ensure_catalog()
        for run in data["runs"]:
            if run.get("id") == run_id:
                run["name"] = str(name or "").strip()
                _save_runs(data)
                return run
        return None


def _run_rows(run: dict, records: list[dict]) -> list[dict]:
    start = int(run.get("start_index") or 0)
    if run.get("open") or run.get("end_index") in (None, ""):
        return records[start:]
    end = int(run.get("end_index") or start)
    return records[start:end]


def list_live_runs() -> list[dict]:
    from .combo_v2 import dashboard

    data = _ensure_catalog()
    records = read_records("live")
    out = []
    for run in reversed(data["runs"]):
        rows = _run_rows(run, records)
        dash = dashboard(rows)
        started = float(run.get("started_at") or 0)
        name = str(run.get("name") or "").strip()
        settings = run.get("settings") or {}
        brief = mode_brief(settings)
        amounts = str(settings.get("custom_amounts") or "")
        risk = str(settings.get("risk") or "low")
        risk_name = {"low": "低等", "medium": "中等", "classic": "典型", "high": "高等"}.get(risk, risk)
        day = time.strftime("%Y-%m-%d", time.localtime(started)) if started else ""
        out.append(
            {
                "id": run.get("id"),
                "name": name,
                "open": bool(run.get("open")),
                "when": _fmt_when(started),
                "day": day,
                "started_at": started,
                "ended_at": run.get("ended_at"),
                "brief": brief,
                "strategy_key": f"{risk}|{amounts}",
                "strategy_label": f"{risk_name} · {amounts or '未写梯子'}",
                "settings": settings,
                "rounds": dash["rounds"],
                "profit": dash["profit"],
                "winrate": dash["winrate"],
                "wins": dash["wins"],
                "fails": dash["fails"],
                "staked": dash["staked"],
                "returned": dash["returned"],
            }
        )
    return out


def _run_duration_sec(run: dict) -> float:
    start = float(run.get("play_started_at") or 0)
    end = float(run.get("play_ended_at") or 0)
    if start <= 0:
        start = float(run.get("started_at") or 0)
        end = float(run.get("ended_at") or 0)
    if start <= 0:
        return 0.0
    if end > start:
        return end - start
    return 0.0


def get_live_run(run_id: str) -> dict | None:
    from .combo_v2 import dashboard

    data = _ensure_catalog()
    records = read_records("live")
    for run in data["runs"]:
        if run.get("id") != run_id:
            continue
        rows = _run_rows(run, records)
        dash = dashboard(rows)
        curve = dash.get("curve") or []
        stamped = []
        for i, row in enumerate(rows):
            item = dict(row)
            if i < len(curve):
                item["cum_profit"] = curve[i]["cum"]
                if not item.get("n"):
                    item["n"] = curve[i]["n"]
            stamped.append(item)
        started = float(run.get("started_at") or 0)
        return {
            "id": run.get("id"),
            "name": run.get("name") or _fmt_when(started),
            "open": bool(run.get("open")),
            "when": _fmt_when(started),
            "started_at": started,
            "ended_at": run.get("ended_at"),
            "play_started_at": run.get("play_started_at"),
            "play_ended_at": run.get("play_ended_at"),
            "duration_sec": _run_duration_sec(run),
            "brief": mode_brief(run.get("settings") or {}),
            "settings": run.get("settings") or {},
            "dashboard": dash,
            "records": stamped,
        }
    return None


def _path_for(book: str) -> Path:
    return LIVE_PATH if book == "live" else PAPER_PATH


def read_records(book: str) -> list[dict]:
    path = _path_for(book)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        row.setdefault("book", book)
        rows.append(row)
    return rows


def append_record(book: str, record: dict) -> dict:
    payload = dict(record)
    payload["book"] = book
    path = _path_for(book)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def scoped_records(book: str, scope: str = "session") -> list[dict]:
    if book == "all":
        rows = [{**r, "book": r.get("book") or "paper"} for r in read_records("paper")]
        rows.extend(read_records("live"))
        rows.sort(key=lambda r: str(r.get("ts") or ""))
        return rows
    rows = read_records(book)
    if scope != "session":
        return rows
    if book == "live":
        start = int(_LIVE_META.get("start_index") or 0)
        return rows[start:]
    return rows


def summarize(records: list[dict]) -> dict:
    staked = Decimal("0")
    returned = Decimal("0")
    wins = 0
    streak = 0
    longest_loss = 0
    for row in records:
        bet = Decimal(str(row.get("bet") or "0"))
        payout = Decimal(str(row.get("payout") or "0"))
        staked += bet
        returned += payout
        if payout > bet:
            wins += 1
            streak = 0
        else:
            streak += 1
            longest_loss = max(longest_loss, streak)
    profit = _q(returned - staked)
    return {
        "rounds": len(records),
        "staked": str(_q(staked)),
        "returned": str(_q(returned)),
        "profit": str(profit),
        "success_rate": (wins / len(records)) if records else 0.0,
        "current_loss_streak": streak,
        "longest_loss_streak": longest_loss,
        "wins": wins,
        "fails": len(records) - wins,
    }


def loss_p_pick10() -> float:
    total = comb(40, 10)
    p0 = comb(30, 10) / total
    p1 = comb(10, 1) * comb(30, 9) / total
    return p0 + p1


def viability(live_records: list[dict], paper_records: list[dict] | None = None) -> dict:
    """Whether live play is justified. Consecutive losses are not an edge."""
    loss_p = loss_p_pick10()
    live_sum = summarize(live_records)
    streak = live_sum["current_loss_streak"]
    p_streak = loss_p ** max(streak, 0)
    unusual = streak >= 8
    if streak >= 8:
        recommendation = "pause"
        reason = (
            f"当前实盘连败 {streak} 局。pick-10 单局失败率约 {loss_p:.1%}，"
            f"连续 {streak} 次失败的概率约 {p_streak:.4%}。这是方差，不是该加注追回的信号。"
            "先停实盘，回虚拟盘。"
        )
    else:
        recommendation = "probe-only"
        reason = (
            "官方赔率 RTP 约 98.76%，任何选号和资金管理的长期期望都是亏。"
            "报告里说的连败是 pick-10 约 20% 失败局的正常成串，不能当成该上实盘追的依据。"
            "若仍要实盘，只允许 0.0001 探针 + 硬止损。"
        )
    return {
        "live_ev_positive": False,
        "rtp_pct": 98.7597,
        "loss_p": loss_p,
        "success_p": 1.0 - loss_p,
        "current_loss_streak": streak,
        "streak_probability": p_streak,
        "streak_unusual": unusual,
        "recommendation": recommendation,
        "reason": reason,
        "live_summary": live_sum,
        "paper_summary": summarize(paper_records or []),
    }


def _record_day(row: dict) -> str:
    ts = str(row.get("ts") or "")
    if len(ts) >= 10 and ts[4] == "-" and ts[7] == "-":
        return ts[:10]
    return ""


def _shift_day(ymd: str, days: int) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(ymd) + timedelta(days=days)).isoformat()


def _new_pnl_bucket() -> dict:
    z = Decimal("0")
    return {"profit": z, "staked": z, "returned": z, "rounds": 0, "wins": 0, "fails": 0}


def _add_pnl_row(bucket: dict, row: dict) -> None:
    bet = Decimal(str(row.get("bet") or "0"))
    payout = Decimal(str(row.get("payout") or "0"))
    profit = Decimal(str(row.get("profit") or (payout - bet)))
    bucket["profit"] += profit
    bucket["staked"] += bet
    bucket["returned"] += payout
    bucket["rounds"] += 1
    if payout >= bet:
        bucket["wins"] += 1
    else:
        bucket["fails"] += 1


def _pack_pnl_bucket(bucket: dict) -> dict:
    staked = bucket["staked"]
    profit = bucket["profit"]
    roi = float(profit / staked) if staked else 0.0
    return {
        "profit": str(_q(profit)),
        "staked": str(_q(staked)),
        "returned": str(_q(bucket["returned"])),
        "rounds": int(bucket["rounds"]),
        "wins": int(bucket["wins"]),
        "fails": int(bucket["fails"]),
        "roi": roi,
    }


def _row_pnl(row: dict) -> Decimal:
    if row.get("profit") not in (None, ""):
        return Decimal(str(row["profit"]))
    bet = Decimal(str(row.get("bet") or "0"))
    payout = Decimal(str(row.get("payout") or "0"))
    return payout - bet


def _downsample(points: list, max_points: int = 360) -> list:
    n = len(points)
    if n <= max_points:
        return points
    out = []
    last_idx = n - 1
    for i in range(max_points - 1):
        idx = int(i * last_idx / (max_points - 1))
        out.append(points[idx])
    out.append(points[-1])
    return out


def _curve_point(ts: str, cum: Decimal, pnl: Decimal) -> dict:
    return {"ts": ts, "cum": str(_q(cum)), "profit": str(_q(pnl))}


def pnl_from_records(records: list[dict], today: str | None = None) -> dict:
    """Daily / weekly / monthly P&L. Curves follow the calendar window, not one session."""
    today = today or time.strftime("%Y-%m-%d")
    start_7 = _shift_day(today, -6)
    start_30 = _shift_day(today, -29)
    ordered = sorted(
        (r for r in records if _record_day(r)),
        key=lambda r: str(r.get("ts") or ""),
    )
    by_day: dict[str, dict] = {}
    all_b = _new_pnl_bucket()
    today_b = _new_pnl_bucket()
    d7_b = _new_pnl_bucket()
    d30_b = _new_pnl_bucket()
    today_curve: list[dict] = []
    d7_curve: list[dict] = []
    d30_curve: list[dict] = []
    today_cum = Decimal("0")
    d7_cum = Decimal("0")
    d30_cum = Decimal("0")
    for row in ordered:
        day = _record_day(row)
        pnl = _row_pnl(row)
        ts = str(row.get("ts") or "")
        _add_pnl_row(all_b, row)
        bucket = by_day.setdefault(day, _new_pnl_bucket())
        _add_pnl_row(bucket, row)
        if day == today:
            _add_pnl_row(today_b, row)
            today_cum += pnl
            today_curve.append(_curve_point(ts, today_cum, pnl))
        if start_7 <= day <= today:
            _add_pnl_row(d7_b, row)
            d7_cum += pnl
            d7_curve.append(_curve_point(ts, d7_cum, pnl))
        if start_30 <= day <= today:
            _add_pnl_row(d30_b, row)
            d30_cum += pnl
            d30_curve.append(_curve_point(ts, d30_cum, pnl))
    days = []
    running = Decimal("0")
    for day in sorted(by_day):
        packed = _pack_pnl_bucket(by_day[day])
        running += Decimal(packed["profit"])
        packed["day"] = day
        packed["cum"] = str(_q(running))
        days.append(packed)
    today_packed = _pack_pnl_bucket(today_b)
    return {
        "today": today,
        "buckets": {
            "today": today_packed,
            "d7": _pack_pnl_bucket(d7_b),
            "d30": _pack_pnl_bucket(d30_b),
            "all": _pack_pnl_bucket(all_b),
        },
        "days": days,
        "today_curve": _downsample(today_curve),
        "d7_curve": _downsample(d7_curve),
        "d30_curve": _downsample(d30_curve),
    }


def live_pnl_board() -> dict:
    return pnl_from_records(read_records("live"))
