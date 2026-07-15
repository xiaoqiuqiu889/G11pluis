from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "server"))

from llm_runtime import _TaskAwareGameplayMockProvider, build_default_runtime, reset_default_runtime  # noqa: E402
from model import Message, MessageRole, SchemaValidator  # noqa: E402


def _complete(provider: _TaskAwareGameplayMockProvider, payload: dict) -> dict:
    result = provider.complete(
        model="mock-model",
        messages=[Message(role=MessageRole.USER, content=json.dumps(payload))],
        temperature=0.3, max_output_tokens=400, timeout_ms=4000,
    )
    return json.loads(result.content)


def test_director_payload_uses_first_allowed_beat_and_validates() -> None:
    payload = _complete(_TaskAwareGameplayMockProvider(), {
        "sceneId": "photo_lab_2008",
        "allowedBeats": ["beat_divide_photos", "beat_darkroom_door"],
        "forbiddenReveals": ["future_reunion"],
        "actionType": "give",
    })
    assert payload["proposedBeat"] == "beat_divide_photos"
    assert SchemaValidator().validate(schema_name="director_beat", payload=payload).ok


def test_action_payload_returns_schema_valid_npc_proposal() -> None:
    payload = _complete(_TaskAwareGameplayMockProvider(), {
        "actionType": "question", "targetId": "arash", "utterance": "涓轰粈涔堬紵",
    })
    assert payload["targetId"] == "arash"
    assert SchemaValidator().validate(schema_name="npc_proposal", payload=payload).ok


def test_default_runtime_injects_task_aware_mock_into_gateway(monkeypatch) -> None:
    monkeypatch.setenv("G1N_USE_MOCK", "1")
    reset_default_runtime()
    runtime = build_default_runtime()
    try:
        assert isinstance(runtime.gateway._providers["mock"], _TaskAwareGameplayMockProvider)
    finally:
        reset_default_runtime()
