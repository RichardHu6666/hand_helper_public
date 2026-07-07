from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


DominantSide = Literal["none", "signer_left", "signer_right"]
Location = Literal[
    "unknown",
    "signer_left",
    "signer_center",
    "signer_right",
    "signer_left_upper",
    "signer_left_lower",
    "signer_right_upper",
    "signer_right_lower",
    "signer_left_middle",
    "signer_center_middle",
    "signer_right_middle",
    "signer_center_upper",
    "signer_center_lower",
]
Movement = Literal[
    "hold",
    "left_right",
    "up_down",
    "toward_away",
    "open_close",
    "repeat",
    "unknown",
]
RelativeMotion = Literal[
    "unknown",
    "hold",
    "left_right",
    "left_to_right",
    "right_to_left",
    "up_down",
    "up_to_down",
    "down_to_up",
    "toward_away",
    "toward",
    "away",
    "open_close",
    "repeat",
]
BimanualRelation = Literal[
    "none",
    "single_hand",
    "dual_hand",
    "same_shape",
    "different_shape",
    "unknown",
]
HandShape = Literal[
    "one",
    "two",
    "three",
    "four",
    "five",
    "like",
    "ok",
    "call",
    "dislike",
    "no_gesture",
    "no_hand",
    "unknown",
]


class Primitive(BaseModel):
    hand_count: Literal[0, 1, 2]
    dominant_side: DominantSide
    location: Location
    movement: Movement
    relative_motion: RelativeMotion | None = None
    bimanual_relation: BimanualRelation
    dominant_shape: HandShape
    nondominant_shape: HandShape
    duration_ms: int | None = Field(default=None, ge=0)
    repeat_count: int | None = Field(default=None, ge=0)


class PrimitiveMatchRequest(BaseModel):
    primitive: Primitive
    top_k: int = Field(default=5, ge=1, le=20)
    debug: bool = False


class SegmentsMatchRequest(BaseModel):
    segments: list[Primitive] = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    debug: bool = False


class Candidate(BaseModel):
    id: int
    word: str
    score: float
    reason: str
    word_description: str
    action_description: str


class PrimitiveMatchResponse(BaseModel):
    ok: bool
    query_text: str
    candidates: list[Candidate]
    debug: dict[str, Any] | None = None


class SegmentMatchResult(BaseModel):
    segment_index: int
    query_text: str
    candidates: list[Candidate]


class SegmentsMatchResponse(BaseModel):
    ok: bool
    results: list[SegmentMatchResult]
    debug: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    ok: bool
    service: str
    version: str
    vocab_size: int | None = None
    vocab: dict[str, Any] | None = None
    sessions: dict[str, Any] | None = None
    embedding: dict[str, Any] | None = None
    llm: dict[str, Any] | None = None


class StreamFrameRequest(BaseModel):
    session_id: str = Field(min_length=1)
    timestamp: str
    primitive: Primitive
    debug: bool = False

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        from app.stream_models import parse_stream_timestamp

        parse_stream_timestamp(value)
        return value


class StreamBatchFrameRequest(BaseModel):
    client_seq: int = Field(ge=0)
    timestamp: str
    primitive: Primitive

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        from app.stream_models import parse_stream_timestamp

        parse_stream_timestamp(value)
        return value


class StreamFramesRequest(BaseModel):
    session_id: str = Field(min_length=1)
    frames: list[StreamBatchFrameRequest] = Field(min_length=1)
    debug: bool = False


class StreamCandidate(BaseModel):
    id: int
    word_base: str
    score: float
    start_ts: str
    end_ts: str
    reason_pending: list[str] | None = None


class StreamResult(BaseModel):
    id: int
    word_base: str
    confidence: float
    start_ts: str
    end_ts: str


class LastConfirmedSummary(BaseModel):
    word_base: str
    sentence: str
    timestamp: str | None = None


class StreamFrameResponse(BaseModel):
    ok: bool
    status: Literal["collecting", "pending", "confirmed"]
    session_id: str
    buffer_frames: int
    result: StreamResult | None = None
    partial_candidates: list[StreamCandidate] | None = None
    sentence: dict[str, Any] | None = None
    last_confirmed: LastConfirmedSummary | None = None
    debug: dict[str, Any] | None = None

