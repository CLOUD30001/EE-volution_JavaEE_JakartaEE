"""Cross-references Stage 1's discovery-report.json against a TransformerRun to
produce the actual point of Impact Analysis: which Discovery findings are
mechanically covered by the rewrite tool, and which aren't.

Build-system scope: Maven only.
Path mapping follows the standard Maven WAR layout (src/main/webapp -> WAR root,
src/main/resources -> WEB-INF/classes, src/main/java -> WEB-INF/classes as .class).
Non-Maven layouts are not supported — Gradle and Ant support is future work.
"""
from __future__ import annotations

from dataclasses import dataclass

from .transformer_runner import TransformRun


def _source_java_to_class_key(discovery_path: str) -> str | None:
    p = discovery_path.replace("\\", "/")
    marker = "src/main/java/"
    if marker not in p or not p.endswith(".java"):
        return None
    rel = p.split(marker, 1)[1][: -len(".java")]
    return rel


def _descriptor_source_to_war_path(discovery_path: str) -> str | None:
    p = discovery_path.replace("\\", "/")
    if "src/main/webapp/" in p:
        return p.split("src/main/webapp/", 1)[1]
    if "src/main/resources/" in p:
        return "WEB-INF/classes/" + p.split("src/main/resources/", 1)[1]
    return None


@dataclass
class SourceCoverageEntry:
    sourceFile: str
    javaxSymbols: list[str]
    classKey: str | None
    transformerFound: bool
    transformerChanged: bool | None  # None when transformerFound is False


@dataclass
class DescriptorCoverageEntry:
    sourceFile: str
    warPath: str | None
    riskCategory: str | None
    transformerFound: bool
    transformerChanged: bool | None


def build_source_coverage(discovery: dict, run: TransformRun) -> list[SourceCoverageEntry]:
    file_details = discovery.get("javaxUsage", {}).get("fileDetails")
    if file_details is None:
        # Discovery artifact stored only spec-family counts, not per-file symbols -
        # nothing to cross-reference against.
        file_details = {}

    entries: list[SourceCoverageEntry] = []
    for source_file, symbols in file_details.items():
        class_key = _source_java_to_class_key(source_file)
        found = False
        changed_any = False
        if class_key:
            war_prefix = f"WEB-INF/classes/{class_key}"
            for r in run.resources:
                if r.action != "Class Action":
                    continue
                # match the top-level class file and any of its inner classes ($-suffixed)
                candidate = r.path[len("WEB-INF/classes/"):-len(".class")] if r.path.startswith("WEB-INF/classes/") and r.path.endswith(".class") else None
                if candidate and candidate.split("$", 1)[0] == class_key:
                    found = True
                    changed_any = changed_any or r.changed
        entries.append(SourceCoverageEntry(
            sourceFile=source_file,
            javaxSymbols=symbols,
            classKey=class_key,
            transformerFound=found,
            transformerChanged=changed_any if found else None,
        ))
    return entries


def build_descriptor_coverage(discovery: dict, run: TransformRun) -> list[DescriptorCoverageEntry]:
    descriptors = discovery.get("descriptors", {}).get("entries", [])
    entries: list[DescriptorCoverageEntry] = []
    for d in descriptors:
        source_file = d["file"]
        war_path = _descriptor_source_to_war_path(source_file)
        found = False
        changed = None
        if war_path:
            r = run.by_path(war_path)
            if r is not None:
                found = True
                changed = r.changed
        entries.append(DescriptorCoverageEntry(
            sourceFile=source_file,
            warPath=war_path,
            riskCategory=d.get("riskCategory"),
            transformerFound=found,
            transformerChanged=changed,
        ))
    return entries
