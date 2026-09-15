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

from powercontext_eval.benchmarks.longmemeval_v2 import score_smoke
from powercontext_eval.benchmarks.longmemeval_v2.score_smoke import ScoreSmokeError, run_score_smoke


class FakeMetrics:
    def eval_name(self, spec: str) -> str:
        return spec.split("|", 1)[0]

    def extract_boxed_answer(self, text: str) -> str:
        return text

    def eval_from_spec(self, spec: str, prediction: str, answer: str) -> bool:
        return prediction == answer and not spec.startswith("llm_")

    def score_to_bool(self, value: Any) -> bool:
        return bool(value)

    def _build_abstention_judge_messages(self, **kwargs: Any) -> list[dict[str, str]]:
        return [{"role": "system", "content": "abstention"}, {"role": "user", "content": kwargs["reference_answer"]}]

    def _build_gotchas_judge_messages(self, **kwargs: Any) -> list[dict[str, str]]:
        return [{"role": "system", "content": "gotchas"}, {"role": "user", "content": kwargs["reference_answer"]}]

    def _parse_llm_binary_judgement(self, text: str) -> tuple[int, str]:
        assert text == '{"label":1}'
        return 1, "accepted"


class FakeJudge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, object]]]] = []

    def complete(self, *, system: str, content: list[dict[str, object]]) -> Mapping[str, object]:
        self.calls.append((system, content))
        return {
            "content": [{"type": "text", "text": '{"label":1}'}],
            "usage": {"input_tokens": 10, "output_tokens": 2},
        }


def score_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    reader = tmp_path / "reader"
    data = tmp_path / "data"
    reader.mkdir()
    data.mkdir()
    reader_manifest = {"classification": "smoke-subset-reader-only", "judge": None}
    reader_summary = {"classification": "smoke-subset-reader-only", "question_count": 10, "failed": 0}
    (reader / "reader-manifest.json").write_text(json.dumps(reader_manifest), encoding="utf-8")
    (reader / "reader-summary.json").write_text(json.dumps(reader_summary), encoding="utf-8")
    cases = []
    with (
        (reader / "reader-outputs.jsonl").open("w", encoding="utf-8") as outputs,
        (data / "questions.jsonl").open("w", encoding="utf-8") as questions,
    ):
        for index in range(10):
            question_id = f"q-{index}"
            evaluator = "llm_abstention_checker" if index < 2 else "llm_gotchas_checker" if index < 4 else "exact"
            answer = f"answer-{index}"
            cases.append({"question_id": question_id, "ability": "static_state"})
            outputs.write(json.dumps({"question_id": question_id, "response_text": answer}) + "\n")
            questions.write(
                json.dumps(
                    {
                        "id": question_id,
                        "domain": "web",
                        "question": f"question {index}",
                        "answer": answer,
                        "eval_function": evaluator,
                    }
                )
                + "\n"
            )
    manifest = tmp_path / "smoke.json"
    manifest.write_text(
        json.dumps({"schema": "powercontext.longmemeval-v2-smoke.v1", "tier": "small", "cases": cases}),
        encoding="utf-8",
    )
    return reader, data, manifest


def test_score_smoke_keeps_gold_only_in_local_scoring_inputs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reader, data, manifest = score_fixture(tmp_path)
    output = tmp_path / "score"
    judge = FakeJudge()
    monkeypatch.setattr(score_smoke, "validate_harness_checkout", lambda root: None)
    monkeypatch.setattr(score_smoke, "_load_metrics", lambda root: FakeMetrics())

    result = run_score_smoke(
        reader_dir=reader,
        data_root=data,
        smoke_manifest=manifest,
        harness_root=tmp_path / "harness",
        output_dir=output,
        judge_transport=judge,
    )

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["correct"] == 10
    assert summary["accuracy"] == 1.0
    assert summary["judge_calls"] == 4
    assert summary["judge_usage"] == {"input_tokens": 40, "output_tokens": 8}
    assert len(judge.calls) == 4
    results = [json.loads(line) for line in result.results_path.read_text(encoding="utf-8").splitlines()]
    assert {row["score_mode"] for row in results} == {"deterministic", "llm_judge"}
    assert all("reference_answer" not in row for row in results)
    scoring_inputs = result.inputs_path.read_text(encoding="utf-8")
    assert "answer-0" in scoring_inputs
    assert '"reference_answer"' not in result.results_path.read_text(encoding="utf-8")


def test_score_smoke_refuses_to_overwrite_before_reading_inputs(tmp_path: Path) -> None:
    output = tmp_path / "score"
    output.mkdir()

    with pytest.raises(ScoreSmokeError, match="Refusing to overwrite"):
        run_score_smoke(
            reader_dir=tmp_path / "missing",
            data_root=tmp_path / "missing-data",
            smoke_manifest=tmp_path / "missing-smoke",
            harness_root=tmp_path / "missing-harness",
            output_dir=output,
        )
