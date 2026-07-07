from __future__ import annotations

from typing import Any

from app.candidate_scorer import ambiguity_penalty, build_signature_counts, score_candidate
from app.config import CONFIG
from app.debug_tools import build_buffer_summary, build_pending_analysis, enrich_candidates
from app.output_state_machine import decide_output
from app.rolling_buffer import RollingBufferStore, SessionState
from app.span_generator import generate_spans
from app.span_summary import summarize_span
from app.step_aligner import align_span_to_steps
from app.storage import lite_vocab_entries
from app.stream_models import StreamFrame
from app.wide_filter import passes_wide_filter


class StreamDecoder:
    def __init__(self, reranker: Any | None = None, sentence_composer: Any | None = None) -> None:
        self.store = RollingBufferStore()
        self.reranker = reranker
        self.sentence_composer = sentence_composer

    def reset(self, session_id: str) -> None:
        self.store.reset(session_id)
        if self.sentence_composer is not None:
            self.sentence_composer.reset(session_id)

    def decode(self, frame: StreamFrame, include_debug: bool = False) -> dict[str, Any]:
        state = self.store.add_frame(frame)
        spans = generate_spans(state.frames)
        if not spans:
            decision = {"status": "collecting", "selected": None, "reason": ["not_enough_frames"], "suppressed": []}
            state.last_decision = decision
            state.last_top_candidates = []
            state.suppressed_candidates = []
            return self._response(
                frame.session_id,
                state,
                decision,
                [],
                [],
                include_debug,
                {"enabled": bool(self.reranker), "applied": False, "reason": "not_enough_frames"},
                [],
            )

        all_candidates: list[dict[str, Any]] = []
        debug_spans: list[dict[str, Any]] = []
        entries = lite_vocab_entries()
        step_signature_counts, loose_signature_counts = build_signature_counts(entries)
        for span in spans:
            summary = summarize_span(span)
            span_candidates: list[dict[str, Any]] = []
            passed = 0
            rejected = 0
            for entry in entries:
                passed_filter, wide_conflicts = passes_wide_filter(summary, entry.steps)
                if not passed_filter:
                    rejected += 1
                    continue
                passed += 1
                alignment = align_span_to_steps(span, entry.steps)
                expected_fields = [
                    value
                    for step in entry.steps
                    for value in step["expected"].values()
                ]
                expected_unknown_ratio = sum(1 for value in expected_fields if value == "unknown") / max(len(expected_fields), 1)
                ambiguity = ambiguity_penalty(entry.steps, step_signature_counts, loose_signature_counts)
                breakdown = score_candidate(span, summary, alignment, wide_conflicts, expected_unknown_ratio, ambiguity)
                candidate = {
                    "id": entry.id,
                    "word_base": entry.word_base,
                    "score": breakdown["final_score"],
                    "start_ts": span.start_ts,
                    "end_ts": span.end_ts,
                    "start_ms": span.frames[0].timestamp_ms,
                    "end_ms": span.frames[-1].timestamp_ms,
                    "complete": alignment["complete"],
                    "step_alignment": alignment["path"],
                    "score_breakdown": breakdown,
                    "wide_conflicts": wide_conflicts,
                    "span_summary": summary,
                    "conflict_count": alignment["conflict_count"],
                }
                span_candidates.append(candidate)
            span_candidates.sort(key=lambda item: (-item["score"], item["id"]))
            all_candidates.extend(span_candidates[: int(CONFIG["WIDE_FILTER_TOP_N"])])
            debug_spans.append(
                {
                    "duration_ms": span.duration_ms,
                    "frame_count": len(span.frames),
                    "summary": summary,
                    "wide_filter": {
                        "input_entries": len(entries),
                        "passed_entries": passed,
                        "rejected_entries": rejected,
                    },
                    "top_candidates": enrich_candidates(self._public_candidates(span_candidates[:5], debug=True)),
                }
            )

        all_candidates.sort(key=lambda item: (-item["score"], item["id"]))
        deduped_candidates: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for candidate in all_candidates:
            if candidate["id"] in seen_ids:
                continue
            seen_ids.add(candidate["id"])
            deduped_candidates.append(candidate)

        primitive_top_candidates = deduped_candidates[:5]
        rerank_debug = {
            "enabled": False,
            "applied": False,
            "primitive_top1": primitive_top_candidates[0]["word_base"] if primitive_top_candidates else None,
            "reranked_top1": primitive_top_candidates[0]["word_base"] if primitive_top_candidates else None,
            "rank_changed": False,
        }
        top_candidates = primitive_top_candidates
        if self.reranker is not None:
            rerank_result = self.reranker.rerank(primitive_top_candidates)
            top_candidates = rerank_result.candidates[:5]
            rerank_debug = rerank_result.debug

        decision = decide_output(state, top_candidates, frame.timestamp_ms)
        selected = decision["selected"]
        state.last_decision = {
            "status": decision["status"],
            "selected_id": selected["id"] if selected else None,
            "selected_word": selected["word_base"] if selected else None,
            "selected_score": selected.get("score") if selected else None,
            "selected_primitive_score": selected.get("primitive_score") if selected else None,
            "selected_rag_score": selected.get("rag_score") if selected else None,
            "selected_final_score": selected.get("final_score", selected.get("score")) if selected else None,
            "reason": decision["reason"],
            "margin": decision.get("margin"),
            "stable_count": decision.get("stable_count"),
            "cooldown_until_ms": decision.get("cooldown_until_ms"),
            "suppressed": [
                {"id": item["id"], "word_base": item["word_base"], "score": item.get("score"), "reason": item["reason"]}
                for item in decision["suppressed"]
            ],
        }
        state.last_top_candidates = self._public_candidates(top_candidates, debug=True)
        return self._response(frame.session_id, state, decision, top_candidates, debug_spans, include_debug, rerank_debug, primitive_top_candidates)

    def decode_batch(self, frames: list[StreamFrame], include_debug: bool = False) -> dict[str, Any]:
        ordered_frames = sorted(
            enumerate(frames),
            key=lambda item: ((*item[1].sort_key(), item[0])),
        )
        latest_response: dict[str, Any] | None = None
        latest_confirmed_response: dict[str, Any] | None = None
        frame_results: list[dict[str, Any]] = []
        for _, frame in ordered_frames:
            response = self.decode(frame, include_debug=False)
            latest_response = response
            state = self.store.get(frame.session_id)
            decision = state.last_decision or {}
            frame_result = {
                "client_seq": frame.client_seq,
                "timestamp": frame.timestamp,
                "status": response["status"],
                "reason": decision.get("reason", []),
            }
            selected_id = decision.get("selected_id")
            selected_suppressed = next(
                (item for item in decision.get("suppressed", []) if item.get("id") == selected_id),
                None,
            )
            if selected_suppressed is not None:
                frame_result["suppress_reason"] = selected_suppressed.get("reason")
            if response["status"] == "confirmed" and response.get("result"):
                frame_result["word_base"] = response["result"]["word_base"]
                frame_result["confidence"] = response["result"]["confidence"]
                latest_confirmed_response = response
            elif response["status"] == "pending" and response.get("partial_candidates"):
                frame_result["word_base"] = response["partial_candidates"][0].get("word_base")
            frame_results.append(frame_result)
        if latest_response is None:
            raise ValueError("decode_batch requires at least one frame")
        merged_response = dict(latest_response)
        if latest_confirmed_response is not None:
            merged_response["status"] = "confirmed"
            merged_response["result"] = latest_confirmed_response.get("result")
            merged_response["sentence"] = latest_confirmed_response.get("sentence")
            merged_response["last_confirmed"] = latest_confirmed_response.get("last_confirmed")
            merged_response["partial_candidates"] = None
        merged_response["debug"] = {"frame_results": frame_results} if include_debug else None
        return merged_response

    def _response(
        self,
        session_id: str,
        state: SessionState,
        decision: dict[str, Any],
        top_candidates: list[dict[str, Any]],
        debug_spans: list[dict[str, Any]],
        include_debug: bool,
        rerank_debug: dict[str, Any] | None = None,
        primitive_top_candidates: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        result = None
        partial_candidates = None
        sentence_payload = None
        if decision["status"] == "confirmed" and decision["selected"]:
            selected = decision["selected"]
            result = {
                "id": selected["id"],
                "word_base": selected["word_base"],
                "confidence": selected["score"],
                "start_ts": selected["start_ts"],
                "end_ts": selected["end_ts"],
            }
            if self.sentence_composer is not None:
                alternatives = [
                    {"id": item["id"], "word_base": item["word_base"], "score": item["score"]}
                    for item in top_candidates
                    if item["id"] != selected["id"]
                ]
                sentence_state = self.sentence_composer.add_confirmed(session_id, result, alternatives[:5])
                sentence_payload = {
                    "text": sentence_state.last_sentence or "",
                    "status": sentence_state.last_sentence_status,
                    "confirmed_words": [word.word_base for word in sentence_state.confirmed_words],
                    "source": "llm" if sentence_state.last_sentence_status == "draft" else sentence_state.last_sentence_status,
                }
        elif decision["status"] == "pending":
            partial_candidates = self._public_candidates(top_candidates[:3], pending=True)
        response = {
            "ok": True,
            "status": decision["status"],
            "session_id": session_id,
            "buffer_frames": len(state.frames),
            "result": result,
            "partial_candidates": partial_candidates,
            "sentence": sentence_payload,
            "last_confirmed": self._last_confirmed_summary(session_id),
            "debug": None,
        }
        if include_debug:
            primitive_debug = self._public_candidates((primitive_top_candidates or [])[:5], debug=True)
            reranked_debug = self._public_candidates(top_candidates[:5], debug=True)
            response["debug"] = {
                "method": "primitive_stream_alignment_v1",
                "tested_spans": len(debug_spans),
                "spans": debug_spans,
                "decision": state.last_decision,
                "pending_analysis": build_pending_analysis(state.frames, state.last_decision, state.last_top_candidates, state.suppressed_candidates),
                "buffer_summary": build_buffer_summary(state.frames),
                "rerank": rerank_debug or {},
                "primitive_top_candidates": enrich_candidates(primitive_debug, state.suppressed_candidates),
                "reranked_top_candidates": enrich_candidates(reranked_debug, state.suppressed_candidates),
                "sentence": response["sentence"],
            }
        return response

    def _last_confirmed_summary(self, session_id: str) -> dict[str, Any] | None:
        if self.sentence_composer is None:
            return None
        state = self.sentence_composer.get(session_id)
        if not state.confirmed_words:
            return None
        last_word = state.confirmed_words[-1]
        return {
            "word_base": last_word.word_base,
            "sentence": state.last_sentence or "",
            "timestamp": state.updated_at,
        }

    def _public_candidates(
        self,
        candidates: list[dict[str, Any]],
        pending: bool = False,
        debug: bool = False,
    ) -> list[dict[str, Any]]:
        public = []
        for item in candidates:
            value = {
                "id": item["id"],
                "word_base": item["word_base"],
                "score": item["score"],
                "start_ts": item["start_ts"],
                "end_ts": item["end_ts"],
                "primitive_score": item.get("primitive_score", item.get("score")),
                "rag_score": item.get("rag_score"),
                "final_score": item.get("final_score", item.get("score")),
                "rerank_applied": item.get("rerank_applied", False),
            }
            if pending or item.get("reason_pending"):
                value["reason_pending"] = item.get("reason_pending", ["awaiting_confirmation"])
            if debug:
                value["step_alignment"] = item.get("step_alignment", [])
                value["score_breakdown"] = item.get("score_breakdown", {})
                value["span_summary"] = item.get("span_summary", {})
                value["wide_conflicts"] = item.get("wide_conflicts", [])
                value["conflict_count"] = item.get("conflict_count", 0)
            public.append(value)
        return public

