"""MCP server for the Migration Planning stage (Layer A).

Turns impact-facts.json (produced by jakarta-impact-server) into a
sequenced, batched migration plan with per-finding effort estimates.

This server is deterministic — it sequences and sizes work but never
resolves a finding that requires a human decision. Judgment calls are
preserved as-is in the 'needs_human_input' batch so the judgment layer
above can act on them.

Verified against the installed fastmcp SDK (PyPI "fastmcp" >=2.14.1,
the same version used by jakarta-impact-server). The high-level API is
the @server.tool() decorator on a FastMCP instance; older docs referencing
mcp.server.MCPServer do not apply to this SDK.

Run with:  python tools/run_jakarta_plan_server.py
       or:  python tools/jakarta-plan/jakarta_plan_server.py
"""
from __future__ import annotations

import json
from pathlib import Path

from fastmcp import FastMCP

from plan_builder import build_migration_plan, plan_to_dict, write_migration_plan

server = FastMCP(
    name="jakarta-plan-server",
    version="0.1.0",
    instructions=(
        "Layer A (deterministic ground truth) tool for the Migration Planning stage "
        "of a JavaEE8 -> Jakarta EE 10 migration. Consumes impact-facts.json produced "
        "by jakarta-impact-server and emits a sequenced, batched migration plan with "
        "per-finding effort estimates. Produces facts only — no decisions, no risk "
        "verdicts. Findings that require human judgment are preserved in the "
        "'needs_human_input' batch for the judgment layer above this one."
    ),
)


@server.tool()
def plan_migration(
    impact_report_path: str,
    out_path: str | None = None,
) -> dict:
    """Sequence impact-facts.json findings into a migration plan.

    Reads the impact-facts.json produced by analyze_impact (jakarta-impact-server)
    and returns a migration-plan.json structure: findings grouped into ordered
    batches, each with a per-finding effort estimate and the formula trace that
    produced it.

    Batch execution order (lowest index first):
      0 - needs_human_input  : judgment-call candidates and mechanically-uncovered
                               source files whose fix requires a decision first
      1 - foundational       : build/dependency/runtime-config changes (pom.xml,
                               server.xml javaee features, etc.) — compile target
                               for everything downstream
      2 - mechanical         : files fully handled by Eclipse Transformer (zero
                               net-new effort — transformer already rewrote them)
      3 - manual_remediation : source files requiring hand edits after foundational
                               changes land

    Effort formula (transparent):
      effort_hours = BASE_HOURS[batch] * max(1.0, n^0.55)
      where n = number of files in the finding.
      BASE_HOURS: needs_human_input=6, foundational=4, mechanical=0, manual_remediation=2.
      The 0.55 exponent is strictly sub-linear for all n >= 1 (verified at import).

    If out_path is given, the plan is also written to that file in addition to
    being returned.  If impact_report_path does not exist or is not valid JSON,
    an error dict is returned instead.
    """
    report_path = Path(impact_report_path)
    try:
        impact_report = json.loads(report_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"error": f"impact report not found: {impact_report_path}"}
    except json.JSONDecodeError as exc:
        return {"error": f"impact report is not valid JSON: {exc}"}

    plan = build_migration_plan(impact_report, source_report_path=impact_report_path)
    plan_dict = plan_to_dict(plan)

    if out_path:
        write_migration_plan(plan_dict, Path(out_path))

    return plan_dict


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
