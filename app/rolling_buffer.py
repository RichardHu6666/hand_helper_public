from __future__ import annotations

from dataclasses import dataclass, field

from app.config import CONFIG
from app.stream_models import StreamFrame


@dataclass
class SessionState:
    frames: list[StreamFrame] = field(default_factory=list)
    last_decision: dict | None = None
    last_top_candidates: list[dict] = field(default_factory=list)
    suppressed_candidates: list[dict] = field(default_factory=list)
    confirmed_history: list[dict] = field(default_factory=list)
    stable_candidate_id: int | None = None
    stable_count: int = 0
    cooldown_until_ms: int = 0
    last_confirmed_id: int | None = None
    candidate_changed_since_confirm: bool = True
    repeat_gap_ready: bool = False
    inactive_streak_start_ms: int | None = None
    last_frame_timestamp_ms: int | None = None


class RollingBufferStore:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionState] = {}

    def add_frame(self, frame: StreamFrame) -> SessionState:
        state = self.sessions.setdefault(frame.session_id, SessionState())
        by_identity = {existing.identity_key(): existing for existing in state.frames}
        by_identity[frame.identity_key()] = frame
        frames = sorted(by_identity.values(), key=lambda item: item.sort_key())
        newest_ms = frames[-1].timestamp_ms
        keep_after = newest_ms - int(CONFIG["BUFFER_KEEP_MS"])
        state.frames = [item for item in frames if item.timestamp_ms >= keep_after]
        return state

    def get(self, session_id: str) -> SessionState:
        return self.sessions.setdefault(session_id, SessionState())

    def reset(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    def active_count(self) -> int:
        return len(self.sessions)

