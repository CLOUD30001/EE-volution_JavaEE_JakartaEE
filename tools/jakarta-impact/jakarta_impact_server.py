"""MCP server wrapping jakarta_impact's Layer A functions so any MCP-aware agent
(not just one with shell/Bash access) can call them directly - the same pattern
jakarta-discovery-server already uses for Stage 1.

Run with: python -m jakarta_impact.mcp_server

Verified against the installed "mcp" SDK (PyPI "mcp" 2.0.0,
https://github.com/modelcontextprotocol/python-sdk) on 2026-08-21. Its current
high-level API is `mcp.server.MCPServer` - older docs and examples referencing
`mcp.server.fastmcp.FastMCP` do not apply to this version; that module does not
exist in 2.0.0.
"""
from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP

from report_builder import build_impact_facts

server = FastMCP(
    name="jakarta-impact-server",
    version="0.1.0",
    instructions=(
        "Layer A (deterministic ground truth) tools for the Impact Analysis stage "
        "of a JavaEE8 -> Jakarta EE 10 migration. Consumes Stage 1's "
        "discovery-report.json plus a built WAR; produces raw facts only - no risk "
        "levels or rationale. Assigning those is a separate classification step for "
        "the calling agent, done by reading these facts alongside the discovery "
        "report - not something this server does itself."
    ),
)


@server.tool()
def analyze_impact(
    repo_path: str,
    discovery_report_path: str,
    java_home: str,
    mvn_cmd: str = "mvn",
    work_dir: str | None = None,
) -> dict:
    """Run Eclipse Transformer against the target project's built WAR, cross-reference
    the result against Stage 1's discovery-report.json, and scan for judgment-call
    candidates (reflection, custom serialization, SPI registrations).

    Maven projects only. The repo must contain a pom.xml at its root and must
    already be built (run `mvn package` first - a .war must exist under target/).
    Gradle and Ant are not supported; passing a non-Maven repo returns an error dict
    immediately. This mirrors the Maven-only scope of the upstream Discovery stage.

    java_home must point at a JDK 11+ install; this is unrelated to whatever JDK the
    target project compiles with - Eclipse Transformer's own jars failed to load
    under JDK 8 in testing (UnsupportedClassVersionError).

    Returns the full impact-facts.json structure: transformerRun (tool version,
    return code, per-action-type change counts), sourceCoverage (per javax-using
    source file: was it mechanically fixed by the rewrite tool, yes/no/not-found),
    descriptorCoverage (the same, for XML/text descriptors), judgmentCallCandidates
    (pattern-matched risks no rewrite tool resolves), and scopeNotes - read those
    last few before trusting a clean result, they spell out exactly what this tool
    does NOT check (e.g. EE9->EE10 behavioral changes, third-party jar contents).
    """
    repo = Path(repo_path)
    try:
        return build_impact_facts(
            repo_path=repo,
            discovery_report_path=Path(discovery_report_path),
            java_home=java_home,
            work_dir=Path(work_dir) if work_dir else repo / "target" / "jakarta-impact",
            mvn_cmd=mvn_cmd,
        )
    except ValueError as exc:
        # Non-Maven project (no pom.xml) — fail fast with a clear message.
        return {"error": str(exc)}
    except FileNotFoundError as exc:
        # WAR not found — project not built yet.
        return {"error": str(exc)}


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
