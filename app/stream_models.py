from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.schemas import Primitive


TIMESTAMP_FORMAT = "%y%m%d-%H%M%S"


def parse_stream_timestamp(value: str) -> tuple[int, int]:
    try:
        base, seq_text = value.rsplit("-", 1)
        dt = datetime.strptime(base, TIMESTAMP_FORMAT)
        seq = int(seq_text)
    except ValueError as exc:
        raise ValueError("timestamp must match YYMMDD-HHMMSS-XXX") from exc
    if seq < 0:
        raise ValueError("timestamp sequence must be non-negative")
    return int(dt.timestamp() * 1000) + seq * 100, seq


@dataclass(frozen=True)
class StreamFrame:
    session_id: str
    timestamp: str
    timestamp_ms: int
    seq_in_second: int
    primitive: Primitive
    client_seq: int | None = None

    @classmethod
    def from_request(cls, request: Any, session_id: str | None = None) -> "StreamFrame":
        timestamp_ms, seq = parse_stream_timestamp(request.timestamp)
        return cls(
            session_id=session_id or request.session_id,
            timestamp=request.timestamp,
            timestamp_ms=timestamp_ms,
            seq_in_second=seq,
            client_seq=getattr(request, "client_seq", None),
            primitive=request.primitive,
        )

    def identity_key(self) -> tuple[str, int | None]:
        return (self.timestamp, self.client_seq)

    def sort_key(self) -> tuple[int, int, int]:
        return (
            self.timestamp_ms,
            self.client_seq if self.client_seq is not None else self.seq_in_second,
            self.seq_in_second,
        )


@dataclass(frozen=True)
class Span:
    duration_ms: int
    frames: list[StreamFrame]

    @property
    def start_ts(self) -> str:
        return self.frames[0].timestamp

    @property
    def end_ts(self) -> str:
        return self.frames[-1].timestamp

    @property
    def actual_duration_ms(self) -> int:
        return self.frames[-1].timestamp_ms - self.frames[0].timestamp_ms

