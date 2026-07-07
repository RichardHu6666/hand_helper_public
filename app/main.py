from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.debug_builder import build_session_debug
from app.matcher import METHOD, match_primitive, primitive_to_text
from app.schemas import (
    HealthResponse,
    PrimitiveMatchRequest,
    PrimitiveMatchResponse,
    SegmentMatchResult,
    SegmentsMatchRequest,
    SegmentsMatchResponse,
    StreamFrameRequest,
    StreamFrameResponse,
    StreamFramesRequest,
)
from app.embedding_store import EmbeddingStore
from app.rag_reranker import RAGReranker
from app.runtime_config import CONFIG
from app.sentence_composer import SentenceComposer, state_payload
from app.storage import init_db, lite_vocab_status, load_lite_vocab, vocab_size
from app.stream_decoder import StreamDecoder
from app.stream_models import StreamFrame


embedding_store = EmbeddingStore()
sentence_composer = SentenceComposer()
stream_decoder = StreamDecoder(reranker=RAGReranker(embedding_store), sentence_composer=sentence_composer)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    load_lite_vocab()
    if CONFIG.enable_rag_rerank:
        embedding_store.load()
    yield


app = FastAPI(title="sign_cloud_v1", version="0.2.0-stream", lifespan=lifespan)


@app.get("/", response_model=HealthResponse)
def root() -> HealthResponse:
    return health()


def _debug_payload(top_k: int) -> dict:
    return {
        "method": METHOD,
        "top_k": top_k,
        "vocab_size": vocab_size(),
    }


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    status = lite_vocab_status()
    return HealthResponse(
        ok=True,
        service="sign_cloud_v1",
        version="0.2.0-stream",
        vocab_size=vocab_size(),
        vocab=status,
        sessions={"active": stream_decoder.store.active_count()},
        embedding=embedding_store.status(CONFIG.enable_rag_rerank),
        llm=sentence_composer.status(),
    )


@app.post("/api/v1/match/primitive", response_model=PrimitiveMatchResponse)
def match_single(request: PrimitiveMatchRequest) -> PrimitiveMatchResponse:
    query_text = primitive_to_text(request.primitive)
    return PrimitiveMatchResponse(
        ok=True,
        query_text=query_text,
        candidates=match_primitive(request.primitive, request.top_k),
        debug=_debug_payload(request.top_k) if request.debug else None,
    )


@app.post("/api/v1/match/segments", response_model=SegmentsMatchResponse)
def match_segments(request: SegmentsMatchRequest) -> SegmentsMatchResponse:
    results = [
        SegmentMatchResult(
            segment_index=index,
            query_text=primitive_to_text(segment),
            candidates=match_primitive(segment, request.top_k),
        )
        for index, segment in enumerate(request.segments)
    ]
    return SegmentsMatchResponse(
        ok=True,
        results=results,
        debug=_debug_payload(request.top_k) if request.debug else None,
    )


@app.post("/api/v1/stream/frame", response_model=StreamFrameResponse)
def stream_frame(request: StreamFrameRequest) -> dict:
    frame = StreamFrame.from_request(request)
    return stream_decoder.decode(frame, include_debug=request.debug)


@app.post("/api/v1/stream/frames", response_model=StreamFrameResponse)
def stream_frames(request: StreamFramesRequest) -> dict:
    frames = [StreamFrame.from_request(item, session_id=request.session_id) for item in request.frames]
    return stream_decoder.decode_batch(frames, include_debug=request.debug)


@app.get("/api/v1/debug/session/{session_id}")
def debug_session(session_id: str) -> dict:
    return build_session_debug(session_id, stream_decoder.store.get(session_id))


@app.post("/api/v1/debug/reset/{session_id}")
def reset_session(session_id: str) -> dict:
    stream_decoder.reset(session_id)
    return {"ok": True, "session_id": session_id, "reset": True}


@app.get("/api/v1/sentence/{session_id}")
def get_sentence(session_id: str) -> dict:
    return state_payload(session_id, sentence_composer.get(session_id))


@app.post("/api/v1/sentence/reset/{session_id}")
def reset_sentence(session_id: str) -> dict:
    sentence_composer.reset(session_id)
    return {"ok": True, "session_id": session_id, "reset": True}

@app.websocket("/ws/ping")
async def websocket_ping(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_text(message)
    except WebSocketDisconnect:
        return

