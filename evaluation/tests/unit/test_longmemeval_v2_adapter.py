# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from powercontext_eval.benchmarks.longmemeval_v2.adapter import (
    AUDIT_SCHEMA,
    PowerContextHTTPRuntime,
    PowerContextMemory,
    PowerContextMemoryAdapterError,
)


class FakeRuntime:
    def __init__(self) -> None:
        self.captures: list[dict[str, object]] = []
        self.memories: list[dict[str, object]] = []
        self.searches: list[dict[str, object]] = []

    def capture_content_source(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        request = dict(payload)
        self.captures.append(request)
        return {
            "status": "accepted",
            "source": {"name": "content", "source_id": request["source_id"]},
            "position": len(self.captures),
        }

    def remember_memory(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        request = dict(payload)
        self.memories.append(request)
        index = len(self.memories)
        return {
            "memory": {"family": "memory", "artifact_id": "memory", "revision": index},
            "entry": {
                "citation": {
                    "memory_ref": {"family": "memory", "artifact_id": "memory", "revision": index},
                    "entry_id": f"entry-{index}",
                    "entry_version_id": f"entry-{index}-v1",
                }
            },
        }

    def search_memory(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        self.searches.append(dict(payload))
        return {
            "hits": [
                {
                    "text": "Use the Network assignment group.",
                    "score": 0.9,
                    "matched_by": ["fts"],
                    "citation": {
                        "memory_ref": {"family": "memory", "artifact_id": "memory", "revision": 2},
                        "entry_id": "entry-2",
                        "entry_version_id": "entry-2-v1",
                    },
                }
            ]
        }


class GuardedTrajectory(dict[str, object]):
    def get(self, key: object, default: object = None) -> object:
        if key in {"question_type", "answer", "gold_answer", "judge", "scorer"}:
            raise AssertionError(f"adapter accessed forbidden field {key}")
        return super().get(key, default)


def adapter(tmp_path: Path, runtime: FakeRuntime, **params: object) -> PowerContextMemory:
    memory = PowerContextMemory(
        {
            "scope_id": "benchmark-run",
            "audit_path": str(tmp_path / "adapter-audit.jsonl"),
            **params,
        }
    )
    memory.configure_runtime(runtime=runtime)
    return memory


def trajectory() -> GuardedTrajectory:
    return GuardedTrajectory(
        {
            "id": "trajectory-1",
            "domain": "enterprise",
            "environment": "workarena",
            "goal": "Assign an incident.",
            "outcome": "success",
            "start_url": "https://example.test/start",
            "states": [
                {
                    "state_index": 0,
                    "step": 0,
                    "url": "https://example.test/start",
                    "action": None,
                    "thought": "Find the incident.",
                    "accessibility_tree": "Incident list " + "记忆" * 500,
                    "screenshot": "screenshots/trajectory-1/0.png",
                }
            ],
            "question_type": "must not be read",
            "gold_answer": "must not be read",
            "judge": {"must": "not be read"},
        }
    )


def audit_events(tmp_path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (tmp_path / "adapter-audit.jsonl").read_text(encoding="utf-8").splitlines()]


def test_insert_uses_public_source_and_memory_operations_with_utf8_safe_chunks(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    memory = adapter(tmp_path, runtime, source_chunk_bytes=512)

    memory.insert(trajectory())

    assert len(runtime.captures) == len(runtime.memories) > 1
    assert all(request["scope_id"] == "benchmark-run" for request in runtime.captures)
    assert all(len(str(request["content"]).encode()) <= 512 for request in runtime.captures)
    assert [request["content"] for request in runtime.captures] == [request["text"] for request in runtime.memories]
    restored = "".join(str(request["content"]) for request in runtime.captures)
    projected = json.loads(restored)
    assert set(projected) == {"id", "domain", "environment", "goal", "outcome", "start_url", "states"}
    assert "question_type" not in restored
    assert "gold_answer" not in restored

    [event] = audit_events(tmp_path)
    assert event["schema"] == AUDIT_SCHEMA
    assert event["operation"] == "ingest"
    assert event["status"] == "succeeded"
    assert event["scope_id"] == "benchmark-run"
    assert isinstance(event["observed_at"], str)
    assert event["chunk_count"] == len(runtime.captures)
    assert len(event["citations"]) == len(runtime.captures)
    assert set(event["timings_ms"]) == {"source_capture", "memory_remember", "total"}


def test_query_returns_upstream_text_items_and_records_citations(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    memory = adapter(tmp_path, runtime, search_mode="fts", search_limit=4)
    memory.set_query_context(query_invocation_id="query-7")

    result = memory.query("Which assignment group should I use?", "question.png")

    assert result == [{"type": "text", "value": "Use the Network assignment group."}]
    assert runtime.searches == [
        {
            "scope_id": "benchmark-run",
            "query": "Which assignment group should I use?",
            "limit": 4,
            "mode": "fts",
        }
    ]
    [event] = audit_events(tmp_path)
    assert event["query_invocation_id"] == "query-7"
    assert event["query_image_present"] is True
    assert event["result_count"] == 1
    assert event["citations"][0]["entry_id"] == "entry-2"
    assert "question.png" not in json.dumps(event)
    assert set(event["timings_ms"]) == {"search", "format", "total"}


def test_failed_query_is_audited_without_question_or_image_content(tmp_path: Path) -> None:
    class FailingRuntime(FakeRuntime):
        def search_memory(self, payload: Mapping[str, object]) -> Mapping[str, object]:
            raise PowerContextMemoryAdapterError("unavailable")

    memory = adapter(tmp_path, FailingRuntime())

    with pytest.raises(PowerContextMemoryAdapterError, match="unavailable"):
        memory.query("secret-looking benchmark question", "private/image.png")

    [event] = audit_events(tmp_path)
    assert event["status"] == "failed"
    assert event["failure_type"] == "PowerContextMemoryAdapterError"
    serialized = json.dumps(event)
    assert "secret-looking" not in serialized
    assert "private/image.png" not in serialized


def test_duplicate_insert_fails_closed_and_records_the_attempt(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    memory = adapter(tmp_path, runtime)
    memory.insert(trajectory())

    with pytest.raises(PowerContextMemoryAdapterError, match="duplicate trajectory"):
        memory.insert(trajectory())

    events = audit_events(tmp_path)
    assert [event["status"] for event in events] == ["succeeded", "failed"]
    assert len(runtime.captures) == 1


def test_partial_ingest_failure_preserves_completed_chunk_citations(tmp_path: Path) -> None:
    class PartiallyFailingRuntime(FakeRuntime):
        def remember_memory(self, payload: Mapping[str, object]) -> Mapping[str, object]:
            if len(self.memories) == 1:
                raise PowerContextMemoryAdapterError("memory unavailable")
            return super().remember_memory(payload)

    runtime = PartiallyFailingRuntime()
    memory = adapter(tmp_path, runtime, source_chunk_bytes=512)

    with pytest.raises(PowerContextMemoryAdapterError, match="memory unavailable"):
        memory.insert(trajectory())

    [event] = audit_events(tmp_path)
    assert event["status"] == "failed"
    assert len(event["citations"]) == 1
    assert len(runtime.captures) == 2


def test_http_runtime_rejects_credentials_and_plaintext_remote_hosts() -> None:
    with pytest.raises(PowerContextMemoryAdapterError, match="credentials"):
        PowerContextHTTPRuntime("https://token@example.test", token=None, timeout_seconds=1)
    with pytest.raises(PowerContextMemoryAdapterError, match="unencrypted non-loopback"):
        PowerContextHTTPRuntime("http://example.test", token=None, timeout_seconds=1)

    PowerContextHTTPRuntime("http://127.0.0.1:8765", token=None, timeout_seconds=1)
