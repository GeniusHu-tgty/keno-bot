from __future__ import annotations

from dataclasses import dataclass
from .hmac_rng import HmacSha256Rng
from .float_generator import FloatGenerator
from ..game.keno_draw import draw_keno

@dataclass(frozen=True)
class VerificationResult:
    expected: list[int]
    observed: list[int]

    @property
    def passed(self) -> bool:
        return self.expected == self.observed

    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"

def verify_round(server_seed: str, client_seed: str, nonce: int, observed: list[int], cursor: int = 0, message_template: str = "{client_seed}:{nonce}:{cursor}") -> VerificationResult:
    rng = FloatGenerator(HmacSha256Rng(server_seed, client_seed, nonce, cursor, message_template))
    expected = draw_keno(rng)
    return VerificationResult(expected=expected, observed=list(observed))
