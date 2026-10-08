from __future__ import annotations

from typing import Protocol

class FloatSource(Protocol):
    def next_float(self) -> float: ...


def draw_keno(float_source: FloatSource, board_size: int = 40, draw_count: int = 10) -> list[int]:
    if board_size <= 0 or draw_count <= 0 or draw_count > board_size:
        raise ValueError("draw_count must be in 1..board_size")
    pool = list(range(1, board_size + 1))
    result: list[int] = []
    for _ in range(draw_count):
        value = float_source.next_float()
        if not 0.0 <= value < 1.0:
            raise ValueError("float source must return values in [0, 1)")
        index = min(int(value * len(pool)), len(pool) - 1)
        result.append(pool.pop(index))
    return result
