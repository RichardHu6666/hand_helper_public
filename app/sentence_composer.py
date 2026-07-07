from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.runtime_config import CONFIG


@dataclass
class ConfirmedWord:
    id: int
    word_base: str
    confidence: float
    start_ts: str
    end_ts: str
    alternatives: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SessionSentenceState:
    confirmed_words: list[ConfirmedWord] = field(default_factory=list)
    last_sentence: str | None = None
    last_sentence_status: str = "empty"
    last_llm_raw: dict[str, Any] | None = None
    updated_at: str | None = None


class LLMClient:
    def __init__(self, api_key: str = CONFIG.llm_api_key, base_url: str = CONFIG.llm_base_url, model: str = CONFIG.llm_model, timeout: int = CONFIG.llm_timeout_sec) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def compose(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "浣犳槸鎵嬭鍊欓€夎瘝搴忓垪鐨勫彞瀛愮骇鏁寸悊鍣ㄣ€傚彧鑳戒娇鐢ㄧ粰瀹氬€欓€夎瘝涓殑璇嶏紝涓嶈兘鍙戞槑鏂版牳蹇冭瘝銆傚鏋滃€欓€変笉瓒充互缁勬垚鑷劧鍙ワ紝杈撳嚭灏介噺蹇犲疄鐨勮瘝搴忓垪銆傚鏋滄槑鏄句笉纭畾锛屼繚鐣欏師璇嶆垨杈撳嚭 unknown銆傝繑鍥?JSON锛屼笉瑕?Markdown銆?,
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                "temperature": 0.1,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - configured endpoint
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        parsed["_raw"] = data
        return parsed


class SentenceComposer:
    def __init__(self, enabled: bool = CONFIG.enable_llm_sentence, client: LLMClient | None = None) -> None:
        self.enabled = enabled
        self.client = client or LLMClient()
        self.sessions: dict[str, SessionSentenceState] = {}

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": CONFIG.llm_provider,
            "model": CONFIG.llm_model,
            "configured": self.client.configured,
        }

    def get(self, session_id: str) -> SessionSentenceState:
        return self.sessions.setdefault(session_id, SessionSentenceState())

    def reset(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    def add_confirmed(self, session_id: str, result: dict[str, Any], alternatives: list[dict[str, Any]]) -> SessionSentenceState:
        state = self.get(session_id)
        if not any(word.id == result["id"] and word.start_ts == result["start_ts"] and word.end_ts == result["end_ts"] for word in state.confirmed_words):
            state.confirmed_words.append(
                ConfirmedWord(
                    id=int(result["id"]),
                    word_base=str(result["word_base"]),
                    confidence=float(result["confidence"]),
                    start_ts=str(result["start_ts"]),
                    end_ts=str(result["end_ts"]),
                    alternatives=alternatives,
                )
            )
        return self.compose_state(state)

    def compose_state(self, state: SessionSentenceState) -> SessionSentenceState:
        if not state.confirmed_words:
            state.last_sentence = ""
            state.last_sentence_status = "empty"
            state.updated_at = None
            return state
        if not self.enabled or not self.client.configured:
            return self._fallback(state)
        payload = {
            "confirmed_words": [
                {
                    "word": word.word_base,
                    "confidence": word.confidence,
                    "alternatives": [alt.get("word_base") for alt in word.alternatives],
                }
                for word in state.confirmed_words
            ],
            "task": "compose_sentence",
        }
        try:
            parsed = self.client.compose(payload)
            self._validate_llm_result(parsed, state)
            state.last_sentence = parsed["sentence"]
            state.last_sentence_status = "draft"
            state.last_llm_raw = parsed
            state.updated_at = state.confirmed_words[-1].end_ts
            return state
        except Exception as exc:
            state.last_llm_raw = {"error": str(exc)}
            return self._fallback(state)

    def _fallback(self, state: SessionSentenceState) -> SessionSentenceState:
        state.last_sentence = " ".join(word.word_base for word in sorted(state.confirmed_words, key=lambda item: item.end_ts))
        state.last_sentence_status = "fallback"
        state.updated_at = state.confirmed_words[-1].end_ts if state.confirmed_words else None
        return state

    def _validate_llm_result(self, result: dict[str, Any], state: SessionSentenceState) -> None:
        if not isinstance(result.get("sentence"), str):
            raise ValueError("llm sentence must be string")
        used_words = result.get("used_words")
        if not isinstance(used_words, list):
            raise ValueError("llm used_words must be list")
        allowed = {word.word_base for word in state.confirmed_words}
        for word in state.confirmed_words:
            allowed.update(str(alt.get("word_base")) for alt in word.alternatives if alt.get("word_base"))
        for word in used_words:
            if word not in allowed:
                raise ValueError(f"llm used word outside candidates: {word}")


def state_payload(session_id: str, state: SessionSentenceState) -> dict[str, Any]:
    return {
        "ok": True,
        "session_id": session_id,
        "status": state.last_sentence_status,
        "sentence": state.last_sentence or "",
        "confirmed_words": [
            {
                "id": word.id,
                "word_base": word.word_base,
                "confidence": word.confidence,
                "start_ts": word.start_ts,
                "end_ts": word.end_ts,
                "alternatives": word.alternatives,
            }
            for word in state.confirmed_words
        ],
        "updated_at": state.updated_at,
        "last_llm_raw": state.last_llm_raw,
    }

