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

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from powercontext_eval.benchmarks.longmemeval_v2.report import REPORT_BANNER, ReportError, build_report

GOLD_SENTINEL = "the gold reference answer that must never reach a report"
SECRET_PATTERNS = (re.compile(r"sk-[A-Za-z0-9_-]{8,}"), re.compile(r"eyJ[A-Za-z0-9_-]{10,}"))
FORBIDDEN_KEYS = frozenset(
    {"reference_answer", "gold", "gold_answer", "api_key", "auth_token", "token", "token_env", "password", "secret"}
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")


def _successful_run(root: Path) -> Path:
    run = root / "run"
    _write_json(
        run / "run-manifest.json",
        {"schema": "powercontext.longmemeval-v2-smoke-run.v1", "classification": "smoke-subset", "run_id": "smoke-v1"},
    )
    _write_json(
        run / "run-summary.json",
        {
            "schema": "powercontext.longmemeval-v2-smoke-run-summary.v1",
            "classification": "smoke-subset",
            "run_id": "smoke-v1",
            "status": "completed",
            "question_count": 10,
            "accuracy": {"correct": 4, "incorrect": 6, "failed": 0, "value": 0.4},
            "artifacts": {"retrieval": "02-retrieval"},
        },
    )
    _write_jsonl(
        run / "02-retrieval" / "retrieval-results.jsonl",
        [
            {
                "question_id": f"q{index}",
                "status": "succeeded",
                "memory_context": [{"type": "text", "value": "x"}] * 3,
                "timings_ms": {"search": 1.0, "format": 0.5, "total": 2.0},
            }
            for index in range(10)
        ],
    )
    _write_jsonl(
        run / "02-retrieval" / "adapter-audit.jsonl",
        [{"operation": "ingest", "timings_ms": {"total": 4.0}}, {"operation": "query", "timings_ms": {"total": 9.0}}],
    )
    _write_json(
        run / "02-retrieval" / "summary.json",
        {
            "question_count": 10,
            "failed": 0,
            "context_bytes": 900,
            "citation_count": 12,
            "elapsed_ms": 100.0,
        },
    )
    _write_json(
        run / "03-prepare" / "prepare-summary.json",
        {"question_count": 10, "failed": 0, "memory_context_tokens": 1234, "elapsed_ms": 7.0},
    )
    _write_jsonl(run / "04-reader" / "reader-outputs.jsonl", [{"question_id": "q0", "reader_latency_ms": 5.0}] * 10)
    _write_json(
        run / "04-reader" / "reader-summary.json",
        {
            "question_count": 10,
            "failed": 0,
            "usage": {"input_tokens": 1000, "output_tokens": 200},
            "elapsed_ms": 50.0,
        },
    )
    _write_jsonl(
        run / "05-score" / "judge-outputs.jsonl",
        [
            {
                "question_id": "q0",
                "evaluator": "llm_abstention_checker",
                "label": 1,
                "judge_latency_ms": 3.0,
            },
            {
                "question_id": "q1",
                "evaluator": "llm_abstention_checker",
                "label": 0,
                "judge_latency_ms": 4.0,
            },
            {"question_id": "q2", "evaluator": "llm_gotchas_checker", "label": 1, "judge_latency_ms": 5.0},
        ],
    )
    _write_json(
        run / "05-score" / "score-summary.json",
        {
            "question_count": 10,
            "correct": 4,
            "incorrect": 6,
            "failed": 0,
            "accuracy": 0.4,
            "judge_usage": {"input_tokens": 300, "output_tokens": 60},
            "elapsed_ms": 40.0,
        },
    )
    _write_json(
        run / "06-replay" / "replay-summary.json",
        {"question_count": 10, "correct": 4, "incorrect": 6, "failed": 0, "accuracy": 0.4},
    )
    # The score stage keeps local reference answers for replay. A report must never read or copy them.
    _write_jsonl(
        run / "05-score" / "scoring-inputs.local.jsonl",
        [{"question_id": "q0", "reference_answer": GOLD_SENTINEL, "api_key": "sk-abcdefghijklmnop"}],
    )
    return run


def test_report_summarizes_a_successful_run_from_saved_artifacts(tmp_path: Path) -> None:
    run = _successful_run(tmp_path)
    result = build_report(run_dir=run)

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["schema"] == "powercontext.longmemeval-v2-smoke-report.v1"
    assert report["classification"] == "smoke-subset"
    assert report["status"] == "completed"
    assert report["question_count"] == 10
    assert report["accuracy"] == {"correct": 4, "incorrect": 6, "failed": 0, "value": 0.4}
    assert report["latency_ms"] == {
        "ingest": 4.0,
        "retrieval": 20.0,
        "prepare": 7.0,
        "reader": 50.0,
        "judge": 12.0,
    }
    assert report["context"] == {"items": 30, "bytes": 900, "tokens": 1234, "citations_available": 12}
    assert report["usage"] == {
        "ingestion_tokens": 0,
        "ingestion_tokens_note": (
            "the PowerContext Memory adapter ingests without a model, so no provider reports ingestion usage"
        ),
        "reader_input_tokens": 1000,
        "reader_output_tokens": 200,
        "judge_input_tokens": 300,
        "judge_output_tokens": 60,
        "estimated_cost_usd": None,
        "estimated_cost_note": "no provider price table revision is pinned for this smoke run",
    }
    assert report["abstention"] == {"count": 2, "correct": 1, "incorrect": 1, "unavailable": False}
    assert report["failures"] == {
        "configuration": 0,
        "infrastructure": 0,
        "retrieval": 0,
        "generation": 0,
        "judge": 0,
        "integrity": 0,
    }
    assert report["artifacts"]["retrieval"] == "02-retrieval"
    assert report["artifacts"]["score"] == "05-score"

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert markdown.splitlines()[0] == REPORT_BANNER
    assert "Accuracy: 4/10 (0.4)" in markdown
    assert "not a complete benchmark result" in markdown
    assert "evaluation/docs/longmemeval-v2-full-run.md" in markdown


def test_report_uses_relative_latency_from_saved_artifacts_only(tmp_path: Path) -> None:
    run = _successful_run(tmp_path)
    result = build_report(run_dir=run)
    report = json.loads(result.report_path.read_text(encoding="utf-8"))

    assert report["latency_ms"]["ingest"] == 4.0  # only the ingest audit row, never the query row
    assert report["latency_ms"]["retrieval"] == 20.0  # ten saved queries at 2 ms each


def test_report_counts_failures_by_class_from_run_and_stage_artifacts(tmp_path: Path) -> None:
    run = _successful_run(tmp_path)
    _write_jsonl(
        run / "failures.jsonl",
        [
            {"phase": "reader", "error_class": "configuration", "summary": "missing key"},
            {"phase": "reader", "error_class": "generation", "summary": "http 500"},
        ],
    )
    _write_jsonl(run / "04-reader" / "reader-failures.jsonl", [{"question_id": "q1", "phase": "reader"}])
    _write_jsonl(
        run / "02-retrieval" / "failures.jsonl",
        [
            {"question_id": "q2", "phase": "query", "category": "integration"},
            {"question_id": "q3", "phase": "query", "category": "infrastructure"},
        ],
    )
    result = build_report(run_dir=run)

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["failures"] == {
        "configuration": 1,
        "infrastructure": 1,
        "retrieval": 1,
        "generation": 2,
        "judge": 0,
        "integrity": 0,
    }


def test_report_covers_a_run_that_stopped_after_a_failed_phase(tmp_path: Path) -> None:
    run = _successful_run(tmp_path)
    for name in ("04-reader", "05-score", "06-replay"):
        shutil.rmtree(run / name)
    _write_json(
        run / "run-summary.json",
        {
            "classification": "smoke-subset",
            "status": "failed",
            "question_count": 10,
            "accuracy": None,
            "completed_phases": ["preflight", "retrieval", "prepare"],
            "failed_phase": "prepare",
        },
    )
    result = build_report(run_dir=run)

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["accuracy"] is None
    assert report["usage"]["reader_input_tokens"] is None
    assert report["latency_ms"]["reader"] is None
    assert report["abstention"] == {"count": 0, "correct": None, "incorrect": None, "unavailable": True}
    assert report["artifacts"]["score"] is None
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "Accuracy: unavailable" in markdown
    assert markdown.splitlines()[0] == REPORT_BANNER


def test_report_covers_a_model_free_run_without_inventing_accuracy(tmp_path: Path) -> None:
    run = tmp_path / "model-free"
    _write_json(run / "run-manifest.json", {"classification": "smoke-subset", "run_id": "model-free"})
    _write_json(
        run / "run-summary.json",
        {"classification": "smoke-subset", "status": "partial", "question_count": 10, "accuracy": None},
    )
    _write_json(run / "02-retrieval" / "summary.json", {"question_count": 10, "failed": 0, "context_bytes": 10})
    result = build_report(run_dir=run)

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["status"] == "partial"
    assert report["accuracy"] is None
    assert report["question_count"] == 10
    assert report["usage"]["estimated_cost_usd"] is None
    assert report["latency_ms"]["judge"] is None


def test_report_never_copies_reference_answers_or_credentials(tmp_path: Path) -> None:
    run = _successful_run(tmp_path)
    result = build_report(run_dir=run)

    for path in (result.report_path, result.markdown_path):
        text = path.read_text(encoding="utf-8")
        assert GOLD_SENTINEL not in text
        assert "sk-abcdefghijklmnop" not in text
        for pattern in SECRET_PATTERNS:
            assert pattern.search(text) is None
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    for key, value in _walk(report):
        assert key.rsplit(".", 1)[-1].lower() not in FORBIDDEN_KEYS, key
        assert GOLD_SENTINEL not in str(value)


def test_report_refuses_to_overwrite_an_existing_report(tmp_path: Path) -> None:
    run = _successful_run(tmp_path)
    build_report(run_dir=run)

    with pytest.raises(ReportError, match="Cannot write report artifact"):
        build_report(run_dir=run)


def test_report_can_be_written_to_a_new_separate_directory(tmp_path: Path) -> None:
    run = _successful_run(tmp_path)
    target = tmp_path / "report"
    result = build_report(run_dir=run, output_dir=target)

    assert result.report_path == target / "report.json"
    assert (target / "report.md").is_file()
    assert not (run / "report.json").exists()

    with pytest.raises(ReportError, match="Refusing to overwrite report artifacts"):
        build_report(run_dir=run, output_dir=target)


def test_report_rejects_a_missing_run_directory(tmp_path: Path) -> None:
    with pytest.raises(ReportError, match="does not exist"):
        build_report(run_dir=tmp_path / "absent")


def _walk(value: Any, prefix: str = "") -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            found.extend(_walk(item, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk(item, prefix))
    else:
        found.append((prefix, value))
    return found
