from __future__ import annotations

from math import inf
from typing import Any

from app.config import CONFIG
from app.frame_step_scorer import score_frame_step
from app.stream_models import Span


def align_span_to_steps(span: Span, steps: list[dict[str, Any]]) -> dict[str, Any]:
    if not steps or not span.frames:
        return {"complete": False, "score": 0.0, "path": [], "conflict_count": 0}
    n = len(span.frames)
    m = len(steps)
    scores = [
        [score_frame_step(frame.primitive, step["expected"]) for step in steps]
        for frame in span.frames
    ]
    dp = [[-inf] * m for _ in range(n)]
    prev: list[list[int | None]] = [[None] * m for _ in range(n)]
    dp[0][0] = scores[0][0]["score"]
    for i in range(1, n):
        for j in range(m):
            stay = dp[i - 1][j] + float(CONFIG["STAY_BONUS"])
            best = stay
            best_prev = j
            if j > 0:
                advance = dp[i - 1][j - 1] - float(CONFIG["ADVANCE_PENALTY"])
                if advance > best:
                    best = advance
                    best_prev = j - 1
            if best > -inf:
                dp[i][j] = best + scores[i][j]["score"]
                prev[i][j] = best_prev
    end_step = max(range(m), key=lambda j: dp[-1][j])
    complete = end_step == m - 1
    path_steps = [end_step]
    cur = end_step
    for i in range(n - 1, 0, -1):
        cur_prev = prev[i][cur]
        cur = 0 if cur_prev is None else cur_prev
        path_steps.append(cur)
    path_steps.reverse()
    segments = []
    conflict_count = 0
    for step_idx in sorted(set(path_steps)):
        indexes = [idx for idx, value in enumerate(path_steps) if value == step_idx]
        if not indexes:
            continue
        step_scores = [scores[idx][step_idx] for idx in indexes]
        conflict_fields = sorted({f for item in step_scores for f in item["conflict_fields"]})
        matched_fields = sorted({f for item in step_scores for f in item["matched_fields"]})
        unknown_frames = sum(1 for item in step_scores if item["unknown_fields"])
        conflict_count += sum(len(item["conflict_fields"]) for item in step_scores)
        avg_score = sum(item["score"] for item in step_scores) / len(step_scores)
        if m > 1 and len(indexes) < int(CONFIG["MIN_STEP_FRAMES"]):
            avg_score -= 0.10
        segments.append(
            {
                "step_index": steps[step_idx]["step_index"],
                "start_ts": span.frames[indexes[0]].timestamp,
                "end_ts": span.frames[indexes[-1]].timestamp,
                "score": round((avg_score + 1.0) / 2.0, 4),
                "matched_fields": matched_fields,
                "conflict_fields": conflict_fields,
                "unknown_frames": unknown_frames,
            }
        )
    normalized = (dp[-1][end_step] / n + 1.0) / 2.0
    if m > 1 and not complete:
        normalized -= 0.18
    return {
        "complete": complete,
        "score": max(0.0, min(1.0, normalized)),
        "path": segments,
        "conflict_count": conflict_count,
    }

