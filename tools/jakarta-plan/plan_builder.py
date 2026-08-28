"""Turns impact-facts.json into a sequenced, batched migration plan.

This is **Layer A** for the Planning stage — it produces ordering and effort
estimates from deterministic signals only. It never resolves a finding that
requires a human decision; that is the judgment layer's responsibility (a
separate tool built above this one).

Batch ordering (execution order, lowest index first):
  1. needs_human_input  — judgment-call candidates and source files that are not
                          mechanically covered; a human must review/decide before
                          downstream work can be planned.
  2. foundational       — build and dependency changes (pom.xml, server.xml with
                          javaee features, dependency declarations). Everything
                          else compiles against what these deliver.
  3. mechanical         — source files and descriptors fully handled by Eclipse
                          Transformer; zero net-new effort.
  4. manual_remediation — source files not mechanically covered (other than those
                          already in needs_human_input): hand edits after
                          foundational changes land.

Categorisation rules are signal-based (file type keywords), NOT tied to specific
finding IDs or source paths.

Effort formula (transparent — not a black box):
  effort_hours = BASE_HOURS[batch] * file_scale(n)
  file_scale(n) = max(1.0, n ** FILE_SCALE_EXP)   where FILE_SCALE_EXP = 0.55

  n  = number of distinct files in the finding

  BASE_HOURS per batch:
    needs_human_input : 6.0  (discovery + triage + fix)
    foundational      : 4.0  (targeted change but high blast radius)
    mechanical        : 0.0  (transformer already did the work)
    manual_remediation: 2.0  (known change, lower uncertainty)

Why 0.55?  x^0.55 < x for all x > 1, so the formula is strictly sub-linear
across every realistic file count — not just asymptotically. Numerical check
(see _verify_sublinearity()) confirms it for the range we care about.

Already-resolved findings (transformerChanged=True in sourceCoverage) cost
nothing; they land in 'mechanical' with effort=0.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Constants — change these to recalibrate, not the formula shape
# ---------------------------------------------------------------------------

BATCH_ORDER: list[str] = [
    "needs_human_input",
    "foundational",
    "mechanical",
    "manual_remediation",
]

BASE_HOURS: dict[str, float] = {
    "needs_human_input": 6.0,
    "foundational": 4.0,
    "mechanical": 0.0,
    "manual_remediation": 2.0,
}

FILE_SCALE_EXP: float = 0.55  # verified sub-linear vs linear for all n >= 1


def _file_scale(n: int) -> float:
    """Sub-linear file-count scaling.  n^0.55 — strictly < n for all n > 1."""
    return max(1.0, n ** FILE_SCALE_EXP)


def _effort(batch: str, file_count: int) -> float:
    """Transparent effort estimate in hours."""
    base = BASE_HOURS[batch]
    if base == 0.0:
        return 0.0
    return round(base * _file_scale(file_count), 2)


# ---------------------------------------------------------------------------
# Batch-assignment signals — rule-based on file type / keyword, not finding IDs
# ---------------------------------------------------------------------------

# Patterns in a file path that indicate a *build/configuration* artefact whose
# change is foundational — everything downstream compiles against it.
_FOUNDATIONAL_PATH_KEYWORDS: frozenset[str] = frozenset({
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "server.xml",       # Liberty runtime config — javaee->jakartaee feature rename
    "manifest.mf",      # OSGi/EBA manifest — import-package namespace lines
    "bnd.bnd",          # BND workspace
    ".mvn/",            # Maven wrapper config
    "gradle/",          # Gradle wrapper config
})


def _is_foundational(file_path: str) -> bool:
    """Return True if this file path matches a known foundational artefact."""
    p = file_path.replace("\\", "/").lower()
    return any(kw in p for kw in _FOUNDATIONAL_PATH_KEYWORDS)


# Judgment-call kinds produced by judgment_scan.py
_JUDGMENT_KINDS: frozenset[str] = frozenset({
    "reflection_string_literal",
    "dynamic_proxy",
    "serializable_class",
    "spi_registration",
})


# ---------------------------------------------------------------------------
# Finding dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PlanFinding:
    id: str                           # stable, opaque identifier
    batch: str                        # one of BATCH_ORDER values
    batch_index: int                  # 0-based integer reflecting BATCH_ORDER
    finding_type: str                 # "source_file" | "descriptor" | "judgment_call" | "dependency"
    files: list[str]                  # files involved
    signals: list[str]                # human-readable reasons for batch assignment
    effort_hours: float
    formula_trace: str                # e.g. "6.0 * max(1, 3^0.55) = 12.47"


@dataclass
class Batch:
    name: str
    index: int
    findings: list[PlanFinding] = field(default_factory=list)


@dataclass
class MigrationPlan:
    source_report: str
    batches: list[Batch]              # ordered by index, always
    summary: dict                     # computed from findings, never hand-typed


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------


def _make_formula_trace(batch: str, file_count: int) -> str:
    base = BASE_HOURS[batch]
    if base == 0.0:
        return "0.0 (mechanical — transformer already rewrote this)"
    scale = _file_scale(file_count)
    hours = _effort(batch, file_count)
    return (
        f"{base} * max(1, {file_count}^{FILE_SCALE_EXP}) "
        f"= {base} * {scale:.4f} = {hours}"
    )


def _assign_batch(
    finding_type: str,
    files: list[str],
    extra_signals: list[str],
) -> tuple[str, list[str]]:
    """Return (batch_name, signals) — rule-based, no hardcoded finding IDs."""
    signals: list[str] = list(extra_signals)

    # Judgment calls always need human input first
    if finding_type == "judgment_call":
        signals.append("judgment-call kind requires human triage before automated work")
        return "needs_human_input", signals

    # Source files not mechanically covered and not foundational: needs human
    # input if the signal says so (caller passes a signal for not-covered), but
    # we look at the actual signal rather than re-deriving here.
    if "not mechanically covered by Eclipse Transformer" in " ".join(signals):
        if not any(_is_foundational(f) for f in files):
            signals.append("requires hand edit — not handled by rewrite tooling")
            return "manual_remediation", signals

    # Foundational: build/config artefacts
    if any(_is_foundational(f) for f in files):
        signals.append("build or runtime-config artefact — foundational change")
        return "foundational", signals

    # Mechanically covered: transformer already rewrote it
    if "mechanically covered by Eclipse Transformer" in " ".join(signals):
        signals.append("rewrite tool handled this — no net-new effort")
        return "mechanical", signals

    # Dependencies flagged as legacy by discovery
    if finding_type == "dependency":
        signals.append("dependency version bump required")
        return "foundational", signals

    # Remaining source/descriptor coverage gaps → manual_remediation
    signals.append("requires hand edit — no rewrite-tool coverage")
    return "manual_remediation", signals


def build_migration_plan(impact_report: dict, source_report_path: str = "") -> MigrationPlan:
    """Build a MigrationPlan from an impact-facts.json dict.

    Batch order is determined by BATCH_ORDER list index — not by dict insertion
    order or any other accident of population sequence.
    """
    findings: list[PlanFinding] = []
    finding_counter = 0

    def _next_id(prefix: str) -> str:
        nonlocal finding_counter
        finding_counter += 1
        return f"{prefix}-{finding_counter:04d}"

    # ------------------------------------------------------------------
    # 1. Source coverage entries
    # ------------------------------------------------------------------
    sc = impact_report.get("sourceCoverage", {})
    for entry in sc.get("entries", []):
        source_file = entry.get("sourceFile", "")
        transformer_changed = entry.get("transformerChanged")
        transformer_found = entry.get("transformerFound", False)

        files = [source_file]
        signals: list[str] = []

        if transformer_changed is True:
            signals.append("mechanically covered by Eclipse Transformer")
            batch, signals = _assign_batch("source_file", files, signals)
        elif transformer_found and transformer_changed is False:
            signals.append("not mechanically covered by Eclipse Transformer (transformer found class but made no changes)")
            batch, signals = _assign_batch("source_file", files, signals)
        else:
            signals.append("not mechanically covered by Eclipse Transformer (class not found in WAR)")
            batch, signals = _assign_batch("source_file", files, signals)

        javax_symbols = entry.get("javaxSymbols", [])
        if javax_symbols:
            signals.append(f"javax symbols: {', '.join(javax_symbols[:5])}" + (" …" if len(javax_symbols) > 5 else ""))

        fid = _next_id("sc")
        batch_idx = BATCH_ORDER.index(batch)
        findings.append(PlanFinding(
            id=fid,
            batch=batch,
            batch_index=batch_idx,
            finding_type="source_file",
            files=files,
            signals=signals,
            effort_hours=_effort(batch, len(files)),
            formula_trace=_make_formula_trace(batch, len(files)),
        ))

    # ------------------------------------------------------------------
    # 2. Descriptor coverage entries
    # ------------------------------------------------------------------
    for entry in impact_report.get("descriptorCoverage", []):
        source_file = entry.get("sourceFile", "")
        transformer_changed = entry.get("transformerChanged")

        files = [source_file]
        signals: list[str] = []

        if transformer_changed is True:
            signals.append("mechanically covered by Eclipse Transformer")
            batch, signals = _assign_batch("descriptor", files, signals)
        elif _is_foundational(source_file):
            # e.g. server.xml — foundational even if transformer didn't touch it
            batch, signals = _assign_batch("descriptor", files, signals)
        else:
            signals.append("not mechanically covered by Eclipse Transformer")
            risk = entry.get("riskCategory")
            if risk:
                signals.append(f"risk category: {risk}")
            batch, signals = _assign_batch("descriptor", files, signals)

        fid = _next_id("dc")
        batch_idx = BATCH_ORDER.index(batch)
        findings.append(PlanFinding(
            id=fid,
            batch=batch,
            batch_index=batch_idx,
            finding_type="descriptor",
            files=files,
            signals=signals,
            effort_hours=_effort(batch, len(files)),
            formula_trace=_make_formula_trace(batch, len(files)),
        ))

    # ------------------------------------------------------------------
    # 3. Judgment-call candidates
    # ------------------------------------------------------------------
    for jc in impact_report.get("judgmentCallCandidates", []):
        file_path = jc.get("file", "")
        kind = jc.get("kind", "unknown")
        detail = jc.get("detail", "")

        files = [file_path]
        signals = [
            f"kind: {kind}",
            f"detail: {detail}",
        ]
        batch, signals = _assign_batch("judgment_call", files, signals)

        fid = _next_id("jc")
        batch_idx = BATCH_ORDER.index(batch)
        findings.append(PlanFinding(
            id=fid,
            batch=batch,
            batch_index=batch_idx,
            finding_type="judgment_call",
            files=files,
            signals=signals,
            effort_hours=_effort(batch, len(files)),
            formula_trace=_make_formula_trace(batch, len(files)),
        ))

    # ------------------------------------------------------------------
    # 4. Assemble ordered batches from BATCH_ORDER — never from dict order
    # ------------------------------------------------------------------
    batch_map: dict[str, Batch] = {
        name: Batch(name=name, index=idx)
        for idx, name in enumerate(BATCH_ORDER)
    }
    for f in findings:
        batch_map[f.batch].findings.append(f)

    # Sort is by the pre-computed BATCH_ORDER index, not dict insertion order
    ordered_batches: list[Batch] = sorted(batch_map.values(), key=lambda b: b.index)

    # ------------------------------------------------------------------
    # 5. Summary — always computed from findings, never hand-typed
    # ------------------------------------------------------------------
    total_findings = len(findings)
    total_effort = round(sum(f.effort_hours for f in findings), 2)
    per_batch_summary = {
        b.name: {
            "finding_count": len(b.findings),
            "effort_hours": round(sum(f.effort_hours for f in b.findings), 2),
        }
        for b in ordered_batches
    }

    summary = {
        "total_findings": total_findings,
        "total_effort_hours": total_effort,
        "per_batch": per_batch_summary,
        "effort_formula": (
            f"BASE_HOURS[batch] * max(1, n^{FILE_SCALE_EXP})  "
            f"where n=file_count; "
            f"BASE_HOURS={BASE_HOURS}"
        ),
    }

    return MigrationPlan(
        source_report=source_report_path,
        batches=ordered_batches,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def plan_to_dict(plan: MigrationPlan) -> dict:
    """Serialise a MigrationPlan to a plain JSON-safe dict."""
    return {
        "stage": "migration-planning-layer-a",
        "sourceReport": plan.source_report,
        "summary": plan.summary,
        "batches": [
            {
                "name": b.name,
                "index": b.index,
                "findings": [
                    {
                        "id": f.id,
                        "batch": f.batch,
                        "batchIndex": f.batch_index,
                        "findingType": f.finding_type,
                        "files": f.files,
                        "signals": f.signals,
                        "effortHours": f.effort_hours,
                        "formulaTrace": f.formula_trace,
                    }
                    for f in b.findings
                ],
            }
            for b in plan.batches
        ],
    }


def write_migration_plan(plan_dict: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan_dict, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Sub-linearity self-check — run once at import to catch misconfiguration
# ---------------------------------------------------------------------------


def _verify_sublinearity() -> None:
    """Assert that file_scale(n) < n for all n in the realistic range 2..100.

    This catches formula regression if FILE_SCALE_EXP is ever changed to a
    value that makes the scaling super-linear.  Runs at import time, which
    means any test or server start surfaces the misconfiguration immediately.
    """
    for n in range(2, 101):
        scale = _file_scale(n)
        assert scale < n, (
            f"Sub-linearity violated at n={n}: file_scale={scale:.4f} >= n. "
            f"Adjust FILE_SCALE_EXP (currently {FILE_SCALE_EXP})."
        )


_verify_sublinearity()
