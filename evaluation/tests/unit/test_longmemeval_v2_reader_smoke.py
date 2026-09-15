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

import pytest

from powercontext_eval.benchmarks.longmemeval_v2.reader_smoke import ReaderSmokeError, run_reader_smoke


class FakeReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, object]]]] = []

    def complete(self, *, system: str, content: list[dict[str, object]]) -> Mapping[str, object]:
        self.calls.append((system, content))
        return {
            "model": "deepseek-flash-latest",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "\\boxed{answer}"}],
            "usage": {"input_tokens": 123, "output_tokens": 7},
        }


def prepared_artifacts(tmp_path: Path) -> Path:
    root = tmp_path / "prepared"
    root.mkdir()
    (root / "prepare-manifest.json").write_text(
        json.dumps({"classification": "smoke-subset-prepare-only", "reader": None, "judge": None}),
        encoding="utf-8",
    )
    (root / "prepare-summary.json").write_text(
        json.dumps({"classification": "smoke-subset-prepare-only", "question_count": 10, "failed": 0}),
        encoding="utf-8",
    )
    with (root / "prepared-prompts.jsonl").open("w", encoding="utf-8") as stream:
        for index in range(10):
            stream.write(
                json.dumps(
                    {
                        "question_id": f"question-{index}",
                        "sequence": index + 1,
                        "domain": "web",
                        "scope_id": "scope-1",
                        "haystack_digest": "digest-1",
                        "prompt_sha256": f"prompt-{index}",
                        "gold_answer": "must-not-be-copied",
                        "messages": [
                            {"role": "system", "content": "system"},
                            {"role": "user", "content": [{"type": "text", "text": "question"}]},
                        ],
                    }
                )
                + "\n"
            )
    return root


def test_reader_smoke_writes_responses_and_never_persists_credentials_or_gold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    transport = FakeReader()
    output = tmp_path / "reader"
    monkeypatch.setenv("PRIVATE_TOKEN_ENV", "super-secret-token")

    result = run_reader_smoke(
        prepared_dir=prepared_artifacts(tmp_path),
        output_dir=output,
        base_url_env="PRIVATE_BASE_URL_ENV",
        token_env="PRIVATE_TOKEN_ENV",
        model="deepseek-flash-latest",
        max_questions=1,
        transport=transport,
    )

    assert transport.calls == [("system", [{"type": "text", "text": "question"}])]
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["reader"]["token_env"] == "PRIVATE_TOKEN_ENV"
    assert "super-secret-token" not in json.dumps(manifest)
    [output_record] = [json.loads(line) for line in result.outputs_path.read_text(encoding="utf-8").splitlines()]
    assert output_record["response_text"] == "\\boxed{answer}"
    assert output_record["usage"] == {"input_tokens": 123, "output_tokens": 7}
    assert "gold_answer" not in output_record
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["usage"] == {"input_tokens": 123, "output_tokens": 7}
    assert summary["estimated_cost"] is None


def test_reader_smoke_refuses_to_overwrite_before_loading_prepared_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "reader"
    output.mkdir()

    with pytest.raises(ReaderSmokeError, match="Refusing to overwrite"):
        run_reader_smoke(
            prepared_dir=tmp_path / "missing",
            output_dir=output,
            transport=FakeReader(),
        )
