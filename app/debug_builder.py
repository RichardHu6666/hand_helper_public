from __future__ import annotations

from app.debug_tools import build_buffer_summary, build_pending_analysis, enrich_candidates
from app.rolling_buffer import SessionState


def build_session_debug(session_id: str, state: SessionState) -> dict:
    top_candidates = enrich_candidates(state.last_top_candidates, state.suppressed_candidates)
    return {
        "ok": True,
        "session_id": session_id,
        "buffer_frames": len(state.frames),
        "latest_timestamp": state.frames[-1].timestamp if state.frames else None,
        "last_decision": state.last_decision,
        "pending_analysis": build_pending_analysis(state.frames, state.last_decision, state.last_top_candidates, state.suppressed_candidates),
        "buffer_summary": build_buffer_summary(state.frames),
        "top_candidates": top_candidates,
        "suppressed_candidates": state.suppressed_candidates,
        "buffer": [
            {
                "timestamp": frame.timestamp,
                "client_seq": frame.client_seq,
                "primitive": frame.primitive.model_dump(),
            }
            for frame in state.frames
        ],
    }

