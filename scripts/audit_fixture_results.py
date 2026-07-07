#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.embedding_store import EmbeddingStore
from app.rag_reranker import RAGReranker
from app.schemas import StreamFrameRequest
from app.sentence_composer import SentenceComposer
from app.storage import lite_vocab_entries, load_lite_vocab
from app.stream_decoder import StreamDecoder
from app.stream_models import StreamFrame


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = [
    PROJECT_ROOT / "tests/fixtures/stream_left_right_single.jsonl",
    PROJECT_ROOT / "tests/fixtures/stream_up_down_single.jsonl",
    PROJECT_ROOT / "tests/fixtures/stream_toward_away_single.jsonl",
    PROJECT_ROOT / "tests/fixtures/stream_dual_hand.jsonl",
    PROJECT_ROOT / "tests/fixtures/stream_noisy_shape.jsonl",
    PROJECT_ROOT / "tests/fixtures/stream_repeat_same_word.jsonl",
]
BREAKDOWN_FIELDS = [
    "step_alignment_score",
    "span_stability_score",
    "duration_score",
    "boundary_quality_score",
    "unknown_penalty",
    "conflict_penalty",
    "overlap_penalty",
]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    frames = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        if "primitive" not in item:
            item = {"primitive": item}
        frames.append(item)
    return frames


def vocab_by_id() -> dict[int, Any]:
    load_lite_vocab()
    return {entry.id: entry for entry in lite_vocab_entries()}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def flatten_step_alignment(candidate: dict[str, Any]) -> dict[str, Any]:
    matched: set[str] = set()
    conflicts: set[str] = set()
    unknown_frames = 0
    for item in as_list(candidate.get("step_alignment")):
        matched.update(as_list(item.get("matched_fields")))
        conflicts.update(as_list(item.get("conflict_fields")))
        unknown_frames += int(item.get("unknown_frames") or 0)
    return {
        "matched_fields": sorted(matched),
        "conflict_fields": sorted(conflicts),
        "unknown_frames": unknown_frames,
    }


def extract_candidates_from_response(response: dict[str, Any], top_k: int) -> tuple[list[dict[str, Any]], list[str]]:
    missing: list[str] = []
    candidates: list[dict[str, Any]] = []
    debug = response.get("debug") or {}
    spans = as_list(debug.get("spans"))
    if spans:
        for span in spans:
            candidates.extend(as_list(span.get("top_candidates")))
    elif response.get("partial_candidates"):
        candidates.extend(as_list(response.get("partial_candidates")))
        missing.append("debug.spans")
    elif response.get("result"):
        candidates.append(response["result"])
        missing.append("debug.spans")
    else:
        missing.append("top_candidates")
    candidates.sort(key=lambda item: (-(item.get("score") or item.get("confidence") or 0.0), item.get("id") or 0))
    deduped: list[dict[str, Any]] = []
    seen: set[int] = set()
    for candidate in candidates:
        candidate_id = candidate.get("id")
        if candidate_id is None or candidate_id in seen:
            continue
        seen.add(candidate_id)
        deduped.append(candidate)
        if len(deduped) >= top_k:
            break
    return deduped, missing


def normalize_candidate(candidate: dict[str, Any], rank: int, margin: float | None, vocab: dict[int, Any]) -> dict[str, Any]:
    candidate_id = candidate.get("id")
    entry = vocab.get(candidate_id) if isinstance(candidate_id, int) else None
    breakdown = candidate.get("score_breakdown") or {}
    alignment = flatten_step_alignment(candidate)
    score = candidate.get("score", candidate.get("confidence"))
    result = {
        "rank": rank,
        "id": candidate_id,
        "word_base": candidate.get("word_base"),
        "score": score,
        "primitive_score": candidate.get("primitive_score"),
        "rag_score": candidate.get("rag_score"),
        "final_score": candidate.get("final_score", score),
        "rerank_applied": candidate.get("rerank_applied"),
        "top_margin": margin,
        "score_breakdown": breakdown,
        "step_alignment_score": breakdown.get("step_alignment_score"),
        "span_stability_score": breakdown.get("span_stability_score"),
        "duration_score": breakdown.get("duration_score"),
        "boundary_quality_score": breakdown.get("boundary_quality_score"),
        "unknown_penalty": breakdown.get("unknown_penalty"),
        "conflict_penalty": breakdown.get("conflict_penalty"),
        "overlap_penalty": breakdown.get("overlap_penalty"),
        "ambiguity_penalty": breakdown.get("ambiguity_penalty"),
        "matched_fields": alignment["matched_fields"],
        "conflict_fields": alignment["conflict_fields"],
        "unknown_frames": alignment["unknown_frames"],
        "start_ts": candidate.get("start_ts"),
        "end_ts": candidate.get("end_ts"),
        "primitive_text": entry.primitive_text if entry else None,
        "action_description": entry.action_description if entry else None,
        "main_reason": None,
    }
    if rank == 1:
        result["main_reason"] = "top_score_candidate"
    return result


def status_reason(response: dict[str, Any]) -> list[str]:
    debug = response.get("debug") or {}
    decision = debug.get("decision") or {}
    reasons = as_list(decision.get("reason"))
    if reasons:
        return [str(item) for item in reasons]
    if response.get("status") == "pending" and response.get("partial_candidates"):
        return as_list(response["partial_candidates"][0].get("reason_pending"))
    if response.get("status") == "confirmed":
        return ["confirmed"]
    return []


def trace_entry(index: int, response: dict[str, Any]) -> dict[str, Any]:
    top = None
    candidates, missing = extract_candidates_from_response(response, 1)
    if candidates:
        top = {
            "id": candidates[0].get("id"),
            "word_base": candidates[0].get("word_base"),
            "score": candidates[0].get("score", candidates[0].get("confidence")),
        }
    result = response.get("result") or {}
    return {
        "frame": index,
        "status": response.get("status"),
        "reason": status_reason(response),
        "top": top,
        "confirmed_word": result.get("word_base"),
        "confirmed_score": result.get("confidence"),
        "extraction_missing": missing,
    }


def run_fixture(path: Path, top_k: int = 5, include_debug: bool = True) -> dict[str, Any]:
    frames = load_jsonl(path)
    embedding_store = EmbeddingStore()
    embedding_store.load()
    decoder = StreamDecoder(reranker=RAGReranker(embedding_store), sentence_composer=SentenceComposer())
    responses: list[dict[str, Any]] = []
    for item in frames:
        request = StreamFrameRequest(
            session_id=item.get("session_id") or path.stem,
            timestamp=item["timestamp"],
            primitive=item["primitive"],
            debug=include_debug,
        )
        responses.append(decoder.decode(StreamFrame.from_request(request), include_debug=True))
    confirmed_words = [
        response["result"]["word_base"]
        for response in responses
        if response.get("status") == "confirmed" and response.get("result")
    ]
    first_pending = next((idx for idx, item in enumerate(responses, start=1) if item.get("status") == "pending"), None)
    first_confirmed = next((idx for idx, item in enumerate(responses, start=1) if item.get("status") == "confirmed"), None)
    final_response = responses[-1] if responses else {}
    raw_candidates, missing = extract_candidates_from_response(final_response, top_k)
    debug = final_response.get("debug") or {}
    primitive_debug_candidates = debug.get("primitive_top_candidates") or []
    reranked_debug_candidates = debug.get("reranked_top_candidates") or []
    vocab = vocab_by_id()
    normalized_candidates = []
    for idx, candidate in enumerate(raw_candidates, start=1):
        next_score = raw_candidates[idx].get("score") if idx < len(raw_candidates) else None
        score = candidate.get("score", candidate.get("confidence"))
        margin = round(score - next_score, 4) if isinstance(score, (int, float)) and isinstance(next_score, (int, float)) else None
        normalized_candidates.append(normalize_candidate(candidate, idx, margin, vocab))
    pending_top_word = None
    if final_response.get("status") == "pending" and final_response.get("partial_candidates"):
        pending_top_word = final_response["partial_candidates"][0].get("word_base")
    elif normalized_candidates:
        pending_top_word = normalized_candidates[0].get("word_base")
    decision = (final_response.get("debug") or {}).get("decision") or {}
    return {
        "name": path.name,
        "path": str(path),
        "frame_count": len(frames),
        "final_status": final_response.get("status"),
        "confirmed_count": len(confirmed_words),
        "confirmed_words": confirmed_words,
        "pending_top_word": pending_top_word,
        "repeated_confirmed_suppressed": len(confirmed_words) == len(set(confirmed_words)),
        "first_pending_frame": first_pending,
        "first_confirmed_frame": first_confirmed,
        "final_top_candidates": normalized_candidates,
        "primitive_top5": [normalize_candidate(candidate, idx, None, vocab) for idx, candidate in enumerate(primitive_debug_candidates[:top_k], start=1)],
        "reranked_top5": [normalize_candidate(candidate, idx, None, vocab) for idx, candidate in enumerate(reranked_debug_candidates[:top_k], start=1)],
        "rank_changed": (debug.get("rerank") or {}).get("rank_changed"),
        "decision_reason": status_reason(final_response),
        "decision": decision,
        "decision_trace": [trace_entry(idx, response) for idx, response in enumerate(responses, start=1)],
        "extraction_missing": missing,
    }


def run_audit(fixtures: list[Path] | None = None, top_k: int = 5, include_debug: bool = True) -> dict[str, Any]:
    selected = fixtures or DEFAULT_FIXTURES
    return {"fixtures": [run_fixture(path, top_k=top_k, include_debug=include_debug) for path in selected]}


def md_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value).replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Fixture Audit Report", "", "## Summary Table", ""]
    lines.append("| fixture | frames | final_status | confirmed_count | confirmed_words | pending_top | first_pending_frame | first_confirmed_frame | repeated_suppressed |")
    lines.append("|---|---:|---|---:|---|---|---:|---:|---|")
    for item in report["fixtures"]:
        lines.append(
            f"| {item['name']} | {item['frame_count']} | {item['final_status']} | {item['confirmed_count']} | "
            f"{md_value(item['confirmed_words'])} | {md_value(item['pending_top_word'])} | "
            f"{md_value(item['first_pending_frame'])} | {md_value(item['first_confirmed_frame'])} | "
            f"{str(item['repeated_confirmed_suppressed']).lower()} |"
        )
    lines.extend(["", "## Per Fixture Detail", ""])
    for item in report["fixtures"]:
        lines.extend([
            f"### {item['name']}",
            "",
            f"- Final status: {md_value(item['final_status'])}",
            f"- Confirmed: {item['confirmed_count']} {md_value(item['confirmed_words'])}",
            f"- Pending top: {md_value(item['pending_top_word'])}",
            f"- First pending frame: {md_value(item['first_pending_frame'])}",
            f"- First confirmed frame: {md_value(item['first_confirmed_frame'])}",
            f"- Suppression: repeated_confirmed_suppressed={str(item['repeated_confirmed_suppressed']).lower()}",
            f"- Notes: decision_reason={md_value(item['decision_reason'])}; extraction_missing={md_value(item['extraction_missing'])}",
            "",
            "#### Top Candidates",
            "",
            "| rank | id | word_base | score | align | stability | duration | boundary | unknown_penalty | conflict_penalty | ambiguity_penalty | overlap_penalty |",
            "|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for candidate in item["final_top_candidates"]:
            lines.append(
                f"| {candidate['rank']} | {candidate['id']} | {candidate['word_base']} | {md_value(candidate['score'])} | "
                f"{md_value(candidate['step_alignment_score'])} | {md_value(candidate['span_stability_score'])} | "
                f"{md_value(candidate['duration_score'])} | {md_value(candidate['boundary_quality_score'])} | "
                f"{md_value(candidate['unknown_penalty'])} | {md_value(candidate['conflict_penalty'])} | {md_value(candidate.get('ambiguity_penalty'))} | {md_value(candidate['overlap_penalty'])} |"
            )
        lines.extend(["", f"- rank_changed: {item.get('rank_changed')}", f"- primitive_top5: {md_value([c.get('word_base') for c in item.get('primitive_top5', [])])}", f"- reranked_top5: {md_value([c.get('word_base') for c in item.get('reranked_top5', [])])}", "", "#### Candidate Details", ""])
        for candidate in item["final_top_candidates"]:
            lines.extend([
                f"##### {candidate['rank']}. {candidate['word_base']} ({candidate['id']})",
                "",
                f"- primitive_text: {md_value(candidate['primitive_text'])}",
                f"- action_description: {md_value(candidate['action_description'])}",
                f"- matched_fields: {md_value(candidate['matched_fields'])}",
                f"- conflict_fields: {md_value(candidate['conflict_fields'])}",
                f"- unknown_frames: {candidate['unknown_frames']}",
                f"- score_breakdown: `{json.dumps(candidate['score_breakdown'], ensure_ascii=False, sort_keys=True)}`",
                f"- main_reason: {md_value(candidate['main_reason'])}",
                "",
            ])
        lines.extend(["#### Decision Trace", ""])
        for trace in item["decision_trace"]:
            if trace.get("status") == "confirmed":
                detail = f"word={trace.get('confirmed_word')}, score={trace.get('confirmed_score')}"
            elif trace.get("top"):
                top = trace["top"]
                detail = f"top={top.get('word_base')}, score={top.get('score')}"
            else:
                detail = ""
            lines.append(f"- frame {trace['frame']:03d}: {trace.get('status')}, {detail}, reason={md_value(trace.get('reason'))}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_report(report: dict[str, Any], output_md: Path, output_json: Path) -> None:
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output-md", default="reports/fixture_audit.md")
    parser.add_argument("--output-json", default="reports/fixture_audit.json")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    fixtures = [PROJECT_ROOT / args.fixture] if args.fixture else DEFAULT_FIXTURES
    report = run_audit(fixtures=fixtures, top_k=args.top_k, include_debug=True)
    write_report(report, PROJECT_ROOT / args.output_md, PROJECT_ROOT / args.output_json)
    if args.debug:
        for item in report["fixtures"]:
            print(
                f"{item['name']}: frames={item['frame_count']} final={item['final_status']} "
                f"confirmed={item['confirmed_count']} words={item['confirmed_words']} top={item['pending_top_word']}"
            )
        print(f"wrote {args.output_md}")
        print(f"wrote {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

