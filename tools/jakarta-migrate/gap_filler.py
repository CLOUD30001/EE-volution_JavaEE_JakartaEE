"""Fill the gaps that Eclipse Transformer does NOT cover.

Transformer handles compiled class files and a subset of XML descriptors, but it
does NOT rename:
  - String literals in Java source (e.g. Class.forName("javax.persistence.…"))
  - JPA property keys in persistence.xml (e.g. javax.persistence.schema-generation…)
  - Facelets taglib namespace URIs in .xhtml files
  - JSF context parameter names in web.xml
  - SPI registration filenames under META-INF/services/javax.*

This module handles all three categories based solely on what the discovery report
already found — no guessing, no extra scanning.

Exported function
-----------------
fill_gaps(repo_path, discovery_report) ->
    tuple[dict[Path, str], list[ChangeRecord]]

    Returns:
      patched_files  — dict mapping absolute Path → patched file content (as str).
                       The caller writes these to disk.
      changes        — list of ChangeRecord, one per substitution (or one "manual_required"
                       when a literal cannot be resolved from the spec map).

VERIFY: Any literal whose javax.* prefix is not in LITERAL_MAP produces a ChangeRecord
        with action="manual_required" and does NOT mutate the file content.
VERIFY: Each unique file is read exactly once and all substitutions are applied in one pass.
VERIFY: SPI rename instructions are returned as ChangeRecord(action="spi_rename"), not written.
"""
from __future__ import annotations

import re
from pathlib import Path

from pom_patcher import ChangeRecord  # shared dataclass — same directory

# ---------------------------------------------------------------------------
# §3 — spec-family prefix map  (longest / most specific prefix FIRST so the
# regex alternation short-circuits correctly)
# ---------------------------------------------------------------------------
LITERAL_MAP: dict[str, str] = {
    # Specific sub-packages before their parent to ensure correct matching order
    "javax.servlet.jsp.":            "jakarta.servlet.jsp.",
    "javax.enterprise.concurrent.":  "jakarta.enterprise.concurrent.",
    "javax.security.enterprise.":    "jakarta.security.enterprise.",
    "javax.xml.bind.":               "jakarta.xml.bind.",
    "javax.xml.ws.":                 "jakarta.xml.ws.",
    "javax.json.bind.":              "jakarta.json.bind.",
    # General packages
    "javax.servlet.":                "jakarta.servlet.",
    "javax.faces.":                  "jakarta.faces.",
    "javax.ejb.":                    "jakarta.ejb.",
    "javax.persistence.":            "jakarta.persistence.",
    "javax.enterprise.":             "jakarta.enterprise.",
    "javax.inject.":                 "jakarta.inject.",
    "javax.interceptor.":            "jakarta.interceptor.",
    "javax.validation.":             "jakarta.validation.",
    "javax.ws.rs.":                  "jakarta.ws.rs.",
    "javax.jws.":                    "jakarta.jws.",
    "javax.jms.":                    "jakarta.jms.",
    "javax.websocket.":              "jakarta.websocket.",
    "javax.annotation.":             "jakarta.annotation.",
}

# ---------------------------------------------------------------------------
# §4 — Facelets taglib namespace URI map  (both legacy sun.com and jcp.org forms)
# ---------------------------------------------------------------------------
FACELETS_URI_MAP: dict[str, str] = {
    # JSF core (f:)
    "http://java.sun.com/jsf/core":          "jakarta.faces.core",
    "http://xmlns.jcp.org/jsf/core":         "jakarta.faces.core",
    # JSF HTML (h:)
    "http://java.sun.com/jsf/html":          "jakarta.faces.html",
    "http://xmlns.jcp.org/jsf/html":         "jakarta.faces.html",
    # JSF Facelets (ui:)
    "http://java.sun.com/jsf/facelets":      "jakarta.faces.facelets",
    "http://xmlns.jcp.org/jsf/facelets":     "jakarta.faces.facelets",
    # JSF passthrough (pt:)
    "http://xmlns.jcp.org/jsf/passthrough":  "jakarta.faces.passthrough",
    # JSF composite (cc:)
    "http://xmlns.jcp.org/jsf/composite":    "jakarta.faces.composite",
    # JSTL core (c:)
    "http://java.sun.com/jsp/jstl/core":          "jakarta.tags.core",
    "http://xmlns.jcp.org/jsp/jstl/core":         "jakarta.tags.core",
    # JSTL functions (fn:)
    "http://java.sun.com/jsp/jstl/functions":     "jakarta.tags.functions",
    "http://xmlns.jcp.org/jsp/jstl/functions":    "jakarta.tags.functions",
}

# Build a regex that matches any legacy Facelets URI — escaped for use in raw text
_FACELETS_PATTERN = re.compile(
    "|".join(re.escape(k) for k in sorted(FACELETS_URI_MAP, key=len, reverse=True))
)

# Build a regex that matches any javax.* literal covered by LITERAL_MAP.
# Matches the full prefix + any subsequent characters up to a quote/whitespace boundary.
_LITERAL_PREFIXES_PATTERN = re.compile(
    r"(" + "|".join(re.escape(k) for k in sorted(LITERAL_MAP, key=len, reverse=True)) + r")"
)


def _resolve_literal(matched_literal: str) -> str | None:
    """Apply LITERAL_MAP to a matched javax.* string.  Returns None if unresolvable."""
    for prefix, replacement in LITERAL_MAP.items():
        if matched_literal.startswith(prefix):
            return replacement + matched_literal[len(prefix):]
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _patch_config_literals(
    repo_path: Path,
    literals_details: list[dict],
) -> tuple[dict[Path, str], list[ChangeRecord]]:
    """Apply javax.* → jakarta.* substitutions to config literals reported by discovery.

    Reads each unique file once, applies ALL substitutions for that file in a single pass,
    and returns patched content keyed by absolute path.
    """
    # Group entries by file path so we read each file only once.
    by_file: dict[Path, list[dict]] = {}
    for entry in literals_details:
        file_rel = entry.get("file", "")
        file_path = repo_path / file_rel if not Path(file_rel).is_absolute() else Path(file_rel)
        by_file.setdefault(file_path, []).append(entry)

    patched: dict[Path, str] = {}
    changes: list[ChangeRecord] = []

    for file_path, entries in by_file.items():
        if not file_path.exists():
            for entry in entries:
                changes.append(ChangeRecord(
                    file=str(file_path),
                    action="manual_required",
                    old_coordinate=entry.get("matched_literal", ""),
                    new_coordinate="",
                    map_key="file_not_found",
                ))
            continue

        content = file_path.read_text(encoding="utf-8", errors="replace")
        original_content = content

        for entry in entries:
            literal = entry.get("matched_literal", "")
            if not literal:
                continue

            resolved = _resolve_literal(literal)
            if resolved is None:
                changes.append(ChangeRecord(
                    file=str(file_path),
                    action="manual_required",
                    old_coordinate=literal,
                    new_coordinate="",
                    map_key="unresolvable_prefix",
                ))
                continue

            # Replace all occurrences in the current content snapshot.
            new_content = content.replace(literal, resolved)
            if new_content != content:
                changes.append(ChangeRecord(
                    file=str(file_path),
                    action="replace",
                    old_coordinate=literal,
                    new_coordinate=resolved,
                    map_key=next(
                        (p for p in LITERAL_MAP if literal.startswith(p)), ""
                    ),
                ))
                content = new_content
            # If unchanged (literal was in the report but not verbatim in file), still note it.
            else:
                changes.append(ChangeRecord(
                    file=str(file_path),
                    action="manual_required",
                    old_coordinate=literal,
                    new_coordinate=resolved,
                    map_key="literal_not_found_verbatim",
                ))

        if content != original_content:
            patched[file_path] = content

    return patched, changes


def _patch_facelets(
    repo_path: Path,
    descriptor_details: list[dict],
) -> tuple[dict[Path, str], list[ChangeRecord]]:
    """Replace legacy Facelets namespace URIs with Jakarta EE 10 equivalents.

    Processes only descriptor entries where descriptor_type == "Facelets View".
    """
    patched: dict[Path, str] = {}
    changes: list[ChangeRecord] = []

    facelets_entries = [
        d for d in descriptor_details
        if d.get("descriptor_type") == "Facelets View"
    ]

    for entry in facelets_entries:
        file_rel = entry.get("file", "")
        file_path = repo_path / file_rel if not Path(file_rel).is_absolute() else Path(file_rel)

        if not file_path.exists():
            changes.append(ChangeRecord(
                file=str(file_path),
                action="manual_required",
                old_coordinate="",
                new_coordinate="",
                map_key="file_not_found",
            ))
            continue

        content = file_path.read_text(encoding="utf-8", errors="replace")
        original_content = content

        def _replace_uri(m: re.Match) -> str:  # noqa: B023 (intentional closure over 'changes')
            old_uri = m.group(0)
            new_uri = FACELETS_URI_MAP[old_uri]
            changes.append(ChangeRecord(
                file=str(file_path),
                action="replace",
                old_coordinate=old_uri,
                new_coordinate=new_uri,
                map_key=old_uri,
            ))
            return new_uri

        content = _FACELETS_PATTERN.sub(_replace_uri, content)

        if content != original_content:
            patched[file_path] = content

    return patched, changes


def _rename_spi_files(repo_path: Path) -> list[ChangeRecord]:
    """Scan META-INF/services/ for javax.* filenames and return rename instructions.

    Does NOT perform the rename itself — returns ChangeRecord(action="spi_rename")
    entries with old_coordinate=old_path, new_coordinate=new_path.
    The caller is responsible for the actual rename + content update.
    """
    changes: list[ChangeRecord] = []

    services_dir = repo_path / "src" / "main" / "resources" / "META-INF" / "services"
    if not services_dir.exists():
        # Also check webapp location
        services_dir_alt = repo_path / "src" / "main" / "webapp" / "META-INF" / "services"
        if not services_dir_alt.exists():
            return changes
        services_dir = services_dir_alt

    for spi_file in services_dir.iterdir():
        if not spi_file.is_file():
            continue
        name = spi_file.name
        if not name.startswith("javax."):
            continue

        # Resolve the new name using LITERAL_MAP (which maps javax.prefix. → jakarta.prefix.)
        new_name = _resolve_literal(name)
        if new_name is None:
            # Unknown javax. prefix — flag as manual_required
            changes.append(ChangeRecord(
                file=str(spi_file),
                action="manual_required",
                old_coordinate=name,
                new_coordinate="",
                map_key="unresolvable_spi_prefix",
            ))
            continue

        new_path = spi_file.parent / new_name
        changes.append(ChangeRecord(
            file=str(spi_file),
            action="spi_rename",
            old_coordinate=str(spi_file),
            new_coordinate=str(new_path),
            map_key=name,
        ))

    return changes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fill_gaps(
    repo_path: Path,
    discovery_report: dict,
) -> tuple[dict[Path, str], list[ChangeRecord]]:
    """Apply all gap-filler transformations driven by the discovery report.

    Processes:
      1. Config literals   — discovery_report["configLiterals"]["details"]
      2. Facelets URIs     — discovery_report["descriptorAudit"]["details"]
                             (only descriptor_type == "Facelets View")
      3. SPI registrations — META-INF/services/javax.* filenames (filesystem scan)

    Args:
        repo_path:         Path to the Maven project root.
        discovery_report:  Parsed discovery-report.json dict.

    Returns:
        patched_files  — dict[Path, str] of files with changed content (caller writes).
        changes        — list of ChangeRecord (include "manual_required" entries).
    """
    all_patched: dict[Path, str] = {}
    all_changes: list[ChangeRecord] = []

    # 1. Config literals
    literals_details = (
        discovery_report.get("configLiterals", {}).get("details", [])
        or discovery_report.get("details", [])  # flat report format fallback
    )
    p1, c1 = _patch_config_literals(repo_path, literals_details)
    all_patched.update(p1)
    all_changes.extend(c1)

    # 2. Facelets namespace URIs
    descriptor_details = (
        discovery_report.get("descriptorAudit", {}).get("details", [])
    )
    p2, c2 = _patch_facelets(repo_path, descriptor_details)
    # Merge: if a file was already patched by step 1, apply step-2 on top of step-1 content
    for path, content in p2.items():
        if path in all_patched:
            # Re-apply facelets regex on the already-patched content
            patched_again = _FACELETS_PATTERN.sub(
                lambda m: FACELETS_URI_MAP[m.group(0)], all_patched[path]
            )
            all_patched[path] = patched_again
        else:
            all_patched[path] = content
    all_changes.extend(c2)

    # 3. SPI registrations (filesystem scan — no discovery report data needed)
    c3 = _rename_spi_files(repo_path)
    all_changes.extend(c3)

    return all_patched, all_changes
