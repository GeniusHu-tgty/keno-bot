"""Filesystem layout for Keno BOT.

Read-only assets (configs, web assets, official payouts, sample rounds) are
resolved from the bundle root: sys._MEIPASS when running from a PyInstaller
build, the repository root when running from source.

Writable state (records, run metadata, logs) goes to a per-user directory so a
one-file .exe never needs to write next to itself.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "KenoBOT"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[2]


def app_home() -> Path:
    """Writable per-user home. Override with KENO_BOT_HOME."""
    override = os.environ.get("KENO_BOT_HOME")
    if override:
        path = Path(override).expanduser()
    elif is_frozen():
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        path = (Path(base) if base else Path.home() / ".local" / "share") / APP_NAME
    else:
        path = bundle_root() / "data" / "webapp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    path = app_home() / "data" if is_frozen() else app_home()
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = app_home() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resource(*parts: str) -> Path:
    """Path inside the read-only bundle, e.g. resource("configs", "payout.yaml")."""
    return bundle_root().joinpath(*parts)


def _first_existing(candidates: list[Path]) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def config_file(name: str) -> Path:
    """Resolve a config file: KENO_CONFIG_DIR, bundled configs, then ./configs."""
    candidates: list[Path] = []
    override = os.environ.get("KENO_CONFIG_DIR")
    if override:
        candidates.append(Path(override).expanduser() / name)
    candidates.append(bundle_root() / "configs" / name)
    candidates.append(Path.cwd() / "configs" / name)
    return _first_existing(candidates)


def static_dir() -> Path:
    if is_frozen():
        return bundle_root() / "keno" / "webapp" / "static"
    return Path(__file__).resolve().parent / "webapp" / "static"


def official_payouts() -> Path:
    return _first_existing(
        [
            bundle_root() / "data" / "reference" / "stake_keno_payouts_official.json",
            Path.cwd() / "data" / "reference" / "stake_keno_payouts_official.json",
        ]
    )


def sample_rounds() -> Path:
    """Self-generated provably-fair sample used by the randomness self-test."""
    return _first_existing(
        [
            bundle_root() / "data" / "samples" / "rounds_sample.jsonl",
            Path.cwd() / "data" / "samples" / "rounds_sample.jsonl",
        ]
    )


def sample_seeds() -> Path:
    return _first_existing(
        [
            bundle_root() / "data" / "samples" / "seeds_sample.json",
            Path.cwd() / "data" / "samples" / "seeds_sample.json",
        ]
    )


def report_prefix(stem: str) -> str:
    """Where generated reports go (never inside a read-only bundle)."""
    directory = app_home() / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory / stem)
