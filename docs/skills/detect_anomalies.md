# detect_anomalies

> MCP tool `detect_anomalies` — the proactive sweep: multi-signal findings
> with computed confidence, suppression of repeats, and logged holds.

## When it activates

- User asks "anything unusual?", "anomalies", "issues", "sweep".
- `proactive_briefing` calls it with `include_previous=False` for openings.

## Flow

1. Runs the pure `analyze_dataset` over the provider ledger (the exact
   function the sealed benchmark scores).
2. `keep` verdicts (growth tracking real value) are separated, never alerted.
3. Ineligible providers (< 3 months history) become logged holds.
4. Low-confidence findings are held with a logged reason — unless the human
   challenged them, which revives them.
5. Already-surfaced findings are suppressed on the proactive path (logged
   once per month); the explicit path re-shows them without re-firing.

## Boundaries & refusal cases

- Never re-alerts a suppressed finding on the proactive path.
- Never flags a provider with insufficient history — it refuses to judge.
- Confidence is computed from signal count/strength, never asserted.

## Linked tests

- `tests/test_tools.py::TestDetectAnomalies` (surface/suppress/re-show,
  keep-not-cut, acknowledge, challenge-revival, alert logging)
- `tests/test_tools.py::TestAnalyzeDataset` (thresholds, boundaries)

## Evidence

- `benchmarks/results/` three tiers; `docs/evidence/benchmark-run.txt`
