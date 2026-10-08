from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .. import paths
from ..config import load_yaml


def resolve_config_path(path: str | Path) -> Path:
    """Accept a bare config name even inside a bundled exe."""
    candidate = Path(path)
    if candidate.is_absolute() or candidate.exists():
        return candidate
    bundled = paths.config_file(candidate.name)
    return bundled if bundled.exists() else candidate

@dataclass(frozen=True)
class Paytable:
    version: str
    difficulty: str
    payouts: dict[int, dict[int, Decimal]]

    @classmethod
    def from_yaml(cls, path: str | Path, difficulty: str | None = None) -> "Paytable":
        data = load_yaml(resolve_config_path(path))
        selected_difficulty = difficulty or str(data.get("difficulty", "default"))
        raw = data.get("payouts", {})
        parsed = {int(picks): {int(hits): Decimal(str(multiplier)) for hits, multiplier in values.items()} for picks, values in raw.items()}
        return cls(str(data.get("version", "unknown")), selected_difficulty, parsed)

    def multiplier(self, pick_count: int, hits: int) -> Decimal:
        try:
            return self.payouts[pick_count][hits]
        except KeyError as exc:
            raise KeyError(f"missing paytable entry for pick_count={pick_count}, hits={hits}") from exc
