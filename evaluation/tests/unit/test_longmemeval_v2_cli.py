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

from pathlib import Path

import pytest
from typer.testing import CliRunner

from powercontext_eval.benchmarks.longmemeval_v2.prepare_smoke import PreparedPromptRun
from powercontext_eval.benchmarks.longmemeval_v2.retrieval_smoke import RetrievalSmokeRun
from powercontext_eval.cli import app


def test_longmemeval_v2_retrieval_smoke_runs_without_reader_or_judge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []

    def run(**kwargs: object) -> RetrievalSmokeRun:
        calls.append(kwargs)
        output = tmp_path / "output"
        return RetrievalSmokeRun(
            output_dir=output,
            manifest_path=output / "retrieval-manifest.json",
            results_path=output / "retrieval-results.jsonl",
            failures_path=output / "failures.jsonl",
            summary_path=output / "summary.json",
            audit_path=output / "adapter-audit.jsonl",
        )

    monkeypatch.setattr("powercontext_eval.cli.run_retrieval_smoke", run)
    result = CliRunner().invoke(
        app,
        [
            "longmemeval-v2",
            "retrieval-smoke",
            "--data-root",
            "/data",
            "--dataset-lock",
            "/dataset-lock.json",
            "--harness-root",
            "/harness",
            "--smoke-manifest",
            "/smoke.json",
            "--output-dir",
            "/output",
            "--run-id",
            "retrieval-1",
            "--powercontext-revision",
            "pc-sha",
            "--integration-revision",
            "adapter-sha",
        ],
    )

    assert result.exit_code == 0, result.output
    assert '"classification": "smoke-subset-retrieval-only"' in result.output
    assert calls == [
        {
            "data_root": Path("/data"),
            "dataset_lock": Path("/dataset-lock.json"),
            "harness_root": Path("/harness"),
            "smoke_manifest": Path("/smoke.json"),
            "output_dir": Path("/output"),
            "run_id": "retrieval-1",
            "powercontext_revision": "pc-sha",
            "integration_revision": "adapter-sha",
            "base_url": "http://127.0.0.1:8000",
            "token_env": "POWERCONTEXT_TOKEN",
            "search_mode": "fts",
            "search_limit": 10,
            "timeout_seconds": 30.0,
        }
    ]


def test_longmemeval_v2_prepare_smoke_runs_without_reader_or_judge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []

    def prepare(**kwargs: object) -> PreparedPromptRun:
        calls.append(kwargs)
        output = tmp_path / "output"
        return PreparedPromptRun(
            output_dir=output,
            manifest_path=output / "prepare-manifest.json",
            prompts_path=output / "prepared-prompts.jsonl",
            failures_path=output / "prepare-failures.jsonl",
            summary_path=output / "prepare-summary.json",
        )

    monkeypatch.setattr("powercontext_eval.cli.prepare_reader_inputs_smoke", prepare)
    result = CliRunner().invoke(
        app,
        [
            "longmemeval-v2",
            "prepare-smoke",
            "--retrieval-dir",
            "/retrieval",
            "--harness-root",
            "/harness",
            "--harness-python",
            "/harness/python",
            "--output-dir",
            "/output",
            "--processor-revision",
            "processor-sha",
        ],
    )

    assert result.exit_code == 0, result.output
    assert '"classification": "smoke-subset-prepare-only"' in result.output
    assert calls == [
        {
            "retrieval_dir": Path("/retrieval"),
            "harness_root": Path("/harness"),
            "harness_python": Path("/harness/python"),
            "output_dir": Path("/output"),
            "processor_model": "Qwen/Qwen3.5-9B",
            "processor_revision": "processor-sha",
            "memory_context_max_tokens": 200_000,
        }
    ]
