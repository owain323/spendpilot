"""Generate the DERIVED INVARIANCE SUITE — labels never enter the repo.

The public fixtures (benchmarks/cases.json) ship with their gold labels, so
they can only ever prove "the engine matches its own regression cases". This
tool derives a second surface from the SAME decision structures with
different data surfaces:

  - every amount is rescaled by a seeded random factor (percent judgments
    are scale-invariant)
  - month keys are shifted to a different calendar window
  - provider ids/names are renamed, so finding ids change

The derived labels are rewritten from the original gold through the id
mapping. The generated files land in benchmarks/derived/ which is
gitignored: anyone can reproduce them from this generator (seeded, fully
deterministic), but the labels are not sitting in the public tree.

HONESTY NOTE — what a pass here does and does not mean: the derived cases
share the public fixtures' decision structures BY CONSTRUCTION, so a pass
proves the judgments are INVARIANT under rescaling, renaming, and calendar
shifts. It is not generalization evidence. For decision structures the
public fixtures do not cover, see the hand-written independent suite
(benchmarks/independent/, run with benchmarks/run.py --independent).

Usage:  python tools/make_derived.py [--seed 20260918]
"""

from __future__ import annotations

import itertools
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BENCH = ROOT / "benchmarks"
DERIVED = BENCH / "derived"

NAME_POOL = [
    "northstack", "brightloop", "vexohost", "quanta-ai", "meshpay",
    "signalhq", "pinegrid", "orbitml", "cascade-io", "ferrodata",
    "lumenapi", "stellarpay", "grandview", "helixops", "northbeam",
    "tidewatch", "cobaltrun", "emberly", "kestrel-ai", "palisade",
]


def month_shift(month: str, offset: int) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    idx = year * 12 + (mon - 1) + offset
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def derive_case(case: dict, case_gold: dict, rng: random.Random,
                rename: dict[str, str], offset: int, seq: int) -> tuple[dict, dict]:
    providers = []
    for prov in case["providers"]:
        scale = rng.uniform(0.45, 2.4)
        new_id = rename[prov["id"]]
        new_prov = {
            "id": new_id,
            "name": new_id.capitalize(),
            "category": prov["category"],
            "monthly": {month_shift(m, offset): round(v * scale, 2)
                        for m, v in prov["monthly"].items()},
            "evidence": dict(prov["evidence"]),
        }
        if "task_volume" in prov:
            # one factor per provider: rescaling must preserve the trend
            # SHAPE (a per-month jitter would destroy the cost-per-task
            # drift the task-drift cases are built on)
            vol_factor = rng.uniform(0.6, 1.5)
            new_prov["task_volume"] = {
                month_shift(m, offset): max(1, int(v * vol_factor))
                for m, v in prov["task_volume"].items()
            }
        providers.append(new_prov)

    def remap(entry: str) -> str:
        kind, _, old_pid = entry.partition("-")
        return f"{kind}-{rename[old_pid]}"

    return (
        {"id": f"d{seq:02d}-{case['id'].split('-', 1)[1]}",
         "note": case["note"] + " (derived invariance)",
         "providers": providers},
        {"flag": sorted(remap(e) for e in case_gold["flag"]),
         "keep": sorted(remap(e) for e in case_gold["keep"]),
         "hold": sorted(remap(e) for e in case_gold["hold"])},
    )


def main() -> int:
    seed = 20260918
    if "--seed" in sys.argv:
        seed = int(sys.argv[sys.argv.index("--seed") + 1])
    rng = random.Random(seed)

    cases_doc = json.loads((BENCH / "cases.json").read_text(encoding="utf-8"))
    gold = json.loads((BENCH / "gold" / "labels.json").read_text(encoding="utf-8"))

    months = cases_doc["months"]
    names = itertools.cycle(NAME_POOL)  # reuse across cases: labels are per-case
    # One global calendar shift: the top-level months array is shared by all
    # cases, so every provider must land on the same window.
    offset = rng.choice([-14, -7, 6, 13])
    shifted_months = [month_shift(m, offset) for m in months]
    out_cases, out_labels = [], {}
    seq = 1
    for case in cases_doc["cases"]:
        base_gold = gold[case["id"]]
        for variant in range(2):  # two derived surfaces per public case
            rename = {p["id"]: next(names) for p in case["providers"]}
            new_case, labels = derive_case(case, base_gold, rng, rename, offset, seq)
            out_cases.append(new_case)
            out_labels[new_case["id"]] = labels
            seq += 1

    DERIVED.mkdir(exist_ok=True)
    (DERIVED / "cases.json").write_text(
        json.dumps({"months": shifted_months, "cases": out_cases}, indent=2), encoding="utf-8")
    (DERIVED / "labels.json").write_text(
        json.dumps(out_labels, indent=2), encoding="utf-8")
    print(f"derived invariance suite written to {DERIVED}: {len(out_cases)} cases, seed {seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
