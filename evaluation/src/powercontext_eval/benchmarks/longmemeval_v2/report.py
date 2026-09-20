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

"""Summarize one saved LongMemEval-V2 smoke run without calling a model or server."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeAlias, TypeGuard

from powercontext_eval.errors import PowerContextEvalError

REPORT_SCHEMA = "powercontext.longmemeval-v2-smoke-report.v1"
REPORT_BANNER = "LongMemEval-V2 smoke subset — not a complete benchmark result."
REPORT_BOUNDARY = (
    "This report describes one fixed smoke subset over pinned upstream trajectories. "
    "It is not a complete benchmark result, not a product reliability claim, and not a substitute "
    "for a full LongMemEval-V2 run. See evaluation/README.md and "
    "evaluation/docs/longmemeval-v2-full-run.md for the recorded boundaries and the unexecuted full run."
)
ERROR_CLASSES = ("configuration", "infrastructure", "retrieval", "generation", "judge", "integrity")
_PHASES = ("preflight", "retrieval", "prepare", "reader", "score", "replay")
_FAILURE_CLASS_BY_PHASE_FILE = {
    "prepare": "infrastructure",
    "reader": "generation",
    "score": "judge",
    "replay": "integrity",
}

ReportStatus: TypeAlias = str


class ReportError(PowerContextEvalError):
    """Saved run artifacts cannot produce one unified report."""


@dataclass(frozen=True)
class ReportRun:
    """The written unified report artifacts."""

    report_path: Path
    markdown_path: Path


def build_report(*, run_dir: Path, output_dir: Path | None = None) -> ReportRun:
    """Read saved stage artifacts and write ``report.json`` and ``report.md`` fail-closed."""

    from powercontext_eval.benchmarks.longmemeval_v2.run_smoke import PHASE_DIRECTORIES

    run_root = run_dir.resolve()
    if not run_root.is_dir():
        raise ReportError(f"LongMemEval-V2 smoke run directory does not exist: {run_root}")
    # Rebuild the phase mapping with plain string keys: ``Mapping`` is invariant in its key
    # type, so the runner's ``Mapping[Phase, str]`` cannot be passed to the str-keyed helpers.
    directories = {str(phase): name for phase, name in PHASE_DIRECTORIES.items()}
    report = _build(run_root, directories)
    if output_dir is None:
        report_path = run_root / "report.json"
        markdown_path = run_root / "report.md"
        _write_text_exclusive(report_path, _json(report))
        _write_text_exclusive(markdown_path, _markdown(report))
        return ReportRun(report_path=report_path, markdown_path=markdown_path)
    target = output_dir.resolve()
    try:
        target.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise ReportError(f"Refusing to overwrite report artifacts: {target}") from error
    except OSError as error:
        raise ReportError(f"Cannot create report artifact directory: {target}") from error
    report_path = target / "report.json"
    markdown_path = target / "report.md"
    _write_text_exclusive(report_path, _json(report))
    _write_text_exclusive(markdown_path, _markdown(report))
    return ReportRun(report_path=report_path, markdown_path=markdown_path)


def _build(run_root: Path, directories: Mapping[str, str]) -> dict[str, object]:
    manifest = _load_json(run_root / "run-manifest.json")
    summary = _load_json(run_root / "run-summary.json")
    retrieval_summary = _load_json(run_root / directories["retrieval"] / "summary.json")
    prepare_summary = _load_json(run_root / directories["prepare"] / "prepare-summary.json")
    reader_summary = _load_json(run_root / directories["reader"] / "reader-summary.json")
    score_summary = _load_json(run_root / directories["score"] / "score-summary.json")
    replay_summary = _load_json(run_root / directories["replay"] / "replay-summary.json")
    retrieval_results = run_root / directories["retrieval"] / "retrieval-results.jsonl"
    audit = run_root / directories["retrieval"] / "adapter-audit.jsonl"
    reader_outputs = run_root / directories["reader"] / "reader-outputs.jsonl"
    judge_outputs = run_root / directories["score"] / "judge-outputs.jsonl"

    context_items = _sum_list_length(retrieval_results, "memory_context")
    retrieval_latency = _sum_nested_ms(retrieval_results, "timings_ms")
    ingest_latency = _sum_ingest_ms(audit)
    reader_latency = _sum_number(reader_outputs, "reader_latency_ms")
    judge_latency, abstention = _judge_totals(judge_outputs)
    artifacts = _artifacts(run_root, directories)
    return {
        "schema": REPORT_SCHEMA,
        "classification": "smoke-subset",
        "status": _status(summary, score_summary, artifacts),
        "run_id": _run_id(manifest, summary),
        "generated_at": datetime.now(UTC).isoformat(),
        "question_count": _question_count(
            summary, score_summary, replay_summary, reader_summary, prepare_summary, retrieval_summary
        ),
        "accuracy": _accuracy(score_summary, replay_summary),
        "latency_ms": {
            "ingest": ingest_latency,
            "retrieval": retrieval_latency,
            "prepare": _number(prepare_summary, "elapsed_ms"),
            "reader": reader_latency,
            "judge": judge_latency,
        },
        "context": {
            "items": context_items,
            "bytes": _number(retrieval_summary, "context_bytes"),
            "tokens": _number(prepare_summary, "memory_context_tokens"),
            "citations_available": _number(retrieval_summary, "citation_count"),
        },
        "usage": {
            "ingestion_tokens": 0,
            "ingestion_tokens_note": "the PowerContext Memory adapter ingests without a model, so no provider reports ingestion usage",
            "reader_input_tokens": _nested_number(reader_summary, "usage", "input_tokens"),
            "reader_output_tokens": _nested_number(reader_summary, "usage", "output_tokens"),
            "judge_input_tokens": _nested_number(score_summary, "judge_usage", "input_tokens"),
            "judge_output_tokens": _nested_number(score_summary, "judge_usage", "output_tokens"),
            "estimated_cost_usd": None,
            "estimated_cost_note": "no provider price table revision is pinned for this smoke run",
        },
        "failures": _failure_counts(run_root, directories),
        "abstention": abstention,
        "artifacts": artifacts,
        "boundary": REPORT_BOUNDARY,
    }


def _status(
    summary: dict[str, object] | None,
    score_summary: dict[str, object] | None,
    artifacts: Mapping[str, object],
) -> ReportStatus:
    if summary is not None and summary.get("status") in {"completed", "partial", "failed"}:
        return str(summary["status"])
    if score_summary is not None and score_summary.get("failed") == 0:
        return "completed"
    if any(artifacts.get(phase) is not None for phase in _PHASES):
        return "partial"
    return "failed"


def _run_id(manifest: dict[str, object] | None, summary: dict[str, object] | None) -> str | None:
    for source in (manifest, summary):
        if source is None:
            continue
        value = source.get("run_id")
        if isinstance(value, str) and value.strip():
            return value
    return None


def _question_count(*summaries: dict[str, object] | None) -> int | None:
    for summary in summaries:
        if summary is None:
            continue
        value = summary.get("question_count")
        if _is_int(value):
            return value
    return None


def _accuracy(
    score_summary: dict[str, object] | None, replay_summary: dict[str, object] | None
) -> dict[str, object] | None:
    for summary in (score_summary, replay_summary):
        if summary is None or summary.get("failed") != 0:
            continue
        correct = summary.get("correct")
        incorrect = summary.get("incorrect")
        if not _is_int(correct) or not _is_int(incorrect):
            continue
        value = summary.get("accuracy")
        return {
            "correct": correct,
            "incorrect": incorrect,
            "failed": 0,
            "value": float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
        }
    return None


def _failure_counts(run_root: Path, directories: Mapping[str, str]) -> dict[str, int]:
    counts = dict.fromkeys(ERROR_CLASSES, 0)
    for row in _iter_jsonl(run_root / "failures.jsonl"):
        error_class = row.get("error_class")
        if error_class in counts:
            counts[str(error_class)] += 1
    for phase, error_class in _FAILURE_CLASS_BY_PHASE_FILE.items():
        for row in _iter_jsonl(run_root / directories[phase] / f"{phase}-failures.jsonl"):
            counts[_phase_failure_class(phase, row, error_class)] += 1
    for row in _iter_jsonl(run_root / directories["retrieval"] / "failures.jsonl"):
        counts[_phase_failure_class("retrieval", row, "infrastructure")] += 1
    return counts


def _phase_failure_class(phase: str, row: Mapping[str, object], fallback: str) -> str:
    if phase == "retrieval":
        category = row.get("category")
        return "retrieval" if category == "integration" else "infrastructure"
    return fallback


def _judge_totals(path: Path) -> tuple[float | None, dict[str, object]]:
    latency = 0.0
    seen = False
    count = 0
    correct = 0
    available = False
    for row in _iter_jsonl(path):
        seen = True
        value = row.get("judge_latency_ms")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            latency += float(value)
        if row.get("evaluator") != "llm_abstention_checker":
            continue
        available = True
        count += 1
        if row.get("label") == 1:
            correct += 1
    abstention: dict[str, object] = {
        "count": count,
        "correct": correct if available else None,
        "incorrect": count - correct if available else None,
        "unavailable": not available,
    }
    return (round(latency, 3) if seen else None), abstention


def _artifacts(run_root: Path, directories: Mapping[str, str]) -> dict[str, str | None]:
    candidates: dict[str, str] = {
        "run_manifest": "run-manifest.json",
        "run_summary": "run-summary.json",
        "failures": "failures.jsonl",
    }
    candidates.update(dict(directories))
    return {name: value if (run_root / value).exists() else None for name, value in candidates.items()}


def _number(source: dict[str, object] | None, key: str) -> int | float | None:
    """Preserve a saved integer count as an integer and never invent a value that was not recorded."""

    if source is None:
        return None
    value = source.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    return None


def _nested_number(source: dict[str, object] | None, key: str, nested: str) -> int | None:
    if source is None:
        return None
    inner = source.get(key)
    if not isinstance(inner, Mapping):
        return None
    value = inner.get(nested)
    return value if _is_int(value) else None


def _sum_list_length(path: Path, key: str) -> int | None:
    total = 0
    seen = False
    for row in _iter_jsonl(path):
        seen = True
        value = row.get(key)
        if isinstance(value, list):
            total += len(value)
    return total if seen else None


def _sum_number(path: Path, key: str) -> float | None:
    total = 0.0
    seen = False
    for row in _iter_jsonl(path):
        seen = True
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total += float(value)
    return round(total, 3) if seen else None


def _sum_nested_ms(path: Path, key: str) -> float | None:
    total = 0.0
    seen = False
    for row in _iter_jsonl(path):
        inner = row.get(key)
        if not isinstance(inner, Mapping):
            continue
        value = inner.get("total")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            seen = True
            total += float(value)
    return round(total, 3) if seen else None


def _sum_ingest_ms(path: Path) -> float | None:
    total = 0.0
    seen = False
    for row in _iter_jsonl(path):
        if row.get("operation") != "ingest":
            continue
        inner = row.get("timings_ms")
        if not isinstance(inner, Mapping):
            continue
        value = inner.get("total")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            seen = True
            total += float(value)
    return round(total, 3) if seen else None


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _load_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _iter_jsonl(path: Path) -> Iterator[dict[str, object]]:
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(value, dict):
                    yield value
    except OSError:
        return


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _markdown(report: Mapping[str, object]) -> str:
    accuracy = _mapping(report["accuracy"])
    latency = _mapping(report["latency_ms"])
    context = _mapping(report["context"])
    usage = _mapping(report["usage"])
    failures = _mapping(report["failures"])
    abstention = _mapping(report["abstention"])
    artifacts = _mapping(report["artifacts"])
    lines = [
        REPORT_BANNER,
        "",
        f"Status: {report['status']}",
        f"Run: {_display(report['run_id'])}",
        f"Questions: {_display(report['question_count'])}",
        f"Accuracy: {_display_accuracy(accuracy)}",
        "",
        "Latency (ms): " + _pairs(latency),
        "Context: " + _pairs(context),
        "Usage: "
        + _pairs(
            {name: value for name, value in usage.items() if name.endswith("tokens") or name == "estimated_cost_usd"}
        ),
        "Failures: " + _pairs(failures),
        "Abstention: " + _pairs(abstention),
        "",
        "Artifacts:",
    ]
    lines.extend(f"- {name}: {_display(value)}" for name, value in sorted(artifacts.items()))
    lines.extend(
        [
            "",
            "What this evaluates:",
            "- Whether the PowerContext Memory adapter retrieved citable evidence through public interfaces",
            "  under fixed upstream data, fixed questions, and a fixed context budget.",
            "- Answer accuracy, latency, context size, failures, and abstention for the configured Reader and Judge.",
            "- Whether saved outputs replay the same deterministic scoring inputs without a model.",
            "",
            "What this does not evaluate:",
            "- Handoff, cross-host recovery, normal Runtime persistence, or Work Continuity.",
            "- Full LongMemEval-V2 performance, general model capability, or product leadership.",
            "- LoCoMo, SWE-bench Pro, or real user-task acceptance.",
            "",
            REPORT_BOUNDARY,
            "",
        ]
    )
    return "\n".join(lines)


def _mapping(value: object) -> Mapping[str, object]:
    """Rebuild an arbitrary mapping with string keys so downstream lookups stay typed."""

    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _pairs(values: Mapping[str, object]) -> str:
    return ", ".join(f"{name}={_display(value)}" for name, value in sorted(values.items()))


def _display(value: object) -> str:
    return "unavailable" if value is None else str(value)


def _display_accuracy(accuracy: Mapping[str, object]) -> str:
    value = accuracy.get("value")
    correct = accuracy.get("correct")
    incorrect = accuracy.get("incorrect")
    if value is None:
        return "unavailable"
    if isinstance(correct, bool) or not isinstance(correct, int):
        return "unavailable"
    if isinstance(incorrect, bool) or not isinstance(incorrect, int):
        return "unavailable"
    return f"{correct}/{correct + incorrect} ({value})"


def _write_text_exclusive(path: Path, value: str) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="") as stream:
            stream.write(value)
    except OSError as error:
        raise ReportError(f"Cannot write report artifact: {path}") from error
