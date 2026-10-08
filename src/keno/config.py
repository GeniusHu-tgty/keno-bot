# Copyright (C) 2026 GeniusHu-tgty
# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
from typing import Any
import yaml

def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
