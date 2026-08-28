"""Assembles Layer A's raw, deterministic facts into impact-facts.json.

Deliberately produces facts only - no risk levels, no rationale, no automatable
verdicts. Assigning those is Layer B's job (a classification pass, done by an
agent reading this file alongside discovery-report.json), matching the split
agreed for the Impact Analysis stage.

Build-system scope: Maven only.
Gradle and Ant are not supported. find_built_war (called below) validates this
upfront and raises ValueError with a clear message if no pom.xml is found.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from .discovery_diff import build_descriptor_coverage, build_source_coverage
from .judgment_scan import scan_judgment_calls
from .transformer_runner import TransformerRunner, find_built_war


def _asdict_list(items) -> list[dict]:
    return [dataclasses.asdict(i) for i in items]


def build_impact_facts(
    repo_path: Path,
    discovery_report_path: Path,
    java_home: str,
    work_dir: Path,
    mvn_cmd: str = "mvn",
) -> dict:
    discovery = json.loads(discovery_report_path.read_text(encoding="utf-8"))
    # find_built_war raises ValueError for non-Maven projects (no pom.xml) and
    # FileNotFoundError when mvn package has not been run yet. Both propagate to
    # the MCP server's analyze_impact tool, which wraps them into an error dict.
    war_path = find_built_war(repo_path)

    runner = TransformerRunner(java_home=java_home, work_dir=work_dir)
    run = runner.run(war_path, mvn_cmd=mvn_cmd)

    source_coverage = build_source_coverage(discovery, run)
    descriptor_coverage = build_descriptor_coverage(discovery, run)
    judgment_calls = scan_judgment_calls(repo_path)

    covered = [e for e in source_coverage if e.transformerFound and e.transformerChanged]
    not_covered = [e for e in source_coverage if not (e.transformerFound and e.transformerChanged)]

    return {
        "stage": "impact-analysis-layer-a",
        "inputWar": str(war_path),
        "transformerRun": {
            "tool": "org.eclipse.transformer.cli.JakartaTransformerCLI",
            "version": "1.0.0",
            "license": "EPL-2.0 OR Apache-2.0",
            "returnCode": run.return_code,
            "actionSummary": run.action_summary,
            "logFile": str(run.raw_log_path),
        },
        "sourceCoverage": {
            "totalFilesWithJavax": len(source_coverage),
            "mechanicallyCovered": len(covered),
            "notMechanicallyCovered": len(not_covered),
            "entries": _asdict_list(source_coverage),
        },
        "descriptorCoverage": _asdict_list(descriptor_coverage),
        "judgmentCallCandidates": _asdict_list(judgment_calls),
        "scopeNotes": [
            "Eclipse Transformer's bundled rules cover the one-time javax->jakarta "
            "package rename plus EE8->EE9 descriptor version bumps. EE9->EE10 "
            "API/behavioral changes (e.g. the servlet cookie RFC6265 behavior change, "
            "removed deprecated methods) are NOT in scope for this tool and will not "
            "show up as gaps here - they need a separate, dedicated check.",
            "Third-party jars bundled under WEB-INF/lib were excluded from "
            "sourceCoverage; their javax surface is a dependency-version-bump "
            "concern already tracked in Discovery's dependency inventory, not "
            "duplicated here.",
            "judgmentCallCandidates are pattern matches, not confirmed risks - e.g. "
            "a Serializable class is flagged even when none of its fields are "
            "actually javax-typed. Confirming real risk is Layer B's job.",
        ],
    }


def write_impact_facts(facts: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(facts, indent=2), encoding="utf-8")
