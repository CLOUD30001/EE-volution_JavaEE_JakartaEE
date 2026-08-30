"""MCP server exposing the Jakarta EE migration tooling as a single callable tool.

Follows the identical fastmcp + @server.tool() pattern used by the existing
three pipeline servers (jakarta-discovery-server, jakarta-impact-server,
jakarta-plan-server).

This server is a thin wrapper: it validates inputs, calls migrate.run_migration(),
and returns the MigrationResult as a plain dict suitable for JSON serialisation.

Run with:  python tools/run_jakarta_migrate_server.py
       or:  python tools/jakarta-migrate/jakarta_migrate_server.py
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from fastmcp import FastMCP

import migrate

server = FastMCP(
    name="jakarta-migrate-server",
    version="0.1.0",
    instructions=(
        "Layer C (automated migration) tool for the JavaEE8 -> Jakarta EE 10 pipeline. "
        "Reads the discovery-report.json, impact-facts.json, and final-plan.json produced "
        "by Layers A and B, then applies all non-blocked work items to the source tree: "
        "runs Eclipse Transformer on src/main/, fills string-literal and Facelets-URI gaps, "
        "patches pom.xml dependency coordinates, and updates Liberty server.xml feature "
        "names. Returns a MigrationResult dict describing every change made and, for "
        "blocked/manual items, what still requires a human decision. "
        "dry_run=True executes all read/compute steps but writes nothing to disk."
    ),
)


@server.tool()
def run_migration(
    repo_path: str,
    reports_dir: str,
    java_home: str,
    mvn_cmd: str = "mvn",
    work_dir: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Run the full automated Jakarta EE 10 migration against a Maven project.

    Requires the following reports to already exist under reports_dir:
      - discovery-report.json   (produced by ee-volution-assess, Phase 0)
      - impact-facts.json       (produced by ee-volution-assess, Phase 1)
      - final-plan.json         (produced by ee-volution-plan)

    Steps executed (in order):
      1  preflight           — validate reports, surface blockers, check Git, check Liberty
      2  transform_source    — run Eclipse Transformer on src/main/ tree
      3  apply_transformer   — copy transformed output back over src/main/
      4  gap_fill            — string literals + Facelets URI patches + SPI renames
      5  patch_pom           — Maven dependency coordinate changes
      6  patch_server_xml    — Liberty <featureManager> feature name changes
      7  git_commit          — commit all changes (skipped if Git unavailable)
      8  build_verify        — mvn package -DskipTests
      9  deploy              — mvn liberty:run (skipped if Liberty unavailable)

    dry_run=True executes all read/compute steps but writes nothing to disk and
    skips git_commit, build_verify, and deploy.

    Returns the MigrationResult as a dict, or {"error": "..."} on hard failure.
    """
    repo = Path(repo_path)

    # Input validation
    if not (repo / "pom.xml").exists():
        return {
            "error": (
                f"No pom.xml found at '{repo_path}'. "
                "Only Maven projects are supported."
            )
        }

    reports = Path(reports_dir)
    for required in ("discovery-report.json", "impact-facts.json", "final-plan.json"):
        if not (reports / required).exists():
            return {
                "error": (
                    f"Required report not found: {reports / required}. "
                    "Run ee-volution-assess (Layer A) and ee-volution-plan (Layer B) first."
                )
            }

    try:
        result = migrate.run_migration(
            repo_path=repo_path,
            reports_dir=reports_dir,
            java_home=java_home,
            mvn_cmd=mvn_cmd,
            work_dir=work_dir,
            dry_run=dry_run,
        )
        # Serialise to a plain dict (MigrationResult contains nested dataclasses)
        return json.loads(
            json.dumps(asdict(result), ensure_ascii=False)
        )
    except Exception as exc:
        return {"error": str(exc)}


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
