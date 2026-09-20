# LongMemEval-V2 smoke workload delivery

This delivery adds a bounded, reproducible LongMemEval-V2 smoke workload for PowerContext.
It uses the public Source and Memory HTTP interfaces, preserves the pinned upstream prompt and
scoring behavior, and labels every result as a smoke subset rather than a complete benchmark.

## Delivered workflow

The `powercontext-eval longmemeval-v2` command group now supports the complete local workflow:

1. validate the pinned dataset, fixed ten-question manifest, and upstream harness checkout;
2. ingest trajectory evidence through public PowerContext Source and Memory APIs;
3. retrieve cited text/image context from isolated evaluation Scopes;
4. prepare bounded Reader messages with the pinned upstream harness implementation;
5. optionally call an explicitly configured Reader and Judge;
6. score with the pinned upstream evaluation functions;
7. replay saved deterministic and Judge decisions without model or network calls; and
8. produce one machine-readable report and one human-readable report.

`run-smoke` orchestrates these stages into a single fail-closed output directory. An existing
output directory is never overwritten. Infrastructure, retrieval, generation, Judge,
configuration, and integrity failures remain distinct from incorrect answers.

## Reproducibility and privacy

- The harness commit, dataset revision and file digests, smoke question order, processor
  revision, model settings, PowerContext revision, and integration revision are recorded.
- The approximately 1.2 GB trajectory input remains streaming; it is not loaded as one string or
  byte array.
- The adapter, retrieval, preparation, and Reader stages do not read question type, reference
  answers, or Judge data. Only local scoring reads the locked reference answers.
- API credentials are resolved from named environment variables. Secret values are not written
  to manifests, reports, failure evidence, examples, or Git.
- `scoring-inputs.local.jsonl` contains local replay evidence and must remain outside Git,
  shared reports, and telemetry.
- Evaluation artifacts remain outside normal Runtime persistence and outside this repository.

## Validation evidence

A real one-command, model-free run completed the preflight, retrieval, and prompt-preparation
stages against a local PowerContext Server:

| Measurement | Result |
| --- | --- |
| Classification | `smoke-subset` |
| Status | `partial` (Reader, Judge, and replay intentionally skipped) |
| Questions | 10 |
| Failed stages | 0 |
| Retrieved context items | 100 |
| Prepared context tokens | 239,765 |
| Ingestion latency | 121,838.524 ms |
| Published accuracy | unavailable, as required for a model-free run |

The generated `report.json` and `report.md` contained no credential values. The local server was
stopped after validation, and the run artifacts were not added to Git.

A separate paid smoke execution of the saved ten Reader inputs produced 4 correct answers out of
10 with the configured DeepSeek Reader/Judge path. This is a smoke-subset observation only. It is
not a full LongMemEval-V2 result and does not establish product or model leadership. The saved
score was also reproduced by the offline replay path with zero Reader and Judge calls.

The scoped verification for this delivery completed with:

- 67 LongMemEval-V2 unit tests passing;
- Ruff lint and format checks passing;
- targeted type checks for the orchestrator, report, and CLI passing;
- `git diff --check` passing; and
- secret-pattern scans of changed files and the real model-free run returning no matches.

## Explicitly not executed

No full-tier dataset run was executed. The repository does not yet contain an approved full-tier
dataset lock or question manifest, and hard case/cost guards are not implemented. A paid full run
therefore requires separate implementation review and explicit approval for cost and data egress.
See [longmemeval-v2-full-run.md](longmemeval-v2-full-run.md) for the recorded prerequisites.

This workload does not validate Handoff, cross-host recovery, normal Runtime persistence, or
Work Continuity. It does not replace LoCoMo, SWE-bench Pro, or PowerContext-native acceptance
tests.
