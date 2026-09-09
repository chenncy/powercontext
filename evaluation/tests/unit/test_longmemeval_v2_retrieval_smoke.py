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

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

from powercontext_eval.benchmarks.longmemeval_v2 import retrieval_smoke
from powercontext_eval.benchmarks.longmemeval_v2.retrieval_smoke import RetrievalSmokeError, run_retrieval_smoke
from powercontext_eval.benchmarks.longmemeval_v2.smoke import PreparedSmokeRun


class FakeRetrievalRuntime:
    def __init__(self, *, fail_scope: str | None = None) -> None:
        self.fail_scope = fail_scope
        self.scopes: list[dict[str, object]] = []
        self.captures: list[dict[str, object]] = []
        self.memories: list[dict[str, object]] = []
        self.searches: list[dict[str, object]] = []
        self.text_by_scope: dict[str, list[str]] = {}

    def get_readiness(self) -> Mapping[str, object]:
        return {"status": "ready"}

    def get_capabilities(self) -> Mapping[str, object]:
        return {
            "search_modes": ["auto", "fts"],
            "source_types": ["content"],
            "artifact_families": ["memory"],
        }

    def create_scope(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        self.scopes.append(dict(payload))
        return {"scope_id": f"scope-{len(self.scopes)}"}

    def capture_content_source(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        request = dict(payload)
        self.captures.append(request)
        return {"source": {"name": "content", "source_id": request["source_id"]}}

    def remember_memory(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        request = dict(payload)
        if request["scope_id"] == self.fail_scope:
            raise RuntimeError("selected group failed")
        self.memories.append(request)
        scope_id = str(request["scope_id"])
        self.text_by_scope.setdefault(scope_id, []).append(str(request["text"]))
        index = len(self.memories)
        return {
            "entry": {
                "citation": {
                    "memory_ref": {"family": "memory", "artifact_id": "memory", "revision": index},
                    "entry_id": f"entry-{index}",
                    "entry_version_id": f"entry-{index}-v1",
                }
            }
        }

    def search_memory(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        request = dict(payload)
        self.searches.append(request)
        scope_id = str(request["scope_id"])
        text = self.text_by_scope[scope_id][0]
        return {
            "hits": [
                {
                    "text": text,
                    "citation": {
                        "memory_ref": {"family": "memory", "artifact_id": "memory", "revision": 1},
                        "entry_id": f"hit-{scope_id}",
                        "entry_version_id": f"hit-{scope_id}-v1",
                    },
                }
            ]
        }


def write_inputs(tmp_path: Path, *, shared_haystack: bool = False) -> tuple[Path, Path]:
    data_root = tmp_path / "data"
    (data_root / "haystacks").mkdir(parents=True)
    smoke_manifest = tmp_path / "smoke.json"
    smoke_manifest.write_text(
        json.dumps(
            {
                "schema": "powercontext.longmemeval-v2-smoke.v1",
                "tier": "small",
                "cases": [
                    {"question_id": "question-a", "ability": "static_state"},
                    {"question_id": "question-b", "ability": "workflow_knowledge"},
                ],
            }
        ),
        encoding="utf-8",
    )
    with (data_root / "questions.jsonl").open("w", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "id": "question-a",
                    "domain": "enterprise",
                    "question": "Where is enterprise evidence?",
                    "question_type": "must-not-be-copied",
                    "answer": "GOLD-MUST-NOT-LEAK",
                }
            )
            + "\n"
        )
        stream.write(
            json.dumps(
                {
                    "id": "question-b",
                    "domain": "web",
                    "question": "Where is web evidence?",
                    "question_type": "must-not-be-copied",
                    "answer": "GOLD-MUST-NOT-LEAK",
                }
            )
            + "\n"
        )
    with (data_root / "trajectories.jsonl").open("w", encoding="utf-8") as stream:
        for trajectory_id, domain, evidence in (
            ("trajectory-a", "enterprise", "enterprise-only-evidence"),
            ("decoy", "web", "decoy-evidence"),
            ("trajectory-b", "web", "web-only-evidence"),
        ):
            stream.write(
                json.dumps(
                    {
                        "id": trajectory_id,
                        "domain": domain,
                        "environment": "test",
                        "goal": evidence,
                        "outcome": "success",
                        "start_url": "https://example.test",
                        "states": [
                            {
                                "url": "https://example.test",
                                "action": evidence,
                                "thought": evidence,
                                "accessibility_tree": evidence,
                                "screenshot": "unused.png",
                            }
                        ],
                        "gold_answer": "GOLD-MUST-NOT-LEAK",
                        "judge": {"secret": "GOLD-MUST-NOT-LEAK"},
                    }
                )
                + "\n"
            )
    second = ["trajectory-a"] if shared_haystack else ["trajectory-b"]
    (data_root / "haystacks" / "lme_v2_small.json").write_text(
        json.dumps({"question-a": ["trajectory-a"], "question-b": second}),
        encoding="utf-8",
    )
    return data_root, smoke_manifest


def fake_preflight(**kwargs: object) -> PreparedSmokeRun:
    output_dir = kwargs["output_dir"]
    assert isinstance(output_dir, Path)
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = output_dir / "manifest.json"
    subset = output_dir / "subset.json"
    manifest.write_text("{}\n", encoding="utf-8")
    subset.write_text("{}\n", encoding="utf-8")
    return PreparedSmokeRun(output_dir=output_dir, manifest_path=manifest, subset_path=subset)


def run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime: FakeRetrievalRuntime, *, shared: bool = False
) -> Path:
    data_root, smoke_manifest = write_inputs(tmp_path, shared_haystack=shared)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(retrieval_smoke, "prepare_smoke_run", fake_preflight)
    digests = {
        "questions.jsonl": hashlib.sha256((data_root / "questions.jsonl").read_bytes()).hexdigest(),
        "trajectories.jsonl": hashlib.sha256((data_root / "trajectories.jsonl").read_bytes()).hexdigest(),
        "haystacks/lme_v2_small.json": hashlib.sha256(
            (data_root / "haystacks" / "lme_v2_small.json").read_bytes()
        ).hexdigest(),
    }
    monkeypatch.setattr(retrieval_smoke, "load_dataset_lock", lambda path: SimpleNamespace(file_digests=digests))
    run_retrieval_smoke(
        data_root=data_root,
        dataset_lock=tmp_path / "dataset-lock.json",
        harness_root=tmp_path / "harness",
        smoke_manifest=smoke_manifest,
        output_dir=output_dir,
        run_id="test-run",
        powercontext_revision="powercontext-sha",
        integration_revision="integration-sha",
        runtime=runtime,
    )
    return output_dir


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_streams_selected_trajectories_into_isolated_haystack_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_read_text = Path.read_text

    def guarded_read_text(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if path.name == "trajectories.jsonl":
            raise AssertionError("trajectories.jsonl must be streamed")
        return original_read_text(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    runtime = FakeRetrievalRuntime()
    output_dir = run(tmp_path, monkeypatch, runtime)

    assert len(runtime.scopes) == 3
    assert runtime.scopes[1]["parent_scope_id"] == "scope-1"
    assert runtime.scopes[2]["parent_scope_id"] == "scope-1"
    assert {request["scope_id"] for request in runtime.captures} == {"scope-2", "scope-3"}
    assert all("decoy-evidence" not in str(request["content"]) for request in runtime.captures)
    results = read_jsonl(output_dir / "retrieval-results.jsonl")
    assert [result["question_id"] for result in results] == ["question-a", "question-b"]
    assert [result["scope_id"] for result in results] == ["scope-2", "scope-3"]
    assert all(result["status"] == "succeeded" for result in results)
    assert "enterprise-only-evidence" in str(results[0]["memory_context"])
    assert "web-only-evidence" in str(results[1]["memory_context"])
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["question_count"] == 2
    assert summary["haystack_count"] == 2
    assert summary["trajectory_count"] == 2
    assert summary["succeeded"] == 2
    assert summary["accuracy"] is None
    assert (output_dir / "failures.jsonl").read_text(encoding="utf-8") == ""
    retained = "".join(path.read_text(encoding="utf-8") for path in output_dir.iterdir() if path.is_file())
    assert "GOLD-MUST-NOT-LEAK" not in retained
    assert "must-not-be-copied" not in retained


def test_reuses_one_child_scope_and_one_ingest_for_an_identical_haystack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = FakeRetrievalRuntime()
    output_dir = run(tmp_path, monkeypatch, runtime, shared=True)

    assert len(runtime.scopes) == 2
    assert len(runtime.captures) == 1
    assert len(runtime.searches) == 2
    results = read_jsonl(output_dir / "retrieval-results.jsonl")
    assert results[0]["scope_id"] == results[1]["scope_id"] == "scope-2"


def test_classifies_one_haystack_ingest_failure_without_stopping_the_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = FakeRetrievalRuntime(fail_scope="scope-2")
    output_dir = run(tmp_path, monkeypatch, runtime)

    results = read_jsonl(output_dir / "retrieval-results.jsonl")
    assert [result["status"] for result in results] == ["failed", "succeeded"]
    [failure] = read_jsonl(output_dir / "failures.jsonl")
    assert failure["phase"] == "ingest"
    assert failure["category"] == "integration"
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["succeeded"] == 1
    assert summary["failed"] == 1


def test_refuses_to_overwrite_before_contacting_powercontext(tmp_path: Path) -> None:
    output_dir = tmp_path / "existing"
    output_dir.mkdir()
    runtime = FakeRetrievalRuntime()

    with pytest.raises(RetrievalSmokeError, match="Refusing to overwrite"):
        run_retrieval_smoke(
            data_root=tmp_path,
            dataset_lock=tmp_path / "lock.json",
            harness_root=tmp_path,
            smoke_manifest=tmp_path / "smoke.json",
            output_dir=output_dir,
            run_id="test",
            powercontext_revision="pc",
            integration_revision="adapter",
            runtime=runtime,
        )

    assert runtime.scopes == []
