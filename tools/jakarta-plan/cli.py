"""python tools/jakarta-plan/cli.py --impact <impact-facts.json> [options]

Produces migration-plan.json — Layer A's output for the Migration Planning stage.

Reads impact-facts.json (output of jakarta-impact-server's analyze_impact tool)
and writes a sequenced, batched migration plan with per-finding effort estimates.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from plan_builder import build_migration_plan, plan_to_dict, write_migration_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--impact",
        required=True,
        type=Path,
        help="Path to impact-facts.json produced by jakarta-impact-server",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path for migration-plan.json (default: alongside --impact)",
    )
    args = parser.parse_args(argv)

    impact_path: Path = args.impact
    if not impact_path.exists():
        print(f"error: impact report not found: {impact_path}", file=sys.stderr)
        return 1

    import json

    try:
        impact_report = json.loads(impact_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: impact report is not valid JSON: {exc}", file=sys.stderr)
        return 1

    out_path: Path = args.out or (impact_path.parent / "migration-plan.json")

    plan = build_migration_plan(impact_report, source_report_path=str(impact_path))
    plan_dict = plan_to_dict(plan)
    write_migration_plan(plan_dict, out_path)

    # ---------------------------------------------------------------
    # Summary to stdout — all numbers sourced from plan_dict, not typed
    # ---------------------------------------------------------------
    s = plan_dict["summary"]
    print(f"Wrote {out_path}")
    print(f"Total findings : {s['total_findings']}")
    print(f"Total effort   : {s['total_effort_hours']} hours")
    print()
    print("Batches (execution order):")
    for b in plan_dict["batches"]:
        pb = s["per_batch"][b["name"]]
        print(
            f"  [{b['index']}] {b['name']:<22} "
            f"{pb['finding_count']:>3} finding(s)  "
            f"{pb['effort_hours']:>6.1f} h"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
