from __future__ import annotations

import hashlib
import hmac

class HmacSha256Rng:
    """Deterministic byte source for a fully specified provably-fair round.

    Stream semantics: consecutive `bytes()` calls continue the same stream.
    Digests for cursor=0,1,2,... are concatenated conceptually — one digest
    yields 32 bytes (8 keno floats); the next digest is computed only after
    the previous digest's bytes are exhausted. (Verified against real Stake
    rounds: 4/4 keno draws reproduced exactly, 2026-09-11.)
    """

    def __init__(self, server_seed: str, client_seed: str, nonce: int, cursor: int = 0, message_template: str = "{client_seed}:{nonce}:{cursor}") -> None:
        if not server_seed:
            raise ValueError("server_seed must not be empty")
        self.server_seed = server_seed
        self.client_seed = client_seed
        self.nonce = int(nonce)
        self.cursor = int(cursor)
        self.message_template = message_template
        self._buffer = bytearray()

    def digest(self, cursor: int | None = None) -> bytes:
        c = self.cursor if cursor is None else int(cursor)
        message = self.message_template.format(client_seed=self.client_seed, nonce=self.nonce, cursor=c).encode("utf-8")
        return hmac.new(self.server_seed.encode("utf-8"), message, hashlib.sha256).digest()

    def bytes(self, count: int) -> bytes:
        if count < 0:
            raise ValueError("count must be non-negative")
        while len(self._buffer) < count:
            self._buffer.extend(self.digest(self.cursor))
            self.cursor += 1
        out = bytes(self._buffer[:count])
        del self._buffer[:count]
        return out
